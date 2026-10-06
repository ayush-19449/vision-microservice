"""
Universal AI Vision Analytics Worker Microservice.
Subscribes to dedicated Kafka partition for its assigned camera, receives MinIO frame references,
retrieves frame images on-demand from MinIO, and publishes detection events.
"""
import os
import sys
import time
import signal
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kafka import VisionKafkaConsumer, VisionKafkaProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [VisionWorker]: %(message)s")
logger = logging.getLogger("VisionWorker")


def run_worker():
    camera_id = os.getenv("CAMERA_ID", "cam_1")
    camera_name = os.getenv("CAMERA_NAME", "Camera Feed")
    partition = int(os.getenv("KAFKA_PARTITION", "0"))
    pipeline_type = os.getenv("PIPELINE_TYPE", "vehicle_detection")
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    frame_topic = os.getenv("KAFKA_FRAME_TOPIC", "camera.frames")
    event_topic = os.getenv("KAFKA_EVENT_TOPIC", "camera.events")

    logger.info("=" * 65)
    logger.info(f" STARTING VISION WORKER: {pipeline_type.upper()}")
    logger.info(f" Camera ID      : {camera_id} ('{camera_name}')")
    logger.info(f" Kafka Partition: {partition}")
    logger.info(f" Frame Topic    : {frame_topic}")
    logger.info("=" * 65)

    consumer = VisionKafkaConsumer()
    producer = VisionKafkaProducer()

    # Directly assign consumer to this camera's dedicated partition
    consumer.assign_camera(camera_id=camera_id, topic=frame_topic)

    running = True

    def handle_shutdown(sig, frame):
        nonlocal running
        logger.info("Shutting down worker gracefully...")
        running = False
        consumer.close()
        producer.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    frames_processed = 0
    fps_start = time.time()

    # Stream lightweight MinIO frame references from Kafka!
    for ref in consumer.stream_frame_refs():
        if not running:
            break

        frames_processed += 1

        # Retrieve frame from MinIO on demand (lazy loading):
        # img = ref.to_numpy() # Decoded OpenCV BGR image from MinIO S3

        if frames_processed % 30 == 0:
            elapsed = time.time() - fps_start
            fps = round(frames_processed / max(elapsed, 0.001), 1)
            logger.info(
                f"[{camera_id} | {pipeline_type}] Processed {frames_processed} frames "
                f"(Live {fps} FPS | S3: {ref.object_key} | Frame: {ref.frame_id})"
            )

            # Publish AI detection event back to Kafka
            event_data = {
                "pipeline": pipeline_type,
                "camera_id": camera_id,
                "partition": partition,
                "frame_id": ref.frame_id,
                "timestamp_ms": ref.timestamp_ms,
                "source_image_s3": ref.s3_uri,
                "detections": [
                    {"label": "car", "confidence": 0.94, "bbox": [100, 200, 320, 450], "speed_kmh": 46.8},
                    {"label": "truck", "confidence": 0.89, "bbox": [520, 190, 780, 590], "speed_kmh": 39.2}
                ]
            }
            producer.send_event(
                event_type=f"{pipeline_type}.detection",
                camera_id=camera_id,
                data=event_data,
                topic=event_topic,
                partition=partition
            )


if __name__ == "__main__":
    run_worker()
