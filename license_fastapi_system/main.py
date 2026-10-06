"""
FastAPI Microservice for Camera Hardware-Bound License Management (.gry) & Container Spawning.
Provides endpoints for:
  - System hardware identity detection (MAC address)
  - Encrypted license generation (AES-256-GCM)
  - Downloading .gry license files
  - Uploading & verifying .gry license files (cryptography, expiry, MAC check)
  - Dynamic container spawning based on cam_id and use_case
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from license_config import (
    get_system_mac_address,
    normalize_mac,
    encrypt_license_data,
    decrypt_license_data
)
from container_spawner import spawner, USE_CASE_CATALOG

app = FastAPI(
    title="Camera License & Container Spawner Microservice (.gry)",
    description="Production-ready Hardware-Bound Encrypted License API & Container Spawner using AES-256-GCM.",
    version="2.1.0"
)

# ----------------- SCHEMAS -----------------

class LicenseGenerateRequest(BaseModel):
    camera_id: str = Field(default="cam-001", description="Camera identifier (e.g. cam-001, cam-002)")
    camera_name: str = Field(default="Office_Main_Gate", description="Human-readable camera location name")
    mac_address: Optional[str] = Field(default=None, description="Target machine MAC (defaults to server MAC if null)")
    days_valid: int = Field(default=365, description="Days license remains valid (negative for expired testing)")
    container_name: str = Field(default="cam001-container", description="Authorized Docker container name")
    topic: str = Field(default="traffic.camera.events", description="Shared Kafka topic for all cameras")
    partition: Optional[int] = Field(
        default=None,
        description="Kafka partition (auto-assigned from camera_id if not provided: cam-001=0, cam-002=1 ...)"
    )
    features: List[str] = Field(
        default=["speed_calculation", "roi_detection", "vehicle_counter"],
        description="List of enabled features / use cases"
    )

def _auto_assign_partition(camera_id: str, explicit_partition: Optional[int]) -> int:
    if explicit_partition is not None:
        return explicit_partition
    import re
    match = re.search(r'(\d+)$', camera_id)
    if match:
        return int(match.group(1)) - 1
    return 0

class LicenseVerifyRequest(BaseModel):
    license_payload: str = Field(..., description="Encrypted base64url license string (.gry content)")

class LicenseResponse(BaseModel):
    is_valid: bool
    status_code: str
    message: str
    system_mac: str
    licensed_mac: Optional[str] = None
    license_details: Optional[dict] = None

class ContainerSpawnRequest(BaseModel):
    cam_id: str = Field(..., description="Camera ID (e.g. 'cam-001')")
    use_case: str = Field(..., description="Vision use case (e.g. 'speed_calculation', 'roi_detection', 'vehicle_counter', 'face_detection', 'anpr')")
    license_file: Optional[str] = Field(default="camera.gry", description="Path to license file (default: camera.gry)")
    license_payload: Optional[str] = Field(default=None, description="Optional raw encrypted license string")
    custom_env: Optional[Dict[str, str]] = Field(default=None, description="Optional extra environment variables")
    dry_run: bool = Field(default=False, description="Verify authorization without actually spawning container")

class ContainerStopRequest(BaseModel):
    cam_id: str = Field(..., description="Camera ID")
    use_case: str = Field(..., description="Vision use case")

# ----------------- HEALTH & SYSTEM ENDPOINTS -----------------

@app.get("/", tags=["Health"])
def root():
    """Service health check and hardware identity summary."""
    sys_mac = get_system_mac_address()
    return {
        "service": "Camera License & Container Spawner Microservice",
        "status": "online",
        "system_mac": sys_mac,
        "supported_use_cases": list(USE_CASE_CATALOG.keys()),
        "utc_time": datetime.now(timezone.utc).isoformat(),
        "docs_url": "/docs"
    }

@app.get("/api/v1/system/mac", tags=["System"])
def get_mac():
    """Retrieve the current host system's normalized physical MAC address."""
    return {"system_mac": get_system_mac_address()}

# ----------------- LICENSE VENDOR ENDPOINTS -----------------

@app.post("/api/v1/license/generate", tags=["License Vendor API"])
def generate_license(req: LicenseGenerateRequest):
    """Generate an encrypted .gry license file bound to a MAC address."""
    target_mac = normalize_mac(req.mac_address) if req.mac_address else get_system_mac_address()
    assigned_partition = _auto_assign_partition(req.camera_id, req.partition)
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=req.days_valid)

    payload = {
        "license_id": f"LIC-{int(now.timestamp())}",
        "camera_id": req.camera_id,
        "camera_name": req.camera_name,
        "mac_address": target_mac,
        "container_name": req.container_name,
        "topic": req.topic,
        "partition": assigned_partition,
        "issued_at": now.isoformat(),
        "expires_at": expiry.isoformat(),
        "features": req.features,
        "version": "1.0"
    }

    encrypted_blob = encrypt_license_data(payload)

    output_path = "camera.gry"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(encrypted_blob)

    return {
        "status": "success",
        "message": f"License generated for '{req.camera_id}' → partition {assigned_partition}",
        "file_name": output_path,
        "encrypted_payload": encrypted_blob,
        "license_data": payload
    }

@app.get("/api/v1/license/download", tags=["License Vendor API"])
def download_license():
    """Download the currently generated camera.gry file."""
    if not os.path.exists("camera.gry"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No camera.gry license file found. Generate one first using POST /api/v1/license/generate"
        )
    return FileResponse(
        path="camera.gry",
        filename="camera.gry",
        media_type="application/octet-stream"
    )

# ----------------- LICENSE VERIFICATION ENDPOINTS -----------------

@app.post("/api/v1/license/verify", response_model=LicenseResponse, tags=["License Verification"])
def verify_license_text(req: LicenseVerifyRequest):
    """Verify an encrypted license payload string."""
    return _verify_payload_data(req.license_payload.strip())

@app.post("/api/v1/license/verify-file", response_model=LicenseResponse, tags=["License Verification"])
async def verify_license_file(file: UploadFile = File(..., description="Upload .gry or .lic file")):
    """Upload and verify a .gry license file directly."""
    try:
        content = await file.read()
        payload_str = content.decode("utf-8").strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e}")

    return _verify_payload_data(payload_str)

# ----------------- CONTAINER SPAWNER ENDPOINTS -----------------

@app.get("/api/v1/containers/catalog", tags=["Container Management"])
def get_use_case_catalog():
    """Returns the list of supported computer vision use cases and their default container specifications."""
    return {
        "status": "success",
        "use_cases": USE_CASE_CATALOG
    }

@app.post("/api/v1/containers/spawn", tags=["Container Management"])
def spawn_container(req: ContainerSpawnRequest):
    """
    Spawns a Docker container based on cam_id and use_case.
    Security Pipeline:
      1. Validates AES-256-GCM license decryption & auth tag
      2. Verifies license expiry
      3. Validates hardware MAC address match
      4. Checks that cam_id matches the licensed camera
      5. Checks that use_case is authorized in licensed features
      6. Spawns and configures the container with appropriate environment & isolation
    """
    result = spawner.spawn(
        cam_id=req.cam_id,
        use_case=req.use_case,
        license_path=req.license_file or "camera.gry",
        encrypted_payload=req.license_payload,
        custom_env=req.custom_env,
        dry_run=req.dry_run
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN if result.get("status_code") == "UNAUTHORIZED" else status.HTTP_400_BAD_REQUEST,
            detail=result
        )

    return result

@app.get("/api/v1/containers", tags=["Container Management"])
def list_containers():
    """List all tracked and active vision containers spawned by cam_id and use_case."""
    return {
        "status": "success",
        "count": len(spawner.list_containers()),
        "containers": spawner.list_containers()
    }

@app.post("/api/v1/containers/stop", tags=["Container Management"])
def stop_container_by_cam_and_usecase(req: ContainerStopRequest):
    """Stop a vision container identified by cam_id and use_case."""
    container_name = spawner.generate_container_name(req.cam_id, req.use_case)
    res = spawner.stop_container(container_name)
    return res

@app.delete("/api/v1/containers/{container_name}", tags=["Container Management"])
def stop_container_by_name(container_name: str):
    """Stop and remove a container by exact container name."""
    res = spawner.stop_container(container_name)
    return res

# ----------------- INTERNAL HELPER -----------------

def _verify_payload_data(encrypted_str: str) -> LicenseResponse:
    sys_mac = get_system_mac_address()

    # 1. Decrypt and check cryptographic authentication tag
    try:
        data = decrypt_license_data(encrypted_str)
    except Exception as e:
        return LicenseResponse(
            is_valid=False,
            status_code="LICENSE_DECRYPTION_FAILED",
            message=f"Cryptographic check failed: {str(e)}",
            system_mac=sys_mac
        )

    licensed_mac = normalize_mac(data.get("mac_address", ""))

    # 2. Expiration check
    try:
        exp_dt = datetime.fromisoformat(data.get("expires_at", ""))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)

        if now_dt >= exp_dt:
            return LicenseResponse(
                is_valid=False,
                status_code="LICENSE_EXPIRED",
                message=f"License expired on {exp_dt.isoformat()}",
                system_mac=sys_mac,
                licensed_mac=licensed_mac,
                license_details=data
            )
    except Exception as e:
        return LicenseResponse(
            is_valid=False,
            status_code="LICENSE_FORMAT_INVALID",
            message=f"Invalid expiration date: {e}",
            system_mac=sys_mac,
            licensed_mac=licensed_mac
        )

    # 3. Hardware MAC validation
    if sys_mac != licensed_mac:
        return LicenseResponse(
            is_valid=False,
            status_code="MAC_ADDRESS_MISMATCH",
            message=f"Hardware mismatch! License locked to MAC '{licensed_mac}', but system MAC is '{sys_mac}'.",
            system_mac=sys_mac,
            licensed_mac=licensed_mac,
            license_details=data
        )

    # 4. Verified & Authorized
    return LicenseResponse(
        is_valid=True,
        status_code="AUTHORIZED",
        message="License cryptographically verified, active, and locked to this machine's MAC.",
        system_mac=sys_mac,
        licensed_mac=licensed_mac,
        license_details=data
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
