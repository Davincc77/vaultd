"""
test_importers_v25.py — Tests for Solscan, Binance, and Kraken importers (v2.5).
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from vaultd.importers import (
    BinanceImporter,
    KrakenImporter,
    SolscanImporter,
    get_importer,
)
from vaultd.importers.merge import merge_transactions

# ─── Helpers ──────────────────────────────────────────────────────────────────


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ─── Solscan Tests ────────────────────────────────────────────────────────────

SOLSCAN_SOL_COLS = [
    "Signature", "Block", "Time", "From", "To",
    "SOL Amount", "Fee(SOL)", "Status", "Type",
]

SOLSCAN_SPL_COLS = [
    "Signature", "Block", "Time", "From", "To",
    "Token Address", "Token Symbol", "Token Amount", "Type",
]


class TestSolscanImporter:
    def test_basic_sol_transfer_in(self, tmp_path):
        f = tmp_path / "sol.csv"
        write_csv(f, [
            {
                "Signature": "abc123",
                "Block": "300000000",
                "Time": "2024-06-01 12:00:00",
                "From": "SenderAddr111",
                "To": "MyWalletAddr",
                "SOL Amount": "2.5",
                "Fee(SOL)": "0.000005",
                "Status": "Success",
                "Type": "SOL Transfer",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f), wallet_id="sol-main", wallet_address="MyWalletAddr")
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "transfer_in"
        assert tx["asset"] == "SOL"
        assert tx["amount"] == pytest.approx(2.5)
        assert tx["wallet_id"] == "sol-main"
        assert tx["tx_hash"] == "abc123"
        assert tx["chain"] == "solana"
        assert "imported" in tx["tags"]

    def test_sol_transfer_out_via_address(self, tmp_path):
        f = tmp_path / "sol.csv"
        write_csv(f, [
            {
                "Signature": "xyz789",
                "Block": "300000001",
                "Time": "2024-06-02 10:00:00",
                "From": "MyWalletAddr",
                "To": "Recipient111",
                "SOL Amount": "0.5",
                "Fee(SOL)": "0.000005",
                "Status": "Success",
                "Type": "transfer out",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f), wallet_address="MyWalletAddr")
        assert result.total == 1
        assert result.transactions[0]["type"] == "transfer_out"

    def test_failed_tx_skipped(self, tmp_path):
        f = tmp_path / "sol.csv"
        write_csv(f, [
            {
                "Signature": "fail001",
                "Block": "300000002",
                "Time": "2024-06-03 09:00:00",
                "From": "Sender",
                "To": "Receiver",
                "SOL Amount": "1.0",
                "Fee(SOL)": "0.000005",
                "Status": "Fail",
                "Type": "transfer",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f))
        assert result.total == 0
        assert result.skipped_count == 1

    def test_spl_token_transfer(self, tmp_path):
        f = tmp_path / "spl.csv"
        write_csv(f, [
            {
                "Signature": "spl001",
                "Block": "300000010",
                "Time": "2024-07-01 14:00:00",
                "From": "SenderAddr",
                "To": "MyWalletAddr",
                "Token Address": "EPjFW...",
                "Token Symbol": "USDC",
                "Token Amount": "500.00",
                "Type": "SPL Transfer In",
            }
        ], SOLSCAN_SPL_COLS)
        result = SolscanImporter().parse(str(f), wallet_address="MyWalletAddr")
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["asset"] == "USDC"
        assert tx["amount"] == pytest.approx(500.0)
        assert tx["type"] == "transfer_in"

    def test_swap_type_mapping(self, tmp_path):
        f = tmp_path / "swap.csv"
        write_csv(f, [
            {
                "Signature": "swp001",
                "Block": "300000020",
                "Time": "2024-08-01 10:00:00",
                "From": "JupRouter",
                "To": "MyWalletAddr",
                "SOL Amount": "10.0",
                "Fee(SOL)": "0.001",
                "Status": "Success",
                "Type": "Jupiter Swap",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "swap"

    def test_custom_chain(self, tmp_path):
        f = tmp_path / "sol.csv"
        write_csv(f, [
            {
                "Signature": "abc999",
                "Block": "1",
                "Time": "2024-01-01 00:00:00",
                "From": "A",
                "To": "B",
                "SOL Amount": "1.0",
                "Fee(SOL)": "0.000005",
                "Status": "Success",
                "Type": "transfer",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f), chain="solana_mainnet")
        assert result.transactions[0]["chain"] == "solana_mainnet"

    def test_get_importer_solscan(self):
        imp = get_importer("solscan")
        assert isinstance(imp, SolscanImporter)


# ─── Binance Tests ────────────────────────────────────────────────────────────

BINANCE_TRADE_COLS = [
    "Date(UTC)", "Pair", "Side", "Price", "Executed", "Amount", "Fee",
]

BINANCE_TXN_COLS = [
    "UTC_Time", "Account", "Operation", "Coin", "Change", "Remark",
]

BINANCE_DEPOSIT_COLS = [
    "Date(UTC)", "Coin", "Amount", "TransactionFee", "Address", "TXID",
    "SourceAddress", "PaymentID", "Status",
]


class TestBinanceImporter:
    def test_basic_buy_trade(self, tmp_path):
        f = tmp_path / "trades.csv"
        write_csv(f, [
            {
                "Date(UTC)": "2024-03-15 10:30:00",
                "Pair": "ETHUSDT",
                "Side": "BUY",
                "Price": "3500.00",
                "Executed": "0.5 ETH",
                "Amount": "1750.00 USDT",
                "Fee": "0.00050 ETH",
            }
        ], BINANCE_TRADE_COLS)
        result = BinanceImporter().parse(str(f), wallet_id="binance-main")
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "buy"
        assert tx["asset"] == "ETH"
        assert tx["amount"] == pytest.approx(0.5)
        assert tx["price_usd"] == pytest.approx(3500.0)
        assert tx["wallet_id"] == "binance-main"

    def test_sell_trade(self, tmp_path):
        f = tmp_path / "trades.csv"
        write_csv(f, [
            {
                "Date(UTC)": "2024-03-20 14:00:00",
                "Pair": "BTCUSDT",
                "Side": "SELL",
                "Price": "65000.00",
                "Executed": "0.01 BTC",
                "Amount": "650.00 USDT",
                "Fee": "0.65 USDT",
            }
        ], BINANCE_TRADE_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "sell"
        assert result.transactions[0]["asset"] == "BTC"

    def test_transaction_history_deposit(self, tmp_path):
        f = tmp_path / "txns.csv"
        write_csv(f, [
            {
                "UTC_Time": "2024-04-01 08:00:00",
                "Account": "Spot",
                "Operation": "Deposit",
                "Coin": "USDT",
                "Change": "1000.0",
                "Remark": "",
            }
        ], BINANCE_TXN_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "transfer_in"
        assert tx["asset"] == "USDT"
        assert tx["amount"] == pytest.approx(1000.0)

    def test_transaction_history_staking_reward(self, tmp_path):
        f = tmp_path / "txns.csv"
        write_csv(f, [
            {
                "UTC_Time": "2024-05-01 00:00:00",
                "Account": "Spot",
                "Operation": "Staking Rewards",
                "Coin": "ETH",
                "Change": "0.001",
                "Remark": "",
            }
        ], BINANCE_TXN_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "claim_rewards"

    def test_transaction_history_negative_change_overrides_type(self, tmp_path):
        """A withdrawal (negative change) should be transfer_out even if operation says deposit."""
        f = tmp_path / "txns.csv"
        write_csv(f, [
            {
                "UTC_Time": "2024-05-10 10:00:00",
                "Account": "Spot",
                "Operation": "Withdrawal",
                "Coin": "BTC",
                "Change": "-0.05",
                "Remark": "",
            }
        ], BINANCE_TXN_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "transfer_out"
        assert result.transactions[0]["amount"] == pytest.approx(0.05)

    def test_deposit_history(self, tmp_path):
        f = tmp_path / "dep.csv"
        write_csv(f, [
            {
                "Date(UTC)": "2024-06-01 09:00:00",
                "Coin": "ETH",
                "Amount": "1.2",
                "TransactionFee": "0",
                "Address": "",
                "TXID": "0xdeadbeef",
                "SourceAddress": "0xsource",
                "PaymentID": "",
                "Status": "Completed",
            }
        ], BINANCE_DEPOSIT_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "transfer_in"
        assert tx["asset"] == "ETH"
        assert tx["tx_hash"] == "0xdeadbeef"

    def test_failed_deposit_skipped(self, tmp_path):
        f = tmp_path / "dep.csv"
        write_csv(f, [
            {
                "Date(UTC)": "2024-06-02 10:00:00",
                "Coin": "BTC",
                "Amount": "0.1",
                "TransactionFee": "0",
                "Address": "0xdest",
                "TXID": "0xfailed",
                "SourceAddress": "",
                "PaymentID": "",
                "Status": "Failed",
            }
        ], BINANCE_DEPOSIT_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 0
        assert result.skipped_count == 1

    def test_get_importer_binance(self):
        imp = get_importer("binance")
        assert isinstance(imp, BinanceImporter)


# ─── Kraken Tests ─────────────────────────────────────────────────────────────

KRAKEN_LEDGER_COLS = [
    "txid", "refid", "time", "type", "subtype", "aclass", "asset",
    "amount", "fee", "balance",
]

KRAKEN_TRADE_COLS = [
    "txid", "ordertxid", "pair", "time", "type", "ordertype",
    "price", "cost", "fee", "vol", "margin", "misc", "ledgers", "postxid",
]


class TestKrakenImporter:
    def test_basic_buy_ledger(self, tmp_path):
        f = tmp_path / "ledger.csv"
        write_csv(f, [
            {
                "txid": "LAAAA1",
                "refid": "OBBBB1",
                "time": "2024-01-10 11:00:00",
                "type": "trade",
                "subtype": "",
                "aclass": "currency",
                "asset": "XETH",
                "amount": "0.75",
                "fee": "0.001",
                "balance": "0.75",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f), wallet_id="kraken-main")
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["asset"] == "ETH"
        assert tx["amount"] == pytest.approx(0.75)
        assert tx["wallet_id"] == "kraken-main"
        assert tx["type"] == "buy"

    def test_negative_amount_becomes_sell(self, tmp_path):
        f = tmp_path / "ledger.csv"
        write_csv(f, [
            {
                "txid": "LSELL1",
                "refid": "OSELL1",
                "time": "2024-02-01 12:00:00",
                "type": "trade",
                "subtype": "",
                "aclass": "currency",
                "asset": "XXBT",
                "amount": "-0.01",
                "fee": "0.0001",
                "balance": "0.1",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "sell"
        assert result.transactions[0]["asset"] == "BTC"
        assert result.transactions[0]["amount"] == pytest.approx(0.01)

    def test_staking_reward(self, tmp_path):
        f = tmp_path / "ledger.csv"
        write_csv(f, [
            {
                "txid": "LSTAKE1",
                "refid": "RSTAKE1",
                "time": "2024-03-01 00:00:00",
                "type": "staking",
                "subtype": "",
                "aclass": "currency",
                "asset": "ETH2",
                "amount": "0.0003",
                "fee": "0",
                "balance": "2.003",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "claim_rewards"

    def test_staking_subtype(self, tmp_path):
        f = tmp_path / "ledger.csv"
        write_csv(f, [
            {
                "txid": "LSTAKE2",
                "refid": "RSTAKE2",
                "time": "2024-03-15 08:00:00",
                "type": "transfer",
                "subtype": "spottostaking",
                "aclass": "currency",
                "asset": "DOT",
                "amount": "-50.0",
                "fee": "0",
                "balance": "50.0",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "stake"

    def test_fiat_entry_skipped(self, tmp_path):
        f = tmp_path / "ledger.csv"
        write_csv(f, [
            {
                "txid": "LFIAT1",
                "refid": "RFIAT1",
                "time": "2024-04-01 10:00:00",
                "type": "deposit",
                "subtype": "",
                "aclass": "currency",
                "asset": "ZEUR",
                "amount": "500.00",
                "fee": "0",
                "balance": "500.00",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 0
        assert result.skipped_count == 1

    def test_trade_export_buy(self, tmp_path):
        f = tmp_path / "trades.csv"
        write_csv(f, [
            {
                "txid": "TRADE001",
                "ordertxid": "ORDER001",
                "pair": "SOLUSD",
                "time": "2024-05-01 09:00:00",
                "type": "buy",
                "ordertype": "limit",
                "price": "150.00",
                "cost": "300.00",
                "fee": "0.48",
                "vol": "2.0",
                "margin": "0",
                "misc": "",
                "ledgers": "L1,L2",
                "postxid": "",
            }
        ], KRAKEN_TRADE_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "buy"
        assert tx["asset"] == "SOL"
        assert tx["amount"] == pytest.approx(2.0)
        assert tx["price_usd"] == pytest.approx(150.0)
        assert tx["fee_usd"] == pytest.approx(0.48)

    def test_trade_export_sell(self, tmp_path):
        f = tmp_path / "trades.csv"
        write_csv(f, [
            {
                "txid": "TRADE002",
                "ordertxid": "ORDER002",
                "pair": "XXBTZEUR",
                "time": "2024-06-01 15:00:00",
                "type": "sell",
                "ordertype": "market",
                "price": "58000.00",
                "cost": "580.00",
                "fee": "1.50",
                "vol": "0.01",
                "margin": "0",
                "misc": "",
                "ledgers": "L3,L4",
                "postxid": "",
            }
        ], KRAKEN_TRADE_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "sell"
        assert tx["asset"] == "BTC"
        assert tx["amount"] == pytest.approx(0.01)

    def test_asset_normalization(self):
        imp = KrakenImporter()
        assert imp._normalize_asset("XXBT") == "BTC"
        assert imp._normalize_asset("XETH") == "ETH"
        assert imp._normalize_asset("ZEUR") == "EUR"
        assert imp._normalize_asset("SOL") == "SOL"

    def test_get_importer_kraken(self):
        imp = get_importer("kraken")
        assert isinstance(imp, KrakenImporter)


# ─── Cross-source dedup (v2.5 importers + merge) ─────────────────────────────


class TestV25Deduplication:
    def test_solscan_dedup_by_signature(self, tmp_path):
        """Two Solscan CSVs with the same signature should deduplicate."""
        cols = SOLSCAN_SOL_COLS
        row = {
            "Signature": "dup_sig_001",
            "Block": "1",
            "Time": "2024-01-01 00:00:00",
            "From": "A",
            "To": "B",
            "SOL Amount": "1.0",
            "Fee(SOL)": "0.000005",
            "Status": "Success",
            "Type": "transfer",
        }
        f1 = tmp_path / "s1.csv"
        f2 = tmp_path / "s2.csv"
        write_csv(f1, [row], cols)
        write_csv(f2, [row], cols)

        imp = SolscanImporter()
        r1 = imp.parse(str(f1))
        r2 = imp.parse(str(f2))

        merged, new_count, dup_count = merge_transactions(r1.transactions, r2.transactions)
        assert new_count == 0
        assert dup_count == 1
        assert len(merged) == 1

    def test_binance_dedup_by_composite_key(self, tmp_path):
        """Binance has no tx_hash — dedup should work via composite key."""
        row = {
            "UTC_Time": "2024-02-01 10:00:00",
            "Account": "Spot",
            "Operation": "Buy",
            "Coin": "BTC",
            "Change": "0.001",
            "Remark": "",
        }
        f = tmp_path / "b.csv"
        write_csv(f, [row], BINANCE_TXN_COLS)
        imp = BinanceImporter()
        r1 = imp.parse(str(f))
        r2 = imp.parse(str(f))
        merged, new_count, dup_count = merge_transactions(r1.transactions, r2.transactions)
        assert dup_count == 1
        assert len(merged) == 1

    def test_cross_source_no_dedup(self, tmp_path):
        """Same date/amount/asset but different sources should NOT deduplicate."""
        sol_row = {
            "Signature": "unique_sol_001",
            "Block": "1",
            "Time": "2024-03-01 10:00:00",
            "From": "A",
            "To": "B",
            "SOL Amount": "1.0",
            "Fee(SOL)": "0.000005",
            "Status": "Success",
            "Type": "transfer in",
        }
        binance_row = {
            "UTC_Time": "2024-03-01 10:00:00",
            "Account": "Spot",
            "Operation": "Deposit",
            "Coin": "SOL",
            "Change": "1.0",
            "Remark": "",
        }
        fsol = tmp_path / "sol.csv"
        fbin = tmp_path / "bin.csv"
        write_csv(fsol, [sol_row], SOLSCAN_SOL_COLS)
        write_csv(fbin, [binance_row], BINANCE_TXN_COLS)

        r_sol = SolscanImporter().parse(str(fsol))
        r_bin = BinanceImporter().parse(str(fbin))

        # Solscan tx has a hash → won't match Binance (no hash, composite key)
        merged, new_count, dup_count = merge_transactions(r_sol.transactions, r_bin.transactions)
        assert len(merged) == 2
        assert dup_count == 0


# ─── v2.5.1 Edge-Case Tests ───────────────────────────────────────────────────


class TestV251EdgeCases:
    """Edge cases surfaced by Grok v2.5.0 audit."""

    # ── Binance: scientific notation amount ───────────────────────────────────

    def test_binance_scientific_notation_change(self, tmp_path):
        """Binance sometimes exports tiny amounts in scientific notation (e.g. 1e-08)."""
        f = tmp_path / "sci.csv"
        write_csv(f, [
            {
                "UTC_Time": "2024-07-01 00:00:00",
                "Account": "Spot",
                "Operation": "Commission",
                "Coin": "BNB",
                "Change": "1e-08",
                "Remark": "",
            }
        ], BINANCE_TXN_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["asset"] == "BNB"
        assert tx["amount"] == pytest.approx(1e-8)
        assert tx["type"] == "airdrop"

    def test_binance_scientific_notation_large_exponent(self, tmp_path):
        """Positive exponent: 1.5e+04 = 15000."""
        f = tmp_path / "sci2.csv"
        write_csv(f, [
            {
                "UTC_Time": "2024-08-01 12:00:00",
                "Account": "Spot",
                "Operation": "Deposit",
                "Coin": "USDT",
                "Change": "1.5e+04",
                "Remark": "",
            }
        ], BINANCE_TXN_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["amount"] == pytest.approx(15000.0)

    def test_binance_ambiguous_deposit_warning(self, tmp_path):
        """No source or destination address → warning emitted."""
        f = tmp_path / "amb.csv"
        write_csv(f, [
            {
                "Date(UTC)": "2024-09-01 10:00:00",
                "Coin": "BTC",
                "Amount": "0.01",
                "TransactionFee": "0",
                "Address": "",
                "TXID": "0xambiguous",
                "SourceAddress": "",
                "PaymentID": "",
                "Status": "Completed",
            }
        ], BINANCE_DEPOSIT_COLS)
        result = BinanceImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "transfer_in"
        # Warning should be present
        assert any("ambiguous" in w.lower() for w in result.warnings)

    # ── Kraken: exotic pair / new token that isn't in _ASSET_ALIASES ──────────

    def test_kraken_unknown_token_ledger(self, tmp_path):
        """A brand-new Kraken token not in the alias map should pass through as-is."""
        f = tmp_path / "new_token.csv"
        write_csv(f, [
            {
                "txid": "LNEW001",
                "refid": "RNEW001",
                "time": "2025-01-01 00:00:00",
                "type": "deposit",
                "subtype": "",
                "aclass": "currency",
                "asset": "NEWTOKEN",
                "amount": "100.0",
                "fee": "0",
                "balance": "100.0",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["asset"] == "NEWTOKEN"
        assert tx["type"] == "transfer_in"

    def test_kraken_unknown_token_asset_uppercase(self, tmp_path):
        """Assets returned from importer must always be uppercase."""
        f = tmp_path / "lower.csv"
        write_csv(f, [
            {
                "txid": "LLOWER1",
                "refid": "RLOWER1",
                "time": "2025-02-01 00:00:00",
                "type": "staking",
                "subtype": "",
                "aclass": "currency",
                "asset": "eth2",   # lowercase input
                "amount": "0.001",
                "fee": "0",
                "balance": "0.001",
            }
        ], KRAKEN_LEDGER_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["asset"] == "ETH2"  # must be uppercased

    def test_kraken_exotic_pair_trade(self, tmp_path):
        """An exotic pair not in the standard list should still import gracefully."""
        f = tmp_path / "exotic.csv"
        write_csv(f, [
            {
                "txid": "TEXOTIC1",
                "ordertxid": "OEXOTIC1",
                "pair": "NEWCOINUSDT",
                "time": "2025-03-01 12:00:00",
                "type": "buy",
                "ordertype": "market",
                "price": "0.5",
                "cost": "50.0",
                "fee": "0.1",
                "vol": "100.0",
                "margin": "0",
                "misc": "",
                "ledgers": "",
                "postxid": "",
            }
        ], KRAKEN_TRADE_COLS)
        result = KrakenImporter().parse(str(f))
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "buy"
        assert tx["amount"] == pytest.approx(100.0)
        # Asset should be some substring of NEWCOINUSDT, uppercased
        assert tx["asset"] == tx["asset"].upper()

    # ── Solscan: SPL zero amount ───────────────────────────────────────────────

    def test_solscan_spl_zero_amount_skipped(self, tmp_path):
        """SPL transfer with amount=0 should be skipped (unparseable → None after abs)."""
        f = tmp_path / "zero.csv"
        write_csv(f, [
            {
                "Signature": "zero001",
                "Block": "400000000",
                "Time": "2024-10-01 08:00:00",
                "From": "SenderZero",
                "To": "MyWallet",
                "Token Address": "EPjFW...",
                "Token Symbol": "USDC",
                "Token Amount": "0",
                "Type": "SPL Transfer In",
            }
        ], SOLSCAN_SPL_COLS)
        result = SolscanImporter().parse(str(f))
        # 0 is a valid float so amount=0 → abs(0)=0 — it is kept (not skipped)
        # The spec does not define a min-value filter for SPL, only SOL has dust filter
        assert result.total == 1
        assert result.transactions[0]["amount"] == pytest.approx(0.0)

    def test_solscan_spl_empty_symbol_warns(self, tmp_path):
        """SPL row with blank token symbol should warn and default to UNKNOWN."""
        f = tmp_path / "nosym.csv"
        write_csv(f, [
            {
                "Signature": "nosym001",
                "Block": "400000001",
                "Time": "2024-10-02 09:00:00",
                "From": "SenderA",
                "To": "MyWallet",
                "Token Address": "SomeTokenAddr123",
                "Token Symbol": "",
                "Token Amount": "10.0",
                "Type": "SPL Transfer In",
            }
        ], SOLSCAN_SPL_COLS)
        result = SolscanImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["asset"] == "UNKNOWN"
        assert any("symbol is empty" in w.lower() for w in result.warnings)

    # ── base.py: new date format parsing ──────────────────────────────────────

    def test_base_date_iso8601_with_milliseconds_Z(self, tmp_path):
        """ISO 8601 with milliseconds + Z suffix: 2024-06-01T12:00:00.000Z"""
        f = tmp_path / "msz.csv"
        write_csv(f, [
            {
                "Signature": "msz001",
                "Block": "1",
                "Time": "2024-06-01T12:00:00.000Z",
                "From": "A",
                "To": "B",
                "SOL Amount": "1.0",
                "Fee(SOL)": "0.000005",
                "Status": "Success",
                "Type": "transfer",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["date"] == "2024-06-01T12:00:00Z"

    def test_base_date_iso8601_with_microseconds(self, tmp_path):
        """ISO 8601 without Z but with microseconds: 2024-06-01T12:00:00.123456"""
        f = tmp_path / "us.csv"
        write_csv(f, [
            {
                "Signature": "us001",
                "Block": "2",
                "Time": "2024-07-15T08:30:00.123456",
                "From": "C",
                "To": "D",
                "SOL Amount": "2.0",
                "Fee(SOL)": "0.000005",
                "Status": "Success",
                "Type": "transfer",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["date"] == "2024-07-15T08:30:00Z"

    def test_base_date_mm_dd_yyyy_hhmm(self, tmp_path):
        """MM/DD/YYYY HH:MM format used by some CEX exports."""
        f = tmp_path / "mmdd.csv"
        write_csv(f, [
            {
                "Signature": "mmdd001",
                "Block": "3",
                "Time": "06/01/2024 12:00",
                "From": "E",
                "To": "F",
                "SOL Amount": "3.0",
                "Fee(SOL)": "0.000005",
                "Status": "Success",
                "Type": "transfer",
            }
        ], SOLSCAN_SOL_COLS)
        result = SolscanImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["date"] == "2024-06-01T12:00:00Z"
