"""
vaultd-save — CLI entry point for encrypting a .vaultd file.

Usage:
  vaultd-save --payload examples/example_v11_full.json --output portfolio.vaultd
  vaultd-save --payload data.json --output vault.vaultd --argon2-m 131072 --argon2-t 4
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from vaultd.core import (
    DEFAULT_ARGON2_M,
    DEFAULT_ARGON2_P,
    DEFAULT_ARGON2_T,
    MIN_PASSPHRASE_LEN,
    VAULTD_E_PASSPHRASE,
    create_vaultd,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vaultd-save",
        description="Create an encrypted .vaultd file (AES-256-GCM + Argon2id)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vaultd-save --payload portfolio.json --output portfolio.vaultd
  vaultd-save --payload data.json --output vault.vaultd --argon2-m 131072 --argon2-t 4
  vaultd-save --payload data.json --output vault.vaultd --skip-validation
        """,
    )
    parser.add_argument("--payload", required=True, help="Path to JSON payload file")
    parser.add_argument("--output", required=True, help="Output .vaultd file path")
    parser.add_argument(
        "--argon2-m",
        type=int,
        default=DEFAULT_ARGON2_M,
        help=f"Argon2id memory cost in KiB (default: {DEFAULT_ARGON2_M} = 64 MiB). "
        "Use 131072 for high-value vaults.",
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

    with open(args.payload, "r", encoding="utf-8") as f:
        payload = json.load(f)

    passphrase = getpass.getpass("Passphrase: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if passphrase != confirm:
        print(f"[ERROR] {VAULTD_E_PASSPHRASE}: Passphrases do not match", file=sys.stderr)
        sys.exit(1)
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        print(
            f"[WARN] Passphrase is short ({len(passphrase)} chars). "
            f"Use at least {MIN_PASSPHRASE_LEN} characters for a financial vault."
        )
        answer = input("Continue anyway? [y/N] ").strip().lower()
        if answer != "y":
            sys.exit(0)

    if args.argon2_m < 16384:
        print("[WARN] Argon2id memory < 16 MiB — consider at least 65536 (64 MiB).")
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
        print(f"[OK] .vaultd file created: {args.output}")
        print(f"     Argon2id: m={args.argon2_m}, t={args.argon2_t}, p={args.argon2_p}")
        print(f"     Version : vaultd v1.2 / klickd v3.0")
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
