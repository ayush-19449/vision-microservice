"""
Service Catalog module loading declarative services.yml specifications.
Supports dependency resolution (topological ordering) and hardware resource constraints (CPU/GPU/RAM).
Raises ServiceNotFoundError if an undeclared service is requested.
"""
import os
import yaml
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger("ServiceCatalog")

DEFAULT_YML_PATH = os.path.join(os.path.dirname(__file__), "services.yml")


class ServiceNotFoundError(KeyError):
    """Raised when a requested vision service is not defined in services.yml."""
    pass


@dataclass
class GpuSpec:
    enabled: bool = False
    gpu_count: int = 0
    device_ids: str = "all"
    driver: str = "nvidia"


@dataclass
class ResourceSpec:
    cpu: str = "1.0"
    memory: str = "2G"
    gpu: GpuSpec = field(default_factory=GpuSpec)


@dataclass
class ServiceSpec:
    service_name: str
    display_name: str
    docker_image: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    resources: ResourceSpec = field(default_factory=ResourceSpec)
    environment: Dict[str, str] = field(default_factory=dict)
    restart_policy: str = "unless-stopped"


class ServiceCatalog:
    """
    Manages loading and resolving services from services.yml.
    """

    def __init__(self, yml_path: str = DEFAULT_YML_PATH):
        self.yml_path = os.path.abspath(yml_path)
        self.catalog: Dict[str, ServiceSpec] = {}
        self.reload()

    def reload(self):
        """Loads and parses services.yml."""
        if not os.path.exists(self.yml_path):
            raise FileNotFoundError(f"[ServiceCatalog] YAML file not found at: {self.yml_path}")

        try:
            with open(self.yml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            raw_services = data.get("services", {})
            parsed: Dict[str, ServiceSpec] = {}

            for s_name, s_data in raw_services.items():
                res_data = s_data.get("resources", {})
                gpu_data = res_data.get("gpu", {})

                gpu_spec = GpuSpec(
                    enabled=gpu_data.get("enabled", False),
                    gpu_count=gpu_data.get("gpu_count", 0),
                    device_ids=str(gpu_data.get("device_ids", "all")),
                    driver=gpu_data.get("driver", "nvidia")
                )

                res_spec = ResourceSpec(
                    cpu=str(res_data.get("cpu", "1.0")),
                    memory=str(res_data.get("memory", "2G")),
                    gpu=gpu_spec
                )

                # Canonicalize service name
                canonical_name = s_name.lower().strip()
                parsed[canonical_name] = ServiceSpec(
                    service_name=canonical_name,
                    display_name=s_data.get("display_name", canonical_name),
                    docker_image=s_data.get("docker_image", f"vision-{canonical_name}:latest"),
                    description=s_data.get("description", ""),
                    dependencies=s_data.get("dependencies", []),
                    resources=res_spec,
                    environment={str(k): str(v) for k, v in s_data.get("environment", {}).items()},
                    restart_policy=s_data.get("restart_policy", "unless-stopped")
                )

            self.catalog = parsed
            logger.info(f"[ServiceCatalog] Loaded {len(self.catalog)} services from {self.yml_path}")
        except Exception as e:
            logger.error(f"[ServiceCatalog] Failed to parse {self.yml_path}: {e}")
            raise

    def get_spec(self, service_name: str, strict: bool = True) -> Optional[ServiceSpec]:
        """
        Lookup a service by name (e.g., 'anpr', 'speed_detection', 'vehicle_detection').
        If strict=True, raises ServiceNotFoundError when service is not declared in services.yml.
        """
        key = service_name.lower().strip()
        # Aliases
        if key == "speed_calculation":
            key = "speed_detection"

        spec = self.catalog.get(key)
        if spec is None and strict:
            available = list(self.catalog.keys())
            raise ServiceNotFoundError(
                f"Service '{service_name}' not found in services.yml! Available services: {available}"
            )
        return spec

    def resolve_dependencies(self, requested_services: List[str]) -> List[str]:
        """
        Takes a list of requested service names and returns an ordered list
        including all required dependencies in topological order.
        Raises ServiceNotFoundError if any requested service or dependency is missing.
        """
        ordered: List[str] = []
        visited: Set[str] = set()
        visiting: Set[str] = set()

        def visit(node: str):
            node_key = node.lower().strip()
            if node_key == "speed_calculation":
                node_key = "speed_detection"

            if node_key in visiting:
                raise ValueError(f"Circular dependency detected in service definition: {node_key}")
            if node_key not in visited:
                visiting.add(node_key)
                
                # Strict lookup - raises ServiceNotFoundError if not in services.yml
                spec = self.get_spec(node_key, strict=True)
                
                for dep in spec.dependencies:
                    visit(dep)
                    
                visiting.remove(node_key)
                visited.add(node_key)
                if node_key not in ordered:
                    ordered.append(node_key)

        for s in requested_services:
            visit(s)

        return ordered


# Singleton
_catalog_instance: Optional[ServiceCatalog] = None

def get_service_catalog(yml_path: Optional[str] = None) -> ServiceCatalog:
    global _catalog_instance
    if _catalog_instance is None:
        _catalog_instance = ServiceCatalog(yml_path or DEFAULT_YML_PATH)
    return _catalog_instance
