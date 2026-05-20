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
