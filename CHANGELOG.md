# Changelog

All notable changes to `.vaultd` are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [2.5.1] — 2026-05-20

### Added
- **base.py** — three new date formats in `_normalize_date`:
  - `%Y-%m-%dT%H:%M:%S.%fZ` — ISO 8601 with milliseconds + Z (e.g. Binance API exports)
  - `%Y-%m-%dT%H:%M:%S.%f` — ISO 8601 with microseconds (no Z)
  - `%Y-%m-%dT%H:%M:%S` — ISO 8601 without timezone suffix
- **`--version` flag** on all CLI entry points (`vaultd-save`, `vaultd-load`, `vaultd-import`, `vaultd-price`, `vaultd-tui`)
- **`vaultd-load --json`** — output now includes `_meta.vaultd_version` and `_meta.vaultd_schema_version` for agent consumers
- **`vaultd-import --verbose`** — when combined with `--dry-run`, shows all warnings (not truncated at 10) and full skipped-row details
- **11 new tests** in `tests/test_importers_v25.py` (`TestV251EdgeCases`) — 98 total, all passing

### Fixed
- **solscan.py** — SPL rows with empty `Token Symbol` now emit a warning and default to `"UNKNOWN"` instead of silently using it
- **binance.py** — deposit/withdrawal rows where both source and destination address are empty now emit a warning before defaulting to `transfer_in`
- **kraken.py** — `asset` field in ledger and trade rows now explicitly normalized with `.upper().strip()`

---

## [2.5.0] — 2026-05-20

### Added
- **Solscan importer** (`vaultd/importers/solscan.py`) — Solana native transaction CSV and SPL token transfer CSV exports
  - Maps to `transfer_in`, `transfer_out`, `swap`, `stake`, `unstake`, `claim_rewards`, `nft_mint`, `airdrop`
  - Direction detection via wallet address matching
  - Dust filter (< 0.0001 SOL)
  - `--chain` flag on CLI to override chain label (default: `solana`)
- **Binance importer** (`vaultd/importers/binance.py`) — three Binance export formats:
  - Trade History CSV (Date/Pair/Side/Price/Executed/Amount/Fee)
  - Transaction History CSV (UTC_Time/Operation/Coin/Change)
  - Deposit/Withdrawal History CSV (TXID-linked, status filter)
  - 30+ operation type mappings including staking, rewards, P2P, auto-invest, convert
- **Kraken importer** (`vaultd/importers/kraken.py`) — two Kraken export formats:
  - Ledger export — full operation type + subtype mapping (spottostaking, stakingtospot, etc.)
  - Trade export — vol/price/fee with quote-currency fee_usd resolution
  - Automatic Kraken asset normalization (XXBT→BTC, XETH→ETH, ZEUR→EUR, etc.)
  - Fiat-only ledger entries skipped automatically
- `vaultd/importers/__init__.py` — registered `solscan`, `binance`, `kraken` in IMPORTERS registry
- `vaultd/cli/import_cmd.py` — `--chain` flag for Solscan; `--wallet-address` help updated
- 27 new tests in `tests/test_importers_v25.py` (87 total, all passing)
- `ROADMAP.md` — v2.5→v3.5 roadmap with philosophy, milestones, RFC governance
- `RFC-001-roadmap.md` — GitHub Discussions RFC post with community questions

### Changed
- Version bumped: `2.1.0` → `2.5.0`
- `vaultd-import` CLI help text updated with Solscan/Binance/Kraken examples
- Binance `staking_rewards` → `claim_rewards` (was `airdrop`)

### Fixed
- `test_get_importer_unknown` used `"binance"` as the unknown name — updated to `"not_a_real_exchange"`

---

## [1.2] — 2026-05-20

### Added
- `schemas/vaultd_v12.json` — fixed and hardened JSON Schema (v1.2)
  - `transactions[]` block now fully defined in `properties` (was missing, only in `required`)
  - `strategy` moved out of `required` — it is genuinely optional
  - All ID fields now enforce `pattern: ^[a-zA-Z0-9_\-]+$`
  - `minLength` / `maxLength` constraints on all string fields
  - `minimum` / `maximum` on numeric fields (`amount`, `threshold_pct`, Argon2 percents)
  - `additionalProperties: false` on all objects to catch typos
  - `transactions[].type` enum: buy, sell, transfer_in, transfer_out, swap, bridge, stake, unstake, airdrop, fee
  - `tax_summary.method` enum: FIFO, LIFO, average_cost, specific_id
- `pyproject.toml` — proper Python packaging with entry points (`vaultd-save`, `vaultd-load`)
- `requirements.txt` + `requirements-dev.txt` — pinned dependencies
- `tests/test_roundtrip.py` — 19-test suite covering roundtrip, authentication, integrity, custom Argon2 params, atomic writes, error handling, version compat, Hypothesis property-based tests
- `.github/workflows/ci.yml` — GitHub Actions CI on Python 3.10–3.13 (lint + test + schema validation)

### Changed
- `save_vaultd.py` — major improvements:
  - JSON Schema validation on save (via `jsonschema`, warns if not installed)
  - Atomic write via `tempfile` + `os.replace` (crash-safe)
  - Custom Argon2id params via `--argon2-m`, `--argon2-t`, `--argon2-p` CLI flags
  - `created_at` now always written back into payload before encryption
  - Minimum passphrase length raised to 16 chars with interactive confirmation
  - Explicit error codes (`VAULTD_E_FORMAT`, `VAULTD_E_SCHEMA`, `VAULTD_E_PASSPHRASE`)
  - `vaultd_version` bumped to `1.2` in new envelopes
- `load_vaultd.py` — major improvements:
  - JSON Schema validation on load (v1.2 envelopes only)
  - `--output` flag to write decrypted JSON to a file instead of stdout
  - Specific `base64.b64decode` error handling per field (`salt`, `iv`, `ciphertext`)
  - Pre-flight check for missing envelope fields before any crypto operations
  - v1.1 envelopes remain supported (backward compatible)
  - Richer human-readable summary: NFTs, risk events, agent handoffs, strategy, tax summary, active alerts printed inline
  - `SUPPORTED_VAULTD_VERSIONS = {"1.1", "1.2"}` — explicit compatibility set

### Fixed
- Schema: `transactions` was listed in `required` but missing from `properties` (Grok review)
- Schema: `strategy` was `required` but marked optional in its own definition (contradictory)
- `load_vaultd.py`: AAD reconstruction could `KeyError` on malformed envelopes before decryption
- `load_vaultd.py`: Broad `except Exception` on base64 replaced with field-specific handling

---

## [1.1] — 2026-05-20

### Added
- `thesis[]` block — per-position investment thesis with conviction level, entry rationale, invalidation hypothesis, exit targets, review notes
- `risk_events[]` block — decision log during market stress events with sentiment, action, outcome, and lesson fields
- `alerts[]` block — personal threshold rules stored in file, checked by agent on session open (price_below, price_above, allocation_above_pct, stablecoin_below_pct, pnl_target_reached, stop_loss_approach, defi_apy_below)
- `tax_summary` block — taxable events log for accountant handoff, jurisdiction-aware (LU/FR/BE/DE/...)
- `agent_handoffs[]` block — log of context passed to other AI models with result summary
- `thesis_id` field added to `holdings[]`, `transactions[]`, and `defi_positions[]` for cross-referencing
- `restaking` added to `defi_positions[].type` enum
- `experience_level` field added to `identity`
- Error codes: `VAULTD_E_VERSION`, `VAULTD_E_DOMAIN`, `VAULTD_E_DECRYPT`, `VAULTD_E_FORMAT`, `VAULTD_E_FORBIDDEN`

### Changed
- AAD now includes `vaultd_version` as 5th field (previously 4 fields matching .klickd)

---

## [1.0] — 2026-05-20

### Added
- Initial release
- Cryptographic envelope: AES-256-GCM + Argon2id, based on `.klickd` v3.0
- Payload blocks: `identity`, `wallets[]`, `holdings[]`, `transactions[]`, `defi_positions[]`, `nfts[]`, `pnl`, `watchlist[]`, `strategy`, `journal[]`, `history`
- Reference scripts: `save_vaultd.py`, `load_vaultd.py`
- JSON Schema: `schemas/vaultd_v11.json`
- Example payload: `examples/example_v11_full.json`
