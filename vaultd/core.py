"""
vaultd.core — Core encrypt/decrypt functions for .vaultd files.

These are the same functions as in scripts/save_vaultd.py and scripts/load_vaultd.py,
packaged as a proper importable library.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Schema path (relative to this file)
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "vaultd_v12.json"

# Supported versions
SUPPORTED_KLICKD_VERSIONS = {"3.0"}
SUPPORTED_VAULTD_VERSIONS = {"1.1", "1.2"}

# Error codes
VAULTD_E_FORMAT = "VAULTD_E_FORMAT"
VAULTD_E_SCHEMA = "VAULTD_E_SCHEMA"
VAULTD_E_PASSPHRASE = "VAULTD_E_PASSPHRASE"
VAULTD_E_VERSION = "VAULTD_E_VERSION"
VAULTD_E_DOMAIN = "VAULTD_E_DOMAIN"
VAULTD_E_DECRYPT = "VAULTD_E_DECRYPT"

# Argon2id defaults
DEFAULT_ARGON2_M = 65536
DEFAULT_ARGON2_T = 3
DEFAULT_ARGON2_P = 1

# Size limits
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_ENVELOPE_BYTES = 1 * 1024 * 1024

# Minimum passphrase length
MIN_PASSPHRASE_LEN = 16


def validate_payload(payload: dict[str, Any]) -> None:
    """
    Validate a payload dict against the vaultd_v12 JSON Schema.

    Raises ValueError with VAULTD_E_SCHEMA on failure.
    Prints a warning and returns if jsonschema is not installed or schema file not found.
    """
    try:
        import jsonschema
    except ImportError:
        print(
            "[WARN] jsonschema not installed — skipping schema validation. "
            "Run: pip install jsonschema",
            file=sys.stderr,
        )
        return

    if not _SCHEMA_PATH.exists():
        print(
            f"[WARN] Schema not found at {_SCHEMA_PATH} — skipping validation.",
            file=sys.stderr,
        )
        return

    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"{VAULTD_E_SCHEMA}: Payload validation failed — "
            f"{e.message} (path: {list(e.absolute_path)})"
        )


def create_vaultd(
    payload: dict[str, Any],
    passphrase: str,
    output_path: str | Path,
    argon2_m: int = DEFAULT_ARGON2_M,
    argon2_t: int = DEFAULT_ARGON2_T,
    argon2_p: int = DEFAULT_ARGON2_P,
    skip_validation: bool = False,
) -> None:
    """
    Encrypt a payload dict into a .vaultd file.

    Args:
        payload: Dict conforming to the vaultd payload schema.
        passphrase: Encryption passphrase (min 16 chars recommended).
        output_path: Destination file path (e.g. "portfolio.vaultd").
        argon2_m: Argon2id memory cost in KiB (default 65536 = 64 MiB).
        argon2_t: Argon2id time cost / iterations (default 3).
        argon2_p: Argon2id parallelism (default 1).
        skip_validation: Skip JSON Schema validation (not recommended).

    Raises:
        ValueError: With VAULTD_E_* error codes on failure.

    The file is written atomically (temp file + os.replace) to prevent
    corruption if the process is interrupted mid-write.
    """
    if not skip_validation:
        validate_payload(payload)

    # Ensure created_at is present and written into payload
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    created_at = payload["created_at"]

    # Serialize payload
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(plaintext) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"{VAULTD_E_FORMAT}: Payload exceeds {MAX_PAYLOAD_BYTES // (1024 * 1024)} MB limit"
        )

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

    # Build AAD from envelope metadata (RFC 8785 JCS — lexicographically sorted)
    envelope_meta = {
        "created_at": created_at,
        "domain": "crypto",
        "encrypted": True,
        "klickd_version": "3.0",
        "vaultd_version": "1.2",
    }
    aad = json.dumps(
        envelope_meta, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    # Encrypt — AES-256-GCM appends a 16-byte authentication tag
    ciphertext_with_tag = AESGCM(key).encrypt(iv, plaintext, aad)

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
        "aad_fields": [
            "created_at",
            "domain",
            "encrypted",
            "klickd_version",
            "vaultd_version",
        ],
    }

    envelope_bytes = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")
    if len(envelope_bytes) > MAX_ENVELOPE_BYTES:
        raise ValueError(
            f"{VAULTD_E_FORMAT}: Envelope exceeds {MAX_ENVELOPE_BYTES // 1024} KB limit"
        )

    # Atomic write — temp file + os.replace (crash-safe on POSIX)
    output_path = Path(output_path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, suffix=".vaultd.tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(envelope_bytes.decode("utf-8"))
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_vaultd(
    path: str | Path,
    passphrase: str,
    skip_validation: bool = False,
) -> dict[str, Any]:
    """
    Decrypt a .vaultd file and return the payload as a dict.

    Args:
        path: Path to the .vaultd file.
        passphrase: Decryption passphrase.
        skip_validation: Skip JSON Schema validation on the decrypted payload.

    Returns:
        Decrypted payload as a dict.

    Raises:
        ValueError: With VAULTD_E_* error codes on failure.
            - VAULTD_E_FORMAT: File not found, invalid JSON, size limits
            - VAULTD_E_VERSION: Unsupported klickd_version or vaultd_version
            - VAULTD_E_DOMAIN: Unexpected domain value
            - VAULTD_E_DECRYPT: Wrong passphrase or tampered file
            - VAULTD_E_SCHEMA: Decrypted payload fails schema validation
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"{VAULTD_E_FORMAT}: File not found: {path}")

    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_ENVELOPE_BYTES:
        raise ValueError(
            f"{VAULTD_E_FORMAT}: Envelope exceeds {MAX_ENVELOPE_BYTES // 1024} KB limit"
        )

    try:
        envelope = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Invalid JSON envelope — {e}")

    if not isinstance(envelope, dict):
        raise ValueError(f"{VAULTD_E_FORMAT}: Envelope must be a JSON object")

    # Version checks
    klickd_ver = envelope.get("klickd_version")
    if klickd_ver not in SUPPORTED_KLICKD_VERSIONS:
        raise ValueError(
            f"{VAULTD_E_VERSION}: Unsupported klickd_version '{klickd_ver}' "
            f"(supported: {SUPPORTED_KLICKD_VERSIONS})"
        )

    vaultd_ver = envelope.get("vaultd_version")
    if vaultd_ver not in SUPPORTED_VAULTD_VERSIONS:
        raise ValueError(
            f"{VAULTD_E_VERSION}: Unsupported vaultd_version '{vaultd_ver}' "
            f"(supported: {SUPPORTED_VAULTD_VERSIONS})"
        )

    if envelope.get("domain") != "crypto":
        raise ValueError(
            f"{VAULTD_E_DOMAIN}: Expected domain 'crypto', got '{envelope.get('domain')}'"
        )

    # Unencrypted variant (examples/testing only)
    if not envelope.get("encrypted", True):
        print(
            "[WARN] File is NOT encrypted. Never use unencrypted .vaultd for real data.",
            file=sys.stderr,
        )
        return envelope.get("payload", {})

    # Pre-flight: check required encrypted fields before any crypto
    required_fields = {"kdf_params", "iv", "ciphertext", "created_at"}
    missing = required_fields - envelope.keys()
    if missing:
        raise ValueError(f"{VAULTD_E_FORMAT}: Missing envelope fields: {missing}")

    kdf_params = envelope["kdf_params"]
    required_kdf = {"salt", "m", "t", "p"}
    missing_kdf = required_kdf - kdf_params.keys()
    if missing_kdf:
        raise ValueError(f"{VAULTD_E_FORMAT}: Missing kdf_params fields: {missing_kdf}")

    # Decode base64 components — specific error per field
    try:
        salt = base64.b64decode(kdf_params["salt"])
    except Exception as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Malformed base64 in kdf_params.salt — {e}")

    try:
        iv = base64.b64decode(envelope["iv"])
    except Exception as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Malformed base64 in iv — {e}")

    try:
        ciphertext = base64.b64decode(envelope["ciphertext"])
    except Exception as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Malformed base64 in ciphertext — {e}")

    if len(ciphertext) < 16:
        raise ValueError(f"{VAULTD_E_FORMAT}: Ciphertext too short (< 16 bytes)")
    if len(iv) != 12:
        raise ValueError(
            f"{VAULTD_E_FORMAT}: IV must be 12 bytes for AES-256-GCM, got {len(iv)}"
        )

    # Derive key using Argon2id with params from file
    key = hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=int(kdf_params["t"]),
        memory_cost=int(kdf_params["m"]),
        parallelism=int(kdf_params["p"]),
        hash_len=32,
        type=Type.ID,
    )

    # Reconstruct AAD — must match exactly what was used during encryption
    aad_fields = {
        "created_at": envelope["created_at"],
        "domain": envelope["domain"],
        "encrypted": envelope["encrypted"],
        "klickd_version": envelope["klickd_version"],
        "vaultd_version": envelope["vaultd_version"],
    }
    aad = json.dumps(
        aad_fields, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    # Decrypt
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, aad)
    except InvalidTag:
        raise ValueError(
            f"{VAULTD_E_DECRYPT}: Decryption failed — wrong passphrase or tampered file"
        )

    if len(plaintext) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"{VAULTD_E_FORMAT}: Decrypted payload exceeds "
            f"{MAX_PAYLOAD_BYTES // (1024 * 1024)} MB limit"
        )

    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Decrypted payload is not valid JSON — {e}")

    # Schema validation (v1.2 envelopes only)
    if not skip_validation and vaultd_ver == "1.2":
        validate_payload(payload)

    return payload
