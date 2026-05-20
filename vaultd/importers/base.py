"""
vaultd.importers.base — Abstract base class for exchange importers.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportResult:
    """Result of a CSV import operation."""

    transactions: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)   # rows that couldn't be mapped
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.transactions)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


class BaseImporter(ABC):
    """Abstract base for all exchange importers."""

    source_name: str = "unknown"

    @abstractmethod
    def parse(self, csv_path: str, wallet_id: str = "default") -> ImportResult:
        """
        Parse a CSV export file and return an ImportResult.

        Args:
            csv_path: Path to the CSV export file.
            wallet_id: The wallet_id to assign to imported transactions.

        Returns:
            ImportResult with transactions, skipped rows, and warnings.
        """

    def _make_tx_id(self, source: str, tx_hash: str | None, date: str, asset: str, idx: int) -> str:
        """Generate a deterministic transaction ID."""
        if tx_hash and tx_hash.strip():
            raw = f"{source}-{tx_hash.strip()}"
        else:
            raw = f"{source}-{date}-{asset}-{idx}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _safe_float(self, value: str | None) -> float | None:
        """Parse a float from a CSV cell, return None if empty or unparseable."""
        if not value or str(value).strip() in ("", "-", "N/A", "null", "None"):
            return None
        try:
            cleaned = str(value).replace(",", "").replace("$", "").strip()
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _normalize_date(self, raw: str) -> str | None:
        """
        Normalize various date formats to ISO 8601 UTC: YYYY-MM-DDTHH:MM:SSZ.
        Returns None if unparseable.
        """
        from datetime import datetime, timezone

        raw = raw.strip()
        formats = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S UTC",
            "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(raw, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
        return None
