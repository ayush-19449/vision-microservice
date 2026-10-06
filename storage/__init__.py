"""
MinIO Object Storage Module for Camera Video Frames.
Handles high-performance S3 uploads, bucket provisioning, and frame retrieval.
"""

from .minio_client import MinioFrameStorage, get_minio_storage

__all__ = ["MinioFrameStorage", "get_minio_storage"]
