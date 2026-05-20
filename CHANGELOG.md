# Changelog

All notable changes to `.vaultd` are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

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
