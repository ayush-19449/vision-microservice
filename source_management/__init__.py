"""
Source Management Module for Camera Ingestion & Stream Registry.
Provides file-backed CRUD operations and FastAPI routes for managing camera sources.
"""

from .models import CameraSource, CameraCreateRequest, CameraUpdateRequest
from .camera_service import CameraService, get_camera_service

__all__ = [
    "CameraSource",
    "CameraCreateRequest",
    "CameraUpdateRequest",
    "CameraService",
    "get_camera_service",
]
