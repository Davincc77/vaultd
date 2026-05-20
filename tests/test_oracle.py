"""
test_oracle.py — Tests for the price oracle (CoinGecko + cache + delta builder).

Network calls are mocked — these tests run offline.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from vaultd.oracle import (
    PriceCache,
    PriceResult,
    _ticker_to_cg_id,
    build_price_update_delta,
    fetch_prices,
)

# ─── PriceCache ──────────────────────────────────────────────────────────────


class TestPriceCache:
    def test_cache_miss_when_empty(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        prices, age = cache.get_prices(["BTC"])
        assert prices is None

    def test_cache_hit_within_ttl(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        cache.set_prices({"BTC": 65000.0, "ETH": 3500.0})
        prices, age = cache.get_prices(["BTC", "ETH"])
        assert prices is not None
        assert prices["BTC"] == 65000.0
        assert prices["ETH"] == 3500.0
        assert age < 5  # just set

    def test_cache_miss_when_expired(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        # Write cache with old timestamp
        data = {"timestamp": time.time() - 400, "prices": {"BTC": 65000.0}}
        (tmp_path / "cache.json").write_text(json.dumps(data))
        prices, age = cache.get_prices(["BTC"])
        assert prices is None
        assert age > 300

    def test_cache_miss_when_ticker_missing(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        cache.set_prices({"BTC": 65000.0})
        prices, age = cache.get_prices(["BTC", "ETH"])  # ETH not cached
        assert prices is None

    def test_cache_set_merges_with_existing(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        cache.set_prices({"BTC": 65000.0})
        cache.set_prices({"ETH": 3500.0})
        prices, _ = cache.get_prices(["BTC", "ETH"])
        assert prices is not None
        assert prices["BTC"] == 65000.0
        assert prices["ETH"] == 3500.0

    def test_corrupt_cache_file_handled(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not-valid-json")
        cache = PriceCache(cache_file)
        prices, _ = cache.get_prices(["BTC"])
        assert prices is None


# ─── Ticker mapping ──────────────────────────────────────────────────────────


def test_known_tickers_map():
    assert _ticker_to_cg_id("BTC") == "bitcoin"
    assert _ticker_to_cg_id("ETH") == "ethereum"
    assert _ticker_to_cg_id("SOL") == "solana"
    assert _ticker_to_cg_id("btc") == "bitcoin"  # case insensitive


def test_unknown_ticker_returns_none():
    assert _ticker_to_cg_id("FAKECOIN999") is None


# ─── fetch_prices (mocked network) ──────────────────────────────────────────


class TestFetchPrices:
    def _mock_cg_response(self, data: dict):
        """Create a mock urllib response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_fetch_known_tickers(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        cg_response = {
            "bitcoin": {"usd": 65000.0},
            "ethereum": {"usd": 3500.0},
        }
        with patch("urllib.request.urlopen", return_value=self._mock_cg_response(cg_response)):
            result = fetch_prices(["BTC", "ETH"], cache=cache)

        assert result.cached is False
        assert result.prices["BTC"] == 65000.0
        assert result.prices["ETH"] == 3500.0

    def test_unknown_ticker_returns_null(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        with patch("urllib.request.urlopen", return_value=self._mock_cg_response({})):
            result = fetch_prices(["FAKECOIN999"], cache=cache)

        assert result.prices.get("FAKECOIN999") is None
        assert "FAKECOIN999" in result.unknown_tickers

    def test_served_from_cache(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        cache.set_prices({"BTC": 64000.0})

        with patch("urllib.request.urlopen") as mock_url:
            result = fetch_prices(["BTC"], cache=cache)
            mock_url.assert_not_called()

        assert result.cached is True
        assert result.prices["BTC"] == 64000.0

    def test_force_refresh_bypasses_cache(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        cache.set_prices({"BTC": 64000.0})  # stale price in cache
        cg_response = {"bitcoin": {"usd": 66000.0}}

        with patch("urllib.request.urlopen", return_value=self._mock_cg_response(cg_response)):
            result = fetch_prices(["BTC"], force_refresh=True, cache=cache)

        assert result.cached is False
        assert result.prices["BTC"] == 66000.0

    def test_network_error_returns_null_prices(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = fetch_prices(["BTC"], cache=cache)

        assert result.prices.get("BTC") is None
        assert "error" in result.source

    def test_empty_tickers_returns_empty(self, tmp_path):
        cache = PriceCache(tmp_path / "cache.json")
        result = fetch_prices([], cache=cache)
        assert result.total == 0 if hasattr(result, "total") else result.prices == {}


# ─── build_price_update_delta ────────────────────────────────────────────────


class TestBuildDelta:
    def _holding(self, id_, asset, amount, avg_buy, current=None):
        return {
            "id": id_,
            "asset": asset,
            "amount": amount,
            "avg_buy_price_usd": avg_buy,
            "current_price_usd": current,
        }

    def test_basic_delta(self):
        holdings = [self._holding("h1", "BTC", 0.5, 30000.0, current=30000.0)]
        price_result = PriceResult(prices={"BTC": 65000.0})
        deltas = build_price_update_delta(holdings, price_result)
        assert len(deltas) == 1
        assert deltas[0]["holding_id"] == "h1"
        assert deltas[0]["new_value"] == 65000.0
        assert deltas[0]["old_value"] == 30000.0
        # PnL: (65000 - 30000) * 0.5 = 17500
        assert deltas[0]["pnl_impact_usd"] == 17500.0

    def test_no_delta_when_price_unchanged(self):
        holdings = [self._holding("h1", "BTC", 1.0, 30000.0, current=65000.0)]
        price_result = PriceResult(prices={"BTC": 65000.0})
        deltas = build_price_update_delta(holdings, price_result)
        assert len(deltas) == 0

    def test_no_delta_when_price_missing(self):
        holdings = [self._holding("h1", "BTC", 1.0, 30000.0)]
        price_result = PriceResult(prices={"ETH": 3500.0})  # no BTC
        deltas = build_price_update_delta(holdings, price_result)
        assert len(deltas) == 0

    def test_null_current_updated_to_new_price(self):
        holdings = [self._holding("h1", "ETH", 2.0, 1500.0, current=None)]
        price_result = PriceResult(prices={"ETH": 3500.0})
        deltas = build_price_update_delta(holdings, price_result)
        assert len(deltas) == 1
        assert deltas[0]["old_value"] is None

    def test_multiple_holdings(self):
        holdings = [
            self._holding("h1", "BTC", 0.1, 20000.0, current=None),
            self._holding("h2", "ETH", 1.0, 1000.0, current=None),
            self._holding("h3", "SOL", 10.0, 20.0, current=None),
        ]
        price_result = PriceResult(prices={"BTC": 65000.0, "ETH": 3500.0, "SOL": 145.0})
        deltas = build_price_update_delta(holdings, price_result)
        assert len(deltas) == 3
