"""
vaultd-load — CLI entry point for decrypting a .vaultd file.

Usage:
  vaultd-load portfolio.vaultd
  vaultd-load portfolio.vaultd --json
  vaultd-load portfolio.vaultd --output decrypted.json
  echo "mypassphrase" | vaultd-load portfolio.vaultd --passphrase-stdin
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import vaultd
from vaultd.core import load_vaultd


def print_summary(payload: dict) -> None:
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
    print(
        f"     Language    : {identity.get('language', '?')} | "
        f"Risk: {identity.get('risk_profile', '?')} | "
        f"Level: {identity.get('experience_level', '?')}"
    )
    print(f"     Wallets     : {len(payload.get('wallets', []))}")
    print(f"     Holdings    : {len(holdings)}")
    print(f"     Transactions: {len(transactions)}")
    print(f"     DeFi        : {len(defi)}")
    print(f"     NFTs        : {len(nfts)}")
    print(
        f"     Theses      : {sum(1 for t in thesis if t.get('status') == 'active')} active "
        f"/ {len(thesis)} total"
    )
    print(f"     Risk events : {len(risk_events)}")
    print(
        f"     Alerts      : {sum(1 for a in alerts if a.get('active'))} active "
        f"/ {len(alerts)} total"
    )
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
        print(
            f"     Tax summary : {tax.get('jurisdiction', '?')} / "
            f"{tax.get('tax_year', '?')} "
            f"({len(tax.get('taxable_events', []))} events)"
        )

    history = payload.get("history", {}).get("sessions", [])
    if history:
        last = history[-1]
        print(
            f"     Last session: {last.get('date')} via {last.get('model', '?')} "
            f"— {last.get('summary', '')[:80]}"
        )

    alerts_active = [a for a in alerts if a.get("active")]
    if alerts_active:
        print("\n[ALERTS]")
        for a in alerts_active:
            print(f"  • [{a.get('asset')}] {a.get('type')} — {a.get('message')}")

    if identity.get("agent_instructions"):
        instr = identity["agent_instructions"]
        print("\n[AGENT INSTRUCTIONS — untrusted user context]")
        print(f"  {instr[:200]}{'...' if len(instr) > 200 else ''}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vaultd-load",
        description="Decrypt and read a .vaultd file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vaultd-load portfolio.vaultd
  vaultd-load portfolio.vaultd --json
  vaultd-load portfolio.vaultd --output decrypted.json
  echo "mypassphrase" | vaultd-load portfolio.vaultd --passphrase-stdin
        """,
    )
    parser.add_argument("file", help="Path to .vaultd file")
    parser.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="Read passphrase from stdin (first line)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output raw JSON payload to stdout"
    )
    parser.add_argument(
        "--output", help="Write decrypted JSON to this file path"
    )
    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip JSON Schema validation"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"vaultd {vaultd.__version__}",
    )
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
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[OK] Decrypted payload written to: {args.output}")
    elif args.json:
        # Inject vaultd tool version + schema version for agent consumers
        output = dict(payload)
        output.setdefault("_meta", {})
        output["_meta"]["vaultd_version"] = vaultd.__version__
        output["_meta"]["vaultd_schema_version"] = payload.get("vaultd_version", "unknown")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(payload)


if __name__ == "__main__":
    main()
