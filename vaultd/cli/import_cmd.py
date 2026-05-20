"""
vaultd-import — CLI entry point for importing exchange CSV exports into a .vaultd vault.

Usage:
  vaultd-import coinbase export.csv --vault portfolio.vaultd --wallet-id coinbase-main
  vaultd-import etherscan txns.csv --vault portfolio.vaultd --wallet-id hw-ledger --wallet-address 0xabc...
  vaultd-import solscan txns.csv --vault portfolio.vaultd --wallet-id sol-main --chain solana
  vaultd-import binance trades.csv --vault portfolio.vaultd --wallet-id binance
  vaultd-import kraken ledger.csv --vault portfolio.vaultd --wallet-id kraken-main
  vaultd-import coinbase export.csv --vault portfolio.vaultd --dry-run
"""

from __future__ import annotations

import argparse
import getpass
import sys

from vaultd.core import create_vaultd, load_vaultd
from vaultd.importers import IMPORTERS, get_importer
from vaultd.importers.merge import merge_transactions


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vaultd-import",
        description="Import exchange CSV exports into a .vaultd vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supported sources: {", ".join(IMPORTERS.keys())}

Examples:
  vaultd-import coinbase export.csv --vault portfolio.vaultd --wallet-id coinbase-main
  vaultd-import etherscan txns.csv --vault portfolio.vaultd --wallet-id hw-ledger --wallet-address 0xabc123
  vaultd-import coinbase export.csv --vault portfolio.vaultd --dry-run
        """,
    )
    parser.add_argument(
        "source",
        choices=list(IMPORTERS.keys()),
        help="Exchange source to import from",
    )
    parser.add_argument("csv_file", help="Path to the CSV export file")
    parser.add_argument("--vault", required=True, help="Path to your .vaultd file")
    parser.add_argument(
        "--wallet-id",
        default="default",
        help="wallet_id to assign to imported transactions (must exist in wallets[])",
    )
    parser.add_argument(
        "--wallet-address",
        default=None,
        help="(Etherscan/Solscan) Your wallet address, used to determine transfer direction",
    )
    parser.add_argument(
        "--chain",
        default=None,
        help="(Solscan only) Chain label to record on transactions (default: solana)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and show what would be imported without modifying the vault",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip JSON Schema validation after merge",
    )
    args = parser.parse_args()

    # Parse CSV first (no passphrase needed yet)
    print(f"[*] Parsing {args.source} CSV: {args.csv_file}")
    importer = get_importer(args.source)

    kwargs: dict = {"wallet_id": args.wallet_id}
    if args.source == "etherscan" and args.wallet_address:
        kwargs["wallet_address"] = args.wallet_address
    if args.source == "solscan":
        if args.wallet_address:
            kwargs["wallet_address"] = args.wallet_address
        if args.chain:
            kwargs["chain"] = args.chain

    try:
        result = importer.parse(args.csv_file, **kwargs)
    except FileNotFoundError:
        print(f"[ERROR] CSV file not found: {args.csv_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to parse CSV: {e}", file=sys.stderr)
        sys.exit(1)

    # Show parse results
    print(f"[*] Parsed {result.total} transactions, {result.skipped_count} skipped")
    if result.warnings:
        print(f"[WARN] {len(result.warnings)} warnings:")
        for w in result.warnings[:10]:
            print(f"  • {w}")
        if len(result.warnings) > 10:
            print(f"  … and {len(result.warnings) - 10} more")

    if result.total == 0:
        print("[INFO] No transactions to import. Exiting.")
        return

    # Dry run — show preview and exit
    if args.dry_run:
        print(f"\n[DRY RUN] Would import {result.total} transactions:")
        for tx in result.transactions[:5]:
            print(f"  {tx['date']} | {tx['type']:15s} | {tx['asset']:8s} | {tx['amount']}")
        if result.total > 5:
            print(f"  … and {result.total - 5} more")
        print("\n[DRY RUN] No changes made to vault.")
        return

    # Load vault
    passphrase = getpass.getpass(f"Passphrase for {args.vault}: ")
    try:
        payload = load_vaultd(args.vault, passphrase, skip_validation=True)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # Merge
    existing_txs = payload.get("transactions", [])
    merged, new_count, dup_count = merge_transactions(existing_txs, result.transactions)

    print("\n[*] Merge result:")
    print(f"    New transactions : {new_count}")
    print(f"    Duplicates skipped: {dup_count}")
    print(f"    Total after merge : {len(merged)}")

    if new_count == 0:
        print("[INFO] All transactions already exist in vault. Nothing to write.")
        return

    # Confirm before writing
    print(f"\n[?] Write {new_count} new transactions to {args.vault}? [y/N] ", end="")
    answer = input().strip().lower()
    if answer != "y":
        print("[INFO] Aborted. No changes made.")
        return

    # Update payload
    payload["transactions"] = merged

    # Save vault (atomic write, re-encrypt with same passphrase)
    try:
        create_vaultd(payload, passphrase, args.vault, skip_validation=args.skip_validation)
    except ValueError as e:
        print(f"[ERROR] Failed to save vault: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Vault updated: {new_count} new transactions added to {args.vault}")


if __name__ == "__main__":
    main()
