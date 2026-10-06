"""
FastAPI Router for Camera Source Management CRUD.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from .models import CameraSource, CameraCreateRequest, CameraUpdateRequest
from .camera_service import get_camera_service

router = APIRouter(prefix="/sources/cameras", tags=["Source Management - Cameras"])


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
