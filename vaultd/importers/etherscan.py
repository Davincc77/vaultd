"""
vaultd.importers.etherscan — Etherscan CSV importer.

Supports:
  - ETH normal transactions export (etherscan.io/exportData → Transactions)
  - ERC-20 token transfers export (etherscan.io/exportData → ERC-20 Token Txns)

Etherscan normal TX columns:
  Txhash, Blockno, UnixTimestamp, DateTime (UTC), From, To, ContractAddress,
  Value_IN(ETH), Value_OUT(ETH), CurrentValue, TxnFee(ETH), TxnFee(USD),
  Historical $Price/Eth, Status, ErrCode, Method

Etherscan ERC-20 columns:
  Txhash, Blockno, UnixTimestamp, DateTime (UTC), From, To, TokenValue,
  USDValueDayOf, ContractAddress, TokenName, TokenSymbol
"""

from __future__ import annotations

import csv
from typing import Any

from vaultd.importers.base import BaseImporter, ImportResult

# Spam/dust filter: ignore transfers below this USD value if price available
_MIN_USD_VALUE = 0.01

# Internal/zero-value tx: skip if ETH value is 0 and it's a contract interaction
_ZERO_ETH = 0.0


class EtherscanImporter(BaseImporter):
    """Parse an Etherscan transaction export CSV (normal txs or ERC-20 token transfers)."""

    source_name = "etherscan"

    def parse(
        self,
        csv_path: str,
        wallet_id: str = "default",
        wallet_address: str | None = None,
    ) -> ImportResult:
        """
        Args:
            csv_path: Path to Etherscan CSV export.
            wallet_id: The wallet_id to assign in vaultd.
            wallet_address: Your Ethereum address (lowercase). Used to determine
                           transfer_in vs transfer_out. If None, defaults to transfer_in.
        """
        result = ImportResult()
        wallet_address = (wallet_address or "").lower().strip()

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                result.warnings.append("CSV has no columns.")
                return result

            # Detect export type
            fieldnames_lower = [c.lower().strip() for c in reader.fieldnames]
            is_erc20 = "tokensymbol" in fieldnames_lower or "token symbol" in fieldnames_lower
            is_normal = "value_in(eth)" in fieldnames_lower or "value_out(eth)" in fieldnames_lower

            col_map = {c.lower().strip(): c for c in reader.fieldnames}

            def get(row: dict, *keys: str) -> str | None:
                for k in keys:
                    original = col_map.get(k)
                    if original and row.get(original, "").strip():
                        return row[original].strip()
                return None

            for idx, row in enumerate(reader):
                tx_hash = get(row, "txhash", "hash")
                date_raw = get(row, "datetime (utc)", "datetime", "date(utc)")
                status = get(row, "status") or ""
                err_code = get(row, "errcode", "error") or ""

                # Skip failed transactions
                if status.lower() in ("error", "fail", "failed") or err_code not in ("", "0", None):
                    result.skipped.append({"row": idx, "reason": f"Failed tx: status={status}", "tx_hash": tx_hash})
                    continue

                date = self._normalize_date(date_raw or "")
                if not date:
                    result.skipped.append({"row": idx, "reason": f"Unparseable date: {date_raw}", "tx_hash": tx_hash})
                    continue

                if is_erc20:
                    tx = self._parse_erc20_row(row, get, idx, tx_hash, date, wallet_id, wallet_address, result)
                elif is_normal:
                    tx = self._parse_normal_row(row, get, idx, tx_hash, date, wallet_id, wallet_address, result)
                else:
                    # Unknown format — try best-effort
                    tx = self._parse_normal_row(row, get, idx, tx_hash, date, wallet_id, wallet_address, result)
                    result.warnings.append(f"Row {idx}: unknown Etherscan export format, attempting best-effort parse.")

                if tx:
                    result.transactions.append(tx)

        return result

    def _parse_normal_row(
        self, row: dict, get, idx: int, tx_hash: str | None,
        date: str, wallet_id: str, wallet_address: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a normal ETH transaction row."""
        value_in = self._safe_float(get(row, "value_in(eth)")) or 0.0
        value_out = self._safe_float(get(row, "value_out(eth)")) or 0.0
        fee_eth = self._safe_float(get(row, "txnfee(eth)", "txfee(eth)"))
        fee_usd = self._safe_float(get(row, "txnfee(usd)", "txfee(usd)"))
        eth_price = self._safe_float(get(row, "historical $price/eth", "historicalprice"))
        from_addr = (get(row, "from") or "").lower()
        to_addr = (get(row, "to") or "").lower()

        # Determine direction
        net_value = value_in - value_out
        if abs(net_value) < 1e-10 and (fee_eth or 0) > 0:
            # Pure contract interaction / internal tx with no ETH value — record as fee
            amount = fee_eth or 0.0
            tx_type = "fee"
            asset = "ETH"
            price_usd = eth_price
        elif net_value > 0:
            amount = net_value
            tx_type = "transfer_in"
            asset = "ETH"
            price_usd = eth_price
        elif net_value < 0:
            amount = abs(net_value)
            tx_type = "transfer_out"
            asset = "ETH"
            price_usd = eth_price
        else:
            result.skipped.append({"row": idx, "reason": "Zero-value internal tx", "tx_hash": tx_hash})
            return None

        # Spam filter
        if price_usd and amount * price_usd < _MIN_USD_VALUE:
            result.skipped.append({"row": idx, "reason": f"Dust tx (value < ${_MIN_USD_VALUE})", "tx_hash": tx_hash})
            return None

        # Convert fee from ETH to USD if possible
        if fee_usd is None and fee_eth and eth_price:
            fee_usd = fee_eth * eth_price

        tx_id = self._make_tx_id("etherscan", tx_hash, date, asset, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": tx_type,
            "asset": asset,
            "amount": round(amount, 18),
            "price_usd": price_usd,
            "fee_usd": round(fee_usd, 6) if fee_usd else None,
            "wallet_id": wallet_id,
            "tx_hash": tx_hash,
            "exchange": "etherscan",
            "note": f"From: {from_addr[:10]}… → To: {to_addr[:10]}…" if from_addr else "",
            "tags": ["imported", "etherscan", "eth"],
        }

    def _parse_erc20_row(
        self, row: dict, get, idx: int, tx_hash: str | None,
        date: str, wallet_id: str, wallet_address: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse an ERC-20 token transfer row."""
        token_symbol = get(row, "tokensymbol", "token symbol") or "UNKNOWN"
        token_value_raw = get(row, "tokenvalue", "token value", "quantity")
        usd_value = self._safe_float(get(row, "usdvaluedayof", "usd value (day of)"))
        from_addr = (get(row, "from") or "").lower()
        to_addr = (get(row, "to") or "").lower()

        amount = self._safe_float(token_value_raw)
        if amount is None:
            result.skipped.append({"row": idx, "reason": f"Unparseable token value: {token_value_raw}", "tx_hash": tx_hash})
            return None

        amount = abs(amount)

        # Spam filter
        if usd_value is not None and usd_value < _MIN_USD_VALUE:
            result.skipped.append({"row": idx, "reason": f"Dust token transfer (< ${_MIN_USD_VALUE})", "tx_hash": tx_hash})
            return None

        # Determine direction using wallet address
        if wallet_address:
            if to_addr == wallet_address:
                tx_type = "transfer_in"
            elif from_addr == wallet_address:
                tx_type = "transfer_out"
            else:
                tx_type = "transfer_in"  # default if address unknown
                result.warnings.append(f"Row {idx}: could not determine direction for {token_symbol}, defaulted to transfer_in")
        else:
            tx_type = "transfer_in"

        # Compute price_usd per token if possible
        price_usd = (usd_value / amount) if (usd_value and amount > 0) else None

        tx_id = self._make_tx_id("etherscan", tx_hash, date, token_symbol, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": tx_type,
            "asset": token_symbol.upper(),
            "amount": amount,
            "price_usd": price_usd,
            "fee_usd": None,  # Fee is in ETH, not available in ERC-20 export
            "wallet_id": wallet_id,
            "tx_hash": tx_hash,
            "exchange": "etherscan",
            "note": f"ERC-20 transfer from {from_addr[:10]}…" if from_addr else "",
            "tags": ["imported", "etherscan", "erc20"],
        }
