"""
File-based Camera Registry and CRUD Service.
Uses thread-safe atomic JSON file persistence without requiring external database dependencies.
"""
import os
import re
import json
import logging
import threading
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

from .models import CameraSource, CameraCreateRequest, CameraUpdateRequest, _resolve_partition

logger = logging.getLogger("CameraService")

DEFAULT_STORAGE_PATH = os.path.join(os.path.dirname(__file__), "cameras.json")


class CameraService:
    """
    Thread-safe CRUD operations for camera sources stored in a local JSON file.
    """

    def __init__(self, storage_path: str = DEFAULT_STORAGE_PATH):
        self.storage_path = os.path.abspath(storage_path)
        self._lock = threading.Lock()
        self._init_storage()

    def _init_storage(self):
        """Creates default storage file if it does not exist."""
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            self._write_file_atomic({})
            logger.info(f"[CameraService] Initialized camera registry at: {self.storage_path}")

    def _read_file(self) -> Dict[str, Dict[str, Any]]:
        """Reads JSON data from file."""
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[CameraService] Failed to read {self.storage_path}: {e}")
            return {}

    def _write_file_atomic(self, data: Dict[str, Dict[str, Any]]):
        """Atomically writes JSON data to prevent file corruption."""
        import shutil
        temp_path = f"{self.storage_path}.tmp"
        if os.path.exists(temp_path) and os.path.isdir(temp_path):
            shutil.rmtree(temp_path)
        if os.path.exists(self.storage_path) and os.path.isdir(self.storage_path):
            shutil.rmtree(self.storage_path)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, self.storage_path)

    def _verify_license_for_camera(self, camera_id: str, requested_features: Optional[List[str]] = None) -> List[str]:
        """
        Validates that active hardware service license is valid.
        Raises PermissionError if license is missing, MAC mismatched, or expired.
        """
        try:
            from service_management.license_reader import LicenseReader
            lic = LicenseReader.load_and_verify()
            if not lic.is_valid:
                raise PermissionError(f"Cannot register camera source: Hardware license verification failed! ({lic.validation_error})")

            # Restrict features to licensed features only
            if requested_features:
                authorized = [f for f in requested_features if f in lic.features or f == "speed_detection" and "speed_calculation" in lic.features]
                return authorized or lic.features
            return lic.features
        except ImportError:
            # Standalone dev mode
            return requested_features or ["speed_calculation", "roi_detection"]

    def create_camera(self, req: CameraCreateRequest, enforce_license: bool = True) -> CameraSource:
        """Adds or updates a camera in the registry with strict hardware license validation."""
        with self._lock:
            authorized_features = req.features or ["speed_calculation", "roi_detection"]

            # Determine target camera_id
            target_cam_id = (req.camera_id or req.cam_id or "").strip()
            if not target_cam_id:
                target_cam_id = "cam_1"

            # 1. Strict License Verification (Raises 403 PermissionError if invalid MAC/expired)
            if enforce_license:
                authorized_features = self._verify_license_for_camera(target_cam_id, req.features)

            cameras = self._read_file()

            target_name = req.name or req.cam_name or f"Camera {target_cam_id}"
            target_url = req.rtsp_url or req.url or f"rtsp://127.0.0.1:8554/{target_cam_id}"
            target_source_type = req.source_type or "rtsp"
            target_location = req.location or req.source_location

            # Resolution calculation
            target_resolution = req.resolution
            if not target_resolution and req.width and req.height:
                target_resolution = f"{req.width}x{req.height}"
            elif not target_resolution:
                target_resolution = "1920x1080"

            # Parse width/height if needed
            w = req.width
            h = req.height
            if (not w or not h) and target_resolution:
                match = re.match(r'^(\d+)x(\d+)$', target_resolution.strip(), re.I)
                if match:
                    if not w: w = int(match.group(1))
                    if not h: h = int(match.group(2))

            # If camera already exists, update its configuration
            if target_cam_id in cameras:
                curr = cameras[target_cam_id]
                curr["rtsp_url"] = target_url
                if target_name: curr["name"] = target_name
                if target_source_type: curr["source_type"] = target_source_type
                if req.fps: curr["fps"] = req.fps
                if target_resolution: curr["resolution"] = target_resolution
                if w: curr["width"] = w
                if h: curr["height"] = h
                if target_location is not None: curr["location"] = target_location
                if req.is_active is not None: curr["is_active"] = req.is_active
                if authorized_features: curr["features"] = authorized_features
                if req.metadata: curr["metadata"].update(req.metadata)
                curr["updated_at"] = datetime.now(timezone.utc).isoformat()
                cameras[target_cam_id] = curr
                self._write_file_atomic(cameras)
                return CameraSource(**curr)

            partition = req.partition if req.partition is not None else _resolve_partition(target_cam_id)
            now = datetime.now(timezone.utc).isoformat()

            cam_dict = {
                "camera_id": target_cam_id,
                "name": target_name,
                "source_type": target_source_type,
                "rtsp_url": target_url,
                "width": w or 1920,
                "height": h or 1080,
                "resolution": target_resolution,
                "location": target_location,
                "fps": req.fps or 25,
                "partition": partition,
                "is_active": req.is_active if req.is_active is not None else True,
                "features": authorized_features,
                "metadata": req.metadata or {},
                "created_at": now,
                "updated_at": now
            }
            cameras[target_cam_id] = cam_dict
            self._write_file_atomic(cameras)
            return CameraSource(**cam_dict)

    def get_camera(self, camera_id: str) -> Optional[CameraSource]:
        """Fetches a camera by camera_id."""
        with self._lock:
            cameras = self._read_file()
            data = cameras.get(camera_id.strip())
            return CameraSource(**data) if data else None

    def list_cameras(self, active_only: bool = False) -> List[CameraSource]:
        """Lists all registered cameras."""
        with self._lock:
            cameras = self._read_file()
            result = []
            for cam in cameras.values():
                if active_only and not cam.get("is_active", True):
                    continue
                result.append(CameraSource(**cam))
            return result

    def update_camera(self, camera_id: str, req: CameraUpdateRequest) -> CameraSource:
        """Updates an existing camera configuration."""
        with self._lock:
            cameras = self._read_file()
            cam_id = camera_id.strip()
            if cam_id not in cameras:
                raise KeyError(f"Camera '{cam_id}' not found.")

            curr = cameras[cam_id]
            if req.name is not None:
                curr["name"] = req.name
            if req.source_type is not None:
                curr["source_type"] = req.source_type
            if req.rtsp_url is not None:
                curr["rtsp_url"] = req.rtsp_url
            if req.fps is not None:
                curr["fps"] = req.fps
            if req.resolution is not None:
                curr["resolution"] = req.resolution
            if req.partition is not None:
                curr["partition"] = req.partition
            if req.is_active is not None:
                curr["is_active"] = req.is_active
            if req.features is not None:
                curr["features"] = req.features
            if req.metadata is not None:
                curr["metadata"].update(req.metadata)

            curr["updated_at"] = datetime.now(timezone.utc).isoformat()
            cameras[cam_id] = curr
            self._write_file_atomic(cameras)
            return CameraSource(**curr)

    def delete_camera(self, camera_id: str) -> bool:
        """Deletes a camera from the registry."""
        with self._lock:
            cameras = self._read_file()
            cam_id = camera_id.strip()
            if cam_id not in cameras:
                return False
            del cameras[cam_id]
            self._write_file_atomic(cameras)
            return True


# Global Singleton instance
_service_instance: Optional[CameraService] = None

def get_camera_service(storage_path: Optional[str] = None) -> CameraService:
    global _service_instance
    if _service_instance is None:
        _service_instance = CameraService(storage_path or DEFAULT_STORAGE_PATH)
    return _service_instance
