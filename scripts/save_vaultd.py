#!/usr/bin/env python3
"""
save_vaultd.py — Reference encrypt script for .vaultd v1.2

Usage:
  python save_vaultd.py --payload examples/example_v11_full.json --output portfolio.vaultd
  python save_vaultd.py --payload data.json --output portfolio.vaultd --argon2-m 131072 --argon2-t 4

Requirements: pip install cryptography argon2-cffi jsonschema
"""

import json
import base64
import os
import argparse
import getpass
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type

# Resolve schema path relative to this file
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "vaultd_v12.json"

# Error codes
VAULTD_E_FORMAT = "VAULTD_E_FORMAT"
VAULTD_E_SCHEMA = "VAULTD_E_SCHEMA"
VAULTD_E_PASSPHRASE = "VAULTD_E_PASSPHRASE"

# Argon2id defaults (NIST-compliant minimum for financial data)
DEFAULT_ARGON2_M = 65536   # 64 MiB
DEFAULT_ARGON2_T = 3       # time cost
DEFAULT_ARGON2_P = 1       # parallelism

# Size limits
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024   # 4 MB
MAX_ENVELOPE_BYTES = 1 * 1024 * 1024  # 1 MB

# Minimum passphrase length
MIN_PASSPHRASE_LEN = 16


def validate_payload(payload: dict) -> None:
    """Validate payload against vaultd_v12 JSON Schema. Raises on failure."""
    try:
        import jsonschema
    except ImportError:
        print("[WARN] jsonschema not installed — skipping schema validation. Run: pip install jsonschema", file=sys.stderr)
        return

    if not _SCHEMA_PATH.exists():
        print(f"[WARN] Schema not found at {_SCHEMA_PATH} — skipping validation.", file=sys.stderr)
        return

    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"{VAULTD_E_SCHEMA}: Payload validation failed — {e.message} (path: {list(e.absolute_path)})")


def create_vaultd(
    payload: dict,
    passphrase: str,
    output_path: str,
    argon2_m: int = DEFAULT_ARGON2_M,
    argon2_t: int = DEFAULT_ARGON2_T,
    argon2_p: int = DEFAULT_ARGON2_P,
    skip_validation: bool = False,
) -> None:
    """
    Encrypt a payload dict into a .vaultd file.

    Uses AES-256-GCM with Argon2id key derivation.
    Writes atomically via a temp file to prevent corruption on crash.
    """
    # Schema validation
    if not skip_validation:
        validate_payload(payload)

    # Ensure created_at is present and written into payload
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    created_at = payload["created_at"]

    # Serialize payload
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    if len(plaintext) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"{VAULTD_E_FORMAT}: Payload exceeds {MAX_PAYLOAD_BYTES // (1024*1024)} MB limit")

    # Generate random salt (16 bytes) and IV (12 bytes)
    salt = os.urandom(16)
    iv = os.urandom(12)

    # Derive 256-bit key using Argon2id
    key = hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=argon2_t,
        memory_cost=argon2_m,
        parallelism=argon2_p,
        hash_len=32,
        type=Type.ID,
    )

    # Build AAD from envelope metadata (RFC 8785 JCS — lexicographically sorted keys)
    envelope_meta = {
        "created_at": created_at,
        "domain": "crypto",
        "encrypted": True,
        "klickd_version": "3.0",
        "vaultd_version": "1.2",
    }
    aad = json.dumps(envelope_meta, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Encrypt — AES-256-GCM appends a 16-byte authentication tag
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext, aad)

    # Build final envelope
    envelope = {
        "klickd_version": "3.0",
        "vaultd_version": "1.2",
        "domain": "crypto",
        "created_at": created_at,
        "encrypted": True,
        "encryption": "AES-256-GCM",
        "kdf": "argon2id",
        "kdf_params": {
            "m": argon2_m,
            "t": argon2_t,
            "p": argon2_p,
            "salt": base64.b64encode(salt).decode("ascii"),
        },
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext_with_tag).decode("ascii"),
        "aad_fields": ["created_at", "domain", "encrypted", "klickd_version", "vaultd_version"],
    }

    envelope_bytes = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")
    if len(envelope_bytes) > MAX_ENVELOPE_BYTES:
        raise ValueError(f"{VAULTD_E_FORMAT}: Envelope exceeds {MAX_ENVELOPE_BYTES // 1024} KB limit")

    # Atomic write — write to temp file first, then rename (crash-safe)
    output_path = Path(output_path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, suffix=".vaultd.tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(envelope_bytes.decode("utf-8"))
        os.replace(tmp_path, output_path)  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    print(f"[OK] .vaultd file created: {output_path}")
    print(f"     Payload size : {len(plaintext):,} bytes")
    print(f"     Envelope size: {len(envelope_bytes):,} bytes")
    print(f"     Argon2id     : m={argon2_m}, t={argon2_t}, p={argon2_p}")
    print(f"     Version      : vaultd v1.2 / klickd v3.0")


def main():
    parser = argparse.ArgumentParser(
        description="Create an encrypted .vaultd file (AES-256-GCM + Argon2id)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python save_vaultd.py --payload examples/example_v11_full.json --output portfolio.vaultd
  python save_vaultd.py --payload data.json --output vault.vaultd --argon2-m 131072 --argon2-t 4
  python save_vaultd.py --payload data.json --output vault.vaultd --skip-validation
        """,
    )
    parser.add_argument("--payload", required=True, help="Path to JSON payload file")
    parser.add_argument("--output", required=True, help="Output .vaultd file path")
    parser.add_argument(
        "--argon2-m",
        type=int,
        default=DEFAULT_ARGON2_M,
        help=f"Argon2id memory cost in KiB (default: {DEFAULT_ARGON2_M} = 64 MiB). Use 131072 for high-value vaults.",
    )
    parser.add_argument(
        "--argon2-t",
        type=int,
        default=DEFAULT_ARGON2_T,
        help=f"Argon2id time cost / iterations (default: {DEFAULT_ARGON2_T})",
    )
    parser.add_argument(
        "--argon2-p",
        type=int,
        default=DEFAULT_ARGON2_P,
        help=f"Argon2id parallelism (default: {DEFAULT_ARGON2_P})",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip JSON Schema validation (not recommended)",
    )
    args = parser.parse_args()

    # Load payload
    with open(args.payload, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # Passphrase handling
    passphrase = getpass.getpass("Passphrase: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if passphrase != confirm:
        print(f"[ERROR] {VAULTD_E_PASSPHRASE}: Passphrases do not match", file=sys.stderr)
        sys.exit(1)
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        print(
            f"[WARN] Passphrase is short ({len(passphrase)} chars). Use at least {MIN_PASSPHRASE_LEN} characters "
            "for a financial vault — Argon2id cannot protect a weak passphrase."
        )
        answer = input("Continue anyway? [y/N] ").strip().lower()
        if answer != "y":
            sys.exit(0)

    # Argon2 param sanity checks
    if args.argon2_m < 16384:
        print("[WARN] Argon2id memory < 16 MiB — consider using at least 65536 (64 MiB) for financial data.")
    if args.argon2_t < 1:
        print("[ERROR] Argon2id time cost must be >= 1", file=sys.stderr)
        sys.exit(1)

    try:
        create_vaultd(
            payload,
            passphrase,
            args.output,
            argon2_m=args.argon2_m,
            argon2_t=args.argon2_t,
            argon2_p=args.argon2_p,
            skip_validation=args.skip_validation,
        )
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
