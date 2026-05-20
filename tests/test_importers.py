"""
test_importers.py — Tests for Coinbase + Etherscan importers and merge logic.
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from vaultd.importers import CoinbaseImporter, EtherscanImporter, get_importer
from vaultd.importers.merge import merge_transactions

# ─── Fixtures ────────────────────────────────────────────────────────────────


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


COINBASE_COLS = [
    "Timestamp",
    "Transaction Type",
    "Asset",
    "Quantity Transacted",
    "USD Spot Price at Transaction",
    "USD Subtotal",
    "USD Total (inclusive of fees and/or spread)",
    "USD Fees",
    "Notes",
]

ETHERSCAN_NORMAL_COLS = [
    "Txhash", "Blockno", "UnixTimestamp", "DateTime (UTC)",
    "From", "To", "ContractAddress",
    "Value_IN(ETH)", "Value_OUT(ETH)", "CurrentValue",
    "TxnFee(ETH)", "TxnFee(USD)", "Historical $Price/Eth",
    "Status", "ErrCode", "Method",
]

ETHERSCAN_ERC20_COLS = [
    "Txhash", "Blockno", "UnixTimestamp", "DateTime (UTC)",
    "From", "To", "TokenValue", "USDValueDayOf",
    "ContractAddress", "TokenName", "TokenSymbol",
]


# ─── Coinbase Tests ──────────────────────────────────────────────────────────


class TestCoinbaseImporter:
    def test_basic_buy(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "2024-01-15T10:00:00Z",
                "Transaction Type": "Buy",
                "Asset": "BTC",
                "Quantity Transacted": "0.5",
                "USD Spot Price at Transaction": "42000",
                "USD Subtotal": "21000",
                "USD Total (inclusive of fees and/or spread)": "21210",
                "USD Fees": "210",
                "Notes": "First BTC purchase",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f), wallet_id="coinbase-main")
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "buy"
        assert tx["asset"] == "BTC"
        assert tx["amount"] == 0.5
        assert tx["price_usd"] == 42000.0
        assert tx["fee_usd"] == 210.0
        assert tx["wallet_id"] == "coinbase-main"
        assert tx["exchange"] == "coinbase"
        assert "imported" in tx["tags"]
        assert "coinbase" in tx["tags"]

    def test_sell(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "2024-03-01T14:30:00Z",
                "Transaction Type": "Sell",
                "Asset": "ETH",
                "Quantity Transacted": "2.0",
                "USD Spot Price at Transaction": "3500",
                "USD Subtotal": "7000", "USD Total (inclusive of fees and/or spread)": "6930",
                "USD Fees": "70", "Notes": "",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f))
        assert result.transactions[0]["type"] == "sell"
        assert result.transactions[0]["amount"] == 2.0

    def test_rewards_map_to_airdrop(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "2024-02-01T00:00:00Z",
                "Transaction Type": "Rewards Income",
                "Asset": "USDC",
                "Quantity Transacted": "5.00",
                "USD Spot Price at Transaction": "1.00",
                "USD Subtotal": "5", "USD Total (inclusive of fees and/or spread)": "5",
                "USD Fees": "0", "Notes": "Staking reward",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f))
        assert result.transactions[0]["type"] == "airdrop"

    def test_missing_price_becomes_null(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "2024-04-01T08:00:00Z",
                "Transaction Type": "Receive",
                "Asset": "SOL",
                "Quantity Transacted": "10",
                "USD Spot Price at Transaction": "",
                "USD Subtotal": "", "USD Total (inclusive of fees and/or spread)": "",
                "USD Fees": "", "Notes": "",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f))
        assert result.transactions[0]["price_usd"] is None
        assert result.transactions[0]["fee_usd"] is None

    def test_bad_timestamp_is_skipped(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "not-a-date",
                "Transaction Type": "Buy", "Asset": "BTC",
                "Quantity Transacted": "0.1",
                "USD Spot Price at Transaction": "40000",
                "USD Subtotal": "4000", "USD Total (inclusive of fees and/or spread)": "4040",
                "USD Fees": "40", "Notes": "",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f))
        assert result.total == 0
        assert result.skipped_count == 1

    def test_multiasset_convert_skipped(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "2024-05-01T12:00:00Z",
                "Transaction Type": "Convert",
                "Asset": "BTC -> ETH",
                "Quantity Transacted": "0.1",
                "USD Spot Price at Transaction": "", "USD Subtotal": "",
                "USD Total (inclusive of fees and/or spread)": "",
                "USD Fees": "", "Notes": "",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f))
        assert result.total == 0
        assert result.skipped_count == 1

    def test_unknown_type_defaults_with_warning(self, tmp_path):
        f = tmp_path / "cb.csv"
        write_csv(f, [
            {
                "Timestamp": "2024-06-01T10:00:00Z",
                "Transaction Type": "Some Future Type",
                "Asset": "ETH", "Quantity Transacted": "1.0",
                "USD Spot Price at Transaction": "3000",
                "USD Subtotal": "3000", "USD Total (inclusive of fees and/or spread)": "3000",
                "USD Fees": "0", "Notes": "",
            }
        ], COINBASE_COLS)
        result = CoinbaseImporter().parse(str(f))
        assert result.total == 1
        assert result.transactions[0]["type"] == "transfer_in"
        assert any("unknown" in w.lower() for w in result.warnings)

    def test_ids_are_deterministic(self, tmp_path):
        """Same import run twice produces same IDs."""
        rows = [
            {
                "Timestamp": "2024-01-01T00:00:00Z",
                "Transaction Type": "Buy", "Asset": "BTC",
                "Quantity Transacted": "1.0",
                "USD Spot Price at Transaction": "30000",
                "USD Subtotal": "30000", "USD Total (inclusive of fees and/or spread)": "30300",
                "USD Fees": "300", "Notes": "",
            }
        ]
        f = tmp_path / "cb.csv"
        write_csv(f, rows, COINBASE_COLS)
        r1 = CoinbaseImporter().parse(str(f))
        r2 = CoinbaseImporter().parse(str(f))
        assert r1.transactions[0]["id"] == r2.transactions[0]["id"]


# ─── Etherscan Tests ─────────────────────────────────────────────────────────


MY_ADDR = "0xabc123def456abc123def456abc123def456abc1"


class TestEtherscanImporter:
    def test_eth_transfer_in(self, tmp_path):
        f = tmp_path / "eth.csv"
        write_csv(f, [
            {
                "Txhash": "0xdeadbeef", "Blockno": "19000000",
                "UnixTimestamp": "1700000000",
                "DateTime (UTC)": "2024-01-01 12:00:00 UTC",
                "From": "0xsender000", "To": MY_ADDR,
                "ContractAddress": "",
                "Value_IN(ETH)": "1.5", "Value_OUT(ETH)": "0",
                "CurrentValue": "3000",
                "TxnFee(ETH)": "0.001", "TxnFee(USD)": "2.50",
                "Historical $Price/Eth": "2000",
                "Status": "", "ErrCode": "", "Method": "Transfer",
            }
        ], ETHERSCAN_NORMAL_COLS)
        result = EtherscanImporter().parse(str(f), wallet_id="hw", wallet_address=MY_ADDR)
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["type"] == "transfer_in"
        assert tx["asset"] == "ETH"
        assert tx["amount"] == 1.5
        assert tx["tx_hash"] == "0xdeadbeef"
        assert tx["fee_usd"] == 2.50
        assert "etherscan" in tx["tags"]

    def test_eth_transfer_out(self, tmp_path):
        f = tmp_path / "eth.csv"
        write_csv(f, [
            {
                "Txhash": "0xaabbcc", "Blockno": "19000001",
                "UnixTimestamp": "1700001000",
                "DateTime (UTC)": "2024-01-02 08:00:00 UTC",
                "From": MY_ADDR, "To": "0xrecipient000",
                "ContractAddress": "",
                "Value_IN(ETH)": "0", "Value_OUT(ETH)": "0.5",
                "CurrentValue": "", "TxnFee(ETH)": "0.0005",
                "TxnFee(USD)": "1.00", "Historical $Price/Eth": "2000",
                "Status": "", "ErrCode": "", "Method": "Transfer",
            }
        ], ETHERSCAN_NORMAL_COLS)
        result = EtherscanImporter().parse(str(f), wallet_id="hw", wallet_address=MY_ADDR)
        assert result.transactions[0]["type"] == "transfer_out"

    def test_failed_tx_skipped(self, tmp_path):
        f = tmp_path / "eth.csv"
        write_csv(f, [
            {
                "Txhash": "0xfailed", "Blockno": "19000002",
                "UnixTimestamp": "1700002000",
                "DateTime (UTC)": "2024-01-03 10:00:00 UTC",
                "From": MY_ADDR, "To": "0xcontract",
                "ContractAddress": "0xcontract",
                "Value_IN(ETH)": "0", "Value_OUT(ETH)": "0",
                "CurrentValue": "", "TxnFee(ETH)": "0.002",
                "TxnFee(USD)": "4.00", "Historical $Price/Eth": "2000",
                "Status": "Error", "ErrCode": "Bad jump destination", "Method": "",
            }
        ], ETHERSCAN_NORMAL_COLS)
        result = EtherscanImporter().parse(str(f))
        assert result.total == 0
        assert result.skipped_count == 1

    def test_erc20_transfer_in(self, tmp_path):
        f = tmp_path / "erc20.csv"
        write_csv(f, [
            {
                "Txhash": "0xtokenTx", "Blockno": "19000010",
                "UnixTimestamp": "1700010000",
                "DateTime (UTC)": "2024-01-10 15:00:00 UTC",
                "From": "0xsender", "To": MY_ADDR,
                "TokenValue": "500.0", "USDValueDayOf": "500.00",
                "ContractAddress": "0xusdc", "TokenName": "USD Coin", "TokenSymbol": "USDC",
            }
        ], ETHERSCAN_ERC20_COLS)
        result = EtherscanImporter().parse(str(f), wallet_id="hw", wallet_address=MY_ADDR)
        assert result.total == 1
        tx = result.transactions[0]
        assert tx["asset"] == "USDC"
        assert tx["amount"] == 500.0
        assert tx["type"] == "transfer_in"
        assert "erc20" in tx["tags"]

    def test_dust_filter(self, tmp_path):
        f = tmp_path / "erc20.csv"
        write_csv(f, [
            {
                "Txhash": "0xdust", "Blockno": "1",
                "UnixTimestamp": "1700020000",
                "DateTime (UTC)": "2024-01-20 00:00:00 UTC",
                "From": "0xspammer", "To": MY_ADDR,
                "TokenValue": "0.000001", "USDValueDayOf": "0.000001",
                "ContractAddress": "0xspam", "TokenName": "Spam", "TokenSymbol": "SPAM",
            }
        ], ETHERSCAN_ERC20_COLS)
        result = EtherscanImporter().parse(str(f), wallet_address=MY_ADDR)
        assert result.total == 0
        assert result.skipped_count == 1


# ─── Merge Tests ─────────────────────────────────────────────────────────────


class TestMerge:
    def _tx(self, tx_hash=None, date="2024-01-01T00:00:00Z", asset="BTC",
            type_="buy", amount=1.0, id_="tx1"):
        return {
            "id": id_, "date": date, "type": type_,
            "asset": asset, "amount": amount,
            "tx_hash": tx_hash, "wallet_id": "w1", "exchange": "coinbase",
        }

    def test_no_duplicates(self):
        existing = [self._tx(id_="tx1", tx_hash="0xaaa")]
        incoming = [self._tx(id_="tx2", tx_hash="0xbbb")]
        merged, new, dupes = merge_transactions(existing, incoming)
        assert len(merged) == 2
        assert new == 1
        assert dupes == 0

    def test_dedup_by_tx_hash(self):
        tx = self._tx(tx_hash="0xabc", id_="tx1")
        duplicate = self._tx(tx_hash="0xabc", id_="tx99")  # different id, same hash
        merged, new, dupes = merge_transactions([tx], [duplicate])
        assert len(merged) == 1
        assert new == 0
        assert dupes == 1

    def test_dedup_by_composite_key(self):
        tx = self._tx(tx_hash=None, id_="tx1", date="2024-01-01T00:00:00Z", amount=0.5)
        duplicate = self._tx(tx_hash=None, id_="tx2", date="2024-01-01T00:00:00Z", amount=0.5)
        merged, new, dupes = merge_transactions([tx], [duplicate])
        assert dupes == 1

    def test_merged_sorted_by_date(self):
        tx1 = self._tx(id_="tx1", date="2024-03-01T00:00:00Z", tx_hash="0x1")
        tx2 = self._tx(id_="tx2", date="2024-01-01T00:00:00Z", tx_hash="0x2")
        merged, _, _ = merge_transactions([tx1], [tx2])
        assert merged[0]["date"] < merged[1]["date"]

    def test_empty_existing(self):
        incoming = [self._tx(id_="tx1", tx_hash="0xnew")]
        merged, new, dupes = merge_transactions([], incoming)
        assert new == 1
        assert len(merged) == 1

    def test_empty_incoming(self):
        existing = [self._tx(id_="tx1", tx_hash="0xexist")]
        merged, new, dupes = merge_transactions(existing, [])
        assert new == 0
        assert len(merged) == 1


# ─── get_importer ────────────────────────────────────────────────────────────


def test_get_importer_coinbase():
    assert isinstance(get_importer("coinbase"), CoinbaseImporter)


def test_get_importer_etherscan():
    assert isinstance(get_importer("etherscan"), EtherscanImporter)


def test_get_importer_unknown():
    with pytest.raises(ValueError, match="Unknown importer"):
        get_importer("not_a_real_exchange")
