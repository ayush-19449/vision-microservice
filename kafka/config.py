"""
Kafka Configuration & Helpers for Computer Vision Pipelines.
Provides central settings, partition routing, and librdkafka tuning.
"""
import os
import re
import struct
import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple


@dataclass
class KafkaConfig:
    """
    Centralized Kafka configuration loaded from environment or default parameters.
    Tuned for high-throughput video frame streaming and low-latency event processing.
    """
    bootstrap_servers: str = field(
        default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    )
    frame_topic: str = field(
        default_factory=lambda: os.getenv("KAFKA_FRAME_TOPIC", "camera.frames")
    )
    event_topic: str = field(
        default_factory=lambda: os.getenv("KAFKA_EVENT_TOPIC", "camera.events")
    )
    alert_topic: str = field(
        default_factory=lambda: os.getenv("KAFKA_ALERT_TOPIC", "camera.alerts")
    )
    
    # Message max size (default 10MB to easily accommodate uncompressed/JPEG 4K frames)
    max_message_bytes: int = int(os.getenv("KAFKA_MAX_MESSAGE_BYTES", 10 * 1024 * 1024))
    
    # Compression codec: lz4, snappy, gzip, or none (lz4 recommended for real-time video)
    compression_type: str = os.getenv("KAFKA_COMPRESSION_TYPE", "lz4")
    
    # Batching and throughput tuning
    linger_ms: int = int(os.getenv("KAFKA_LINGER_MS", "5"))
    batch_num_messages: int = int(os.getenv("KAFKA_BATCH_NUM_MESSAGES", "50"))
    queue_buffering_max_messages: int = int(os.getenv("KAFKA_QUEUE_BUFFERING_MAX_MESSAGES", "100000"))
    queue_buffering_max_kbytes: int = int(os.getenv("KAFKA_QUEUE_BUFFERING_MAX_KBYTES", "1048576")) # 1GB
    
    # Producer delivery reliability: "1" (leader ack) or "all"
    acks: str = os.getenv("KAFKA_ACKS", "1")

    def get_producer_config(self, client_id: str = "vision-producer") -> Dict[str, Any]:
        """Returns librdkafka-compatible dictionary configuration for producer."""
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "client.id": client_id,
            "message.max.bytes": self.max_message_bytes,
            "compression.type": self.compression_type,
            "linger.ms": self.linger_ms,
            "batch.num.messages": self.batch_num_messages,
            "queue.buffering.max.messages": self.queue_buffering_max_messages,
            "queue.buffering.max.kbytes": self.queue_buffering_max_kbytes,
            "acks": self.acks,
            # Handle socket reconnections smoothly
            "socket.keepalive.enable": True,
            "socket.timeout.ms": 10000,
        }

    def get_consumer_config(
        self,
        group_id: str = "vision-consumer-group",
        auto_offset_reset: str = "latest",
        enable_auto_commit: bool = True
    ) -> Dict[str, Any]:
        """Returns librdkafka-compatible dictionary configuration for consumer."""
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": enable_auto_commit,
            "message.max.bytes": self.max_message_bytes,
            "fetch.message.max.bytes": self.max_message_bytes,
            "max.partition.fetch.bytes": self.max_message_bytes,
            "session.timeout.ms": 15000,
            "socket.keepalive.enable": True,
        }


def resolve_camera_partition(camera_id: str or int, max_partitions: Optional[int] = None) -> int:
    """
    Deterministically resolves a Camera ID to a Kafka Partition.
    
    Examples:
        - 1 -> 1
        - "1" -> 1
        - "cam_1" -> 1
        - "cam-001" -> 1
        - "camera_5" -> 5
        - "gate_north" -> hash-based partition (if non-numeric)
    
    If max_partitions is given, wraps around via modulo: partition % max_partitions.
    """
    if isinstance(camera_id, int):
        partition = camera_id
    else:
        cam_str = str(camera_id).strip()
        # Look for the last sequence of digits in string (e.g. cam-001 -> 1, cam_2 -> 2)
        match = re.search(r'(\d+)$', cam_str)
        if match:
            partition = int(match.group(1))
        else:
            # Fallback for non-numeric camera names: stable hash
            partition = abs(hash(cam_str)) % (max_partitions or 64)
            
    if max_partitions is not None and max_partitions > 0:
        return partition % max_partitions
    return partition


# ==========================================
# Binary Frame Header Packaging Protocol
# ==========================================
# Header Format:
# MAGIC (2 bytes: b'VF') + VERSION (1 byte) + CAM_ID_LEN (2 bytes) +
# FRAME_ID (8 bytes unsigned long long) + TIMESTAMP_MS (8 bytes float/double) +
# WIDTH (4 bytes uint) + HEIGHT (4 bytes uint) + CHANNELS (2 bytes uint) +
# CODEC (4 bytes ascii, e.g. 'JPEG', 'H264', 'RAW8') + CAM_ID_BYTES

MAGIC_HEADER = b'VF'  # Vision Frame
PROTOCOL_VERSION = 1
HEADER_FORMAT_PREFIX = "!2sBHQdII4s"
# !: network (big-endian)
# 2s: MAGIC
# B: version (1 byte)
# H: cam_id string byte length (2 bytes)
# Q: frame_id (8 bytes uint64)
# d: timestamp_ms (8 bytes double)
# I: width (4 bytes uint32)
# I: height (4 bytes uint32)
# 4s: codec (4 bytes string)


def pack_frame_message(
    frame_bytes: bytes,
    camera_id: str,
    frame_id: int,
    timestamp_ms: float,
    width: int,
    height: int,
    codec: str = "JPEG"
) -> bytes:
    """
    Packs a frame buffer with compact binary metadata for ultra-low latency transmission.
    """
    cam_bytes = camera_id.encode('utf-8')
    cam_len = len(cam_bytes)
    codec_bytes = codec.ljust(4)[:4].encode('ascii')
    
    header = struct.pack(
        HEADER_FORMAT_PREFIX,
        MAGIC_HEADER,
        PROTOCOL_VERSION,
        cam_len,
        frame_id,
        timestamp_ms,
        width,
        height,
        codec_bytes
    )
    return header + cam_bytes + frame_bytes


def unpack_frame_message(raw_bytes: bytes) -> Dict[str, Any]:
    """
    Unpacks a binary frame message produced by pack_frame_message.
    Returns dictionary with frame metadata and raw frame payload bytes.
    """
    prefix_size = struct.calcsize(HEADER_FORMAT_PREFIX)
    if len(raw_bytes) < prefix_size:
        raise ValueError("Payload too small for vision frame header.")
        
    magic, version, cam_len, frame_id, timestamp_ms, width, height, codec_bytes = struct.unpack_from(
        HEADER_FORMAT_PREFIX, raw_bytes, 0
    )
    
    if magic != MAGIC_HEADER:
        raise ValueError(f"Invalid magic bytes in frame payload: {magic}")
        
    cam_offset = prefix_size
    cam_id = raw_bytes[cam_offset:cam_offset + cam_len].decode('utf-8')
    
    payload_offset = cam_offset + cam_len
    frame_data = raw_bytes[payload_offset:]
    
    return {
        "camera_id": cam_id,
        "frame_id": frame_id,
        "timestamp_ms": timestamp_ms,
        "width": width,
        "height": height,
        "codec": codec_bytes.decode('ascii').strip(),
        "frame_bytes": frame_data
    }
