"""
Media Server Frame Ingestion Engine.
Captures frames from GStreamer pipelines, uploads to MinIO Object Storage,
and publishes lightweight S3 frame references to Kafka partitions per Camera ID.
"""
import os
import sys
import time
import logging
import threading
from typing import Optional, Dict, Any

# Add workspace paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kafka import VisionKafkaProducer, resolve_camera_partition
from media_server.gstreamer_pipeline import GStreamerPipelineBuilder
from storage.minio_client import get_minio_storage, MinioFrameStorage

try:
    import cv2
except ImportError:
    cv2 = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [MediaIngestor]: %(message)s")
logger = logging.getLogger("MediaIngestor")


class CameraFrameIngestor:
    """
    Ingests video frames from a camera RTSP/GStreamer pipeline:
    1. Grabs frame from GStreamer
    2. Encodes to JPEG
    3. Uploads to MinIO S3 bucket (frames/{cam_id}/{date}/{frame_id}_{timestamp}.jpg)
    4. Emits JSON frame metadata to Kafka partition matching cam_id (e.g. cam 1 -> partition 1)
    """

    def __init__(
        self,
        camera_id: str,
        rtsp_url: Optional[str] = None,
        source_type: str = "camera",
        partition: Optional[int] = None,
        target_fps: int = 25,
        jpeg_quality: int = 85,
        use_test_source: bool = False,
        producer: Optional[VisionKafkaProducer] = None,
        storage: Optional[MinioFrameStorage] = None
    ):
        self.camera_id = str(camera_id).strip()
        self.rtsp_url = rtsp_url
        self.source_type = source_type.lower().strip() if source_type else "camera"
        self.partition = partition if partition is not None else resolve_camera_partition(self.camera_id)
        self.target_fps = target_fps
        self.jpeg_quality = jpeg_quality
        self.use_test_source = use_test_source

        self.producer = producer or VisionKafkaProducer()
        self.storage = storage or get_minio_storage()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.frame_counter = 0
        self.fps_meter = 0.0

    def _open_capture(self):
        """Initializes OpenCV VideoCapture for camera, video file, or test stream."""
        if cv2 is None:
            raise ImportError("OpenCV (cv2) is required for frame ingestion.")

        if self.use_test_source or not self.rtsp_url:
            gst_str = GStreamerPipelineBuilder.build_test_pipeline(fps=self.target_fps)
            logger.info(f"[{self.camera_id}] Opening GStreamer Test Source: {gst_str}")
            cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
            if not cap.isOpened():
                return None
            return cap

        # 1. Video File Source
        if self.source_type == "video":
            logger.info(f"[{self.camera_id}] Opening local video file source: {self.rtsp_url}")
            cap = cv2.VideoCapture(self.rtsp_url)
            return cap

        # 2. Still Image Source
        if self.source_type == "image":
            logger.info(f"[{self.camera_id}] Single/Batch Image source: {self.rtsp_url}")
            return None

        # 3. RTSP Camera Stream (try GStreamer then native OpenCV)
        gst_str = GStreamerPipelineBuilder.build_rtsp_pipeline(self.rtsp_url, fps=self.target_fps)
        logger.info(f"[{self.camera_id}] Attempting GStreamer RTSP Pipeline: {gst_str}")
        cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
        
        if not cap.isOpened():
            logger.info(f"[{self.camera_id}] GStreamer fallback to OpenCV VideoCapture: {self.rtsp_url}")
            cap = cv2.VideoCapture(self.rtsp_url)
            
        return cap

    def _ingest_loop(self):
        """Continuous frame grab, MinIO upload & Kafka produce loop."""
        logger.info(f"[{self.camera_id}] Ingestion active -> MinIO storage & Kafka Partition {self.partition}")
        cap = self._open_capture()

        frame_interval = 1.0 / max(self.target_fps, 1)
        fps_start = time.time()
        fps_frames = 0
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality] if cv2 else []

        while self._running:
            loop_start = time.time()

            if cap is not None and cap.isOpened():
                ret, frame = cap.read()
                if not ret or frame is None:
                    logger.warning(f"[{self.camera_id}] Frame read failed. Reconnecting in 2s...")
                    time.sleep(2.0)
                    cap.release()
                    cap = self._open_capture()
                    continue
            else:
                # Synthetic fallback frame
                import numpy as np
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                frame[:] = (35, 35, 35)
                cv2.putText(
                    frame,
                    f"Camera: {self.camera_id} | Partition: {self.partition} | Frame: {self.frame_counter}",
                    (40, 360),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.1,
                    (0, 255, 128),
                    2
                )

            h, w = frame.shape[:2]
            ts_ms = time.time() * 1000.0

            # 1. Encode frame to JPEG
            success, encoded_img = cv2.imencode('.jpg', frame, encode_param)
            if not success:
                continue

            frame_bytes = encoded_img.tobytes()

            # 2. Upload frame buffer to MinIO S3
            storage_info = self.storage.upload_frame(
                camera_id=self.camera_id,
                frame_id=self.frame_counter,
                frame_bytes=frame_bytes,
                timestamp_ms=ts_ms,
                content_type="image/jpeg"
            )

            # 3. Publish lightweight reference to Kafka topic on camera's partition
            image_metadata = {
                "width": w,
                "height": h,
                "codec": "JPEG",
                "quality": self.jpeg_quality,
                "target_fps": self.target_fps
            }

            self.producer.send_frame_reference(
                camera_id=self.camera_id,
                frame_id=self.frame_counter,
                storage_info=storage_info,
                image_metadata=image_metadata,
                timestamp_ms=ts_ms,
                partition=self.partition
            )

            self.frame_counter += 1
            fps_frames += 1

            if fps_frames >= 50:
                elapsed = time.time() - fps_start
                self.fps_meter = round(fps_frames / max(elapsed, 0.001), 1)
                logger.info(
                    f"[{self.camera_id}] Streaming live at {self.fps_meter} FPS "
                    f"| S3: {storage_info['key']} | Partition: {self.partition}"
                )
                fps_frames = 0
                fps_start = time.time()

            # Throttle FPS
            elapsed_loop = time.time() - loop_start
            sleep_time = frame_interval - elapsed_loop
            if sleep_time > 0:
                time.sleep(sleep_time)

        if cap is not None:
            cap.release()
        logger.info(f"[{self.camera_id}] Ingest loop stopped.")

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._ingest_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)


class MediaServerManager:
    """Manages multiple camera ingestion pipelines concurrently."""

    def __init__(self):
        self.ingestors: Dict[str, CameraFrameIngestor] = {}
        self.shared_producer = VisionKafkaProducer()
        self.shared_storage = get_minio_storage()

    def start_camera_stream(
        self,
        camera_id: str,
        rtsp_url: Optional[str] = None,
        partition: Optional[int] = None,
        target_fps: int = 25,
        use_test_source: bool = False
    ) -> CameraFrameIngestor:
        if camera_id in self.ingestors:
            return self.ingestors[camera_id]

        ingestor = CameraFrameIngestor(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            partition=partition,
            target_fps=target_fps,
            use_test_source=use_test_source,
            producer=self.shared_producer,
            storage=self.shared_storage
        )
        ingestor.start()
        self.ingestors[camera_id] = ingestor
        return ingestor

    def stop_camera_stream(self, camera_id: str):
        if camera_id in self.ingestors:
            self.ingestors[camera_id].stop()
            del self.ingestors[camera_id]

    def stop_all(self):
        for cam_id in list(self.ingestors.keys()):
            self.stop_camera_stream(cam_id)
        self.shared_producer.close()
