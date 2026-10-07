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
    service_name: str = "vision_analytics_service",
    mac_address: str = None,
    start_date: str = None,
    end_date: str = None,
    days_valid: int = 365,
    features: list = None,
    **kwargs  # Ignore legacy parameters if passed
):
    """
    Generates a cryptographically signed & encrypted .gry license.
    Locks Service Name, Authorized Features, Machine Hardware MAC, and Duration (start date to end date).
    """
    # If no MAC specified, auto-detect current PC's physical MAC
    target_mac = normalize_mac(mac_address) if mac_address else get_system_mac_address()

    now = datetime.now(timezone.utc)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except Exception:
            start_dt = now
    else:
        start_dt = now

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            duration_days = (end_dt - start_dt).days
        except Exception:
            end_dt = start_dt + timedelta(days=days_valid)
            duration_days = days_valid
    else:
        end_dt = start_dt + timedelta(days=days_valid)
        duration_days = days_valid

    allowed_features = features if features is not None else ["speed_calculation", "roi_detection", "vehicle_counter", "anpr", "face_detection"]

    license_payload = {
        "license_id": f"LIC-{int(now.timestamp())}",
        "service_name": service_name,
        "mac_address": target_mac,
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "issued_at": start_dt.isoformat(),
        "expires_at": end_dt.isoformat(),
        "duration_days": duration_days,
        "features": allowed_features,
        "version": "2.0"
    }

    print("\n" + "="*50)
    print(" [INFO] GENERATING NEW HARDWARE-LOCKED LICENSE")
    print("="*50)
    print(f" - License ID    : {license_payload['license_id']}")
    print(f" - Service Name  : {license_payload['service_name']}")
    print(f" - Target MAC    : {license_payload['mac_address']}")
    print(f" - Start Date    : {license_payload['start_date']}")
    print(f" - End Date      : {license_payload['end_date']}")
    print(f" - Duration Days : {license_payload['duration_days']}")
    print(f" - Features      : {', '.join(license_payload['features'])}")
    print("="*50)

    encrypted_blob = encrypt_license_data(license_payload)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(encrypted_blob)

    print(f"\n[+] Success! Encrypted license written to: '{output_file}'")
    print(f" - Ciphertext Preview: {encrypted_blob[:35]}... (AES-256-GCM)")
    return output_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create encrypted service license file (.gry)")
    parser.add_argument("--out", default="camera.gry", help="Output .gry file path")
    parser.add_argument("--service", default="vision_analytics_service", help="Service Name")
    parser.add_argument("--mac", default=None, help="Target MAC address (defaults to this machine's MAC)")
    parser.add_argument("--start", default=None, help="Start Date ISO format")
    parser.add_argument("--end", default=None, help="End Date ISO format")
    parser.add_argument("--days", type=int, default=365, help="Number of days valid (if --end not given)")
    args = parser.parse_args()

    create_license_file(
        output_file=args.out,
        service_name=args.service,
        mac_address=args.mac,
        start_date=args.start,
        end_date=args.end,
        days_valid=args.days
    )
