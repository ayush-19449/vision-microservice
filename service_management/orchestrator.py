"""
Master Vision Orchestrator Engine with Autonomous License Watching.
Automatically decrypts hardware licenses (.gry), validates MAC/Expiry,
auto-registers cameras into Source Management, resolves services.yml dependencies,
and auto-spawns vision analytics containers with CPU/GPU hardware limits.
"""
import os
import sys
import time
import threading
import logging
from typing import Dict, Any, List, Optional

from .license_reader import LicenseReader, LicenseInfo
from .service_catalog import get_service_catalog, ServiceCatalog, ServiceSpec, ServiceNotFoundError
from .container_manager import ContainerManager

# Import Source Management
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from source_management.camera_service import get_camera_service
    from source_management.models import CameraCreateRequest
    from kafka.config import resolve_camera_partition
except ImportError:
    get_camera_service = None
    CameraCreateRequest = None
    resolve_camera_partition = lambda cid: 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("VisionOrchestrator")


class VisionOrchestrator:
    """
    100% Autonomous Vision Orchestrator:
    - Automatically watches .gry license file on disk.
    - Decrypts AES-256-GCM payload and validates hardware MAC & expiry.
    - Auto-registers camera in Source Management.
    - Resolves topological dependencies from services.yml (e.g. anpr -> vehicle_detection).
    - Auto-spawns Docker containers applying GPU devices and CPU limits.
    - Shuts down containers automatically if license expires or is tampered.
    """

    def __init__(
        self,
        license_path: str = "camera.gry",
        services_yml: Optional[str] = None,
        kafka_bootstrap: str = "localhost:9092",
        auto_start: bool = False
    ):
        self.license_path = license_path
        self.kafka_bootstrap = kafka_bootstrap
        self.catalog = get_service_catalog(services_yml)
        self.container_mgr = ContainerManager()
        self.active_services: Dict[str, Dict[str, Any]] = {}
        self.license_info: Optional[LicenseInfo] = None
        self._last_mtime: float = 0.0
        self._watching: bool = False
        self._watch_thread: Optional[threading.Thread] = None

        if auto_start:
            self.orchestrate()

    def load_license(self) -> LicenseInfo:
        """Decrypts and authenticates the hardware license file."""
        self.license_info = LicenseReader.load_and_verify(self.license_path)
        return self.license_info

    def _auto_register_camera(self, lic: LicenseInfo):
        """Auto-registers or activates the camera in Source Management registry."""
        if not get_camera_service or not CameraCreateRequest:
            return

        try:
            svc = get_camera_service()
            existing = svc.get_camera(lic.camera_id)
            partition = lic.partition if lic.partition is not None else resolve_camera_partition(lic.camera_id)
            target_url = lic.rtsp_url or f"rtsp://127.0.0.1:8554/{lic.camera_id}"
            target_type = lic.source_type or "camera"

            if not existing:
                logger.info(f"[ORCHESTRATOR] Auto-registering camera '{lic.camera_id}' with RTSP: {target_url}...")
                svc.create_camera(CameraCreateRequest(
                    camera_id=lic.camera_id,
                    name=lic.camera_name or f"Camera {lic.camera_id}",
                    source_type=target_type,
                    rtsp_url=target_url,
                    partition=partition,
                    is_active=True,
                    features=lic.features
                ))
            else:
                from source_management.models import CameraUpdateRequest
                # Update RTSP URL if provided in license and reactivate
                update_req = CameraUpdateRequest(
                    is_active=True,
                    features=lic.features
                )
                if lic.rtsp_url and lic.rtsp_url != existing.rtsp_url:
                    update_req.rtsp_url = lic.rtsp_url
                svc.update_camera(lic.camera_id, update_req)
        except Exception as e:
            logger.warning(f"[ORCHESTRATOR] Camera auto-registration note: {e}")

    def orchestrate(self) -> Dict[str, Any]:
        """
        Executes full automated reconciliation:
        1. Decrypts & checks license
        2. Auto-provisions camera in source management
        3. Resolves services.yml dependencies
        4. Spawns Docker containers with GPU/CPU/RAM limits
        """
        logger.info("=" * 65)
        logger.info(" [ORCHESTRATOR] RUNNING AUTOMATED SERVICE RECONCILIATION")
        logger.info("=" * 65)

        # 1. Decrypt & Authenticate License
        lic = self.load_license()
        if not lic.is_valid:
            logger.error(f"[ORCHESTRATOR] LICENSE INVALID OR REJECTED: {lic.validation_error}")
            if self.active_services:
                logger.warning("[ORCHESTRATOR] Shutting down active vision services due to invalid license.")
                self.stop_all()
            return {
                "status": "failed",
                "reason": lic.validation_error,
                "services_spawned": []
            }

        logger.info(f"[ORCHESTRATOR] License decrypted successfully! ID={lic.license_id}, Target Camera={lic.camera_id}")
        logger.info(f"[ORCHESTRATOR] Authorized License Features: {lic.features}")

        # 2. Auto-Register Camera in Source Management
        self._auto_register_camera(lic)

        # 3. Fetch Camera Source Configurations
        camera_service = get_camera_service() if get_camera_service else None
        target_cameras = []

        if camera_service:
            all_cams = camera_service.list_cameras(active_only=True)
            for cam in all_cams:
                if cam.camera_id == lic.camera_id or lic.camera_id in ("*", "all"):
                    target_cameras.append(cam)

        if not target_cameras:
            from source_management.models import CameraSource
            fallback_cam = CameraSource(
                camera_id=lic.camera_id,
                name=lic.camera_name or f"Camera {lic.camera_id}",
                source_type="camera",
                rtsp_url=f"rtsp://127.0.0.1:8554/{lic.camera_id}",
                partition=lic.partition or resolve_camera_partition(lic.camera_id),
                features=lic.features
            )
            target_cameras.append(fallback_cam)

        # 4. Canonicalize and Intersect Features
        spawned = []
        def _canon(feat_name: str) -> str:
            f = feat_name.lower().strip()
            return "speed_detection" if f == "speed_calculation" else f

        allowed_by_license = {_canon(f) for f in lic.features}

        for cam in target_cameras:
            cam_partition = cam.partition if cam.partition is not None else resolve_camera_partition(cam.camera_id)
            logger.info(f"\n[*] Processing Camera: '{cam.camera_id}' (Kafka Partition: {cam_partition})")

            cam_feats = {_canon(f) for f in (cam.features or lic.features)}
            raw_requested = list(cam_feats.intersection(allowed_by_license))

            # 5. Resolve Service Dependencies from services.yml
            resolved_pipeline = self.catalog.resolve_dependencies(raw_requested)
            logger.info(f"  -> Requested Features: {raw_requested}")
            logger.info(f"  -> Auto-Resolved Pipeline Order: {resolved_pipeline}")

            # 6. Auto-Spawn Vision Containers
            for feat in resolved_pipeline:
                spec = self.catalog.get_spec(feat, strict=True)
                container_name = f"{cam.camera_id}_{feat}_worker"

                # If container is already tracked and running, keep it
                if container_name in self.active_services and self.active_services[container_name].get("status") in ("running", "simulated_started"):
                    spawned.append(container_name)
                    continue

                env_vars = {
                    "CAMERA_ID": cam.camera_id,
                    "CAMERA_NAME": cam.name,
                    "KAFKA_BOOTSTRAP_SERVERS": self.kafka_bootstrap,
                    "KAFKA_FRAME_TOPIC": lic.topic or "camera.frames",
                    "KAFKA_PARTITION": str(cam_partition),
                    "PIPELINE_TYPE": feat,
                    "LICENSE_ID": lic.license_id,
                }
                env_vars.update(spec.environment)

                res_spec = spec.resources
                gpu_info = f"GPU: {res_spec.gpu.device_ids} (Count: {res_spec.gpu.gpu_count})" if res_spec.gpu.enabled else "GPU: Disabled"
                logger.info(
                    f"  [+] Auto-Spawning '{container_name}' "
                    f"| Image: {spec.docker_image} "
                    f"| CPU: {res_spec.cpu} | RAM: {res_spec.memory} | {gpu_info}"
                )

                spawn_res = self.container_mgr.spawn_service_container(
                    container_name=container_name,
                    image_name=spec.docker_image,
                    env_vars=env_vars,
                    resources=res_spec,
                    restart_policy=spec.restart_policy
                )

                self.active_services[container_name] = {
                    "camera_id": cam.camera_id,
                    "partition": cam_partition,
                    "feature": feat,
                    "image": spec.docker_image,
                    "dependencies": spec.dependencies,
                    "resources": {
                        "cpu": res_spec.cpu,
                        "memory": res_spec.memory,
                        "gpu_enabled": res_spec.gpu.enabled,
                        "gpu_devices": res_spec.gpu.device_ids
                    },
                    "status": spawn_res.get("status"),
                    "details": spawn_res
                }
                spawned.append(container_name)

        logger.info("\n" + "=" * 65)
        logger.info(f" [ORCHESTRATOR SUCCESS] Automated orchestration complete. Active workers: {len(spawned)}")
        logger.info("=" * 65 + "\n")

        return {
            "status": "success",
            "license_id": lic.license_id,
            "camera_id": lic.camera_id,
            "services_spawned": spawned,
            "active_services": self.active_services
        }

    def start_auto_watcher(self, interval_seconds: int = 5):
        """
        Starts a background daemon watching the license file for automatic reconciliation.
        """
        if self._watching:
            return

        self._watching = True

        def _watch_loop():
            logger.info(f"[ORCHESTRATOR WATCHER] Started automated license watcher on '{self.license_path}' (interval: {interval_seconds}s)")
            while self._watching:
                try:
                    # Check file existence & modified time
                    if os.path.exists(self.license_path):
                        mtime = os.path.getmtime(self.license_path)
                        if mtime != self._last_mtime or not self.license_info or not self.license_info.is_valid:
                            self._last_mtime = mtime
                            logger.info(f"[ORCHESTRATOR WATCHER] Detected license file change/creation on '{self.license_path}'. Triggering automated orchestration!")
                            self.orchestrate()
                    else:
                        if self.active_services:
                            logger.warning(f"[ORCHESTRATOR WATCHER] License file '{self.license_path}' removed. Stopping all services.")
                            self.stop_all()
                except Exception as e:
                    logger.error(f"[ORCHESTRATOR WATCHER] Error during automated reconciliation: {e}")

                time.sleep(interval_seconds)

        self._watch_thread = threading.Thread(target=_watch_loop, daemon=True)
        self._watch_thread.start()

    def stop_watcher(self):
        self._watching = False

    def get_status(self) -> Dict[str, Any]:
        """Returns live orchestrator and container state."""
        return {
            "license_status": "valid" if self.license_info and self.license_info.is_valid else "unverified/invalid",
            "license_info": self.license_info.__dict__ if self.license_info else None,
            "total_active_services": len(self.active_services),
            "services": self.active_services
        }

    def stop_all(self):
        """Stops all running containers."""
        for name in list(self.active_services.keys()):
            logger.info(f"[ORCHESTRATOR] Stopping service: {name}")
            self.container_mgr.stop_container(name)
        self.active_services.clear()


# Global Singleton
_orchestrator_instance: Optional[VisionOrchestrator] = None

def get_orchestrator(license_path: str = "camera.gry") -> VisionOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = VisionOrchestrator(license_path=license_path)
    return _orchestrator_instance


if __name__ == "__main__":
    orch = VisionOrchestrator(license_path="camera.gry")
    result = orch.orchestrate()
    import pprint
    pprint.pprint(result)
