"""
High-Performance Vision Kafka Consumer using confluent-kafka.
Supports consuming MinIO frame reference messages and direct binary frames.
"""
import os
import sys
import time
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, Generator, List

try:
    from confluent_kafka import Consumer, TopicPartition, KafkaError, KafkaException
except ImportError:
    Consumer = None
    TopicPartition = None
    KafkaError = None
    KafkaException = Exception

from .config import (
    KafkaConfig,
    resolve_camera_partition,
    unpack_frame_message
)

# Import MinIO storage
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from storage.minio_client import get_minio_storage
except ImportError:
    get_minio_storage = None

logger = logging.getLogger("KafkaVisionConsumer")


@dataclass
class FrameReference:
    """
    Lightweight structured frame reference pointing to MinIO storage.
    """
    camera_id: str
    partition: int
    frame_id: int
    timestamp_ms: float
    timestamp_iso: str
    storage: Dict[str, Any]
    image_metadata: Dict[str, Any]
    offset: int

    @property
    def s3_uri(self) -> str:
        return self.storage.get("s3_uri", "")

    @property
    def object_key(self) -> str:
        return self.storage.get("key", "")

    @property
    def width(self) -> int:
        return self.image_metadata.get("width", 1920)

    @property
    def height(self) -> int:
        return self.image_metadata.get("height", 1080)

    def get_frame_bytes(self) -> Optional[bytes]:
        """Fetches raw frame bytes from MinIO S3 storage."""
        if get_minio_storage is None:
            raise ImportError("Storage module not available.")
        storage = get_minio_storage()
        return storage.download_frame(
            object_key=self.object_key,
            bucket=self.storage.get("bucket")
        )

    def to_numpy(self):
        """
        Downloads frame bytes from MinIO and decodes into OpenCV BGR numpy array.
        """
        raw_bytes = self.get_frame_bytes()
        if raw_bytes is None:
            raise ValueError(f"Could not retrieve frame bytes from MinIO for key: {self.object_key}")
        try:
            import cv2
            import numpy as np
            np_arr = np.frombuffer(raw_bytes, np.uint8)
            return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        except ImportError:
            raise ImportError("OpenCV (cv2) and numpy are required to decode frames to numpy arrays.")


@dataclass
class FramePacket:
    """Container for directly packed binary frames."""
    camera_id: str
    frame_id: int
    timestamp_ms: float
    width: int
    height: int
    codec: str
    frame_bytes: bytes
    partition: int
    offset: int

    def to_numpy(self):
        try:
            import cv2
            import numpy as np
            np_arr = np.frombuffer(self.frame_bytes, np.uint8)
            return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        except ImportError:
            raise ImportError("OpenCV (cv2) and numpy are required to decode frames.")


class VisionKafkaConsumer:
    """
    Production-grade Kafka Consumer for computer vision models & workers:
    - Partition-specific direct assignment (cam 1 -> partition 1)
    - Automatic JSON MinIO FrameReference deserialization
    - Binary packet fallback
    - Stream generator stream_frames() for video processing loops
    """

    def __init__(
        self,
        config: Optional[KafkaConfig] = None,
        group_id: str = "vision-analytics-worker",
        auto_offset_reset: str = "latest",
        enable_auto_commit: bool = True
    ):
        if Consumer is None:
            raise ImportError(
                "confluent-kafka is not installed. Run: pip install confluent-kafka"
            )

        self.config = config or KafkaConfig()
        self.consumer_conf = self.config.get_consumer_config(
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=enable_auto_commit
        )
        self.consumer = Consumer(self.consumer_conf)
        self._assigned_partition: Optional[int] = None
        self._is_running = True

    def assign_camera(self, camera_id: Union[str, int], topic: Optional[str] = None):
        """
        Assigns the consumer directly to the exact partition dedicated to this Camera ID.
        """
        target_topic = topic or self.config.frame_topic
        partition = resolve_camera_partition(camera_id)
        self._assigned_partition = partition
        
        tp = TopicPartition(target_topic, partition)
        self.consumer.assign([tp])
        logger.info(f"[KafkaConsumer] Assigned directly to topic='{target_topic}', partition={partition} (cam_id='{camera_id}')")

    def subscribe(self, topics: List[str]):
        """Subscribes the consumer to topics with group balancing."""
        self.consumer.subscribe(topics)
        logger.info(f"[KafkaConsumer] Subscribed to topics: {topics}")

    def poll_frame_ref(self, timeout: float = 1.0) -> Optional[FrameReference]:
        """
        Polls Kafka for a MinIO FrameReference message.
        """
        msg = self.consumer.poll(timeout=timeout)
        if msg is None:
            return None

        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                return None
            logger.error(f"[KafkaConsumer] Error: {msg.error()}")
            return None

        try:
            val = msg.value().decode('utf-8')
            data = json.loads(val)
            return FrameReference(
                camera_id=data.get("camera_id", ""),
                partition=msg.partition(),
                frame_id=data.get("frame_id", 0),
                timestamp_ms=data.get("timestamp_ms", 0.0),
                timestamp_iso=data.get("timestamp_iso", ""),
                storage=data.get("storage", {}),
                image_metadata=data.get("image_metadata", {}),
                offset=msg.offset()
            )
        except Exception as e:
            logger.error(f"[KafkaConsumer] Error parsing FrameReference at offset {msg.offset()}: {e}")
            return None

    def stream_frame_refs(self, timeout: float = 0.5) -> Generator[FrameReference, None, None]:
        """Continuous generator loop yielding MinIO FrameReferences."""
        self._is_running = True
        while self._is_running:
            ref = self.poll_frame_ref(timeout=timeout)
            if ref is not None:
                yield ref

    def stop(self):
        self._is_running = False

    def close(self):
        self.stop()
        try:
            self.consumer.close()
        except Exception:
            pass
