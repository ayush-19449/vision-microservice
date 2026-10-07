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
    """Structured view of decrypted service license data."""
    license_id: str
    service_name: str = "vision_analytics_service"
    mac_address: str = ""
    start_date: str = ""
    end_date: str = ""
    issued_at: str = ""
    expires_at: str = ""
    duration_days: int = 0
    features: List[str] = field(default_factory=list)
    is_valid: bool = False
    validation_error: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def camera_id(self) -> str:
        return self.raw_data.get("camera_id", "*")

    @property
    def camera_name(self) -> str:
        return self.raw_data.get("camera_name", self.service_name)

    @property
    def topic(self) -> str:
        return self.raw_data.get("topic", "camera.frames")

    @property
    def partition(self) -> int:
        return self.raw_data.get("partition", 0)


class LicenseReader:
    """
    Decrypts and validates .gry / .lic license files for the orchestrator.
    """

    @staticmethod
    def load_and_verify(license_path: str = "camera.gry") -> LicenseInfo:
        """
        Loads an encrypted license file from disk or string, decrypts it,
        and enforces MAC matching and duration validity (start_date to end_date).
        """
        # Resolve path
        if not os.path.isabs(license_path) or not os.path.exists(license_path):
            filename = os.path.basename(license_path)
            candidates = [
                os.path.join("/app/licenses", filename),
                os.path.join("licenses", filename),
                os.path.join(os.path.dirname(__file__), "..", "licenses", filename),
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
                service_name="",
                mac_address="",
                start_date="",
                end_date="",
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
                license_id="", service_name="", mac_address="",
                start_date="", end_date="", issued_at="", expires_at="",
                features=[], is_valid=False, validation_error=f"Could not read license file: {e}"
            )

        # 1. Decrypt AES-256-GCM
        try:
            payload = decrypt_license_data(encrypted_blob)
        except Exception as e:
            logger.error(f"[LicenseReader] Decryption / MAC tag verification failed: {e}")
            return LicenseInfo(
                license_id="", service_name="", mac_address="",
                start_date="", end_date="", issued_at="", expires_at="",
                features=[], is_valid=False, validation_error=f"License decryption/tamper verification failed: {e}"
            )

        # 2. Expiration & Duration validation
        try:
            start_str = payload.get("start_date") or payload.get("issued_at", "")
            exp_str = payload.get("end_date") or payload.get("expires_at", "")
            now_dt = datetime.now(timezone.utc)

            if start_str:
                start_dt = datetime.fromisoformat(start_str)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                if now_dt < start_dt:
                    return LicenseInfo(
                        license_id=payload.get("license_id", ""),
                        service_name=payload.get("service_name", "vision_analytics_service"),
                        mac_address=payload.get("mac_address", ""),
                        start_date=start_str,
                        end_date=exp_str,
                        issued_at=payload.get("issued_at", ""),
                        expires_at=exp_str,
                        duration_days=payload.get("duration_days", 0),
                        features=payload.get("features", []),
                        is_valid=False,
                        validation_error=f"License not yet active (start_date: {start_str})",
                        raw_data=payload
                    )

            exp_dt = datetime.fromisoformat(exp_str)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)

            if now_dt >= exp_dt:
                return LicenseInfo(
                    license_id=payload.get("license_id", ""),
                    service_name=payload.get("service_name", "vision_analytics_service"),
                    mac_address=payload.get("mac_address", ""),
                    start_date=start_str,
                    end_date=exp_str,
                    issued_at=payload.get("issued_at", ""),
                    expires_at=exp_str,
                    duration_days=payload.get("duration_days", 0),
                    features=payload.get("features", []),
                    is_valid=False,
                    validation_error=f"License expired at {exp_str} (current UTC: {now_dt.isoformat()})",
                    raw_data=payload
                )
        except Exception as e:
            return LicenseInfo(
                license_id=payload.get("license_id", ""),
                service_name=payload.get("service_name", "vision_analytics_service"),
                mac_address=payload.get("mac_address", ""),
                start_date="",
                end_date="",
                issued_at=payload.get("issued_at", ""),
                expires_at="",
                duration_days=0,
                features=payload.get("features", []),
                is_valid=False,
                validation_error=f"Invalid duration/expiration date format: {e}",
                raw_data=payload
            )

        # 3. Hardware MAC Validation
        system_mac = get_system_mac_address()
        licensed_mac = normalize_mac(payload.get("mac_address", ""))
        if system_mac != licensed_mac:
            logger.warning(f"[LicenseReader] Hardware MAC mismatch: Host={system_mac}, License={licensed_mac}")
            return LicenseInfo(
                license_id=payload.get("license_id", ""),
                service_name=payload.get("service_name", "vision_analytics_service"),
                mac_address=licensed_mac,
                start_date=payload.get("start_date", ""),
                end_date=payload.get("end_date", ""),
                issued_at=payload.get("issued_at", ""),
                expires_at=payload.get("expires_at", ""),
                duration_days=payload.get("duration_days", 0),
                features=payload.get("features", []),
                is_valid=False,
                validation_error=f"Hardware MAC mismatch! Host={system_mac}, Licensed={licensed_mac}",
                raw_data=payload
            )

        # Save decrypted cache
        try:
            import json
            save_dir = os.path.join(os.path.dirname(__file__), "..", "licenses")
            if not os.path.exists(save_dir):
                save_dir = os.path.join(os.path.dirname(__file__), "..", "license_fastapi_system")
            save_path = os.path.join(save_dir, "decrypted_license.json")
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as out_f:
                json.dump(payload, out_f, indent=2)
            logger.info(f"[LicenseReader] Saved decrypted license data to: {save_path}")
        except Exception as save_err:
            logger.warning(f"[LicenseReader] Could not save decrypted license payload: {save_err}")

        return LicenseInfo(
            license_id=payload.get("license_id", ""),
            service_name=payload.get("service_name", "vision_analytics_service"),
            mac_address=licensed_mac,
            start_date=payload.get("start_date", payload.get("issued_at", "")),
            end_date=payload.get("end_date", payload.get("expires_at", "")),
            issued_at=payload.get("issued_at", ""),
            expires_at=payload.get("expires_at", ""),
            duration_days=payload.get("duration_days", 0),
            features=payload.get("features", []),
            is_valid=True,
            validation_error=None,
            raw_data=payload
        )
