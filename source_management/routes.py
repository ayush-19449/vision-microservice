import os
import shutil
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, File, UploadFile, status

from .models import CameraSource, CameraCreateRequest, CameraUpdateRequest
from .camera_service import get_camera_service

router = APIRouter(prefix="/sources/cameras", tags=["Source Management - Cameras"])

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_source_file(file: UploadFile = File(...)):
    """
    Upload a local video (.mp4, .mov) or image (.jpg, .png) file for testing feeds.
    Saves to shared container storage and returns the local file path to use in 'url'.
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_filename = os.path.basename(file.filename or "uploaded_source.mp4")
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_size = os.path.getsize(file_path)
        return {
            "status": "success",
            "filename": safe_filename,
            "file_path": file_path,
            "content_type": file.content_type,
            "size_bytes": file_size,
            "message": f"File uploaded successfully. Pass 'url': '{file_path}' when creating camera with source_type='video' or 'image'."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")


@router.post("", response_model=CameraSource, status_code=status.HTTP_201_CREATED)
def create_camera(req: CameraCreateRequest):
    """Register a new camera source (Strictly verified against active hardware license)."""
    service = get_camera_service()
    try:
        return service.create_camera(req)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[CameraSource])
def list_cameras(active_only: bool = Query(False, description="Filter for active cameras only")):
    """List all registered cameras."""
    service = get_camera_service()
    return service.list_cameras(active_only=active_only)


@router.get("/{camera_id}", response_model=CameraSource)
def get_camera(camera_id: str):
    """Retrieve details for a specific camera."""
    service = get_camera_service()
    cam = service.get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")
    return cam


@router.put("/{camera_id}", response_model=CameraSource)
def update_camera(camera_id: str, req: CameraUpdateRequest):
    """Update camera configuration (RTSP URL, FPS, active status, etc.)."""
    service = get_camera_service()
    try:
        return service.update_camera(camera_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str):
    """Delete a camera from the registry."""
    service = get_camera_service()
    deleted = service.delete_camera(camera_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")
    return None
