# 🚀 AI Vision & Camera Microservices Platform

An enterprise-grade, fully Dockerized computer vision streaming, licensing, and orchestration platform.

---

## 🏗️ Architecture & Services

```
┌────────────────────────────────────────────────────────────────────────┐
│                          DOCKER COMPOSE STACK                          │
├───────────────────┬───────────────────┬────────────────────────────────┤
│ 📹 Media Server   │ 📡 Kafka Broker   │ 🎛️ Kafka Web UI                │
│    (GStreamer     │    (KRaft Engine, │    (Visual Topics/Partitions)  │
│     RTSP Ingest)  │     High-Through) │    Port: 8080                  │
├───────────────────┼───────────────────┼────────────────────────────────┤
│ 🔐 License API    │ 📂 Source CRUD    │ ⚡ Service Orchestrator        │
│    (AES-256-GCM)  │    (Cameras DB)   │    (Auto-Spawns AI Workers)    │
│    Port: 8000     │    Port: 8001     │    Port: 8002                  │
└───────────────────┴───────────────────┴────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│        AUTO-SPAWNED AI WORKERS (Topological Dependency Resolution)      │
│  - cam_1_vehicle_detection_worker (Base detector / GPU: all / 4GB RAM) │
│  - cam_1_anpr_worker              (OCR engine   / GPU: all / 4GB RAM)  │
│  - cam_1_speed_worker             (Homography   / CPU: 2.0 / 2GB RAM)  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🌐 Port Mappings & Endpoints

| Service | Port | Description | Swagger / Web URL |
|---|---|---|---|
| **Kafka Web UI** | `8080` | Real-time visual dashboard for topics, messages, & partitions | 👉 `http://localhost:8080` |
| **License Microservice** | `8000` | AES-256-GCM license generation & verification | 👉 `http://localhost:8000/docs` |
| **Source Management** | `8001` | Camera CRUD API, RTSP configs, and partition mapping | 👉 `http://localhost:8001/docs` |
| **Service Orchestrator**| `8002` | Automated container lifecycle manager & hardware enforcer | 👉 `http://localhost:8002/docs` |
| **Apache Kafka** | `9092` / `29092` | High-throughput video frame broker | `localhost:29092` |

---

## 🚀 1-Click Launch with Docker Compose

### 1. Start the entire ecosystem
```bash
docker compose up --build -d
```

### 2. View running containers & logs
```bash
docker compose ps
docker compose logs -f service-orchestrator
```

### 3. Check Kafka Web UI
Open your browser to:
👉 **`http://localhost:8080`**

---

## 📁 Directory Structure

```
d:\vision/
├── docker-compose.yml              # Master multi-container compose file
├── .env.example                    # Environment template
│
├── kafka/                          # Reusable confluent-kafka layer (Producer/Consumer)
│   ├── config.py
│   ├── producer.py
│   └── consumer.py
│
├── source_management/              # Camera CRUD microservice
│   ├── Dockerfile
│   ├── main.py
│   ├── camera_service.py
│   └── cameras.json
│
├── media_server/                   # GStreamer video ingestion service
│   ├── Dockerfile
│   ├── main.py
│   ├── gstreamer_pipeline.py
│   └── frame_ingestor.py
│
├── service_management/             # Master orchestrator & license decryptor
│   ├── Dockerfile
│   ├── main.py
│   ├── services.yml               # Declarative service, dependency & GPU catalog
│   ├── orchestrator.py
│   └── container_manager.py
│
├── license_fastapi_system/         # Core AES-256-GCM cryptography & license generator
│   ├── Dockerfile
│   └── main.py
│
└── workers/                        # Vision worker container templates
    ├── Dockerfile
    └── base_worker.py
```
