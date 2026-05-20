"""
vaultd-price — Fetch live prices from CoinGecko and optionally update vault.

Usage:
  vaultd-price --vault portfolio.vaultd
  vaultd-price --vault portfolio.vaultd --write
  vaultd-price --vault portfolio.vaultd --tickers BTC ETH SOL
  vaultd-price --vault portfolio.vaultd --force-refresh
"""

from __future__ import annotations

import argparse
import getpass
import sys

from vaultd.core import create_vaultd, load_vaultd
from vaultd.oracle import build_price_update_delta, fetch_prices


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vaultd-price",
        description="Fetch live prices from CoinGecko and optionally update vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vaultd-price --vault portfolio.vaultd
  vaultd-price --vault portfolio.vaultd --write
  vaultd-price --vault portfolio.vaultd --tickers BTC ETH SOL --force-refresh
        """,
    )
    parser.add_argument("--vault", required=True, help="Path to your .vaultd file")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Specific tickers to fetch (default: all assets in holdings)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Prompt to write updated prices back to vault (requires confirmation)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass cache and fetch live from CoinGecko",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip JSON Schema validation",
    )
    args = parser.parse_args()

    # Load vault
    passphrase = getpass.getpass(f"Passphrase for {args.vault}: ")
    try:
        payload = load_vaultd(args.vault, passphrase, skip_validation=True)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    holdings = payload.get("holdings", [])
    if not holdings:
        print("[INFO] No holdings found in vault.")
        return

    # Determine which tickers to fetch
    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        tickers = list({h.get("asset", "").upper() for h in holdings if h.get("asset")})

    if not tickers:
        print("[INFO] No tickers to fetch.")
        return

    print(f"[*] Fetching prices for: {', '.join(sorted(tickers))}")
    result = fetch_prices(tickers, force_refresh=args.force_refresh)

    if result.cached:
        print(f"[*] Served from cache ({result.cache_age_seconds:.0f}s old — use --force-refresh to bypass)")
    else:
        print(f"[*] Live prices fetched at {result.fetched_at}")

    # Display prices
    print()
    print(f"  {'Asset':<8} {'Price (USD)':>14}  {'Avg Buy':>14}  {'Unrealized PnL':>16}  {'Change'}")
    print(f"  {'-'*8} {'-'*14}  {'-'*14}  {'-'*16}  {'-'*10}")

    for h in sorted(holdings, key=lambda x: x.get("asset", "")):
        asset = h.get("asset", "?").upper()
        price = result.get(asset)
        avg_buy = h.get("avg_buy_price_usd")
        amount = h.get("amount", 0)
        old_price = h.get("current_price_usd")

        if price is not None:
            pnl = (price - avg_buy) * amount if avg_buy else None
            pnl_str = f"${pnl:>+,.2f}" if pnl is not None else "N/A"
            change_str = ""
            if old_price:
                chg_pct = (price - old_price) / old_price * 100
                arrow = "▲" if chg_pct >= 0 else "▼"
                change_str = f"{arrow} {abs(chg_pct):.1f}%"
            print(f"  {asset:<8} ${price:>13,.2f}  ${avg_buy:>13,.2f}  {pnl_str:>16}  {change_str}")
        else:
            print(f"  {asset:<8} {'N/A':>14}  {'':>14}  {'':>16}")

    if result.unknown_tickers:
        print(f"\n[WARN] Unknown tickers (not in CoinGecko map): {', '.join(result.unknown_tickers)}")
        print("       Add them to vaultd/oracle.py _TICKER_TO_CG_ID or provide prices manually.")

    # Portfolio summary
    total_value = sum(
        (result.get(h.get("asset", "")) or 0) * h.get("amount", 0)
        for h in holdings
    )
    total_cost = sum(
        (h.get("avg_buy_price_usd") or 0) * h.get("amount", 0)
        for h in holdings
    )
    if total_value > 0:
        print(f"\n  Total portfolio value : ${total_value:>12,.2f}")
        print(f"  Total cost basis      : ${total_cost:>12,.2f}")
        print(f"  Unrealized PnL        : ${total_value - total_cost:>+12,.2f}  ({(total_value - total_cost) / total_cost * 100:.1f}%)" if total_cost else "")

    # Check alerts
    alerts = [a for a in payload.get("alerts", []) if a.get("active")]
    triggered = []
    for alert in alerts:
        asset = alert.get("asset", "").upper()
        price = result.get(asset)
        if price is None:
            continue
        atype = alert.get("type", "")
        threshold = alert.get("threshold_usd")
        if atype == "price_below" and threshold and price < threshold:
            triggered.append(f"⚠ {asset} price ${price:,.2f} is below your alert threshold ${threshold:,.2f} — {alert.get('message')}")
        elif atype == "price_above" and threshold and price > threshold:
            triggered.append(f"⚠ {asset} price ${price:,.2f} is above your alert threshold ${threshold:,.2f} — {alert.get('message')}")

    if triggered:
        print("\n[ALERTS TRIGGERED]")
        for t in triggered:
            print(f"  {t}")

    # Write prices back to vault
    if not args.write:
        print("\n[INFO] Prices not written. Use --write to update current_price_usd in vault.")
        return

    deltas = build_price_update_delta(holdings, result)
    if not deltas:
        print("\n[INFO] No price changes to write.")
        return

    print(f"\n[?] Proposed updates to current_price_usd ({len(deltas)} holdings):")
    for d in deltas:
        old = f"${d['old_value']:,.2f}" if d["old_value"] else "null"
        new = f"${d['new_value']:,.2f}"
        pnl = f"  (PnL: ${d['pnl_impact_usd']:+,.2f})" if d["pnl_impact_usd"] is not None else ""
        print(f"  [{d['asset']}] {old} → {new}{pnl}")

    print(f"\n[?] Write {len(deltas)} price updates to {args.vault}? [y/N] ", end="")
    answer = input().strip().lower()
    if answer != "y":
        print("[INFO] Aborted. No changes made.")
        return

    # Apply deltas
    price_map = {d["holding_id"]: d["new_value"] for d in deltas}
    for h in holdings:
        if h.get("id") in price_map:
            h["current_price_usd"] = price_map[h["id"]]

    payload["holdings"] = holdings

    try:
        create_vaultd(payload, passphrase, args.vault, skip_validation=args.skip_validation)
    except ValueError as e:
        print(f"[ERROR] Failed to save vault: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] {len(deltas)} prices updated in {args.vault}")


if __name__ == "__main__":
    main()
