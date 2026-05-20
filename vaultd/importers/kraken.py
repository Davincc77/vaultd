"""
vaultd.importers.kraken — Kraken CSV importer.

Supported export formats:
  1. Kraken Ledger Export  (kraken.com → History → Export → Ledgers)
  2. Kraken Trade Export   (kraken.com → History → Export → Trades)

Kraken Ledger columns:
  txid, refid, time, type, subtype, aclass, asset, amount, fee, balance

Kraken Trades columns:
  txid, ordertxid, pair, time, type, ordertype, price, cost, fee, vol, margin,
  misc, ledgers, postxid

Download from: kraken.com → History → Export → select Ledgers or Trades → All time

Notes:
  - Kraken uses its own asset naming convention (XXBT = BTC, XETH = ETH, ZEUR = EUR)
    which is normalised automatically.
  - Staking entries appear as type=transfer with subtype=stakingtospot or spottostaking.
  - Staking rewards appear as type=staking.
"""

from __future__ import annotations

import csv
from typing import Any

from vaultd.importers.base import BaseImporter, ImportResult

# Kraken asset name → canonical symbol
_ASSET_ALIASES: dict[str, str] = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "XLTC": "LTC",
    "XXRP": "XRP",
    "XXLM": "XLM",
    "XZEC": "ZEC",
    "XXMR": "XMR",
    "ZEUR": "EUR",
    "ZUSD": "USD",
    "ZGBP": "GBP",
    "ZCAD": "CAD",
    "ZJPY": "JPY",
    "ETHW": "ETHW",
    # Most other assets use their plain symbol (SOL, DOT, MATIC, etc.)
}

# Kraken ledger type + subtype → vaultd transaction type
_LEDGER_TYPE_MAP: dict[str, str] = {
    "buy": "buy",
    "sell": "sell",
    "trade": "buy",       # resolved per-row via sign of amount
    "deposit": "transfer_in",
    "withdrawal": "transfer_out",
    "transfer": "transfer_in",  # refined by subtype below
    "staking": "claim_rewards",
    "reward": "claim_rewards",
    "receive": "transfer_in",
    "spend": "transfer_out",
    "earn": "claim_rewards",
    "airdrop": "airdrop",
    "dividend": "airdrop",
    "settled": "buy",
    "margin trade": "buy",
}

# Kraken transfer subtypes
_SUBTYPE_MAP: dict[str, str] = {
    "spottostaking": "stake",
    "stakingtospot": "unstake",
    "spotfromstaking": "unstake",
    "stakingtospotfromstaking": "unstake",
    "stakingtospot.": "unstake",
    "spotfromfutures": "transfer_in",
    "spottofutures": "transfer_out",
}

# Kraken trade types (from trades export)
_TRADE_TYPE_MAP: dict[str, str] = {
    "buy": "buy",
    "sell": "sell",
}


class KrakenImporter(BaseImporter):
    """Parse a Kraken Ledger or Trade history CSV export."""

    source_name = "kraken"

    def parse(self, csv_path: str, wallet_id: str = "default") -> ImportResult:
        result = ImportResult()

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                result.warnings.append("CSV has no columns. Is this a valid Kraken export?")
                return result

            fieldnames_lower = [c.lower().strip() for c in reader.fieldnames]
            col_map = {c.lower().strip(): c for c in reader.fieldnames}

            # Detect export type
            is_trades = "ordertxid" in fieldnames_lower or "vol" in fieldnames_lower

            def get(row: dict, *keys: str) -> str | None:
                for k in keys:
                    original = col_map.get(k)
                    if original and row.get(original, "").strip():
                        return row[original].strip()
                return None

            for idx, row in enumerate(reader):
                if is_trades:
                    tx = self._parse_trade_row(row, get, idx, wallet_id, result)
                else:
                    # Default to ledger (also works for unlabelled exports)
                    tx = self._parse_ledger_row(row, get, idx, wallet_id, result)

                if tx:
                    result.transactions.append(tx)

        return result

    def _parse_ledger_row(
        self, row: dict, get, idx: int, wallet_id: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a Kraken Ledger export row."""
        txid = get(row, "txid")
        refid = get(row, "refid")
        time_raw = get(row, "time", "date")
        type_raw = (get(row, "type") or "").lower().strip()
        subtype_raw = (get(row, "subtype") or "").lower().strip().replace(" ", "")
        asset_raw = (get(row, "asset") or "").strip()
        amount_raw = get(row, "amount")
        fee_raw = get(row, "fee")

        # Skip empty / header repeat rows
        if not time_raw and not asset_raw:
            return None

        date = self._normalize_date(time_raw or "")
        if not date:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable date: {time_raw}", "txid": txid}
            )
            return None

        # Normalize asset symbol
        asset = self._normalize_asset(asset_raw)
        if not asset:
            result.skipped.append({"row": idx, "reason": "Missing asset symbol", "txid": txid})
            return None

        # Skip pure fiat currency entries (EUR/USD/GBP deposits don't represent crypto)
        if asset in ("EUR", "USD", "GBP", "CAD", "JPY", "CHF", "AUD"):
            result.skipped.append(
                {"row": idx, "reason": f"Fiat currency entry ({asset}) skipped", "txid": txid}
            )
            return None

        amount = self._safe_float(amount_raw)
        if amount is None:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable amount: {amount_raw}", "txid": txid}
            )
            return None

        fee_raw_val = self._safe_float(fee_raw)
        # fee is in the same asset — only useful as USD if the asset is a stablecoin
        fee_usd = fee_raw_val if asset in ("USDT", "USDC", "BUSD", "DAI") else None

        # Determine vaultd transaction type
        vaultd_type = _SUBTYPE_MAP.get(subtype_raw) if subtype_raw else None
        if not vaultd_type:
            vaultd_type = _LEDGER_TYPE_MAP.get(type_raw)

        if not vaultd_type:
            # Infer from sign
            if amount > 0:
                vaultd_type = "transfer_in"
            else:
                vaultd_type = "transfer_out"
            result.warnings.append(
                f"Row {idx}: unknown Kraken type '{type_raw}' subtype '{subtype_raw}' "
                f"→ inferred '{vaultd_type}' from sign"
            )
        else:
            # Correct direction from amount sign for ambiguous types
            if vaultd_type in ("buy", "transfer_in", "claim_rewards", "airdrop") and amount < 0:
                vaultd_type = "sell" if type_raw == "trade" else "transfer_out"
            elif vaultd_type in ("sell", "transfer_out") and amount > 0:
                vaultd_type = "buy" if type_raw == "trade" else "transfer_in"

        tx_id = self._make_tx_id("kraken", txid or refid, date, asset, idx)

        note_parts = []
        if type_raw:
            note_parts.append(f"type: {type_raw}")
        if subtype_raw:
            note_parts.append(f"subtype: {subtype_raw}")
        if fee_raw_val and fee_raw_val > 0:
            note_parts.append(f"fee: {fee_raw_val} {asset}")

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": asset,
            "amount": abs(amount),
            "price_usd": None,  # Kraken ledger doesn't include price
            "fee_usd": fee_usd,
            "wallet_id": wallet_id,
            "tx_hash": txid,
            "exchange": "kraken",
            "note": ", ".join(note_parts),
            "tags": ["imported", "kraken", type_raw] if type_raw else ["imported", "kraken"],
        }

    def _parse_trade_row(
        self, row: dict, get, idx: int, wallet_id: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a Kraken Trade export row.

        Trades columns: txid, ordertxid, pair, time, type, ordertype, price, cost, fee, vol
        """
        txid = get(row, "txid")
        pair_raw = (get(row, "pair") or "").strip().upper()
        time_raw = get(row, "time", "date")
        type_raw = (get(row, "type") or "").lower().strip()
        price_raw = get(row, "price")
        fee_raw = get(row, "fee")
        vol_raw = get(row, "vol", "volume")
        cost_raw = get(row, "cost")

        date = self._normalize_date(time_raw or "")
        if not date:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable date: {time_raw}", "txid": txid}
            )
            return None

        vaultd_type = _TRADE_TYPE_MAP.get(type_raw)
        if not vaultd_type:
            vaultd_type = "buy"
            result.warnings.append(
                f"Row {idx}: unknown Kraken trade type '{type_raw}' → defaulted to 'buy'"
            )

        # Parse volume (base asset quantity traded)
        amount = self._safe_float(vol_raw)
        if amount is None:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable volume: {vol_raw}", "txid": txid}
            )
            return None

        price_usd = self._safe_float(price_raw)
        cost = self._safe_float(cost_raw)
        fee_val = self._safe_float(fee_raw)

        # Extract base asset from pair (e.g. XXBTZEUR → BTC, SOLUSD → SOL)
        asset = self._asset_from_pair(pair_raw)

        # fee_usd: Kraken trade fees are in the quote currency
        # If quote is a stablecoin/fiat, fee is effectively USD
        quote = self._quote_from_pair(pair_raw)
        fee_usd = fee_val if quote in ("USD", "USDT", "USDC", "EUR") else None

        tx_id = self._make_tx_id("kraken", txid, date, asset, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": asset,
            "amount": abs(amount),
            "price_usd": price_usd,
            "fee_usd": fee_usd,
            "wallet_id": wallet_id,
            "tx_hash": txid,
            "exchange": "kraken",
            "note": f"pair: {pair_raw}" + (f", cost: {cost} {quote}" if cost else ""),
            "tags": ["imported", "kraken", "trade"],
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _normalize_asset(self, raw: str) -> str | None:
        """Normalize Kraken asset codes to standard symbols."""
        if not raw:
            return None
        raw = raw.strip().upper()
        return _ASSET_ALIASES.get(raw, raw) or None

    def _asset_from_pair(self, pair: str) -> str:
        """Extract base asset from Kraken pair string."""
        # Kraken uses XXBTZEUR, ETHUSD, SOLUSD, etc.
        # Normalize first
        normalized = _ASSET_ALIASES.get(pair[:4], None)
        if normalized:
            return normalized

        # Strip known quote currencies from end
        for quote in ["ZEUR", "ZUSD", "XXBT", "XETH", "USD", "EUR", "USDT", "USDC", "GBP"]:
            if pair.endswith(quote):
                base = pair[: -len(quote)]
                return _ASSET_ALIASES.get(base, base)

        # Fallback: return first 3 chars as asset
        return _ASSET_ALIASES.get(pair[:3], pair[:3])

    def _quote_from_pair(self, pair: str) -> str:
        """Extract quote currency from Kraken pair."""
        for quote in ["ZEUR", "ZUSD", "USDT", "USDC", "EUR", "USD", "GBP", "XXBT", "XETH"]:
            if pair.endswith(quote):
                return _ASSET_ALIASES.get(quote, quote)
        return ""
