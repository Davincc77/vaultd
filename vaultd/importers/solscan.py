"""
vaultd.importers.solscan — Solscan CSV importer for Solana transactions.

Supported export formats:
  1. Solscan account transactions export (solscan.io → Account → Transactions → Export CSV)
  2. Solscan SPL token transfers export (solscan.io → Account → Token Accounts → Export)

Solscan transactions CSV columns:
  Signature, Block, Time, From, To, SOL Amount, Fee(SOL), Status, Type, Program

Solscan SPL token transfers CSV columns:
  Signature, Block, Time, From, To, Token Address, Token Symbol, Token Amount, Type

Download from:
  - https://solscan.io/account/<ADDRESS> → Transactions tab → Export
  - https://solscan.io/account/<ADDRESS> → Token Accounts → individual token → Transfers → Export
"""

from __future__ import annotations

import csv
from typing import Any

from vaultd.importers.base import BaseImporter, ImportResult

# SOL price is not included in Solscan exports — price_usd will be None
# Users should run vaultd-price to populate current prices after import.

# Solscan transaction type → vaultd transaction type
_TYPE_MAP: dict[str, str] = {
    "sol transfer": "transfer_in",
    "spl transfer": "transfer_in",
    "spl transfer in": "transfer_in",
    "spl transfer out": "transfer_out",
    "transfer": "transfer_in",
    "transfer in": "transfer_in",
    "transfer out": "transfer_out",
    "send": "transfer_out",
    "receive": "transfer_in",
    "swap": "swap",
    "jupiter swap": "swap",
    "orca swap": "swap",
    "raydium swap": "swap",
    "stake": "stake",
    "unstake": "unstake",
    "stake account creation": "stake",
    "deactivate stake": "unstake",
    "claim rewards": "claim_rewards",
    "staking reward": "claim_rewards",
    "airdrop": "airdrop",
    "mint": "airdrop",
    "nft mint": "nft_mint",
}

_MIN_SOL_VALUE = 0.0001  # Filter out dust / failed-fee-only txs


class SolscanImporter(BaseImporter):
    """Parse a Solscan account transaction or SPL token transfer CSV export."""

    source_name = "solscan"

    def parse(
        self,
        csv_path: str,
        wallet_id: str = "default",
        wallet_address: str | None = None,
        chain: str = "solana",
    ) -> ImportResult:
        """
        Args:
            csv_path: Path to the Solscan CSV export.
            wallet_id: wallet_id to assign to imported transactions.
            wallet_address: Your Solana public key. Used to determine
                            transfer_in vs transfer_out direction. Optional.
            chain: chain label to record on transactions (default: "solana").
        """
        result = ImportResult()
        wallet_address = (wallet_address or "").strip()

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                result.warnings.append("CSV has no columns. Is this a valid Solscan export?")
                return result

            fieldnames_lower = [c.lower().strip() for c in reader.fieldnames]
            col_map = {c.lower().strip(): c for c in reader.fieldnames}

            # Detect export type
            is_spl = "token symbol" in fieldnames_lower or "token amount" in fieldnames_lower
            is_normal = "sol amount" in fieldnames_lower

            if not is_spl and not is_normal:
                result.warnings.append(
                    "Could not detect export type (expected 'SOL Amount' or 'Token Symbol' columns). "
                    "Attempting best-effort parse."
                )

            def get(row: dict, *keys: str) -> str | None:
                for k in keys:
                    original = col_map.get(k)
                    if original and row.get(original, "").strip():
                        return row[original].strip()
                return None

            for idx, row in enumerate(reader):
                sig = get(row, "signature", "txhash", "tx hash", "hash")
                time_raw = get(row, "time", "datetime", "date", "block time")
                status = (get(row, "status") or "").lower().strip()
                tx_type_raw = (get(row, "type", "transaction type") or "").lower().strip()
                from_addr = (get(row, "from") or "").strip()
                to_addr = (get(row, "to") or "").strip()

                # Skip failed transactions
                if status in ("fail", "error", "failed"):
                    result.skipped.append(
                        {"row": idx, "reason": f"Failed tx: {status}", "sig": sig}
                    )
                    continue

                date = self._normalize_date(time_raw or "")
                if not date:
                    result.skipped.append(
                        {"row": idx, "reason": f"Unparseable timestamp: {time_raw}", "sig": sig}
                    )
                    continue

                if is_spl:
                    tx = self._parse_spl_row(
                        row, get, idx, sig, date, wallet_id, wallet_address,
                        from_addr, to_addr, tx_type_raw, chain, result
                    )
                else:
                    tx = self._parse_sol_row(
                        row, get, idx, sig, date, wallet_id, wallet_address,
                        from_addr, to_addr, tx_type_raw, chain, result
                    )

                if tx:
                    result.transactions.append(tx)

        return result

    def _parse_sol_row(
        self, row: dict, get, idx: int, sig: str | None, date: str,
        wallet_id: str, wallet_address: str, from_addr: str, to_addr: str,
        tx_type_raw: str, chain: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse a SOL native transaction row."""
        sol_amount_raw = get(row, "sol amount", "amount")
        fee_sol_raw = get(row, "fee(sol)", "fee sol", "fee")

        amount = self._safe_float(sol_amount_raw)
        fee_sol = self._safe_float(fee_sol_raw)

        if amount is None:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable SOL amount: {sol_amount_raw}", "sig": sig}
            )
            return None

        amount = abs(amount)

        # Dust filter
        if amount < _MIN_SOL_VALUE and (fee_sol or 0) < _MIN_SOL_VALUE:
            result.skipped.append(
                {"row": idx, "reason": "Dust SOL tx (< 0.0001 SOL)", "sig": sig}
            )
            return None

        # Determine direction
        vaultd_type = _TYPE_MAP.get(tx_type_raw)
        if not vaultd_type:
            # Fallback: use wallet address direction detection
            if wallet_address:
                if to_addr == wallet_address:
                    vaultd_type = "transfer_in"
                elif from_addr == wallet_address:
                    vaultd_type = "transfer_out"
                else:
                    vaultd_type = "transfer_in"
                    result.warnings.append(
                        f"Row {idx}: unknown type '{tx_type_raw}', "
                        f"wallet address not matched → defaulted to 'transfer_in'"
                    )
            else:
                vaultd_type = "transfer_in"
                result.warnings.append(
                    f"Row {idx}: unknown Solscan type '{tx_type_raw}' → defaulted to 'transfer_in'"
                )

        tx_id = self._make_tx_id("solscan", sig, date, "SOL", idx)

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": "SOL",
            "chain": chain,
            "amount": round(amount, 9),
            "price_usd": None,  # Solscan doesn't provide historical price
            "fee_usd": None,    # Fee in SOL, not USD — user should update manually
            "wallet_id": wallet_id,
            "tx_hash": sig,
            "exchange": "solscan",
            "note": f"fee: {fee_sol} SOL" if fee_sol else "",
            "tags": ["imported", "solscan", "sol"],
        }

    def _parse_spl_row(
        self, row: dict, get, idx: int, sig: str | None, date: str,
        wallet_id: str, wallet_address: str, from_addr: str, to_addr: str,
        tx_type_raw: str, chain: str, result: ImportResult
    ) -> dict[str, Any] | None:
        """Parse an SPL token transfer row."""
        raw_symbol = get(row, "token symbol")
        if not raw_symbol or not raw_symbol.strip():
            result.warnings.append(
                f"Row {idx}: SPL token symbol is empty — "
                f"token address: {get(row, 'token address') or 'N/A'}. "
                f"Defaulting to 'UNKNOWN'. Run vaultd-price or update manually."
            )
            token_symbol = "UNKNOWN"
        else:
            token_symbol = raw_symbol.strip().upper()
        token_amount_raw = get(row, "token amount", "amount")

        amount = self._safe_float(token_amount_raw)
        if amount is None:
            result.skipped.append(
                {"row": idx, "reason": f"Unparseable token amount: {token_amount_raw}", "sig": sig}
            )
            return None

        amount = abs(amount)

        # Determine direction
        vaultd_type = _TYPE_MAP.get(tx_type_raw)
        if not vaultd_type:
            if wallet_address:
                if to_addr == wallet_address:
                    vaultd_type = "transfer_in"
                elif from_addr == wallet_address:
                    vaultd_type = "transfer_out"
                else:
                    vaultd_type = "transfer_in"
                    result.warnings.append(
                        f"Row {idx}: SPL unknown type '{tx_type_raw}' for {token_symbol} "
                        f"→ defaulted to 'transfer_in'"
                    )
            else:
                vaultd_type = "transfer_in"
                result.warnings.append(
                    f"Row {idx}: unknown Solscan SPL type '{tx_type_raw}' for {token_symbol} "
                    f"→ defaulted to 'transfer_in'"
                )

        tx_id = self._make_tx_id("solscan-spl", sig, date, token_symbol, idx)

        return {
            "id": tx_id,
            "date": date,
            "type": vaultd_type,
            "asset": token_symbol,
            "chain": chain,
            "amount": amount,
            "price_usd": None,
            "fee_usd": None,
            "wallet_id": wallet_id,
            "tx_hash": sig,
            "exchange": "solscan",
            "note": f"SPL: {get(row, 'token address') or ''}".strip(": "),
            "tags": ["imported", "solscan", "spl"],
        }
