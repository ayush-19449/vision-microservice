"""
Service Management & Orchestration Module.
Decrypts hardware licenses and automatically spawns/manages vision worker services per camera.
"""

from .license_reader import LicenseReader, LicenseInfo
from .service_catalog import ServiceCatalog, ServiceSpec, ServiceNotFoundError, get_service_catalog
from .orchestrator import VisionOrchestrator, get_orchestrator

__all__ = [
    "LicenseReader",
    "LicenseInfo",
    "ServiceCatalog",
    "ServiceSpec",
    "ServiceNotFoundError",
    "get_service_catalog",
    "VisionOrchestrator",
    "get_orchestrator",
]
