"""
Data models and Pydantic schemas for Camera and Media Sources.
"""
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

SourceType = Literal["rtsp", "video", "image", "camera"]


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
    source_type: SourceType = Field(default="rtsp", description="Type of source: 'rtsp', 'video', 'image', or 'camera'")
    rtsp_url: str = Field(..., description="RTSP URL, video file path, image file URI, or test pattern")
    width: Optional[int] = Field(default=1920, description="Stream frame width in pixels")
    height: Optional[int] = Field(default=1080, description="Stream frame height in pixels")
    resolution: str = Field(default="1920x1080", description="Stream resolution 'WIDTHxHEIGHT'")
    location: Optional[str] = Field(default=None, description="Optional physical location description")
    fps: int = Field(default=25, description="Target processing FPS")
    partition: int = Field(default=None, description="Assigned Kafka partition (auto-derived if None)")
    is_active: bool = Field(default=True, description="Whether stream/ingestion is active")
    features: List[str] = Field(
        default_factory=lambda: ["speed_calculation", "roi_detection"],
        description="Assigned vision analysis pipelines"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata")
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
                return "rtsp"
            if v_low in ("video", "file", "mp4", "mkv", "avi"):
                return "video"
            if v_low in ("image", "img", "jpg", "png", "jpeg"):
                return "image"
            return v_low
        return v or "rtsp"


class CameraCreateRequest(BaseModel):
    cam_id: Optional[str] = Field(default=None, description="Camera identifier (alias for camera_id)")
    camera_id: Optional[str] = Field(default=None, description="Unique camera ID (e.g. 'cam_001')")
    cam_name: Optional[str] = Field(default=None, description="Camera location name (alias for name)")
    name: Optional[str] = Field(default=None, description="Human-readable camera location name")
    source_type: Optional[str] = Field(default="rtsp", description="Source type: 'rtsp', 'image', or 'video'")
    url: Optional[str] = Field(default=None, description="Stream URL or file path (alias for rtsp_url)")
    rtsp_url: Optional[str] = Field(default=None, description="RTSP URL, video file path, or image URI")
    width: Optional[int] = Field(default=None, description="Optional frame width in pixels (e.g. 1920)")
    height: Optional[int] = Field(default=None, description="Optional frame height in pixels (e.g. 1080)")
    resolution: Optional[str] = Field(default=None, description="Resolution string 'WIDTHxHEIGHT' (e.g. '1920x1080')")
    location: Optional[str] = Field(default=None, description="Optional physical camera location")
    source_location: Optional[str] = Field(default=None, description="Optional source location alias")
    fps: Optional[int] = Field(default=25)
    partition: Optional[int] = Field(default=None)
    is_active: Optional[bool] = Field(default=True)
    features: Optional[List[str]] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)

    @model_validator(mode="before")
    def normalize_fields(cls, values):
        if not isinstance(values, dict):
            return values

        if "cam_id" in values and values["cam_id"] and "camera_id" not in values:
            values["camera_id"] = values["cam_id"]
        if "cam_name" in values and values["cam_name"] and "name" not in values:
            values["name"] = values["cam_name"]
        if "url" in values and values["url"] and "rtsp_url" not in values:
            values["rtsp_url"] = values["url"]
        if "source_location" in values and values["source_location"] and "location" not in values:
            values["location"] = values["source_location"]

        w = values.get("width")
        h = values.get("height")
        res = values.get("resolution")
        if w and h and not res:
            values["resolution"] = f"{w}x{h}"
        elif res and (not w or not h):
            match = re.match(r'^(\d+)x(\d+)$', str(res).strip(), re.I)
            if match:
                if not w: values["width"] = int(match.group(1))
                if not h: values["height"] = int(match.group(2))

        return values

    @field_validator("source_type", mode="before")
    def normalize_source_type(cls, v):
        if isinstance(v, str):
            v_low = v.lower().strip()
            if v_low in ("cam", "rtsp", "live", "webcam", "camera"):
                return "rtsp"
            if v_low in ("video", "file", "mp4", "mkv", "avi"):
                return "video"
            if v_low in ("image", "img", "jpg", "png", "jpeg"):
                return "image"
            return v_low
        return v or "rtsp"

    model_config = {
        "json_schema_extra": {
            "example": {
                "cam_id": "cam_001",
                "cam_name": "Main Gate Camera",
                "source_type": "rtsp",
                "url": "rtsp://admin:password@192.168.1.100:554/stream1",
                "width": 1920,
                "height": 1080,
                "location": "North Building Gate 1"
            }
        }
    }


class CameraUpdateRequest(BaseModel):
    cam_name: Optional[str] = None
    name: Optional[str] = None
    source_type: Optional[SourceType] = None
    url: Optional[str] = None
    rtsp_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    resolution: Optional[str] = None
    location: Optional[str] = None
    source_location: Optional[str] = None
    fps: Optional[int] = None
    partition: Optional[int] = None
    is_active: Optional[bool] = None
    features: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    def normalize_fields(cls, values):
        if not isinstance(values, dict):
            return values
        if "cam_name" in values and values["cam_name"] and "name" not in values:
            values["name"] = values["cam_name"]
        if "url" in values and values["url"] and "rtsp_url" not in values:
            values["rtsp_url"] = values["url"]
        if "source_location" in values and values["source_location"] and "location" not in values:
            values["location"] = values["source_location"]
        w = values.get("width")
        h = values.get("height")
        res = values.get("resolution")
        if w and h and not res:
            values["resolution"] = f"{w}x{h}"
        return values

    @field_validator("source_type", mode="before")
    def normalize_source_type(cls, v):
        if isinstance(v, str):
            v_low = v.lower().strip()
            if v_low in ("cam", "rtsp", "live", "webcam", "camera"):
                return "rtsp"
            if v_low in ("video", "file", "mp4", "mkv", "avi"):
                return "video"
            if v_low in ("image", "img", "jpg", "png", "jpeg"):
                return "image"
            return v_low
        return v
