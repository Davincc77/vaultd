"""
vaultd.importers — Exchange CSV import plugins for .vaultd files.

Supported sources:
  - Coinbase (coinbase)
  - Etherscan (etherscan)

Usage:
    from vaultd.importers import get_importer
    importer = get_importer("coinbase")
    transactions = importer.parse("export.csv", wallet_id="main")
"""

from vaultd.importers.base import BaseImporter, ImportResult
from vaultd.importers.coinbase import CoinbaseImporter
from vaultd.importers.etherscan import EtherscanImporter

IMPORTERS: dict[str, type[BaseImporter]] = {
    "coinbase": CoinbaseImporter,
    "etherscan": EtherscanImporter,
}


def get_importer(source: str) -> BaseImporter:
    """Return an importer instance for the given source name."""
    source = source.lower().strip()
    if source not in IMPORTERS:
        raise ValueError(
            f"Unknown importer '{source}'. Available: {list(IMPORTERS.keys())}"
        )
    return IMPORTERS[source]()


__all__ = [
    "BaseImporter",
    "ImportResult",
    "CoinbaseImporter",
    "EtherscanImporter",
    "get_importer",
    "IMPORTERS",
]
