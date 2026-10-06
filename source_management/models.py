"""
Data models and Pydantic schemas for Camera and Media Sources.
"""
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator

SourceType = Literal["camera", "video", "image"]


def _resolve_partition(camera_id: str) -> int:
    """Extract numeric suffix or default to 0."""
    match = re.search(r'(\d+)$', camera_id.strip())
    return int(match.group(1)) if match else 0


class CameraSource(BaseModel):
    """
    Representation of a registered Camera / Media Source.
    """
    camera_id: str = Field(..., description="Unique ID (e.g., 'cam_1', 'video_01', 'img_batch_1')")
    name: str = Field(..., description="Human readable name (e.g., 'North Gate Camera')")
    source_type: SourceType = Field(default="camera", description="Type of source: 'camera', 'video', or 'image'")
    rtsp_url: str = Field(..., description="RTSP URL, video file path, image file URI, or test pattern")
    fps: int = Field(default=25, description="Target processing FPS")
    resolution: str = Field(default="1920x1080", description="Stream resolution 'WIDTHxHEIGHT'")
    partition: int = Field(default=None, description="Assigned Kafka partition (auto-derived if None)")
    is_active: bool = Field(default=True, description="Whether stream/ingestion is active")
    features: List[str] = Field(
        default_factory=lambda: ["speed_calculation", "roi_detection"],
        description="Assigned vision analysis pipelines"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata (e.g. ROI coordinates, calibration)")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("partition", mode="before")
    def set_partition(cls, v, info):
        if v is None and "camera_id" in info.data:
            return _resolve_partition(info.data["camera_id"])
        return v if v is not None else 0

    @field_validator("source_type", mode="before")
    def normalize_source_type(cls, v):
        if isinstance(v, str):
            v_low = v.lower().strip()
            if v_low in ("cam", "rtsp", "live", "webcam"):
                return "camera"
            if v_low in ("video", "file", "mp4", "mkv", "avi"):
                return "video"
            if v_low in ("image", "img", "jpg", "png", "jpeg"):
                return "image"
            return v_low
        return v or "camera"


class CameraCreateRequest(BaseModel):
    rtsp_url: str = Field(..., description="RTSP URL or video stream endpoint (ONLY REQUIRED FIELD)")
    name: Optional[str] = Field(default="Camera Stream", description="Human-readable camera location name")
    camera_id: Optional[str] = Field(default=None, description="Optional. Auto-locked from decrypted license if omitted")
    source_type: Optional[SourceType] = Field(default="camera", description="'camera', 'video', or 'image'")
    fps: Optional[int] = Field(default=25)
    resolution: Optional[str] = Field(default="1920x1080")
    partition: Optional[int] = Field(default=None)
    is_active: Optional[bool] = Field(default=True)
    features: Optional[List[str]] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)

    model_config = {
        "json_schema_extra": {
            "example": {
                "camera_id": "cam_1",
                "rtsp_url": "rtsp://admin:password@192.168.1.100:554/stream1",
                "name": "Main Gate Camera"
            }
        }
    }

    @field_validator("source_type", mode="before")
    def normalize_source_type(cls, v):
        if isinstance(v, str):
            v_low = v.lower().strip()
            if v_low in ("cam", "rtsp", "live", "webcam"):
                return "camera"
            if v_low in ("video", "file", "mp4", "mkv", "avi"):
                return "video"
            if v_low in ("image", "img", "jpg", "png", "jpeg"):
                return "image"
            return v_low
        return v or "camera"


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    source_type: Optional[SourceType] = None
    rtsp_url: Optional[str] = None
    fps: Optional[int] = None
    resolution: Optional[str] = None
    partition: Optional[int] = None
    is_active: Optional[bool] = None
    features: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("source_type", mode="before")
    def normalize_source_type(cls, v):
        if isinstance(v, str):
            v_low = v.lower().strip()
            if v_low in ("cam", "rtsp", "live", "webcam"):
                return "camera"
            if v_low in ("video", "file", "mp4", "mkv", "avi"):
                return "video"
            if v_low in ("image", "img", "jpg", "png", "jpeg"):
                return "image"
            return v_low
        return v
