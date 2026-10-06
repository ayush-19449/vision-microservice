"""
Service Management Orchestrator Web Service & Background Autonomous Reconciler.
Continuously watches hardware license files, auto-spawns vision analytics containers,
and exposes REST endpoints for orchestrator control.
"""
import os
import sys
import time
import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "license_fastapi_system")))

from service_management.orchestrator import VisionOrchestrator, get_orchestrator

app = FastAPI(
    title="Vision Service Orchestrator API",
    description="Autonomous hardware license watcher and automated container lifecycle orchestrator",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LICENSE_PATH = os.getenv("LICENSE_FILE_PATH", "/app/licenses/camera.gry")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
orchestrator = VisionOrchestrator(license_path=LICENSE_PATH, kafka_bootstrap=KAFKA_BOOTSTRAP)


@app.on_event("startup")
def on_startup():
    """Start autonomous background license watcher on container startup."""
    # Start auto watcher every 3 seconds
    orchestrator.start_auto_watcher(interval_seconds=3)


@app.on_event("shutdown")
def on_shutdown():
    orchestrator.stop_watcher()


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "healthy",
        "service": "service_orchestrator",
        "license_valid": orchestrator.license_info.is_valid if orchestrator.license_info else False,
        "active_services": len(orchestrator.active_services)
    }


@app.get("/orchestrator/status", tags=["Orchestration"])
def get_status():
    """Retrieve live orchestration state, verified license info, and running services."""
    return orchestrator.get_status()


@app.post("/orchestrator/sync", tags=["Orchestration"])
def sync_orchestration(background_tasks: BackgroundTasks):
    """Trigger manual re-evaluation and synchronization of cameras and services."""
    background_tasks.add_task(orchestrator.orchestrate)
    return {"message": "Orchestration synchronization triggered."}


@app.post("/orchestrator/stop-all", tags=["Orchestration"])
def stop_all_services():
    """Stop all running vision analytics containers."""
    orchestrator.stop_all()
    return {"message": "All vision containers stopped."}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8002))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("service_management.main:app", host=host, port=port, reload=False)
