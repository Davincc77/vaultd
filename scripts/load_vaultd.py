#!/usr/bin/env python3
"""
load_vaultd.py — Reference decrypt script for .vaultd v1.2

Usage:
  python load_vaultd.py portfolio.vaultd
  python load_vaultd.py portfolio.vaultd --json
  python load_vaultd.py portfolio.vaultd --output decrypted.json
  echo "mypassphrase" | python load_vaultd.py portfolio.vaultd --passphrase-stdin

Requirements: pip install cryptography argon2-cffi jsonschema
"""

import argparse
import base64
import getpass
import json
import sys
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Resolve schema path relative to this file
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "vaultd_v12.json"

# Supported versions
SUPPORTED_KLICKD_VERSIONS = {"3.0"}
SUPPORTED_VAULTD_VERSIONS = {"1.1", "1.2"}

# Error codes
VAULTD_E_VERSION = "VAULTD_E_VERSION"
VAULTD_E_FORMAT = "VAULTD_E_FORMAT"
VAULTD_E_DOMAIN = "VAULTD_E_DOMAIN"
VAULTD_E_DECRYPT = "VAULTD_E_DECRYPT"
VAULTD_E_SCHEMA = "VAULTD_E_SCHEMA"

MAX_ENVELOPE_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024   # 4 MB


def validate_payload(payload: dict) -> None:
    """Validate decrypted payload against vaultd_v12 JSON Schema."""
    try:
        import jsonschema
    except ImportError:
        print("[WARN] jsonschema not installed — skipping schema validation. Run: pip install jsonschema", file=sys.stderr)
        return

    if not _SCHEMA_PATH.exists():
        print(f"[WARN] Schema not found at {_SCHEMA_PATH} — skipping validation.", file=sys.stderr)
        return

    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as e:
        print(
            f"[WARN] {VAULTD_E_SCHEMA}: Payload schema validation failed — {e.message} "
            f"(path: {list(e.absolute_path)}). File may have been created with a different version.",
            file=sys.stderr,
        )


def load_vaultd(path: str, passphrase: str, skip_validation: bool = False) -> dict:
    """
    Decrypt a .vaultd file and return the payload as a dict.

    Raises ValueError with VAULTD_E_* codes on failure.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"{VAULTD_E_FORMAT}: File not found: {path}")

    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_ENVELOPE_BYTES:
        raise ValueError(f"{VAULTD_E_FORMAT}: Envelope exceeds {MAX_ENVELOPE_BYTES // 1024} KB limit")

    try:
        envelope = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Invalid JSON envelope — {e}")

    if not isinstance(envelope, dict):
        raise ValueError(f"{VAULTD_E_FORMAT}: Envelope must be a JSON object")

    # Version checks
    klickd_ver = envelope.get("klickd_version")
    if klickd_ver not in SUPPORTED_KLICKD_VERSIONS:
        raise ValueError(f"{VAULTD_E_VERSION}: Unsupported klickd_version '{klickd_ver}' (supported: {SUPPORTED_KLICKD_VERSIONS})")

    vaultd_ver = envelope.get("vaultd_version")
    if vaultd_ver not in SUPPORTED_VAULTD_VERSIONS:
        raise ValueError(f"{VAULTD_E_VERSION}: Unsupported vaultd_version '{vaultd_ver}' (supported: {SUPPORTED_VAULTD_VERSIONS})")

    if envelope.get("domain") != "crypto":
        raise ValueError(f"{VAULTD_E_DOMAIN}: Expected domain 'crypto', got '{envelope.get('domain')}'")

    # Unencrypted variant (examples/testing only)
    if not envelope.get("encrypted", True):
        print("[WARN] File is NOT encrypted. Never use unencrypted .vaultd for real portfolio data.", file=sys.stderr)
        return envelope.get("payload", {})

    # Validate required encrypted fields exist before accessing them
    required_fields = {"kdf_params", "iv", "ciphertext", "created_at"}
    missing = required_fields - envelope.keys()
    if missing:
        raise ValueError(f"{VAULTD_E_FORMAT}: Missing envelope fields: {missing}")

    kdf_params = envelope["kdf_params"]
    required_kdf = {"salt", "m", "t", "p"}
    missing_kdf = required_kdf - kdf_params.keys()
    if missing_kdf:
        raise ValueError(f"{VAULTD_E_FORMAT}: Missing kdf_params fields: {missing_kdf}")

    # Decode base64 components with specific error handling
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
        raise ValueError(f"{VAULTD_E_FORMAT}: IV must be 12 bytes for AES-256-GCM, got {len(iv)}")

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
    # Keys sorted lexicographically per RFC 8785 JCS
    aad_fields = {
        "created_at": envelope["created_at"],
        "domain": envelope["domain"],
        "encrypted": envelope["encrypted"],
        "klickd_version": envelope["klickd_version"],
        "vaultd_version": envelope["vaultd_version"],
    }
    aad = json.dumps(aad_fields, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Decrypt — InvalidTag means wrong passphrase OR tampered file
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, aad)
    except InvalidTag:
        raise ValueError(f"{VAULTD_E_DECRYPT}: Decryption failed — wrong passphrase or tampered file")

    if len(plaintext) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"{VAULTD_E_FORMAT}: Decrypted payload exceeds {MAX_PAYLOAD_BYTES // (1024*1024)} MB limit")

    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{VAULTD_E_FORMAT}: Decrypted payload is not valid JSON — {e}")

    # Schema validation on decrypted payload (only for v1.2)
    if not skip_validation and vaultd_ver == "1.2":
        validate_payload(payload)

    return payload


def print_summary(payload: dict) -> None:
    """Print a human-readable summary of the decrypted vault."""
    identity = payload.get("identity", {})
    holdings = payload.get("holdings", [])
    transactions = payload.get("transactions", [])
    defi = payload.get("defi_positions", [])
    nfts = payload.get("nfts", [])
    thesis = payload.get("thesis", [])
    risk_events = payload.get("risk_events", [])
    alerts = payload.get("alerts", [])
    agent_handoffs = payload.get("agent_handoffs", [])

    print("\n[OK] .vaultd decrypted successfully")
    print(f"     Alias       : {identity.get('alias', 'unknown')}")
    print(f"     Language    : {identity.get('language', '?')} | Risk: {identity.get('risk_profile', '?')} | Level: {identity.get('experience_level', '?')}")
    print(f"     Wallets     : {len(payload.get('wallets', []))}")
    print(f"     Holdings    : {len(holdings)}")
    print(f"     Transactions: {len(transactions)}")
    print(f"     DeFi        : {len(defi)}")
    print(f"     NFTs        : {len(nfts)}")
    print(f"     Theses      : {sum(1 for t in thesis if t.get('status') == 'active')} active / {len(thesis)} total")
    print(f"     Risk events : {len(risk_events)}")
    print(f"     Alerts      : {sum(1 for a in alerts if a.get('active'))} active / {len(alerts)} total")
    print(f"     AI handoffs : {len(agent_handoffs)}")

    pnl = payload.get("pnl", {})
    if pnl.get("realized_usd") is not None:
        print(f"     Realized PnL: ${pnl['realized_usd']:,.2f}")
    if pnl.get("unrealized_usd") is not None:
        print(f"     Unrealized  : ${pnl['unrealized_usd']:,.2f}")

    strategy = payload.get("strategy", {})
    if strategy.get("time_horizon"):
        print(f"     Strategy    : {strategy['time_horizon'].replace('_', ' ')}")

    tax = payload.get("tax_summary", {})
    if tax:
        print(f"     Tax summary : {tax.get('jurisdiction', '?')} / {tax.get('tax_year', '?')} ({len(tax.get('taxable_events', []))} events)")

    history = payload.get("history", {}).get("sessions", [])
    if history:
        last = history[-1]
        print(f"     Last session: {last.get('date')} via {last.get('model', '?')} — {last.get('summary', '')[:80]}")

    alerts_active = [a for a in alerts if a.get("active")]
    if alerts_active:
        print("\n[ALERTS]")
        for a in alerts_active:
            print(f"  • [{a.get('asset')}] {a.get('type')} — {a.get('message')}")

    if identity.get("agent_instructions"):
        print("\n[AGENT INSTRUCTIONS — untrusted user context]")
        print(f"  {identity['agent_instructions'][:200]}{'...' if len(identity.get('agent_instructions', '')) > 200 else ''}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt and read a .vaultd file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python load_vaultd.py portfolio.vaultd
  python load_vaultd.py portfolio.vaultd --json
  python load_vaultd.py portfolio.vaultd --output decrypted.json
  echo "mypassphrase" | python load_vaultd.py portfolio.vaultd --passphrase-stdin
        """,
    )
    parser.add_argument("file", help="Path to .vaultd file")
    parser.add_argument("--passphrase-stdin", action="store_true", help="Read passphrase from stdin (first line)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON payload to stdout")
    parser.add_argument("--output", help="Write decrypted JSON to this file path instead of stdout")
    parser.add_argument("--skip-validation", action="store_true", help="Skip JSON Schema validation")
    args = parser.parse_args()

    if args.passphrase_stdin:
        passphrase = sys.stdin.readline().rstrip("\n")
    else:
        passphrase = getpass.getpass("Passphrase: ")

    try:
        payload = load_vaultd(args.file, passphrase, skip_validation=args.skip_validation)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Decrypted payload written to: {args.output}")
    elif args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_summary(payload)


if __name__ == "__main__":
    main()
