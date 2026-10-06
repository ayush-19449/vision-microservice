"""
File-based Camera Registry and CRUD Service.
Uses thread-safe atomic JSON file persistence without requiring external database dependencies.
"""
import os
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
        """Creates default storage file with sample data if it does not exist."""
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            default_cameras = {
                "cam_1": {
                    "camera_id": "cam_1",
                    "name": "North_Entrance_Main_Gate",
                    "rtsp_url": "rtsp://127.0.0.1:8554/cam1",
                    "fps": 30,
                    "resolution": "1920x1080",
                    "partition": 1,
                    "is_active": True,
                    "features": ["speed_calculation", "vehicle_counter"],
                    "metadata": {"calibration_height": 3.5, "location": "Building A"},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                },
                "cam_2": {
                    "camera_id": "cam_2",
                    "name": "South_Parking_Exit",
                    "rtsp_url": "rtsp://127.0.0.1:8554/cam2",
                    "fps": 25,
                    "resolution": "1920x1080",
                    "partition": 2,
                    "is_active": True,
                    "features": ["roi_detection", "vehicle_counter"],
                    "metadata": {"roi_points": [[100, 200], [500, 200], [500, 600], [100, 600]]},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
            }
            self._write_file_atomic(default_cameras)
            logger.info(f"[CameraService] Initialized default camera registry at: {self.storage_path}")

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
        temp_path = f"{self.storage_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Atomic rename on Windows/Linux
        os.replace(temp_path, self.storage_path)

    def _verify_license_for_camera(self, camera_id: str, requested_features: Optional[List[str]] = None) -> List[str]:
        """
        Validates that the requested Camera ID and features are permitted by active hardware license.
        Raises PermissionError if license is missing, MAC mismatched, or camera_id is unauthorized.
        """
        try:
            from service_management.license_reader import LicenseReader
            lic = LicenseReader.load_and_verify()
            if not lic.is_valid:
                raise PermissionError(f"Cannot register camera: Hardware license verification failed! ({lic.validation_error})")

            # Check camera_id permission
            allowed_cam = lic.camera_id
            if allowed_cam not in ("*", "all") and camera_id.strip() != allowed_cam.strip():
                raise PermissionError(
                    f"Registration Rejected: Camera ID '{camera_id}' is NOT licensed on this machine! "
                    f"Your active license only permits Camera ID: '{allowed_cam}'."
                )

            # Restrict features to licensed features only
            if requested_features:
                authorized = [f for f in requested_features if f in lic.features or f == "speed_detection" and "speed_calculation" in lic.features]
                return authorized or lic.features
            return lic.features
        except ImportError:
            # Standalone dev mode
            return requested_features or ["speed_calculation", "roi_detection"]

    def create_camera(self, req: CameraCreateRequest, enforce_license: bool = True) -> CameraSource:
        """Adds a new camera to the registry with strict license validation."""
        with self._lock:
            cameras = self._read_file()
            cam_id = req.camera_id.strip()
            if cam_id in cameras:
                raise ValueError(f"Camera with ID '{cam_id}' already exists.")

            # License Gate: Ensure user cannot register unauthorized camera IDs
            if enforce_license:
                authorized_features = self._verify_license_for_camera(cam_id, req.features)
            else:
                authorized_features = req.features or ["speed_calculation", "roi_detection"]

            partition = req.partition if req.partition is not None else _resolve_partition(cam_id)
            now = datetime.now(timezone.utc).isoformat()

            cam_dict = {
                "camera_id": cam_id,
                "name": req.name,
                "source_type": req.source_type or "camera",
                "rtsp_url": req.rtsp_url,
                "fps": req.fps or 25,
                "resolution": req.resolution or "1920x1080",
                "partition": partition,
                "is_active": req.is_active if req.is_active is not None else True,
                "features": authorized_features,
                "metadata": req.metadata or {},
                "created_at": now,
                "updated_at": now
            }
            cameras[cam_id] = cam_dict
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
