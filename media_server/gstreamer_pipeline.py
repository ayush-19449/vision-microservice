"""
GStreamer Pipeline Builder for RTSP, Video Files, Webcams, and Test Patterns.
Optimized for OpenCV cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER) integration.
"""
import sys
from typing import Optional


class GStreamerPipelineBuilder:
    """
    Constructs high-performance GStreamer pipelines for video capture and decoding.
    """

    @staticmethod
    def build_rtsp_pipeline(
        rtsp_url: str,
        latency_ms: int = 200,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        use_hardware_accel: bool = False
    ) -> str:
        """
        Builds an optimized RTSP ingestion GStreamer pipeline string for appsink.
        """
        decoder = "nvh264dec" if use_hardware_accel else "avdec_h264"
        
        # Robust GStreamer string for OpenCV cv2.VideoCapture
        pipeline = (
            f"rtspsrc location={rtsp_url} latency={latency_ms} drop-on-latency=true "
            f"! rtph264depay ! h264parse ! {decoder} "
            f"! videoconvert ! video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1 "
            f"! appsink drop=true max-buffers=2 sync=false"
        )
        return pipeline

    @staticmethod
    def build_test_pipeline(
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        pattern: str = "smpte"
    ) -> str:
        """
        Builds a synthetic videotestsrc pipeline for debugging without physical cameras.
        Patterns: smpte, snow, ball, red, green, blue.
        """
        return (
            f"videotestsrc pattern={pattern} is-live=true "
            f"! video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1 "
            f"! appsink drop=true max-buffers=2 sync=false"
        )

    @staticmethod
    def build_file_pipeline(file_path: str, width: int = 1920, height: int = 1080) -> str:
        """
        Builds a GStreamer pipeline for local video files (.mp4, .mkv, .avi).
        """
        return (
            f"filesrc location=\"{file_path}\" ! decodebin "
            f"! videoconvert ! video/x-raw,format=BGR,width={width},height={height} "
            f"! appsink drop=true max-buffers=2 sync=false"
        )

    @staticmethod
    def build_webcam_pipeline(device_index: int = 0, width: int = 1280, height: int = 720) -> str:
        """
        Builds a GStreamer pipeline for USB webcams (Windows / Linux).
        """
        src = "mfvideosrc" if sys.platform == "win32" else f"v4l2src device=/dev/video{device_index}"
        return (
            f"{src} ! videoconvert ! video/x-raw,format=BGR,width={width},height={height} "
            f"! appsink drop=true max-buffers=2 sync=false"
        )


def build_rtsp_pipeline(rtsp_url: str, **kwargs) -> str:
    return GStreamerPipelineBuilder.build_rtsp_pipeline(rtsp_url, **kwargs)


def build_test_pipeline(**kwargs) -> str:
    return GStreamerPipelineBuilder.build_test_pipeline(**kwargs)
