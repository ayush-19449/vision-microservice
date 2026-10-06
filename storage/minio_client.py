"""
MinIO Object Storage Client for Video Frame Buffers.
Uploads captured frames to MinIO S3 buckets and returns structured paths for Kafka publishing.
"""
import io
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("MinioStorage")

try:
    from minio import Minio
    from minio.error import S3Error
except ImportError:
    Minio = None
    S3Error = Exception


class MinioFrameStorage:
    """
    Production-grade MinIO S3 client for video frames:
    - Auto-provisions 'vision-frames' bucket
    - Partitioned storage hierarchy: frames/{camera_id}/{YYYY-MM-DD}/{frame_id}_{timestamp}.jpg
    - Fast in-memory buffer streaming (io.BytesIO)
    - Fallback local cache mode when MinIO server is unreachable
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        secure: bool = False
    ):
        self.endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin")
        self.bucket_name = bucket_name or os.getenv("MINIO_BUCKET_NAME", "vision-frames")
        self.secure = secure or (os.getenv("MINIO_SECURE", "false").lower() == "true")

        self.client: Optional[Minio] = None
        self._init_client()

    def _init_client(self):
        """Initializes MinIO client and ensures target bucket exists."""
        if Minio is None:
            logger.warning("[MinioStorage] 'minio' package not installed. Operating in local filesystem fallback mode.")
            return

        try:
            self.client = Minio(
                endpoint=self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure
            )

            # Check and create bucket if not exists
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"[MinioStorage] Created MinIO bucket: '{self.bucket_name}'")
            else:
                logger.info(f"[MinioStorage] Connected to MinIO endpoint: {self.endpoint}, bucket: '{self.bucket_name}'")
        except Exception as e:
            logger.warning(f"[MinioStorage] Could not connect to MinIO ({self.endpoint}): {e}. Using local storage fallback.")
            self.client = None

    def upload_frame(
        self,
        camera_id: str,
        frame_id: int,
        frame_bytes: bytes,
        timestamp_ms: Optional[float] = None,
        content_type: str = "image/jpeg"
    ) -> Dict[str, Any]:
        """
        Uploads an encoded frame to MinIO under:
        frames/{camera_id}/{YYYY-MM-DD}/{frame_id}_{timestamp_ms}.jpg
        
        Returns metadata dict for Kafka message publishing.
        """
        ts = timestamp_ms if timestamp_ms is not None else (time.time() * 1000.0)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Object Key (path in S3)
        ext = "jpg" if "jpeg" in content_type.lower() or "jpg" in content_type.lower() else "bin"
        object_key = f"frames/{camera_id}/{date_str}/{frame_id}_{int(ts)}.{ext}"
        file_size = len(frame_bytes)

        # Upload to MinIO
        if self.client is not None:
            try:
                stream = io.BytesIO(frame_bytes)
                self.client.put_object(
                    bucket_name=self.bucket_name,
                    object_name=object_key,
                    data=stream,
                    length=file_size,
                    content_type=content_type
                )
            except Exception as e:
                logger.error(f"[MinioStorage] Failed to upload to MinIO: {e}. Falling back to local file.")
                self._save_local(object_key, frame_bytes)
        else:
            self._save_local(object_key, frame_bytes)

        protocol = "https" if self.secure else "http"
        http_url = f"{protocol}://{self.endpoint}/{self.bucket_name}/{object_key}"
        s3_uri = f"s3://{self.bucket_name}/{object_key}"

        return {
            "provider": "minio",
            "bucket": self.bucket_name,
            "key": object_key,
            "s3_uri": s3_uri,
            "http_url": http_url,
            "file_size_bytes": file_size
        }

    def download_frame(self, object_key: str, bucket: Optional[str] = None) -> Optional[bytes]:
        """Downloads frame bytes from MinIO or local fallback."""
        target_bucket = bucket or self.bucket_name
        if self.client is not None:
            try:
                response = self.client.get_object(target_bucket, object_key)
                return response.read()
            except Exception as e:
                logger.error(f"[MinioStorage] Download error from MinIO for '{object_key}': {e}")
                return self._read_local(object_key)
            finally:
                if 'response' in locals() and hasattr(response, 'close'):
                    response.close()
                    response.release_conn()
        return self._read_local(object_key)

    def _save_local(self, object_key: str, data: bytes):
        """Local disk fallback saving under /tmp/minio_data or local dir."""
        local_dir = os.path.join(os.path.dirname(__file__), "..", "minio_local_cache", self.bucket_name)
        file_path = os.path.join(local_dir, object_key.replace("/", os.sep))
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)

    def _read_local(self, object_key: str) -> Optional[bytes]:
        """Local disk fallback reading."""
        local_dir = os.path.join(os.path.dirname(__file__), "..", "minio_local_cache", self.bucket_name)
        file_path = os.path.join(local_dir, object_key.replace("/", os.sep))
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                return f.read()
        return None


# Global Singleton
_storage_instance: Optional[MinioFrameStorage] = None

def get_minio_storage() -> MinioFrameStorage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = MinioFrameStorage()
    return _storage_instance
