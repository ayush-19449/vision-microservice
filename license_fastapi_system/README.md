# Camera License Microservice (.gry)

A production-ready, standalone **FastAPI** license generation and hardware-verification service using **AES-256-GCM** authenticated encryption.

---

## 📁 Files Included

| File | Purpose |
|---|---|
| `main.py` | **FastAPI Server** (`/generate`, `/verify`, `/verify-file`, `/download`, `/docs`). |
| `license_config.py` | Shared engine for **AES-256-GCM** encryption/decryption & hardware MAC detection. |
| `create_license.py` | CLI tool to create encrypted `.gry` license files. |
| `verify_license.py` | CLI tool to decrypt and verify `.gry` files against host MAC address. |
| `run_demo.py` | 1-Click interactive test runner demonstrating all 4 test cases. |
| `camera.gry` | Pre-generated sample encrypted license file. |
| `requirements.txt` | Python dependencies. |
| `Dockerfile` | Container specification for FastAPI service. |
| `docker-compose.yml` | Multi-container compose configuration. |

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the FastAPI Web Service & Swagger UI
```bash
python main.py
```
Open your browser to:
👉 **http://127.0.0.1:8000/docs**

---

### 3. Run the 1-Click CLI Demo
```bash
python run_demo.py
```
Demonstrates:
- **Scenario 1:** Valid License (Matching Host MAC) -> **PASS**
- **Scenario 2:** License Locked to Another MAC -> **REJECTED (MAC_ADDRESS_MISMATCH)**
- **Scenario 3:** Expired License -> **REJECTED (LICENSE_EXPIRED)**
- **Scenario 4:** Tampered Ciphertext -> **REJECTED (LICENSE_DECRYPTION_FAILED)**

---

### 4. Run with Docker
```bash
docker-compose up --build
```
Access the containerized API at `http://localhost:8000/docs`.
