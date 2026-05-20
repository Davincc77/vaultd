"""
vaultd.oracle — CoinGecko price oracle with local file cache.

Design principles (per SKILL.md hard rules):
- Never silently update current_price_usd in the vault
- User must explicitly confirm before any price is written back
- Cache prices locally to avoid hammering the API
- current_price_usd: null is always safe — never invent a price

Usage:
    from vaultd.oracle import fetch_prices, PriceResult

    result = fetch_prices(["BTC", "ETH", "SOL"])
    print(result.prices)  # {"BTC": 67000.0, "ETH": 3500.0, "SOL": 145.0}
    print(result.cached)  # True if served from cache
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# CoinGecko free API — no key required, rate limit: 10-30 req/min
_COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Cache file location — platform-appropriate temp directory
_CACHE_FILE = Path.home() / ".vaultd_price_cache.json"

# Cache TTL in seconds (5 minutes)
_CACHE_TTL = 300

# CoinGecko ID mappings for common tickers
# Full list: https://api.coingecko.com/api/v3/coins/list
_TICKER_TO_CG_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ALGO": "algorand",
    "XLM": "stellar",
    "VET": "vechain",
    "FIL": "filecoin",
    "THETA": "theta-token",
    "ETC": "ethereum-classic",
    "XMR": "monero",
    "AAVE": "aave",
    "COMP": "compound-governance-token",
    "MKR": "maker",
    "SNX": "havven",
    "CRV": "curve-dao-token",
    "SUSHI": "sushi",
    "1INCH": "1inch",
    "GRT": "the-graph",
    "ENS": "ethereum-name-service",
    "OP": "optimism",
    "ARB": "arbitrum",
    "INJ": "injective-protocol",
    "SUI": "sui",
    "APT": "aptos",
    "SEI": "sei-network",
    "TIA": "celestia",
    "NEAR": "near",
    "FTM": "fantom",
    "HBAR": "hedera-hashgraph",
    "ICP": "internet-computer",
    "RENDER": "render-token",
    "FET": "fetch-ai",
    "AGIX": "singularitynet",
    "OCEAN": "ocean-protocol",
    "WLD": "worldcoin-wld",
    "PYTH": "pyth-network",
    "JUP": "jupiter-exchange-solana",
    "BONK": "bonk",
    "WIF": "dogwifcoin",
    "PEPE": "pepe",
    "FLOKI": "floki",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "DAI": "dai",
    "BUSD": "binance-usd",
    "FRAX": "frax",
    "TUSD": "true-usd",
    "WBTC": "wrapped-bitcoin",
    "WETH": "weth",
    "STETH": "staked-ether",
    "RETH": "rocket-pool-eth",
    "CBETH": "coinbase-wrapped-staked-eth",
}


@dataclass
class PriceResult:
    """Result of a price fetch operation."""

    prices: dict[str, float | None] = field(default_factory=dict)
    unknown_tickers: list[str] = field(default_factory=list)
    cached: bool = False
    cache_age_seconds: float | None = None
    source: str = "coingecko"
    fetched_at: str = ""

    def get(self, ticker: str) -> float | None:
        return self.prices.get(ticker.upper())


class PriceCache:
    """Simple JSON file-based price cache."""

    def __init__(self, cache_file: Path = _CACHE_FILE):
        self.cache_file = cache_file

    def load(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, data: dict[str, Any]) -> None:
        try:
            self.cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # Cache write failure is non-fatal

    def get_prices(self, tickers: list[str]) -> tuple[dict[str, float | None] | None, float | None]:
        """
        Return (prices_dict, cache_age_seconds) if cache is fresh, else (None, None).
        """
        cache = self.load()
        if not cache:
            return None, None

        timestamp = cache.get("timestamp", 0)
        age = time.time() - timestamp
        if age > _CACHE_TTL:
            return None, age

        cached_prices = cache.get("prices", {})
        # Only return from cache if ALL requested tickers are present
        result = {}
        for ticker in tickers:
            upper = ticker.upper()
            if upper not in cached_prices:
                return None, age
            result[upper] = cached_prices[upper]

        return result, age

    def set_prices(self, prices: dict[str, float | None]) -> None:
        cache = self.load()
        existing = cache.get("prices", {})
        existing.update({k.upper(): v for k, v in prices.items()})
        self.save({"timestamp": time.time(), "prices": existing})


def _ticker_to_cg_id(ticker: str) -> str | None:
    """Map a ticker symbol to a CoinGecko ID."""
    return _TICKER_TO_CG_ID.get(ticker.upper())


def fetch_prices(
    tickers: list[str],
    force_refresh: bool = False,
    cache: PriceCache | None = None,
) -> PriceResult:
    """
    Fetch current USD prices for a list of ticker symbols.

    Uses CoinGecko free API (no key required).
    Results are cached for 5 minutes to avoid rate limiting.

    Args:
        tickers: List of ticker symbols (e.g. ["BTC", "ETH", "SOL"]).
        force_refresh: Bypass cache and fetch live.
        cache: Optional PriceCache instance (for testing).

    Returns:
        PriceResult with prices dict, unknown tickers, and cache metadata.

    IMPORTANT: This function only fetches prices — it never modifies the vault.
    The caller must always present prices to the user for confirmation before
    writing current_price_usd to any holding.
    """
    import urllib.request
    from datetime import datetime, timezone

    tickers = [t.upper() for t in tickers if t.strip()]
    if not tickers:
        return PriceResult()

    _cache = cache or PriceCache()

    # Check cache first
    if not force_refresh:
        cached_prices, cache_age = _cache.get_prices(tickers)
        if cached_prices is not None:
            return PriceResult(
                prices=cached_prices,
                cached=True,
                cache_age_seconds=cache_age,
                fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

    # Map tickers to CoinGecko IDs
    cg_id_to_ticker: dict[str, str] = {}
    unknown: list[str] = []

    for ticker in tickers:
        cg_id = _ticker_to_cg_id(ticker)
        if cg_id:
            cg_id_to_ticker[cg_id] = ticker
        else:
            unknown.append(ticker)

    prices: dict[str, float | None] = {t: None for t in tickers}

    if cg_id_to_ticker:
        ids_param = ",".join(cg_id_to_ticker.keys())
        url = f"{_COINGECKO_BASE}/simple/price?ids={ids_param}&vs_currencies=usd"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vaultd/2.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for cg_id, ticker in cg_id_to_ticker.items():
                price = data.get(cg_id, {}).get("usd")
                prices[ticker] = float(price) if price is not None else None

        except Exception as e:
            # Network failure — return None prices with warning
            return PriceResult(
                prices={t: None for t in tickers},
                unknown_tickers=unknown,
                cached=False,
                source=f"coingecko (error: {e})",
                fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

    # Cache results
    _cache.set_prices(prices)

    return PriceResult(
        prices=prices,
        unknown_tickers=unknown,
        cached=False,
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def build_price_update_delta(
    holdings: list[dict],
    price_result: PriceResult,
) -> list[dict]:
    """
    Build a list of proposed JSON deltas for current_price_usd updates.

    Returns a list of dicts describing what would change — never applies them.
    The caller must present these to the user for confirmation.
    """
    deltas = []
    for h in holdings:
        ticker = h.get("asset", "").upper()
        new_price = price_result.get(ticker)
        if new_price is None:
            continue
        old_price = h.get("current_price_usd")
        if old_price == new_price:
            continue
        deltas.append({
            "holding_id": h.get("id"),
            "asset": ticker,
            "field": "current_price_usd",
            "old_value": old_price,
            "new_value": new_price,
            "pnl_impact_usd": round(
                (new_price - h.get("avg_buy_price_usd", 0)) * h.get("amount", 0), 2
            ) if h.get("avg_buy_price_usd") else None,
        })
    return deltas
