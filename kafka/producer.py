"""
High-Performance Vision Kafka Producer using confluent-kafka.
Supports publishing MinIO S3 frame reference payloads and direct binary frames.
"""
import time
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union, Callable

try:
    from confluent_kafka import Producer, KafkaError, KafkaException
except ImportError:
    Producer = None
    KafkaError = None
    KafkaException = Exception

from .config import (
    KafkaConfig,
    resolve_camera_partition,
    pack_frame_message
)

logger = logging.getLogger("KafkaVisionProducer")


class VisionKafkaProducer:
    """
    Enterprise-grade Kafka Producer tailored for video pipelines:
    - Publishes MinIO frame references (S3 path, metadata, camera ID) as lightweight JSON
    - Direct partition routing per Camera ID (cam 1 -> partition 1)
    - Publishes downstream vision detection events & alerts
    - Non-blocking asynchronous delivery with background polling
    """

    def __init__(
        self,
        config: Optional[KafkaConfig] = None,
        client_id: str = "vision-frame-producer",
        delivery_callback: Optional[Callable] = None
    ):
        if Producer is None:
            raise ImportError(
                "confluent-kafka is not installed. Run: pip install confluent-kafka"
            )

        self.config = config or KafkaConfig()
        self.producer_conf = self.config.get_producer_config(client_id=client_id)
        self.producer = Producer(self.producer_conf)
        self.custom_callback = delivery_callback

        # Metrics
        self.frames_sent = 0
        self.events_sent = 0
        self.delivery_errors = 0

    def _default_delivery_report(self, err, msg):
        """Internal delivery callback for librdkafka events."""
        if err is not None:
            self.delivery_errors += 1
            logger.error(f"[KafkaProducer] Delivery failed for message key {msg.key()}: {err}")
        if self.custom_callback:
            self.custom_callback(err, msg)

    def send_frame_reference(
        self,
        camera_id: Union[str, int],
        frame_id: int,
        storage_info: Dict[str, Any],
        image_metadata: Dict[str, Any],
        timestamp_ms: Optional[float] = None,
        topic: Optional[str] = None,
        partition: Optional[int] = None
    ) -> bool:
        """
        Publishes a MinIO frame reference message to Kafka.
        Routes to dedicated partition based on camera_id (e.g. cam 1 -> partition 1).
        
        :param camera_id: Identifier of the camera (e.g., "cam_1", "cam-002", 1)
        :param frame_id: Monotonically increasing sequence number
        :param storage_info: Dict with bucket, key, s3_uri, http_url, file_size_bytes
        :param image_metadata: Dict with width, height, codec, fps
        :param timestamp_ms: Epoch timestamp in ms
        """
        target_topic = topic or self.config.frame_topic
        target_partition = partition if partition is not None else resolve_camera_partition(camera_id)
        ts_ms = timestamp_ms if timestamp_ms is not None else (time.time() * 1000.0)
        ts_iso = datetime.now(timezone.utc).isoformat()

        payload = {
            "event_type": "camera.frame_ingested",
            "camera_id": str(camera_id),
            "partition": target_partition,
            "frame_id": frame_id,
            "timestamp_ms": ts_ms,
            "timestamp_iso": ts_iso,
            "storage": storage_info,
            "image_metadata": image_metadata
        }

        key_bytes = str(camera_id).encode('utf-8')
        val_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')

        try:
            self.producer.produce(
                topic=target_topic,
                key=key_bytes,
                value=val_bytes,
                partition=target_partition,
                on_delivery=self._default_delivery_report
            )
            self.frames_sent += 1
            self.producer.poll(0)
            return True
        except BufferError:
            self.producer.poll(50)
            try:
                self.producer.produce(
                    topic=target_topic,
                    key=key_bytes,
                    value=val_bytes,
                    partition=target_partition,
                    on_delivery=self._default_delivery_report
                )
                self.frames_sent += 1
                return True
            except Exception as e:
                logger.error(f"[KafkaProducer] Failed to send frame reference after flush: {e}")
                self.delivery_errors += 1
                return False
        except Exception as e:
            logger.error(f"[KafkaProducer] Produce exception: {e}")
            self.delivery_errors += 1
            return False

    def send_frame(
        self,
        camera_id: Union[str, int],
        frame_bytes: bytes,
        frame_id: int,
        width: int,
        height: int,
        timestamp_ms: Optional[float] = None,
        codec: str = "JPEG",
        topic: Optional[str] = None,
        partition: Optional[int] = None
    ) -> bool:
        """Publishes raw/JPEG frame bytes with binary header (direct streaming mode)."""
        target_topic = topic or self.config.frame_topic
        target_partition = partition if partition is not None else resolve_camera_partition(camera_id)
        ts_ms = timestamp_ms if timestamp_ms is not None else (time.time() * 1000.0)

        payload = pack_frame_message(
            frame_bytes=frame_bytes,
            camera_id=str(camera_id),
            frame_id=frame_id,
            timestamp_ms=ts_ms,
            width=width,
            height=height,
            codec=codec
        )

        key_bytes = str(camera_id).encode('utf-8')

        try:
            self.producer.produce(
                topic=target_topic,
                key=key_bytes,
                value=payload,
                partition=target_partition,
                on_delivery=self._default_delivery_report
            )
            self.frames_sent += 1
            self.producer.poll(0)
            return True
        except Exception as e:
            logger.error(f"[KafkaProducer] Direct binary produce error: {e}")
            self.delivery_errors += 1
            return False

    def send_event(
        self,
        event_type: str,
        camera_id: Union[str, int],
        data: Dict[str, Any],
        topic: Optional[str] = None,
        partition: Optional[int] = None
    ) -> bool:
        """Publishes structured JSON detection/analytics events."""
        target_topic = topic or self.config.event_topic
        target_partition = partition if partition is not None else resolve_camera_partition(camera_id)

        envelope = {
            "event_type": event_type,
            "camera_id": str(camera_id),
            "timestamp": time.time(),
            "data": data
        }

        key_bytes = str(camera_id).encode('utf-8')
        val_bytes = json.dumps(envelope, separators=(',', ':')).encode('utf-8')

        try:
            self.producer.produce(
                topic=target_topic,
                key=key_bytes,
                value=val_bytes,
                partition=target_partition,
                on_delivery=self._default_delivery_report
            )
            self.events_sent += 1
            self.producer.poll(0)
            return True
        except Exception as e:
            logger.error(f"[KafkaProducer] Event produce exception: {e}")
            self.delivery_errors += 1
            return False

    def flush(self, timeout: float = 5.0) -> int:
        return self.producer.flush(timeout=timeout)

    def close(self):
        self.flush(timeout=5.0)
