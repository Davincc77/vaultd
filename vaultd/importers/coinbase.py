"""
vaultd.importers.coinbase — Coinbase CSV importer.

Supported export format: Coinbase transaction history CSV
Columns: Timestamp, Transaction Type, Asset, Quantity Transacted,
         USD Spot Price at Transaction, USD Subtotal, USD Total (inclusive of fees and/or spread),
         USD Fees, Notes

Download from: Coinbase → Reports → Generate → Transaction History
"""

from __future__ import annotations

import csv
from typing import Any

from vaultd.importers.base import BaseImporter, ImportResult

# Map Coinbase transaction types to vaultd transaction types
_TYPE_MAP: dict[str, str] = {
    "buy": "buy",
    "sell": "sell",
    "send": "transfer_out",
    "receive": "transfer_in",
    "rewards income": "airdrop",
    "coinbase earn": "airdrop",
    "learning reward": "airdrop",
    "staking income": "airdrop",
    "interest income": "airdrop",
    "convert": "swap",
    "pro deposit": "transfer_in",
    "pro withdrawal": "transfer_out",
    "advance trade buy": "buy",
    "advance trade sell": "sell",
}

# Coinbase CSV column names (case-insensitive match)
_COL_TIMESTAMP = "timestamp"
_COL_TYPE = "transaction type"
_COL_ASSET = "asset"
_COL_QUANTITY = "quantity transacted"
_COL_SPOT_PRICE = "usd spot price at transaction"
_COL_SUBTOTAL = "usd subtotal"
_COL_TOTAL = "usd total (inclusive of fees and/or spread)"
_COL_FEES = "usd fees"
_COL_NOTES = "notes"


class CoinbaseImporter(BaseImporter):
    """Parse a Coinbase transaction history CSV export."""

    source_name = "coinbase"

    def parse(self, csv_path: str, wallet_id: str = "default") -> ImportResult:
        result = ImportResult()

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            # Skip Coinbase header lines (they add 7 lines of metadata before the actual CSV)
            lines = f.readlines()

        # Find the actual header row (contains "Timestamp" or "Transaction Type")
        header_idx = None
        for i, line in enumerate(lines):
            if "timestamp" in line.lower() and "transaction type" in line.lower():
                header_idx = i
                break

        if header_idx is None:
            result.warnings.append("Could not find header row. Is this a valid Coinbase CSV?")
            return result

        data_lines = lines[header_idx:]
        reader = csv.DictReader(data_lines)

        # Normalize column names to lowercase for matching
        if reader.fieldnames is None:
            result.warnings.append("CSV has no columns.")
            return result

        col_map = {col.lower().strip(): col for col in reader.fieldnames}

        def get(row: dict, key: str) -> str | None:
            original_key = col_map.get(key)
            if original_key is None:
                return None
            return row.get(original_key, "").strip() or None

        for idx, row in enumerate(reader):
            timestamp_raw = get(row, _COL_TIMESTAMP)
            tx_type_raw = (get(row, _COL_TYPE) or "").lower().strip()
            asset = get(row, _COL_ASSET)
            quantity_raw = get(row, _COL_QUANTITY)
            spot_price_raw = get(row, _COL_SPOT_PRICE)
            fees_raw = get(row, _COL_FEES)
            notes = get(row, _COL_NOTES)

            # Skip empty rows
            if not timestamp_raw and not asset:
                continue

            # Normalize date
            date = self._normalize_date(timestamp_raw or "")
            if not date:
                result.skipped.append({"row": idx, "reason": f"Unparseable timestamp: {timestamp_raw}", "raw": dict(row)})
                continue

            # Asset is required
            if not asset:
                result.skipped.append({"row": idx, "reason": "Missing asset", "raw": dict(row)})
                continue

            # Skip multi-asset convert rows (e.g. "BTC -> ETH" appears as separate rows anyway)
            if "->" in (asset or ""):
                result.warnings.append(f"Row {idx}: multi-asset convert '{asset}' skipped — appears as separate rows.")
                result.skipped.append({"row": idx, "reason": "multi-asset convert", "raw": dict(row)})
                continue

            # Map transaction type
            vaultd_type = _TYPE_MAP.get(tx_type_raw)
            if not vaultd_type:
                # Unknown type — default to transfer_in and warn
                vaultd_type = "transfer_in"
                result.warnings.append(
                    f"Row {idx}: unknown Coinbase type '{tx_type_raw}' → defaulted to 'transfer_in'"
                )

            # Parse amount
            amount = self._safe_float(quantity_raw)
            if amount is None:
                result.skipped.append({"row": idx, "reason": f"Unparseable quantity: {quantity_raw}", "raw": dict(row)})
                continue

            # For sell/transfer_out, amount should be negative in the ledger sense
            # but vaultd stores absolute amount + type encodes direction
            amount = abs(amount)

            price_usd = self._safe_float(spot_price_raw)
            fee_usd = self._safe_float(fees_raw)

            tx_id = self._make_tx_id("coinbase", None, date, asset, idx)

            tx: dict[str, Any] = {
                "id": tx_id,
                "date": date,
                "type": vaultd_type,
                "asset": asset.upper(),
                "amount": amount,
                "price_usd": price_usd,
                "fee_usd": fee_usd,
                "wallet_id": wallet_id,
                "tx_hash": None,
                "exchange": "coinbase",
                "note": notes or "",
                "tags": ["imported", "coinbase"],
            }

            result.transactions.append(tx)

        return result
