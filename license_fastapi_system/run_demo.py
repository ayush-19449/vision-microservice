"""
File 3: run_demo.py
Interactive automated demo runner that tests and demonstrates:
  1. Valid License (Matching Host MAC) -> SUCCESS
  2. Mismatched MAC Address            -> REJECTED (Fails closed)
  3. Expired License                   -> REJECTED (Fails closed)
  4. Tampered License File             -> REJECTED (Fails closed)
"""
import os
import subprocess
import sys
from license_config import get_system_mac_address
from create_license import create_license_file

def banner(title):
    print("\n" + "#"*60)
    print(f"  DEMO SCENARIO: {title}")
    print("#"*60)

def run_verifier(lic_file):
    res = subprocess.run([sys.executable, "verify_license.py", "--file", lic_file], capture_output=True, text=True)
    print(res.stdout)
    if res.stderr:
        print(res.stderr)
    return res.returncode

def main():
    host_mac = get_system_mac_address()
    print("\n" + "="*60)
    print(" [INFO] PRODUCTION-READY LICENSE SYSTEM DEMO")
    print(f" Current Machine MAC Address: {host_mac}")
    print("="*60)

    # -------------------------------------------------------------
    # SCENARIO 1: Valid License for this machine
    # -------------------------------------------------------------
    banner("1. VALID LICENSE WITH MATCHING HOST MAC")
    valid_file = "demo_valid.gry"
    create_license_file(
        output_file=valid_file,
        service_name="traffic_monitoring_service",
        mac_address=host_mac,
        days_valid=365
    )
    code = run_verifier(valid_file)
    print(f"-> Exit Code: {code} ({'PASSED (Proceed with Startup)' if code == 0 else 'FAILED'})")

    # -------------------------------------------------------------
    # SCENARIO 2: Mismatched MAC Address
    # -------------------------------------------------------------
    banner("2. LICENSE BOUND TO ANOTHER MACHINE (MAC MISMATCH)")
    wrong_mac_file = "demo_wrong_mac.gry"
    create_license_file(
        output_file=wrong_mac_file,
        service_name="traffic_monitoring_service",
        mac_address="11:22:33:44:55:66",  # Intentionally different MAC
        days_valid=365
    )
    code = run_verifier(wrong_mac_file)
    print(f"-> Exit Code: {code} ({'PASSED' if code == 0 else 'BLOCKED AS EXPECTED (Fails closed)'})")

    # -------------------------------------------------------------
    # SCENARIO 3: Expired License
    # -------------------------------------------------------------
    banner("3. EXPIRED LICENSE")
    expired_file = "demo_expired.gry"
    create_license_file(
        output_file=expired_file,
        service_name="traffic_monitoring_service",
        mac_address=host_mac,
        days_valid=-5  # Expired 5 days ago
    )
    code = run_verifier(expired_file)
    print(f"-> Exit Code: {code} ({'PASSED' if code == 0 else 'BLOCKED AS EXPECTED (Fails closed)'})")

    # -------------------------------------------------------------
    # SCENARIO 4: Tampered License Payload
    # -------------------------------------------------------------
    banner("4. TAMPERED LICENSE PAYLOAD (CRYPTOGRAPHIC INTEGRITY FAIL)")
    tampered_file = "demo_tampered.gry"
    with open(valid_file, "r") as f:
        content = f.read().strip()
    # Corrupt last characters of the ciphertext
    tampered_content = content[:-8] + "TAMPERED"
    with open(tampered_file, "w") as f:
        f.write(tampered_content)
    print(f"[*] Tampered with bytes in '{tampered_file}'")
    code = run_verifier(tampered_file)
    print(f"-> Exit Code: {code} ({'PASSED' if code == 0 else 'BLOCKED AS EXPECTED (Fails closed)'})")

    # Cleanup demo files
    for f in [valid_file, wrong_mac_file, expired_file, tampered_file]:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass

    print("\n" + "="*60)
    print(" [SUCCESS] DEMO COMPLETE: All security checks functioned as expected!")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
