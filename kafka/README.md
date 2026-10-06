# Reusable Vision Kafka Layer (`/kafka`)

A production-grade, high-throughput video frame and event streaming library built with **`confluent-kafka`**.

---

## 🚀 Key Features

1. **Automatic Camera $\rightarrow$ Partition Routing**:
   - `cam_1` / `cam-001` automatically routes to Kafka Partition `1`.
   - Guaranteed ordered frame ingestion per camera without lock contention.
2. **Compact Binary Frame Packaging**:
   - Sends frames with a custom binary header (Magic bytes, Timestamp, Frame ID, Dimensions, Codec) followed by the JPEG/raw buffer.
   - Zero JSON overhead for high FPS video streams.
3. **Dedicated Camera Consumer**:
   - Direct partition assignment (`assign_camera("cam_1")`) enables vision workers to subscribe directly to a camera partition with no group rebalance delays.
4. **Structured Event Producer**:
   - Seamlessly dispatches analytics events (detections, speed violations, ROI alerts).

---

## 📦 How to Use in Any Vision Microservice

### 1. Send Frames (e.g. Media Server / Ingestor)
```python
from kafka import VisionKafkaProducer

producer = VisionKafkaProducer()

# Read JPEG bytes from camera
with open("frame.jpg", "rb") as f:
    frame_bytes = f.read()

# Automatically sends to Partition 1
producer.send_frame(
    camera_id="cam_1",
    frame_bytes=frame_bytes,
    frame_id=101,
    width=1920,
    height=1080,
    codec="JPEG"
)
```

### 2. Consume Frames (e.g. Analytics / AI Service)
```python
from kafka import VisionKafkaConsumer

consumer = VisionKafkaConsumer()
# Lock this worker directly to camera 1's partition
consumer.assign_camera("cam_1")

# Process frames as they arrive
for packet in consumer.stream_frames():
    img = packet.to_numpy()  # Automatically converts to OpenCV BGR image
    print(f"Received frame {packet.frame_id} from {packet.camera_id} (size: {packet.width}x{packet.height})")
    
    # Run YOLO / OpenCV pipeline here...
```

---

## ⚙️ Environment Variables (Optional)

| Variable | Default | Description |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `KAFKA_FRAME_TOPIC` | `camera.frames` | Topic for raw/JPEG video frames |
| `KAFKA_EVENT_TOPIC` | `camera.events` | Topic for analytics & detections |
| `KAFKA_ALERT_TOPIC` | `camera.alerts` | Topic for urgent alarms |
| `KAFKA_COMPRESSION_TYPE` | `lz4` | Message compression (`lz4`, `snappy`, `none`) |
