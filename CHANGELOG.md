# Changelog

All notable changes to `.vaultd` are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

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
