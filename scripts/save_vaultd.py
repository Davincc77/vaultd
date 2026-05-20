#!/usr/bin/env python3
"""
save_vaultd.py — Reference encrypt script for .vaultd v1.1
Usage: python save_vaultd.py --payload examples/example_v11_full.json --output portfolio.vaultd
Requirements: pip install cryptography argon2-cffi
"""

import json
import base64
import os
import argparse
import getpass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type


def create_vaultd(payload: dict, passphrase: str, output_path: str) -> None:
    # Generate random salt and IV
    salt = os.urandom(16)
    iv = os.urandom(12)

    # Derive key using Argon2id
    key = hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        type=Type.ID,
    )

    # Serialize payload
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    if len(plaintext) > 4 * 1024 * 1024:
        raise ValueError("Payload exceeds 4 MB limit (VAULTD_E_FORMAT)")

    # Build envelope metadata (used for AAD)
    created_at = payload.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    envelope_meta = {
        "created_at": created_at,
        "domain": "crypto",
        "encrypted": True,
        "klickd_version": "3.0",
        "vaultd_version": "1.1",
    }

    # AAD: RFC 8785 JCS — keys sorted lexicographically
    aad = json.dumps(envelope_meta, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Encrypt (AES-256-GCM appends 16-byte auth tag)
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext, aad)

    # Build final envelope
    envelope = {
        "klickd_version": "3.0",
        "vaultd_version": "1.1",
        "domain": "crypto",
        "created_at": created_at,
        "encrypted": True,
        "encryption": "AES-256-GCM",
        "kdf": "argon2id",
        "kdf_params": {
            "m": 65536,
            "t": 3,
            "p": 1,
            "salt": base64.b64encode(salt).decode("ascii"),
        },
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext_with_tag).decode("ascii"),
        "aad_fields": ["klickd_version", "vaultd_version", "domain", "encrypted", "created_at"],
    }

    if len(json.dumps(envelope).encode()) > 1024 * 1024:
        raise ValueError("Envelope exceeds 1 MB limit (VAULTD_E_FORMAT)")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)

    print(f"[OK] .vaultd file created: {output_path}")
    print(f"     Payload size: {len(plaintext):,} bytes")
    print(f"     Argon2id params: m=65536, t=3, p=1")


def main():
    parser = argparse.ArgumentParser(description="Create a .vaultd encrypted file")
    parser.add_argument("--payload", required=True, help="Path to JSON payload file")
    parser.add_argument("--output", required=True, help="Output .vaultd file path")
    args = parser.parse_args()

    with open(args.payload, "r", encoding="utf-8") as f:
        payload = json.load(f)

    passphrase = getpass.getpass("Passphrase: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if passphrase != confirm:
        raise ValueError("Passphrases do not match")
    if len(passphrase) < 12:
        print("[WARN] Passphrase is short. Use at least 12 characters for security.")

    create_vaultd(payload, passphrase, args.output)


if __name__ == "__main__":
    main()
