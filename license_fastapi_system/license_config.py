"""
Shared License Configuration, Cryptography (AES-256-GCM), and Hardware MAC Detection.
"""
import os
import re
import json
import base64
import uuid
import secrets
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Master key: 32 bytes (64 hex characters)
# Reads from LICENSE_SECRET_KEY env var if set, else uses a default demo key
DEFAULT_DEMO_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

def get_secret_key() -> bytes:
    key_hex = os.environ.get("LICENSE_SECRET_KEY", DEFAULT_DEMO_KEY).strip()
    return bytes.fromhex(key_hex)

def normalize_mac(mac: str) -> str:
    """Normalize MAC address to lowercase colon-separated 6-octet format (xx:xx:xx:xx:xx:xx)."""
    if not mac:
        return ""
    clean = re.sub(r'[^0-9a-fA-F]', '', str(mac)).lower()
    if not clean or clean == "0" * len(clean):
        return "00:00:00:00:00:00"
    if len(clean) > 12:
        clean = clean[:12]
    elif len(clean) < 12:
        clean = clean.zfill(12)
    return ":".join(clean[i:i+2] for i in range(0, 12, 2))

def is_virtual_or_container_mac(mac: str) -> bool:
    """
    Returns True if MAC address is a virtual, Docker container, or locally administered MAC.
    Filters out IEEE 802 Locally Administered Addresses (LAA) where bit 1 of byte 0 is set (1).
    All Docker container veth interfaces (e.g. 02:42:*, 0a:84:*, 1e:*, etc.) set this bit.
    """
    norm = normalize_mac(mac)
    if not norm or norm in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        return True

    # 1. Known virtual/hypervisor/container OUI prefixes
    virtual_prefixes = (
        "02:42:",    # Default Docker bridge
        "52:54:00:",  # QEMU / KVM
        "00:05:69:",  # VMware
        "00:0c:29:",  # VMware
        "00:50:56:",  # VMware
        "00:16:3e:",  # Xen / AWS EC2 virtual
        "08:00:27:",  # VirtualBox
    )
    if any(norm.startswith(prefix) for prefix in virtual_prefixes):
        return True

    # 2. IEEE 802 Locally Administered Address (LAA) bit check
    try:
        first_byte = int(norm.split(":")[0], 16)
        if first_byte & 2 != 0:  # Bit 1 set = Locally Administered (Virtual / Container)
            return True
    except Exception:
        pass

    return False

def is_docker_mac(mac: str) -> bool:
    """Backward compatible helper alias."""
    return is_virtual_or_container_mac(mac)

def _save_host_mac(mac: str, paths: list):
    """Saves detected physical host MAC to shared volume paths for container synchronization."""
    if not mac or is_virtual_or_container_mac(mac):
        return
    for p in paths:
        try:
            d = os.path.dirname(p)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(mac.strip() + "\n")
            break
        except Exception:
            continue

def get_system_mac_address() -> str:
    """
    100% Autonomous Host Physical MAC Detector.
    Automatically detects physical host PC MAC address across host OS and Docker containers.
    Priority Order:
    1. Environment Overrides (SYSTEM_MAC / SYSTEM_MAC_OVERRIDE / HOST_MAC)
    2. Shared Host MAC file (/app/licenses/host_mac, /etc/host_mac, /app/host_mac)
    3. Physical Hardware NICs (from /host/sys/class/net, /sys/class/net, or psutil)
    4. Container Active Interface MAC (eth0, en0)
    5. Hardware Node ID via uuid.getnode()
    """
    # 1. Environment variable override if explicitly passed
    for env_var in ["SYSTEM_MAC", "SYSTEM_MAC_OVERRIDE", "HOST_MAC", "HOST_MAC_ADDRESS"]:
        env_mac = os.environ.get(env_var)
        if env_mac and env_mac.strip():
            return normalize_mac(env_mac.strip())

    # 2. Check mounted/shared host MAC file
    host_mac_paths = [
        "/app/licenses/host_mac",
        "./licenses/host_mac",
        "/etc/host_mac",
        "/app/host_mac"
    ]
    for host_mac_file in host_mac_paths:
        if os.path.exists(host_mac_file):
            try:
                with open(host_mac_file, "r") as f:
                    content = f.read().strip()
                    norm = normalize_mac(content)
                    if norm and norm != "00:00:00:00:00:00":
                        return norm
            except Exception:
                pass

    container_fallback_mac = None

    # 3. Check sysfs interfaces (/host/sys/class/net or /sys/class/net)
    sys_net_dirs = ["/host/sys/class/net", "/sys/class/net"]
    virtual_patterns = re.compile(r'^(lo|docker|br-|veth|virbr|vmnet|vboxnet|tun|tap|wg)', re.I)

    for sys_net_dir in sys_net_dirs:
        if os.path.exists(sys_net_dir):
            try:
                for iface in sorted(os.listdir(sys_net_dir)):
                    if virtual_patterns.match(iface):
                        continue
                    addr_path = os.path.join(sys_net_dir, iface, "address")
                    if os.path.exists(addr_path):
                        with open(addr_path, "r") as f:
                            raw = f.read().strip()
                            norm = normalize_mac(raw)
                            if norm and norm not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                                if not is_virtual_or_container_mac(norm):
                                    _save_host_mac(norm, host_mac_paths)
                                    return norm
                                elif not container_fallback_mac:
                                    container_fallback_mac = norm
            except Exception:
                pass

    # 4. Hardware auto-detection via psutil
    try:
        import psutil
        AF_LINK = getattr(psutil, 'AF_LINK', 17)
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()

        for iface in sorted(addrs.keys()):
            if virtual_patterns.match(iface):
                continue
            if iface in stats and not stats[iface].isup:
                continue
            for addr in addrs[iface]:
                if addr.family == AF_LINK:
                    norm = normalize_mac(addr.address)
                    if norm and norm not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                        if not is_virtual_or_container_mac(norm):
                            _save_host_mac(norm, host_mac_paths)
                            return norm
                        elif not container_fallback_mac:
                            container_fallback_mac = norm
    except Exception:
        pass

    # 5. Check container ARP table (/proc/net/arp)
    if os.path.exists("/proc/net/arp"):
        try:
            with open("/proc/net/arp", "r") as f:
                lines = f.readlines()[1:]
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 4:
                        mac = normalize_mac(parts[3])
                        if mac and mac not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                            if not is_virtual_or_container_mac(mac):
                                return mac
                            elif not container_fallback_mac:
                                container_fallback_mac = mac
        except Exception:
            pass

    # 6. Fallback using uuid.getnode()
    try:
        node = uuid.getnode()
        if node and node != 0:
            mac_from_node = normalize_mac(f"{node:012x}")
            if mac_from_node and mac_from_node != "00:00:00:00:00:00":
                if not is_virtual_or_container_mac(mac_from_node):
                    return mac_from_node
                elif not container_fallback_mac:
                    container_fallback_mac = mac_from_node
    except Exception:
        pass

    return container_fallback_mac or "00:00:00:00:00:00"

def encrypt_license_data(payload: dict) -> str:
    """
    Encrypts a license payload dict using AES-256-GCM.
    Returns a single URL-safe base64 string: NONCE(12 bytes) || CIPHERTEXT+TAG.
    """
    key = get_secret_key()
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)  # Standard 96-bit nonce
    plaintext = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')

def decrypt_license_data(encrypted_str: str) -> dict:
    """
    Decrypts an AES-256-GCM encrypted license string.
    Verifies cryptographic integrity/authenticity tag.
    Raises ValueError on tampering, corruption, or wrong key.
    """
    try:
        raw = base64.urlsafe_b64decode(encrypted_str.strip().encode('ascii'))
    except Exception as e:
        raise ValueError(f"Corrupted base64 payload: {e}")

    if len(raw) < 12 + 16:
        raise ValueError("Invalid payload: data too short for nonce + auth tag.")

    nonce = raw[:12]
    ciphertext_with_tag = raw[12:]
    key = get_secret_key()
    aesgcm = AESGCM(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
    except Exception:
        raise ValueError("Decryption/Integrity check failed! (Tampered file or wrong key)")

    return json.loads(plaintext.decode('utf-8'))
