"""
File 1: create_license.py
Creates an encrypted license file (.lic) bound to a hardware MAC address.
"""
import sys
import argparse
from datetime import datetime, timezone, timedelta
from license_config import get_system_mac_address, normalize_mac, encrypt_license_data

def create_license_file(
    output_file: str = "camera.gry",
    camera_id: str = "cam_1",
    camera_name: str = "Office_Main_Gate",
    features: list = None,
    mac_address: str = None,
    days_valid: int = 365,
    container_name: str = "cam001-container",
    topic: str = "camera.frames",
    partition: int = None
):
    """
    Generates a cryptographically signed & encrypted .gry license.
    Locks Camera ID, Camera Name, Authorized AI Features, and Machine Hardware MAC.
    User configures their site RTSP URL separately via Source Management API.
    """
    # Auto-assign partition from camera_id if not provided
    if partition is None:
        import re
        match = re.search(r'(\d+)$', camera_id)
        partition = int(match.group(1)) if match else 0

    # If no MAC specified, auto-detect current PC's physical MAC
    target_mac = normalize_mac(mac_address) if mac_address else get_system_mac_address()

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=days_valid)
    allowed_features = features if features is not None else ["speed_calculation", "roi_detection", "vehicle_counter", "anpr", "face_detection"]

    license_payload = {
        "license_id": f"LIC-{int(now.timestamp())}",
        "camera_id": camera_id,
        "camera_name": camera_name,
        "features": allowed_features,
        "mac_address": target_mac,
        "container_name": container_name,
        "topic": topic,
        "partition": partition,
        "issued_at": now.isoformat(),
        "expires_at": expiry.isoformat(),
        "version": "1.0"
    }

    print("\n" + "="*50)
    print(" [INFO] GENERATING NEW HARDWARE-LOCKED LICENSE")
    print("="*50)
    print(f" - License ID    : {license_payload['license_id']}")
    print(f" - Licensed Cam  : {license_payload['camera_id']} ('{license_payload['camera_name']}')")
    print(f" - Target MAC    : {license_payload['mac_address']}")
    print(f" - Features      : {', '.join(license_payload['features'])}")
    print(f" - Kafka Topic   : {license_payload['topic']} (partition {license_payload['partition']})")
    print(f" - Valid Until   : {license_payload['expires_at']}")
    print("="*50)

    encrypted_blob = encrypt_license_data(license_payload)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(encrypted_blob)

    print(f"\n[+] Success! Encrypted license written to: '{output_file}'")
    print(f" - Ciphertext Preview: {encrypted_blob[:35]}... (AES-256-GCM)")
    return output_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create encrypted camera license file (.gry)")
    parser.add_argument("--out", default="camera.gry", help="Output .gry file path")
    parser.add_argument("--camera", default="cam-001", help="Camera ID (e.g. cam-001, cam-002)")
    parser.add_argument("--cam-name", default="Office_Main_Gate", help="Human-readable Camera Name")
    parser.add_argument("--mac", default=None, help="Target MAC address (defaults to this machine's MAC)")
    parser.add_argument("--days", type=int, default=365, help="Number of days valid")
    parser.add_argument("--partition", type=int, default=None,
                        help="Kafka partition (auto-assigned from camera ID if not provided)")
    args = parser.parse_args()

    create_license_file(
        output_file=args.out,
        camera_id=args.camera,
        camera_name=args.cam_name,
        mac_address=args.mac,
        days_valid=args.days,
        partition=args.partition
    )
