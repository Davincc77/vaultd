"""
vaultd.importers.merge — Merge imported transactions into an existing .vaultd vault.

Deduplication strategy:
  1. tx_hash match (strongest — same on-chain tx)
  2. (date + asset + amount + type) composite key (for CEX imports with no hash)
  3. id match (if same importer re-run)
"""

from __future__ import annotations

from typing import Any


def _dedup_key(tx: dict[str, Any]) -> tuple:
    """Return a tuple used to detect duplicate transactions."""
    tx_hash = (tx.get("tx_hash") or "").strip()
    if tx_hash:
        return ("hash", tx_hash)
    # Composite key for hashless CEX transactions
    return (
        "composite",
        tx.get("date", ""),
        (tx.get("asset") or "").upper(),
        tx.get("type", ""),
        round(float(tx.get("amount") or 0), 8),
    )


def merge_transactions(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Merge incoming transactions into existing list, deduplicating by tx_hash or
    composite key.

    Returns:
        (merged_list, new_count, duplicate_count)
    """
    seen: set[tuple] = set()

    # Index existing transactions
    for tx in existing:
        seen.add(_dedup_key(tx))
        seen.add(("id", tx.get("id", "")))

    merged = list(existing)
    new_count = 0
    dup_count = 0

    for tx in incoming:
        key = _dedup_key(tx)
        id_key = ("id", tx.get("id", ""))
        if key in seen or id_key in seen:
            dup_count += 1
            continue
        merged.append(tx)
        seen.add(key)
        seen.add(id_key)
        new_count += 1

    # Sort by date ascending
    merged.sort(key=lambda t: t.get("date", ""))

    return merged, new_count, dup_count
