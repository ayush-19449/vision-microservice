"""
License Reader and Hardware Authenticator for Vision Orchestrator.
Decrypts AES-256-GCM encrypted .gry license files and validates hardware MAC and expiration.
"""
import os
import sys
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Ensure license_fastapi_system can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "license_fastapi_system")))
try:
    from license_config import (
        get_system_mac_address,
        normalize_mac,
        decrypt_license_data
    )
except ImportError:
    # Fallback to local import if needed
    raise ImportError("Could not load license_config from license_fastapi_system")

logger = logging.getLogger("LicenseReader")


@dataclass
class LicenseInfo:
    """Structured view of decrypted license data."""
    license_id: str
    camera_id: str
    camera_name: str
    rtsp_url: str = ""
    source_type: str = "camera"
    mac_address: str = ""
    container_name: str = ""
    topic: str = "camera.frames"
    partition: int = 0
    issued_at: str = ""
    expires_at: str = ""
    features: List[str] = field(default_factory=list)
    is_valid: bool = False
    validation_error: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


class LicenseReader:
    """
    Decrypts and validates .gry / .lic license files for the orchestrator.
    """

    @staticmethod
    def load_and_verify(license_path: str = "camera.gry") -> LicenseInfo:
        """
        Loads an encrypted license file from disk or string, decrypts it,
        and enforces MAC matching and expiration date.
        """
        # Resolve path
        if not os.path.isabs(license_path):
            candidates = [
                license_path,
                os.path.join(os.path.dirname(__file__), "..", license_path),
                os.path.join(os.path.dirname(__file__), "..", "license_fastapi_system", license_path),
            ]
            for c in candidates:
                if os.path.exists(c):
                    license_path = os.path.abspath(c)
                    break

        if not os.path.exists(license_path):
            return LicenseInfo(
                license_id="",
                camera_id="",
                camera_name="",
                mac_address="",
                container_name="",
                topic="",
                partition=0,
                issued_at="",
                expires_at="",
                features=[],
                is_valid=False,
                validation_error=f"License file not found: '{license_path}'"
            )

        try:
            with open(license_path, "r", encoding="utf-8") as f:
                encrypted_blob = f.read().strip()
        except Exception as e:
            return LicenseInfo(
                license_id="", camera_id="", camera_name="", mac_address="",
                container_name="", topic="", partition=0, issued_at="", expires_at="",
                features=[], is_valid=False, validation_error=f"Could not read license file: {e}"
            )

        # 1. Decrypt AES-256-GCM
        try:
            payload = decrypt_license_data(encrypted_blob)
        except Exception as e:
            logger.error(f"[LicenseReader] Decryption / MAC tag verification failed: {e}")
            return LicenseInfo(
                license_id="", camera_id="", camera_name="", mac_address="",
                container_name="", topic="", partition=0, issued_at="", expires_at="",
                features=[], is_valid=False, validation_error=f"License decryption/tamper verification failed: {e}"
            )

        # 2. Expiration validation
        try:
            exp_str = payload.get("expires_at", "")
            exp_dt = datetime.fromisoformat(exp_str)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            if now_dt >= exp_dt:
                return LicenseInfo(
                    license_id=payload.get("license_id", ""),
                    camera_id=payload.get("camera_id", ""),
                    camera_name=payload.get("camera_name", ""),
                    mac_address=payload.get("mac_address", ""),
                    container_name=payload.get("container_name", ""),
                    topic=payload.get("topic", ""),
                    partition=payload.get("partition", 0),
                    issued_at=payload.get("issued_at", ""),
                    expires_at=exp_str,
                    features=payload.get("features", []),
                    is_valid=False,
                    validation_error=f"License expired at {exp_str} (current UTC: {now_dt.isoformat()})",
                    raw_data=payload
                )
        except Exception as e:
            return LicenseInfo(
                license_id=payload.get("license_id", ""),
                camera_id=payload.get("camera_id", ""),
                camera_name=payload.get("camera_name", ""),
                mac_address=payload.get("mac_address", ""),
                container_name=payload.get("container_name", ""),
                topic=payload.get("topic", ""),
                partition=payload.get("partition", 0),
                issued_at=payload.get("issued_at", ""),
                expires_at="",
                features=payload.get("features", []),
                is_valid=False,
                validation_error=f"Invalid expiration date format: {e}",
                raw_data=payload
            )

        # 3. Hardware MAC Validation
        system_mac = get_system_mac_address()
        licensed_mac = normalize_mac(payload.get("mac_address", ""))
        if system_mac != licensed_mac:
            logger.warning(f"[LicenseReader] Hardware MAC mismatch: Host={system_mac}, License={licensed_mac}")
            return LicenseInfo(
                license_id=payload.get("license_id", ""),
                camera_id=payload.get("camera_id", ""),
                camera_name=payload.get("camera_name", ""),
                mac_address=licensed_mac,
                container_name=payload.get("container_name", ""),
                topic=payload.get("topic", ""),
                partition=payload.get("partition", 0),
                issued_at=payload.get("issued_at", ""),
                expires_at=payload.get("expires_at", ""),
                features=payload.get("features", []),
                is_valid=False,
                validation_error=f"Hardware MAC mismatch! Host={system_mac}, Licensed={licensed_mac}",
                raw_data=payload
            )

        # All checks passed!
        return LicenseInfo(
            license_id=payload.get("license_id", ""),
            camera_id=payload.get("camera_id", ""),
            camera_name=payload.get("camera_name", ""),
            rtsp_url=payload.get("rtsp_url", f"rtsp://127.0.0.1:8554/{payload.get('camera_id', '')}"),
            source_type=payload.get("source_type", "camera"),
            mac_address=licensed_mac,
            container_name=payload.get("container_name", ""),
            topic=payload.get("topic", "camera.frames"),
            partition=payload.get("partition", 0),
            issued_at=payload.get("issued_at", ""),
            expires_at=payload.get("expires_at", ""),
            features=payload.get("features", []),
            is_valid=True,
            validation_error=None,
            raw_data=payload
        )
