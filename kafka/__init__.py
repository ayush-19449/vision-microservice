"""
Kafka Reusable Layer for Vision Microservices.
Provides enterprise-grade, high-throughput confluent-kafka Producer, Consumer,
and Camera-to-Partition resolution.
"""

from .config import KafkaConfig, resolve_camera_partition
from .producer import VisionKafkaProducer
from .consumer import VisionKafkaConsumer, FramePacket

__all__ = [
    "KafkaConfig",
    "resolve_camera_partition",
    "VisionKafkaProducer",
    "VisionKafkaConsumer",
    "FramePacket",
]
