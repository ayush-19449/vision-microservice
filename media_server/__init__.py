"""
Media Server Module for Video Ingestion.
Uses GStreamer pipelines to capture RTSP/camera feeds and streams frames to Kafka partitions.
"""

from .gstreamer_pipeline import GStreamerPipelineBuilder, build_rtsp_pipeline, build_test_pipeline
from .frame_ingestor import CameraFrameIngestor, MediaServerManager

__all__ = [
    "GStreamerPipelineBuilder",
    "build_rtsp_pipeline",
    "build_test_pipeline",
    "CameraFrameIngestor",
    "MediaServerManager",
]
