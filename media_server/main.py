"""
Media Server Video Ingestion Daemon.
Connects to Source Management registry, starts GStreamer RTSP ingestion for each active camera,
and streams encoded frames to Kafka partitions.
"""
import os
import sys
import time
import signal
import logging
import requests
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from media_server.frame_ingestor import MediaServerManager
from source_management.camera_service import get_camera_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [MediaServer]: %(message)s")
logger = logging.getLogger("MediaServer")


def get_active_cameras() -> List[Dict[str, Any]]:
    """Fetches cameras from Source Management API or direct fallback."""
    api_url = os.getenv("SOURCE_MANAGEMENT_URL", "http://source-management:8001/sources/cameras?active_only=true")
    try:
        res = requests.get(api_url, timeout=3)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass

    # Local fallback
    try:
        svc = get_camera_service()
        return [c.model_dump() for c in svc.list_cameras(active_only=True)]
    except Exception as e:
        logger.error(f"Error fetching cameras: {e}")
        return []


def main():
    logger.info("=" * 60)
    logger.info(" STARTING MEDIA SERVER GSTREAMER INGESTION SERVICE")
    logger.info("=" * 60)

    manager = MediaServerManager()
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("Received termination signal. Stopping all camera streams...")
        running = False
        manager.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Polling loop to dynamically sync cameras
    sync_interval = int(os.getenv("SYNC_INTERVAL_SEC", "10"))

    while running:
        cameras = get_active_cameras()
        active_ids = {c["camera_id"] for c in cameras}

        # Start newly registered cameras
        for cam in cameras:
            cam_id = cam["camera_id"]
            if cam_id not in manager.ingestors:
                logger.info(f"Starting ingestion for new camera '{cam_id}' -> Partition {cam.get('partition')} (RTSP: {cam.get('rtsp_url')})")
                manager.start_camera_stream(
                    camera_id=cam_id,
                    rtsp_url=cam.get("rtsp_url"),
                    partition=cam.get("partition"),
                    target_fps=cam.get("fps", 25),
                    use_test_source=os.getenv("USE_TEST_STREAM", "false").lower() == "true"
                )

        # Stop deleted/deactivated cameras
        for existing_id in list(manager.ingestors.keys()):
            if existing_id not in active_ids:
                logger.info(f"Stopping ingestion for inactive/removed camera '{existing_id}'")
                manager.stop_camera_stream(existing_id)

        time.sleep(sync_interval)


if __name__ == "__main__":
    main()
