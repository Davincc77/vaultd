# vaultd Roadmap

> Last updated: May 2026 — v2.5.0 stable

This document describes where vaultd is today, where it is going, and the values that govern every decision along the way. It is a living document. If something here conflicts with reality, open an issue.

---

## Philosophy

These are non-negotiable constraints, not aspirations:

- **Zero server.** Your vault never leaves your machine unless you choose to move it. No telemetry, no sync endpoints, no "cloud backup."
- **Privacy before convenience.** When privacy and a smoother UX conflict, privacy wins.
- **Versioned, backward-compatible schema.** No migration scripts that silently mangle your data. Schema changes follow an RFC process.
- **No VC funding. No tokens. No monetization of user data.** vaultd is a tool, not a product.
- **CC0 forever.** The `.vaultd` format is in the public domain. Build on it freely.

---

## Current State — v2.1.0

Shipped and stable:

| Area | Detail |
|---|---|
| Encryption | AES-256-GCM + Argon2id — `.vaultd` format |
| Schema | v1.2.1, strict (`additionalProperties: false`) |
| CLI commands | `vaultd-save`, `vaultd-load`, `vaultd-import`, `vaultd-price`, `vaultd-tui` |
| Importers | Coinbase, Etherscan (normal + ERC-20), **Solscan**, **Binance**, **Kraken** |
| Price oracle | CoinGecko free tier, 5-min cache, confirmation-required writes |
| TUI | Textual, 6 tabs, dark theme |
| CI | GitHub Actions, Python 3.10–3.13, **87 tests** |

---

## Roadmap

Milestones are ordered by dependency and community priority. Dates are targets, not contracts.

---

### ~~v2.5 — Unified Multi-Chain Importers~~ ✅ SHIPPED
**Released: May 2026**

- ✅ Solscan importer (SOL + SPL token transfers)
- ✅ Binance importer (trade history / transaction history / deposit-withdrawal)
- ✅ Kraken importer (ledger + trade exports, asset normalization)
- ✅ 87 tests, all passing
- ✅ `pip install vaultd` — all importers included

**Remaining from original v2.5 scope (moved to v2.6):**
- `vaultd import --all` — batch from multiple configured sources
- Background watcher mode — `vaultd watch` polls a directory for new CSVs
- Exchange API connectors (read-only) — Coinbase Advanced Trade, Binance

**RFC:** [RFC-001](RFC-001-roadmap.md) — community input open

---

### v2.8 — Private Tax Auditor Mode
**Target: Q3 2026**

Tax reporting without handing your full transaction history to a third-party service.

**Planned work:**

- **`vaultd tax export`** — generate a tax-only slice: `tax_summary` + `taxable_events`, nothing else
- **Koinly CSV export** — drop the output directly into Koinly
- **CoinTracker CSV export** — same for CoinTracker
- **Handoff vault** — an encrypted `.vaultd` slice containing only tax events and your investment thesis; share with an accountant without exposing full portfolio history
- **PnL calculator** — FIFO, LIFO, and average cost methods, computed locally
- **Jurisdiction support (initial):** Luxembourg, France, Belgium, Germany, United Kingdom, United States (basic rules; not legal advice)

**Install:**
```
pip install 'vaultd[tax]'
```

**RFC:** [RFC-001](RFC-001-roadmap.md) — jurisdiction priority is an open question; vote there

---

### v3.0 — Thesis-Linked On-Chain Risk Oracle
**Target: Q4 2026**

Your vault already stores *why* you hold each position via `invalidation_hypothesis`. v3.0 makes it watch the chain for conditions that would invalidate that thesis.

**Planned work:**

- **Hypothesis monitor** — watches `invalidation_hypothesis` fields and queries on-chain data to check conditions
- **DeFi health factor watcher** — tracks Aave and Compound liquidation thresholds; alerts before you get liquidated
- **IL spike detection** — monitors impermanent loss for LP positions against configurable thresholds
- **Contract upgrade detection** — detects proxy upgrades via Etherscan API and flags positions in upgraded contracts
- **Automatic alert triggers** — appends to `risk_events[]` with a confirmation prompt; no silent writes
- **SKILL.md enforcement** — when an agent or TUI session opens, unacknowledged risk events are surfaced immediately

**Install:**
```
pip install 'vaultd[oracle]'
```

**RFC:** [RFC-001](RFC-001-roadmap.md) — open question: which DeFi protocols to prioritize

---

### v3.5 — Mobile Air-Gapped Companion
**Target: Q1 2027**

Read and review your vault on mobile. Propose edits from your phone. Never sync to a server.

**Planned work:**

- **PWA (Progressive Web App)** — reads `.vaultd` files locally via the File System Access API; no upload, no backend
- **QR-code encrypted patch transfer** — desktop proposes a delta → encodes as QR → mobile scans → confirms; the confirmed patch syncs back the same way
- **Encrypted patch format** — `.vaultd-patch`: a signed delta, not a full vault copy; minimizes exposure if a patch file is ever lost
- **Dashboard and alerts on mobile** — view positions, read risk events, confirm proposed changes
- **Strictly offline** — no server, no sync service, no cloud; works on a plane

**RFC:** [RFC-001](RFC-001-roadmap.md) — open question: PWA vs React Native vs Tauri; vote there

---

## Community RFC Process

Schema changes and major feature additions follow a lightweight RFC process:

1. A draft RFC is posted to [GitHub Discussions](https://github.com/Davincc77/vaultd/discussions/1)
2. **Breaking schema changes require a minimum 2-week public comment period** before any merge
3. Non-breaking additions can ship with a single-week comment window
4. The RFC is merged into `/docs/rfcs/` when accepted, or closed with a documented reason if rejected

This exists to keep `.vaultd` an open standard that the community can build on, not a format that shifts under third-party implementations without warning.

**Open threads:**
- [RFC-001: v2.5–v3.5 Roadmap](https://github.com/Davincc77/vaultd/discussions/1) — open for input now

---

## Contributing

- **Issues:** Bug reports, importer requests, schema feedback
- **PRs:** Welcome; check `CONTRIBUTING.md` before opening a large one
- **Discussions:** Architecture questions, RFC comment periods, general direction
- **Email:** [Luxlearn@pm.me](mailto:Luxlearn@pm.me)

---

*This roadmap reflects community analysis and maintainer judgment as of June 2025. Nothing here is a promise. Everything here is open for discussion.*
