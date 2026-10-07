"""
Comprehensive Vision Ecosystem Test Suite.
Tests:
1. Service Catalog & services.yml (including ServiceNotFoundError)
2. Source Management Camera CRUD
3. Kafka Partition Resolvers & Frame Serialization
4. MinIO S3 Object Storage Upload & Retrieval
5. AES-256-GCM Hardware License Encryption/Decryption/Tamper Resistance
6. End-to-End Orchestrator Service Spawning with GPU/CPU Resources
"""
import os
import sys
import json
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "license_fastapi_system")))

from service_management.service_catalog import get_service_catalog, ServiceNotFoundError
from source_management.camera_service import get_camera_service
from source_management.models import CameraCreateRequest, CameraUpdateRequest
from kafka.config import resolve_camera_partition, pack_frame_message, unpack_frame_message
from storage.minio_client import get_minio_storage
from create_license import create_license_file
from license_config import decrypt_license_data
from service_management.orchestrator import VisionOrchestrator


class TestVisionEcosystem(unittest.TestCase):

    def setUp(self):
        self.catalog = get_service_catalog()
        self.camera_service = get_camera_service()
        self.storage = get_minio_storage()

    # ==========================================================================
    # 1. Service Catalog & YAML Tests
    # ==========================================================================
    def test_01_catalog_loaded_services(self):
        """Verify all 6 core services are parsed from services.yml."""
        for name in ["vehicle_detection", "anpr", "speed_detection", "roi_detection", "face_detection", "vehicle_counter"]:
            spec = self.catalog.get_spec(name)
            self.assertIsNotNone(spec, f"Service '{name}' should be loaded in catalog")
            self.assertTrue(len(spec.docker_image) > 0)
            self.assertIsNotNone(spec.resources)
        print("  [PASS] Test 1.1: All services loaded from services.yml")

    def test_02_catalog_dependency_resolution(self):
        """Verify topological dependency resolution: anpr -> [vehicle_detection, anpr]."""
        deps = self.catalog.resolve_dependencies(["anpr"])
        self.assertEqual(deps, ["vehicle_detection", "anpr"])

        multi_deps = self.catalog.resolve_dependencies(["speed_detection", "anpr"])
        self.assertEqual(multi_deps[0], "vehicle_detection")
        self.assertIn("speed_detection", multi_deps)
        self.assertIn("anpr", multi_deps)
        print("  [PASS] Test 1.2: Dependency resolution (ANPR -> vehicle_detection -> anpr)")

    def test_03_catalog_raises_service_not_found(self):
        """Verify ServiceNotFoundError is raised when service is missing in services.yml."""
        with self.assertRaises(ServiceNotFoundError):
            self.catalog.get_spec("unknown_model_v9", strict=True)

        with self.assertRaises(ServiceNotFoundError):
            self.catalog.resolve_dependencies(["unknown_pipeline_xyz"])
        print("  [PASS] Test 1.3: ServiceNotFoundError correctly raised for undeclared services")

    # ==========================================================================
    # 2. Source Management Camera CRUD Tests
    # ==========================================================================
    def test_04_camera_crud_lifecycle(self):
        """Test complete CRUD cycle for Camera sources."""
        test_cam_id = "test_cam_99"
        
        # Cleanup if left over
        self.camera_service.delete_camera(test_cam_id)

        # Create
        created = self.camera_service.create_camera(CameraCreateRequest(
            camera_id=test_cam_id,
            name="Test_Camera_99",
            rtsp_url="rtsp://127.0.0.1:8554/test99",
            fps=30,
            features=["anpr", "vehicle_counter"]
        ), enforce_license=False)
        self.assertEqual(created.camera_id, test_cam_id)
        self.assertEqual(created.partition, 99)

        # Read
        fetched = self.camera_service.get_camera(test_cam_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Test_Camera_99")

        # Update
        updated = self.camera_service.update_camera(test_cam_id, CameraUpdateRequest(
            name="Updated_Camera_99_Name",
            fps=60
        ))
        self.assertEqual(updated.name, "Updated_Camera_99_Name")
        self.assertEqual(updated.fps, 60)

        # Delete
        deleted = self.camera_service.delete_camera(test_cam_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.camera_service.get_camera(test_cam_id))
        print("  [PASS] Test 2: Source Management Camera CRUD lifecycle")

    # ==========================================================================
    # 3. Kafka Partitioning & Frame Serialization Tests
    # ==========================================================================
    def test_05_kafka_partition_mapping(self):
        """Verify strict camera_id -> partition resolution."""
        self.assertEqual(resolve_camera_partition("cam_1"), 1)
        self.assertEqual(resolve_camera_partition("cam_2"), 2)
        self.assertEqual(resolve_camera_partition("cam-005"), 5)
        self.assertEqual(resolve_camera_partition(10), 10)
        print("  [PASS] Test 3.1: Kafka camera_id -> Partition mapping")

    def test_06_kafka_binary_frame_packing(self):
        """Test zero-overhead binary frame protocol serialization."""
        fake_frame = b"\xff\xd8\xff\xe0TEST_JPEG_DATA\xff\xd9"
        packed = pack_frame_message(
            frame_bytes=fake_frame,
            camera_id="cam_1",
            frame_id=12345,
            timestamp_ms=1791312000000.0,
            width=1920,
            height=1080,
            codec="JPEG"
        )
        unpacked = unpack_frame_message(packed)
        self.assertEqual(unpacked["camera_id"], "cam_1")
        self.assertEqual(unpacked["frame_id"], 12345)
        self.assertEqual(unpacked["width"], 1920)
        self.assertEqual(unpacked["height"], 1080)
        self.assertEqual(unpacked["frame_bytes"], fake_frame)
        print("  [PASS] Test 3.2: Kafka binary frame pack/unpack protocol")

    # ==========================================================================
    # 4. MinIO S3 Object Storage Tests
    # ==========================================================================
    def test_07_minio_frame_storage(self):
        """Test MinIO S3 frame upload, path generation, and retrieval."""
        test_frame = b"\xff\xd8\xff\xe0MINIO_TEST_BUFFER\xff\xd9"
        res = self.storage.upload_frame(
            camera_id="cam_1",
            frame_id=9001,
            frame_bytes=test_frame,
            timestamp_ms=1791312500000.0
        )
        self.assertIn("frames/cam_1/", res["key"])
        self.assertIn("s3://vision-frames/", res["s3_uri"])
        self.assertEqual(res["file_size_bytes"], len(test_frame))

        # Retrieve
        downloaded = self.storage.download_frame(res["key"])
        self.assertEqual(downloaded, test_frame)
        print("  [PASS] Test 4: MinIO S3 frame upload & download")

    # ==========================================================================
    # 5. AES-256-GCM Hardware License Tests
    # ==========================================================================
    def test_08_hardware_license_encryption_tamper(self):
        """Test AES-256-GCM encryption, MAC binding, and tamper resistance."""
        lic_file = "test_lic.gry"
        create_license_file(
            output_file=lic_file,
            service_name="test_service",
            features=["anpr", "speed_detection"]
        )
        self.assertTrue(os.path.exists(lic_file))

        with open(lic_file, "r") as f:
            encrypted = f.read().strip()

        # Decrypt valid
        payload = decrypt_license_data(encrypted)
        self.assertEqual(payload["service_name"], "test_service")
        self.assertIn("anpr", payload["features"])

        # Tampered ciphertext check
        tampered = encrypted[:-4] + "AAAA"
        with self.assertRaises(ValueError):
            decrypt_license_data(tampered)

        if os.path.exists(lic_file):
            os.remove(lic_file)
        print("  [PASS] Test 5: AES-256-GCM Hardware License encryption & tamper check")

    # ==========================================================================
    # 6. End-to-End Orchestrator Spawning with GPU/CPU Specs
    # ==========================================================================
    def test_09_orchestrator_end_to_end(self):
        """Test Orchestrator reading license, resolving YAML dependencies, and spawning workers."""
        test_cam_id = "cam_orch_test_01"
        self.camera_service.delete_camera(test_cam_id)
        self.camera_service.create_camera(CameraCreateRequest(
            camera_id=test_cam_id,
            name="Orchestrator Test Camera",
            rtsp_url="rtsp://127.0.0.1:8554/orchtest",
            features=["anpr", "speed_detection"]
        ), enforce_license=False)

        lic_file = "test_orch_lic.gry"
        create_license_file(
            output_file=lic_file,
            service_name="orch_test_service",
            features=["anpr", "speed_detection"]
        )

        orch = VisionOrchestrator(license_path=lic_file)
        res = orch.orchestrate()

        self.assertEqual(res["status"], "success")
        self.assertIn(f"{test_cam_id}_vehicle_detection_worker", res["services_spawned"])
        self.assertIn(f"{test_cam_id}_anpr_worker", res["services_spawned"])
        self.assertIn(f"{test_cam_id}_speed_detection_worker", res["services_spawned"])

        # Check resource limits were passed
        v_det = res["active_services"][f"{test_cam_id}_vehicle_detection_worker"]
        self.assertEqual(v_det["resources"]["cpu"], "2.0")
        self.assertEqual(v_det["resources"]["memory"], "4G")
        self.assertTrue(v_det["resources"]["gpu_enabled"])

        # Cleanup
        self.camera_service.delete_camera(test_cam_id)
        if os.path.exists(lic_file):
            os.remove(lic_file)
        print("  [PASS] Test 6: End-to-end Orchestration & GPU/CPU worker provisioning")


if __name__ == "__main__":
    print("\n" + "=" * 65)
    print(" RUNNING INTEGRATION & UNIT TEST SUITE FOR VISION PLATFORM")
    print("=" * 65 + "\n")
    unittest.main(verbosity=2)
