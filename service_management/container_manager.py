"""
Container Lifecycle Manager for Vision Services.
Handles Docker container spawning with CPU, GPU, and RAM resource limits.
"""
import os
import shutil
import logging
import subprocess
from typing import Dict, Any, List, Optional

from .service_catalog import ResourceSpec

logger = logging.getLogger("ContainerManager")


class ContainerManager:
    """
    Manages Docker container workloads for vision analytics microservices,
    enforcing CPU limits, RAM constraints, and NVIDIA GPU device attachment.
    """

    def __init__(self, network_name: str = "vision_net"):
        self.network_name = network_name
        self.docker_bin = shutil.which("docker")
        self._docker_available_cache = None
        self._last_cache_time = 0.0

    def is_docker_available(self) -> bool:
        """Checks if docker CLI is available and docker daemon is running with fast caching."""
        if not self.docker_bin:
            return False
        import time
        now = time.time()
        if self._docker_available_cache is not None and (now - self._last_cache_time) < 15.0:
            return self._docker_available_cache

        try:
            res = subprocess.run(
                [self.docker_bin, "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=1
            )
            self._docker_available_cache = (res.returncode == 0)
        except Exception:
            self._docker_available_cache = False

        self._last_cache_time = now
        return self._docker_available_cache

    def spawn_service_container(
        self,
        container_name: str,
        image_name: str,
        env_vars: Dict[str, str],
        resources: Optional[ResourceSpec] = None,
        restart_policy: str = "unless-stopped"
    ) -> Dict[str, Any]:
        """
        Runs `docker run -d --name <name> --cpus ... --memory ... --gpus ...`
        """
        if not self.is_docker_available():
            logger.warning(f"[ContainerManager] Docker daemon not reachable. Registering simulated container '{container_name}'.")
            return {
                "status": "simulated_started",
                "container_name": container_name,
                "image": image_name,
                "resources": resources.__dict__ if resources else None,
                "env": env_vars,
                "message": "Docker daemon offline; registered in local orchestrator state."
            }

        # 1. Clean up existing container if exists
        self.remove_container(container_name)

        # 2. Build docker run arguments
        cmd = [
            self.docker_bin, "run", "-d",
            "--name", container_name,
            f"--restart={restart_policy}"
        ]

        # 3. Apply Resource Constraints
        cmd_gpus_included = False
        if resources:
            # CPU limits (e.g. --cpus="2.0")
            if resources.cpu:
                cmd.extend(["--cpus", str(resources.cpu)])

            # Memory limits (e.g. --memory="4G")
            if resources.memory:
                cmd.extend(["--memory", str(resources.memory)])

            # GPU Attachment (only if supported / Linux host)
            import platform
            if resources.gpu and resources.gpu.enabled and platform.system().lower() == "linux":
                dev_ids = resources.gpu.device_ids
                cmd_gpus_included = True
                if dev_ids == "all":
                    cmd.extend(["--gpus", "all"])
                else:
                    cmd.extend(["--gpus", f'"device={dev_ids}"'])

        # 4. Inject Environment Variables
        for k, v in env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])

        cmd.append(image_name)

        def _try_run(run_cmd: list, timeout_sec: int = 5):
            cmd_str = " ".join(run_cmd)
            logger.info(f"[ContainerManager] Spawning container with command: {cmd_str}")
            return subprocess.run(run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec)

        try:
            res = _try_run(cmd, timeout_sec=5)
            if res.returncode == 0:
                container_id = res.stdout.strip()
                return {
                    "status": "running",
                    "container_id": container_id[:12],
                    "container_name": container_name,
                    "image": image_name,
                    "resources": resources.__dict__ if resources else None
                }
            
            # If failed with GPU error, try without --gpus
            if cmd_gpus_included:
                cmd_no_gpu = [arg for arg in cmd if not arg.startswith("--gpus") and arg != "all"]
                logger.warning(f"[ContainerManager] GPU attachment failed. Retrying without GPU flags for container '{container_name}'...")
                res = _try_run(cmd_no_gpu, timeout_sec=5)
                if res.returncode == 0:
                    container_id = res.stdout.strip()
                    return {
                        "status": "running",
                        "container_id": container_id[:12],
                        "container_name": container_name,
                        "image": image_name,
                        "resources": resources.__dict__ if resources else None
                    }

            logger.warning(f"[ContainerManager] Docker run returned code {res.returncode}: {res.stderr.strip() or res.stdout.strip()}. Falling back to simulated container mode.")
            return {
                "status": "simulated_started",
                "container_name": container_name,
                "image": image_name,
                "resources": resources.__dict__ if resources else None,
                "env": env_vars,
                "message": f"Docker image/host fallback: {res.stderr.strip() or 'Image not local'}"
            }
        except Exception as e:
            logger.warning(f"[ContainerManager] Docker run exception ({e}). Falling back to simulated container mode.")
            return {
                "status": "simulated_started",
                "container_name": container_name,
                "image": image_name,
                "resources": resources.__dict__ if resources else None,
                "env": env_vars,
                "message": f"Simulation fallback due to: {e}"
            }

    def stop_container(self, container_name: str) -> bool:
        """Stops a running container."""
        if not self.is_docker_available():
            return True
        try:
            subprocess.run([self.docker_bin, "stop", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            return True
        except Exception:
            return False

    def remove_container(self, container_name: str) -> bool:
        """Stops and removes container."""
        if not self.is_docker_available():
            return True
        try:
            subprocess.run([self.docker_bin, "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            return True
        except Exception:
            return False

    def get_container_status(self, container_name: str) -> str:
        """Returns container status: running, exited, not_found."""
        if not self.is_docker_available():
            return "simulated_running"
        try:
            res = subprocess.run(
                [self.docker_bin, "inspect", "--format", "{{.State.Status}}", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )
            if res.returncode == 0:
                return res.stdout.strip()
            return "not_found"
        except Exception:
            return "unknown"
