"""
vaultd.importers.binance — Binance CSV importer.

Supported export formats:
  1. Binance Trade History CSV  (binance.com → Orders → Trade History → Export)
  2. Binance Transaction History CSV  (binance.com → Wallet → Transaction History → Export)
  3. Binance Deposit History CSV
  4. Binance Withdrawal History CSV

Binance Trade History columns:
  Date(UTC), Pair, Side, Price, Executed, Amount, Fee

Binance Transaction History columns:
  UTC_Time, Account, Operation, Coin, Change, Remark

Binance Deposit/Withdrawal columns:
  Date(UTC), Coin, Amount, TransactionFee, Address, TXID, SourceAddress, PaymentID, Status

Download from: binance.com → Wallet → Transaction History → Generate Statement
"""

from __future__ import annotations

import csv
from typing import Any

from vaultd.importers.base import BaseImporter, ImportResult

# Binance "Operation" field → vaultd transaction type
_OPERATION_MAP: dict[str, str] = {
    "buy": "buy",
    "sell": "sell",
    "deposit": "transfer_in",
    "withdrawal": "transfer_out",
    "transfer in": "transfer_in",
    "transfer out": "transfer_out",
    "fiat deposit": "transfer_in",
    "fiat withdrawal": "transfer_out",
    "spot trading": "buy",
    "commission": "airdrop",
    "commission rebate": "airdrop",
    "referral kickback": "airdrop",
    "distribution": "airdrop",
    "airdrop assets": "airdrop",
    "staking rewards": "claim_rewards",
    "staking reward": "claim_rewards",
    "staking purchase": "stake",
    "staking redemption": "unstake",
    "eth 2.0 staking": "stake",
    "eth 2.0 staking rewards": "claim_rewards",
    "savings interest": "claim_rewards",
    "launchpool interest": "claim_rewards",
    "flexible savings interest": "claim_rewards",
    "locked savings interest": "claim_rewards",
    "simple earn flexible interest": "claim_rewards",
    "simple earn locked rewards": "claim_rewards",
    "crypto box": "airdrop",
    "small assets exchange bnb": "swap",
    "convert": "swap",
    "binance convert": "swap",
    "auto-invest transaction": "buy",
    "buy crypto": "buy",
    "sell crypto": "sell",
    "c2c trading": "buy",
    "p2p trading": "buy",
}

# Binance trade Side field
_SIDE_MAP: dict[str, str] = {
    "buy": "buy",
    "sell": "sell",
    "0": "buy",  # numerical encoding in some exports
    "1": "sell",
}


class BinanceImporter(BaseImporter):
    """Parse Binance CSV exports (trade history or transaction history)."""

    source_name = "binance"

    def parse(self, csv_path: str, wallet_id: str = "default") -> ImportResult:
        result = ImportResult()

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            lines = f.readlines()

        if not lines:
            result.warnings.append("CSV file is empty.")
            return result

        # Skip Binance metadata header lines (some exports prefix with non-CSV lines)
        header_idx = 0
        for i, line in enumerate(lines):
            line_lower = line.lower()
            # Trade history detection
            if "date(utc)" in line_lower and ("pair" in line_lower or "side" in line_lower):
                header_idx = i
                break
            # Transaction history detection
            if "utc_time" in line_lower and "operation" in line_lower:
                header_idx = i
                break
            # Deposit/withdrawal detection
            if "date(utc)" in line_lower and "txid" in line_lower:
                header_idx = i
                break

        data_lines = lines[header_idx:]
        reader = csv.DictReader(data_lines)

        if reader.fieldnames is None:
            result.warnings.append("Could not detect CSV header. Is this a valid Binance export?")
            return result

        fieldnames_lower = [c.lower().strip() for c in reader.fieldnames]
        col_map = {c.lower().strip(): c for c in reader.fieldnames}

        def get(row: dict, *keys: str) -> str | None:
            for k in keys:
                original = col_map.get(k)
                if original and row.get(original, "").strip():
                    return row[original].strip()
            return None

        # Detect format
        is_trade = "pair" in fieldnames_lower and "side" in fieldnames_lower
        is_transaction = "utc_time" in fieldnames_lower and "operation" in fieldnames_lower
        is_deposit_withdrawal = "txid" in fieldnames_lower and "date(utc)" in fieldnames_lower

        for idx, row in enumerate(reader):
            if is_trade:
                tx = self._parse_trade_row(row, get, idx, wallet_id, result)
            elif is_transaction:
                tx = self._parse_transaction_row(row, get, idx, wallet_id, result)
            elif is_deposit_withdrawal:
                tx = self._parse_deposit_withdrawal_row(row, get, idx, wallet_id, result)
            else:
                # Best effort: try transaction format
                tx = self._parse_transaction_row(row, get, idx, wallet_id, result)
                if tx is None:
                    result.warnings.append(
                        f"Row {idx}: unrecognised Binance export format. "
                        "Supported: Trade History, Transaction History, Deposit/Withdrawal History."
                    )

            if tx:
                result.transactions.append(tx)

        return result

    def _parse_trade_row(
        self, row: dict, get, idx: int, wallet_id: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a Binance Trade History row.

        Trade History columns: Date(UTC), Pair, Side, Price, Executed, Amount, Fee
        Example: 2024-01-15 10:30:00, ETHUSDT, BUY, 2350.00, 0.5 ETH, 1175.00 USDT, 0.00050000 BNB
        """
        date_raw = get(row, "date(utc)", "date")
        pair = (get(row, "pair") or "").strip().upper()
        side_raw = (get(row, "side") or "").lower().strip()
        price_raw = get(row, "price")
        executed_raw = get(row, "executed")  # e.g. "0.5 ETH"
        amount_raw = get(row, "amount")      # e.g. "1175.00 USDT"
        fee_raw = get(row, "fee")            # e.g. "0.00050000 BNB"

        date = self._normalize_date(date_raw or "")
        if not date:
            result.skipped.append({"row": idx, "reason": f"Unparseable date: {date_raw}"})
            return None

        if not pair:
            result.skipped.append({"row": idx, "reason": "Missing pair"})
            return None

        vaultd_type = _SIDE_MAP.get(side_raw)
        if not vaultd_type:
            vaultd_type = "buy"
            result.warnings.append(
                f"Row {idx}: unknown Binance side '{side_raw}' → defaulted to 'buy'"
            )

        # Parse "0.5 ETH" → amount=0.5, asset="ETH"
        asset, amount = self._parse_amount_with_symbol(executed_raw or "")
        if amount is None or not asset:
            # Try to extract asset from pair
            asset = self._asset_from_pair(pair, vaultd_type)
            amount_price = self._safe_float(price_raw)
            amount_quote = self._safe_float(amount_raw)
            if amount_price and amount_quote and amount_price > 0:
                amount = amount_quote / amount_price
            else:
                result.skipped.append(
                    {"row": idx, "reason": f"Unparseable executed amount: {executed_raw}"}
                )
                return None

        price_usd = self._safe_float(price_raw)

        # Parse fee: "0.00050000 BNB" — record as note, not fee_usd (cross-asset)
        fee_note = f"fee: {fee_raw}" if fee_raw else ""

        tx_id = self._make_tx_id("binance", None, date, asset, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": asset.upper(),
            "amount": abs(amount),
            "price_usd": price_usd,
            "fee_usd": None,  # Fee is in BNB/base asset; stored in note
            "wallet_id": wallet_id,
            "tx_hash": None,
            "exchange": "binance",
            "note": f"pair: {pair}" + (f", {fee_note}" if fee_note else ""),
            "tags": ["imported", "binance", "trade"],
        }

    def _parse_transaction_row(
        self, row: dict, get, idx: int, wallet_id: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a Binance Transaction History row.

        Columns: UTC_Time, Account, Operation, Coin, Change, Remark
        """
        date_raw = get(row, "utc_time", "date(utc)", "date", "time")
        operation_raw = (get(row, "operation") or "").strip()
        coin = (get(row, "coin") or "").strip().upper()
        change_raw = get(row, "change")
        remark = get(row, "remark") or ""

        date = self._normalize_date(date_raw or "")
        if not date:
            result.skipped.append({"row": idx, "reason": f"Unparseable date: {date_raw}"})
            return None

        if not coin:
            result.skipped.append({"row": idx, "reason": "Missing coin symbol"})
            return None

        change = self._safe_float(change_raw)
        if change is None:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable change amount: {change_raw}"}
            )
            return None

        operation_lower = operation_raw.lower().strip()
        vaultd_type = _OPERATION_MAP.get(operation_lower)

        if not vaultd_type:
            # Infer from sign of change
            if change > 0:
                vaultd_type = "transfer_in"
            else:
                vaultd_type = "transfer_out"
            result.warnings.append(
                f"Row {idx}: unknown Binance operation '{operation_raw}' → "
                f"inferred '{vaultd_type}' from change sign"
            )

        # Override type from sign for buy/sell/transfer operations
        if vaultd_type in ("transfer_in", "buy") and change < 0:
            vaultd_type = "transfer_out"
        elif vaultd_type in ("transfer_out", "sell") and change > 0:
            vaultd_type = "transfer_in"

        tx_id = self._make_tx_id("binance", None, date, coin, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": coin,
            "amount": abs(change),
            "price_usd": None,
            "fee_usd": None,
            "wallet_id": wallet_id,
            "tx_hash": None,
            "exchange": "binance",
            "note": f"{operation_raw}" + (f" — {remark}" if remark else ""),
            "tags": ["imported", "binance", "transaction"],
        }

    def _parse_deposit_withdrawal_row(
        self, row: dict, get, idx: int, wallet_id: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a Binance Deposit/Withdrawal History row.

        Columns: Date(UTC), Coin, Amount, TransactionFee, Address, TXID, SourceAddress, Status
        """
        date_raw = get(row, "date(utc)", "date", "time")
        coin = (get(row, "coin") or "").strip().upper()
        amount_raw = get(row, "amount")
        fee_raw = get(row, "transactionfee", "fee")
        txid = get(row, "txid", "tx_id", "transaction id")
        status_raw = (get(row, "status") or "").lower().strip()

        # Skip incomplete/pending transactions
        if status_raw in ("failed", "fail", "cancelled", "rejected", "pending"):
            result.skipped.append(
                {"row": idx, "reason": f"Non-completed tx: status={status_raw}", "txid": txid}
            )
            return None

        date = self._normalize_date(date_raw or "")
        if not date:
            result.skipped.append({"row": idx, "reason": f"Unparseable date: {date_raw}"})
            return None

        if not coin:
            result.skipped.append({"row": idx, "reason": "Missing coin symbol"})
            return None

        amount = self._safe_float(amount_raw)
        if amount is None:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable amount: {amount_raw}"}
            )
            return None

        fee_usd = self._safe_float(fee_raw)

        # Deposits are transfer_in, withdrawals are transfer_out
        # Detect from context: presence of SourceAddress → deposit, Address is destination → withdrawal
        source_addr = get(row, "sourceaddress", "source address") or ""
        dest_addr = get(row, "address") or ""

        # Heuristic: if source address is present and non-empty, it's a deposit
        if source_addr and source_addr not in ("-", "N/A", ""):
            vaultd_type = "transfer_in"
        elif dest_addr and dest_addr not in ("-", "N/A", ""):
            vaultd_type = "transfer_out"
        else:
            vaultd_type = "transfer_in"  # Default to deposit if ambiguous

        tx_id = self._make_tx_id("binance", txid, date, coin, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": coin,
            "amount": abs(amount),
            "price_usd": None,
            "fee_usd": fee_usd,
            "wallet_id": wallet_id,
            "tx_hash": txid,
            "exchange": "binance",
            "note": "",
            "tags": ["imported", "binance", vaultd_type.replace("transfer_", "")],
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _parse_amount_with_symbol(self, value: str) -> tuple[str | None, float | None]:
        """Parse '0.5 ETH' → ('ETH', 0.5). Returns (None, None) on failure."""
        value = value.strip()
        if not value:
            return None, None
        parts = value.rsplit(" ", 1)
        if len(parts) == 2:
            amount = self._safe_float(parts[0])
            symbol = parts[1].strip().upper()
            if amount is not None and symbol:
                return symbol, amount
        return None, None

    def _asset_from_pair(self, pair: str, side: str) -> str:
        """Extract base asset from a Binance trading pair like 'ETHUSDT'."""
        # Common quote assets to strip
        for quote in ["USDT", "BUSD", "USDC", "BTC", "ETH", "BNB", "EUR", "USD"]:
            if pair.endswith(quote):
                return pair[: -len(quote)]
        return pair  # Fallback: return full pair as asset
