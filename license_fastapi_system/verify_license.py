"""
File 2: verify_license.py
Reads an encrypted license file, decrypts it securely, verifies integrity,
checks expiration, and validates that the licensed MAC matches the host hardware MAC.
"""
import sys
import os
import argparse
from datetime import datetime, timezone
from license_config import (
    get_system_mac_address,
    normalize_mac,
    decrypt_license_data
)

def verify_license(license_path: str = "camera.gry") -> dict:
    """
    Complete license verification pipeline.
    Returns decrypted license dict on success.
    Raises SystemExit(1) on any failure (fail closed).
    """
    # Auto-detect camera.gry or camera.lic if default requested
    if license_path == "camera.gry" and not os.path.exists("camera.gry") and os.path.exists("camera.lic"):
        license_path = "camera.lic"

    print("\n" + "="*55)
    print(" [INFO] STARTING LICENSE VERIFICATION & MAC VALIDATION")
    print("="*55)
    
    # 1. Check file existence
    if not os.path.exists(license_path):
        print(f"\n[FAIL: LICENSE_FILE_NOT_FOUND] Cannot find license file: '{license_path}'")
        sys.exit(1)
        
    print(f"[*] Step 1: Reading encrypted license from '{license_path}'...")
    with open(license_path, "r", encoding="utf-8") as f:
        encrypted_blob = f.read().strip()
        
    # 2. Decrypt & Authenticate Payload (AES-256-GCM)
    print("[*] Step 2: Decrypting payload and validating cryptographic integrity...")
    try:
        data = decrypt_license_data(encrypted_blob)
        print("   [OK] Decryption successful! Cryptographic authentication tag matched.")
    except Exception as e:
        print(f"\n[FAIL: LICENSE_DECRYPTION_FAILED] {e}")
        print("   -> Possible reasons: Tampered license file, corrupted payload, or wrong master key.")
        sys.exit(1)

    # 3. Expiration & Duration Check
    print("[*] Step 3: Checking license validity duration...")
    try:
        start_str = data.get("start_date") or data.get("issued_at", "")
        exp_str = data.get("end_date") or data.get("expires_at", "")

        now_dt = datetime.now(timezone.utc)

        if start_str:
            start_dt = datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if now_dt < start_dt:
                print(f"\n[FAIL: LICENSE_NOT_YET_ACTIVE] License is not active until {start_dt.isoformat()}")
                sys.exit(1)

        exp_dt = datetime.fromisoformat(exp_str)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)

        if now_dt >= exp_dt:
            print(f"\n[FAIL: LICENSE_EXPIRED] License expired on {exp_dt.isoformat()}")
            print(f"   -> Current system UTC time is {now_dt.isoformat()}")
            sys.exit(1)

        print(f"   [OK] License valid duration: {start_str} to {exp_str}")
    except Exception as e:
        print(f"\n[FAIL: LICENSE_FORMAT_INVALID] Invalid expiration/duration date in license: {e}")
        sys.exit(1)

    # 4. Hardware MAC Detection & Comparison
    print("[*] Step 4: Detecting host hardware MAC address...")
    system_mac = get_system_mac_address()
    licensed_mac = normalize_mac(data.get("mac_address", ""))
    
    print(f"   - Detected Host MAC  : {system_mac}")
    print(f"   - Licensed Target MAC: {licensed_mac}")

    if system_mac != licensed_mac:
        print("\n" + "!"*55)
        print("[FAIL: MAC_ADDRESS_MISMATCH] Hardware validation FAILED!")
        print("   The license is locked to another machine.")
        print("   -> DO NOT spawn service containers.")
        print("!"*55)
        sys.exit(1)

    print("   [OK] System MAC matches licensed MAC!")

    # 5. Success summary
    print("\n" + "="*55)
    print(" [SUCCESS] LICENSE FULLY VERIFIED & HARDWARE BOUND")
    print("="*55)
    print(f" - Status           : AUTHORIZED TO RUN")
    print(f" - License ID       : {data.get('license_id')}")
    print(f" - Service Name     : {data.get('service_name', 'vision_analytics_service')}")
    print(f" - MAC Address      : {licensed_mac}")
    print(f" - Duration Start   : {data.get('start_date') or data.get('issued_at')}")
    print(f" - Duration End     : {data.get('end_date') or data.get('expires_at')}")
    print(f" - Duration Days    : {data.get('duration_days', 'N/A')}")
    print(f" - Allowed Features : {', '.join(data.get('features', []))}")
    print("="*55 + "\n")
    
    return data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify encrypted camera license")
    parser.add_argument("--file", default="camera.gry", help="License file path (.gry or .lic)")
    args = parser.parse_args()
    
    verify_license(args.file)
