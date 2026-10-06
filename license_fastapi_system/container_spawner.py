"""
Container Spawner Module
Spawns, manages, and monitors Docker containers based on camera ID (cam_id)
and specific computer vision use case (use_case), secured by AES-256-GCM hardware licenses.
"""
import os
import re
import sys
import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from license_config import (
    get_system_mac_address,
    normalize_mac,
    decrypt_license_data
)

# Default mapping of use_case -> container image & defaults
USE_CASE_CATALOG: Dict[str, Dict[str, Any]] = {
    "speed_calculation": {
        "image": "traffic-speed-service:latest",
        "description": "Calculates vehicle speed using homography and CCTV geometry",
        "env_defaults": {
            "PIPELINE_TYPE": "speed_calculation",
            "DEFAULT_FPS": "30",
            "CALIBRATION_HEIGHT": "3.5",
            "CALIBRATION_TILT": "45.0"
        },
        "default_ports": None,
        "entrypoint_script": "speed_calculator.py"
    },
    "roi_detection": {
        "image": "roi-detector-service:latest",
        "description": "Region of Interest entrance and exit boundary monitoring",
        "env_defaults": {
            "PIPELINE_TYPE": "roi_detection",
            "DETECTION_MODE": "entry_exit"
        },
        "default_ports": None,
        "entrypoint_script": None
    },
    "vehicle_counter": {
        "image": "vehicle-counter-service:latest",
        "description": "Vehicle detection, classification, and directional traffic counting",
        "env_defaults": {
            "PIPELINE_TYPE": "vehicle_counter",
            "COUNTING_LINE": "auto"
        },
        "default_ports": None,
        "entrypoint_script": None
    },
    "face_detection": {
        "image": "face-detection-service:latest",
        "description": "Face detection and bounding box evaluation using YuNet/SCRFD",
        "env_defaults": {
            "PIPELINE_TYPE": "face_detection",
            "CONFIDENCE_THRESHOLD": "0.6"
        },
        "default_ports": None,
        "entrypoint_script": None
    },
    "anpr": {
        "image": "anpr-license-plate-service:latest",
        "description": "Automatic Number Plate Recognition (ANPR / LPR)",
        "env_defaults": {
            "PIPELINE_TYPE": "anpr",
            "OCR_CONFIDENCE": "0.75"
        },
        "default_ports": None,
        "entrypoint_script": None
    },
    "object_tracking": {
        "image": "object-tracker-service:latest",
        "description": "Multi-object tracker across frames with ID re-identification",
        "env_defaults": {
            "PIPELINE_TYPE": "object_tracking",
            "TRACKER_TYPE": "bytetrack"
        },
        "default_ports": None,
        "entrypoint_script": None
    }
}


def sanitize_name(name: str) -> str:
    """Sanitize container name to only alphanumeric, dots, and hyphens."""
    clean = re.sub(r'[^a-zA-Z0-9_.-]', '-', name)
    return clean.strip('-')


class ContainerSpawner:
    def __init__(self, catalog: Optional[Dict[str, Dict[str, Any]]] = None):
        self.catalog = catalog or USE_CASE_CATALOG
        self._tracked_containers: Dict[str, Dict[str, Any]] = {}
        self._docker_available: Optional[bool] = None
        self._last_docker_check: float = 0.0

    def is_docker_daemon_running(self) -> bool:
        """Check if Docker CLI exists and Docker daemon is responsive (cached for 10s)."""
        import time
        now = time.time()
        if self._docker_available is not None and (now - self._last_docker_check) < 10.0:
            return self._docker_available

        self._last_docker_check = now
        if not shutil.which("docker"):
            self._docker_available = False
            return False
        try:
            result = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=1.5
            )
            self._docker_available = (result.returncode == 0)
        except Exception:
            self._docker_available = False
        return self._docker_available

    def generate_container_name(self, cam_id: str, use_case: str) -> str:
        """Generates standard container name e.g. cam001-speed_calculation."""
        return sanitize_name(f"{cam_id}_{use_case}").lower()

    def verify_authorization(
        self,
        cam_id: str,
        use_case: str,
        license_path: str = "camera.gry",
        encrypted_payload: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Validates:
          1. License decryption & cryptographic authentication (AES-256-GCM)
          2. License expiration
          3. Host hardware MAC address matching
          4. Camera ID authorization
          5. Use case authorization within enabled features
        """
        # Read payload
        if not encrypted_payload:
            if not os.path.exists(license_path):
                fallback = license_path.replace(".gry", ".lic")
                if os.path.exists(fallback):
                    license_path = fallback
                else:
                    return False, f"License file '{license_path}' not found.", None
            try:
                with open(license_path, "r", encoding="utf-8") as f:
                    encrypted_payload = f.read().strip()
            except Exception as e:
                return False, f"Failed to read license file: {e}", None

        # 1. Decrypt
        try:
            data = decrypt_license_data(encrypted_payload)
        except Exception as e:
            return False, f"Cryptographic check failed: {e}", None

        licensed_mac = normalize_mac(data.get("mac_address", ""))
        sys_mac = get_system_mac_address()

        # 2. Expiration
        try:
            exp_str = data.get("expires_at", "")
            exp_dt = datetime.fromisoformat(exp_str)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= exp_dt:
                return False, f"License expired on {exp_dt.isoformat()}", data
        except Exception as e:
            return False, f"Invalid license expiration format: {e}", data

        # 3. MAC match
        if sys_mac != licensed_mac:
            return False, f"MAC mismatch: Host is '{sys_mac}' but license is locked to '{licensed_mac}'", data

        # 4. Camera ID verification
        licensed_cam = data.get("camera_id")
        if licensed_cam != cam_id and licensed_cam != "*":
            return False, f"Camera '{cam_id}' is not authorized. License is for '{licensed_cam}'.", data

        # 5. Use Case verification
        licensed_features = [f.lower().strip() for f in data.get("features", [])]
        req_case = use_case.lower().strip()
        if req_case not in licensed_features and "*" not in licensed_features:
            return False, (
                f"Use case '{use_case}' is not licensed for camera '{cam_id}'. "
                f"Authorized use cases: {licensed_features}"
            ), data

        return True, "Authorized", data

    def spawn(
        self,
        cam_id: str,
        use_case: str,
        license_path: str = "camera.gry",
        encrypted_payload: Optional[str] = None,
        custom_env: Optional[Dict[str, str]] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Authorize and spawn a container for the given camera ID and use case.
        """
        case_info = self.catalog.get(use_case)
        if not case_info:
            return {
                "success": False,
                "status_code": "UNKNOWN_USE_CASE",
                "message": f"Unsupported use case: '{use_case}'. Supported: {list(self.catalog.keys())}",
                "cam_id": cam_id,
                "use_case": use_case
            }

        is_auth, reason, license_data = self.verify_authorization(
            cam_id=cam_id,
            use_case=use_case,
            license_path=license_path,
            encrypted_payload=encrypted_payload
        )
        if not is_auth:
            return {
                "success": False,
                "status_code": "UNAUTHORIZED",
                "message": reason,
                "cam_id": cam_id,
                "use_case": use_case,
                "license_details": license_data
            }

        container_name = self.generate_container_name(cam_id, use_case)
        image = case_info["image"]

        env_vars = {
            "CAMERA_ID": cam_id,
            "USE_CASE": use_case,
            "LICENSE_ID": license_data.get("license_id", "N/A"),
            "KAFKA_TOPIC": license_data.get("topic", "camera.events"),
            "KAFKA_PARTITION": str(license_data.get("partition", 0)),
            "HOST_MAC": license_data.get("mac_address", "")
        }
        if "env_defaults" in case_info:
            env_vars.update(case_info["env_defaults"])
        if custom_env:
            env_vars.update(custom_env)

        cmd = ["docker", "run", "-d", "--name", container_name, "--restart", "unless-stopped"]
        for k, v in env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.append(image)

        docker_live = self.is_docker_daemon_running()

        if dry_run or not docker_live:
            mode = "dry_run" if dry_run else "simulated_daemon_offline"
            record = {
                "success": True,
                "status_code": "SPAWNED_SIMULATED" if not docker_live else "DRY_RUN_SUCCESS",
                "mode": mode,
                "container_name": container_name,
                "cam_id": cam_id,
                "use_case": use_case,
                "image": image,
                "env": env_vars,
                "docker_command": " ".join(cmd),
                "container_id": f"sim-{container_name}-{int(datetime.now().timestamp())}",
                "spawned_at": datetime.now(timezone.utc).isoformat(),
                "status": "running (simulated)",
                "message": (
                    f"Container '{container_name}' validated and ready to spawn. "
                    + ("Docker daemon offline; simulation mode active." if not docker_live else "Dry-run succeeded.")
                )
            }
            self._tracked_containers[container_name] = record
            return record

        try:
            inspect = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if inspect.returncode == 0:
                current_status = inspect.stdout.strip()
                if current_status == "running":
                    return {
                        "success": True,
                        "status_code": "ALREADY_RUNNING",
                        "container_name": container_name,
                        "cam_id": cam_id,
                        "use_case": use_case,
                        "message": f"Container '{container_name}' is already running.",
                        "status": "running"
                    }
                else:
                    subprocess.run(["docker", "start", container_name], check=True)
                    return {
                        "success": True,
                        "status_code": "RESTARTED",
                        "container_name": container_name,
                        "cam_id": cam_id,
                        "use_case": use_case,
                        "message": f"Restarted existing container '{container_name}'.",
                        "status": "running"
                    }

            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            container_id = proc.stdout.strip()[:12]

            record = {
                "success": True,
                "status_code": "SPAWNED",
                "mode": "docker_native",
                "container_name": container_name,
                "cam_id": cam_id,
                "use_case": use_case,
                "image": image,
                "container_id": container_id,
                "docker_command": " ".join(cmd),
                "spawned_at": datetime.now(timezone.utc).isoformat(),
                "status": "running",
                "message": f"Docker container '{container_name}' spawned successfully."
            }
            self._tracked_containers[container_name] = record
            return record

        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "status_code": "DOCKER_EXECUTION_ERROR",
                "message": f"Docker error: {e.stderr.strip() or e.stdout.strip()}",
                "cam_id": cam_id,
                "use_case": use_case,
                "container_name": container_name
            }

    def stop_container(self, container_name: str) -> Dict[str, Any]:
        """Stop and remove a container by name."""
        if self.is_docker_daemon_running():
            try:
                subprocess.run(["docker", "stop", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                subprocess.run(["docker", "rm", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except Exception:
                pass

        if container_name in self._tracked_containers:
            self._tracked_containers[container_name]["status"] = "stopped"
            return {
                "success": True,
                "message": f"Container '{container_name}' stopped and removed.",
                "container_name": container_name
            }

        return {
            "success": True,
            "message": f"Container '{container_name}' marked as stopped.",
            "container_name": container_name
        }

    def list_containers(self) -> List[Dict[str, Any]]:
        """List all tracked and running containers."""
        if self.is_docker_daemon_running():
            for name, meta in list(self._tracked_containers.items()):
                res = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                if res.returncode == 0:
                    meta["status"] = res.stdout.strip()
                elif meta["status"] != "stopped":
                    meta["status"] = "not_found"

        return list(self._tracked_containers.values())


spawner = ContainerSpawner()
