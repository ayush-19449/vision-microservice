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
    """Normalize MAC address to lowercase colon-separated format."""
    clean = re.sub(r'[^0-9a-fA-F]', '', mac).lower()
    if len(clean) == 12:
        return ":".join(clean[i:i+2] for i in range(0, 12, 2))
    return mac.lower().strip()

def get_system_mac_address() -> str:
    """
    Detects the current machine's physical MAC address.
    Supports SYSTEM_MAC / SYSTEM_MAC_OVERRIDE env var for Docker containers.
    Filters out virtual/loopback interfaces when psutil is available.
    """
    # 1. Environment variable override (ideal for Docker containers)
    env_mac = os.environ.get("SYSTEM_MAC") or os.environ.get("SYSTEM_MAC_OVERRIDE")
    if env_mac:
        return normalize_mac(env_mac.strip())

    # 2. Hardware auto-detection
    try:
        import psutil
        AF_LINK = getattr(psutil, 'AF_LINK', 17)
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        
        # Priority: active non-virtual interfaces
        virtual_patterns = re.compile(r'^(lo|docker|br-|veth|virbr|vmnet|vboxnet)', re.I)
        for iface, addr_list in addrs.items():
            if virtual_patterns.match(iface):
                continue
            if iface in stats and not stats[iface].isup:
                continue
            for addr in addr_list:
                if addr.family == AF_LINK:
                    norm = normalize_mac(addr.address)
                    if norm and norm != "00:00:00:00:00:00":
                        return norm
    except Exception:
        pass
    
    # Fallback using uuid
    node = uuid.getnode()
    return normalize_mac(f"{node:012x}")

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
