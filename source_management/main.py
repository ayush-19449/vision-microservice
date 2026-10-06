"""
Source Management FastAPI Web Service.
Exposes REST endpoints for Camera CRUD, health checks, and Swagger UI.
"""
import os
import sys
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from source_management.routes import router as camera_router
from source_management.camera_service import get_camera_service

app = FastAPI(
    title="Vision Source Management Service",
    description="REST API for Camera Stream Registration, Partition Mapping & Metadata CRUD",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(camera_router)


@app.get("/health", tags=["Health"])
def health_check():
    svc = get_camera_service()
    cameras = svc.list_cameras()
    return {
        "status": "healthy",
        "service": "source_management",
        "total_cameras": len(cameras),
        "active_cameras": len([c for c in cameras if c.is_active])
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8001))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("source_management.main:app", host=host, port=port, reload=False)
