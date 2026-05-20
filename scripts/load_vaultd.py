#!/usr/bin/env python3
"""
load_vaultd.py — Reference decrypt script for .vaultd v1.1
Usage: python load_vaultd.py portfolio.vaultd
       python load_vaultd.py portfolio.vaultd --passphrase-stdin
Requirements: pip install cryptography argon2-cffi
"""

import json
import base64
import argparse
import getpass
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type
from cryptography.exceptions import InvalidTag


def load_vaultd(path: str, passphrase: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    if len(raw.encode()) > 1024 * 1024:
        raise ValueError("VAULTD_E_FORMAT: Envelope exceeds 1 MB limit")

    envelope = json.loads(raw)

    # Validate envelope fields
    if envelope.get("klickd_version") != "3.0":
        raise ValueError(f"VAULTD_E_VERSION: Unsupported klickd_version '{envelope.get('klickd_version')}'")
    if envelope.get("vaultd_version") != "1.1":
        raise ValueError(f"VAULTD_E_VERSION: Unsupported vaultd_version '{envelope.get('vaultd_version')}'")
    if envelope.get("domain") != "crypto":
        raise ValueError(f"VAULTD_E_DOMAIN: Expected domain 'crypto', got '{envelope.get('domain')}'")

    if not envelope.get("encrypted", True):
        # Unencrypted variant — for examples/testing only
        print("[WARN] File is not encrypted. Never use unencrypted .vaultd for real portfolio data.")
        return envelope.get("payload", {})

    # Decode components
    try:
        salt = base64.b64decode(envelope["kdf_params"]["salt"])
        iv = base64.b64decode(envelope["iv"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
    except Exception as e:
        raise ValueError(f"VAULTD_E_FORMAT: Malformed base64 — {e}")

    if len(ciphertext) < 16:
        raise ValueError("VAULTD_E_FORMAT: Ciphertext too short")

    # Derive key using Argon2id
    kdf = envelope.get("kdf_params", {})
    key = hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=kdf.get("t", 3),
        memory_cost=kdf.get("m", 65536),
        parallelism=kdf.get("p", 1),
        hash_len=32,
        type=Type.ID,
    )

    # Reconstruct AAD (RFC 8785 JCS — sorted keys)
    aad_fields = {
        "created_at": envelope["created_at"],
        "domain": envelope["domain"],
        "encrypted": envelope["encrypted"],
        "klickd_version": envelope["klickd_version"],
        "vaultd_version": envelope["vaultd_version"],
    }
    aad = json.dumps(aad_fields, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Decrypt
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, aad)
    except InvalidTag:
        raise ValueError("VAULTD_E_DECRYPT: Decryption failed — wrong passphrase or tampered file")

    if len(plaintext) > 4 * 1024 * 1024:
        raise ValueError("VAULTD_E_FORMAT: Decrypted payload exceeds 4 MB limit")

    payload = json.loads(plaintext.decode("utf-8"))
    return payload


def main():
    parser = argparse.ArgumentParser(description="Decrypt and read a .vaultd file")
    parser.add_argument("file", help="Path to .vaultd file")
    parser.add_argument("--passphrase-stdin", action="store_true", help="Read passphrase from stdin")
    parser.add_argument("--json", action="store_true", help="Output raw JSON payload")
    args = parser.parse_args()

    if args.passphrase_stdin:
        passphrase = sys.stdin.readline().rstrip("\n")
    else:
        passphrase = getpass.getpass("Passphrase: ")

    try:
        payload = load_vaultd(args.file, passphrase)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        # Human-readable summary
        identity = payload.get("identity", {})
        holdings = payload.get("holdings", [])
        transactions = payload.get("transactions", [])
        defi = payload.get("defi_positions", [])
        thesis = payload.get("thesis", [])
        alerts = payload.get("alerts", [])

        print(f"\n[OK] .vaultd decrypted successfully")
        print(f"     Alias: {identity.get('alias', 'unknown')}")
        print(f"     Language: {identity.get('language', '?')} | Risk: {identity.get('risk_profile', '?')}")
        print(f"     Wallets: {len(payload.get('wallets', []))}")
        print(f"     Holdings: {len(holdings)}")
        print(f"     Transactions: {len(transactions)}")
        print(f"     DeFi positions: {len(defi)}")
        print(f"     Active theses: {sum(1 for t in thesis if t.get('status') == 'active')}")
        print(f"     Active alerts: {sum(1 for a in alerts if a.get('active'))}")

        pnl = payload.get("pnl", {})
        if pnl.get("realized_usd") is not None:
            print(f"     Realized PnL: ${pnl['realized_usd']:,.2f}")

        last_session = None
        history = payload.get("history", {}).get("sessions", [])
        if history:
            last_session = history[-1]
            print(f"     Last session: {last_session.get('date')} — {last_session.get('summary', '')[:80]}")

        print()


if __name__ == "__main__":
    main()
