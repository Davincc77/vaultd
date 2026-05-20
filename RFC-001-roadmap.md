# RFC-001: vaultd v2.5–v3.5 Roadmap — Community Input Wanted

**Status:** Open for comment
**Posted:** June 2025
**Author:** [@Davincc77](https://github.com/Davincc77)
**Contact:** [Luxlearn@pm.me](mailto:Luxlearn@pm.me)
**Closes:** Rolling — no hard deadline, but roadmap decisions will be made by end of Q3 2025

---

## What is this?

This is an open call for community input on the next 18 months of vaultd development. The goal is to make sure the roadmap reflects real needs — not just what the maintainer assumes is important.

If you use vaultd, or tried it and stopped, or looked at it and decided it wasn't there yet — your input matters here.

---

## What vaultd is, briefly

vaultd is a local-first, encrypted portfolio tracker for crypto holdings. Your data lives in a `.vaultd` file on your machine, encrypted with AES-256-GCM and Argon2id. There is no server. There is no account. Nothing leaves your machine unless you deliberately move it.

The design philosophy: you should be able to understand exactly what this tool does to your data, and trust it without reading the source code — though the source code is there if you want it.

**Where it stands at v2.1.0:**

- Encrypted `.vaultd` format (AES-256-GCM + Argon2id)
- Schema v1.2.1 with strict validation
- CLI: `vaultd-save`, `vaultd-load`, `vaultd-import`, `vaultd-price`, `vaultd-tui`
- Importers: Coinbase CSV, Etherscan (normal transactions + ERC-20 transfers)
- Price oracle: CoinGecko free tier, 5-min cache, confirmation-required writes
- TUI: Textual, 6 tabs, dark theme
- CI: GitHub Actions, Python 3.10–3.13, 60 tests

It works. It's useful for a specific kind of user. But there are real gaps.

---

## The Four Pain Points

Based on community feedback and usage patterns, these are the problems that come up most:

### 1. Fragmented tracking

Your portfolio isn't on one chain or one exchange. It's split across Coinbase, Binance, Kraken, a Ledger hardware wallet, some Solana DeFi, and maybe an old Etherscan address you forgot about. Importing each of these manually is painful. vaultd currently handles two of these sources.

### 2. Tax hell

Every year: exporting CSVs from five platforms, uploading them to a third-party service, hoping the categorization is right, paying for a subscription, and handing a stranger your full transaction history. There should be a way to produce a clean, minimal tax report without sharing everything.

### 3. No "why" memory

Most portfolio trackers record *what* you hold and at *what price*. vaultd records *why* — through the `investment_thesis` and `invalidation_hypothesis` fields in the schema. But right now, nothing watches whether those invalidation conditions are actually happening on-chain. Your thesis can be quietly invalidated while you're not looking.

### 4. Multi-chain chaos

Solana, Ethereum L2s, BNB Chain — each has its own explorer, its own CSV format, its own quirks. There's no unified import path.

---

## The Proposed Roadmap

Here's what we're planning to build. These are proposals, not commitments. The shape of each milestone is open to change based on what comes out of this discussion.

---

### v2.5 — Unified Multi-Chain Importers (Q3 2026)

The goal: make `vaultd import` handle the exchanges and chains where most portfolios actually live.

Planned additions:
- **Solscan importer** — Solana transactions and SPL token transfers
- **Binance CSV importer**
- **Kraken CSV importer** (trades, staking rewards, ledger)
- **`vaultd import --all`** — one command, all configured sources
- **Background watcher mode** — `vaultd watch --vault portfolio.vaultd` monitors a directory and proposes imports as new CSVs appear
- **Exchange API connectors (optional, read-only)** — Coinbase Advanced Trade, Binance API; keys stored in vault, never sent anywhere

Available as: `pip install 'vaultd[importers]'`

---

### v2.8 — Private Tax Auditor Mode (Q3 2026)

The goal: generate a tax-ready export from your vault without giving anyone your full transaction history.

Planned additions:
- **`vaultd tax export`** — extracts a `tax_summary` + `taxable_events` slice, nothing else
- **Koinly CSV export**
- **CoinTracker CSV export**
- **Handoff vault** — an encrypted `.vaultd` slice with only tax events and thesis notes; share with your accountant safely
- **PnL calculator** — FIFO, LIFO, and average cost, computed locally
- **Jurisdiction support (initial):** LU, FR, BE, DE, UK, US

Available as: `pip install 'vaultd[tax]'`

---

### v3.0 — Thesis-Linked On-Chain Risk Oracle (Q4 2026)

The goal: let your vault watch its own invalidation conditions.

Planned additions:
- **Hypothesis monitor** — watches `invalidation_hypothesis` fields against live on-chain data
- **DeFi health factor watcher** — Aave, Compound liquidation threshold alerts
- **IL spike detection** — for LP positions, against a configurable threshold
- **Contract upgrade detection** — proxy upgrades via Etherscan API
- **Automatic alert triggers** — appends to `risk_events[]`, always with a confirmation prompt; no silent writes
- **SKILL.md enforcement** — unacknowledged risk events surface on session open

Available as: `pip install 'vaultd[oracle]'`

---

### v3.5 — Mobile Air-Gapped Companion (Q1 2027)

The goal: read your vault and confirm risk events on mobile, with zero server involvement.

Planned additions:
- **PWA** — reads `.vaultd` locally via File System Access API; no upload required
- **QR-code encrypted patch transfer** — desktop generates a delta → QR code → mobile scans and confirms → patch syncs back the same way
- **`.vaultd-patch` format** — signed delta, not a full vault copy
- **Mobile dashboard** — positions, risk events, proposed changes
- **Fully offline** — no backend, no sync service, no cloud account

---

## Questions for the Community

These are the decisions where outside perspective genuinely changes the outcome. Please respond in the comments below, or open a separate Discussion thread if you want to go deep on any of these.

### 1. Which importer do you need most?

After Coinbase and Etherscan, what's your biggest gap?

- Solana (Solscan / native transactions)
- Binance CSV
- Kraken CSV
- MetaMask (transaction history export)
- Ledger Live CSV export
- Something else — tell us what

### 2. Tax jurisdiction priority

We're starting with six jurisdictions (LU, FR, BE, DE, UK, US) for the tax module. If yours isn't in that list and you'd be willing to help document the rules, that would directly accelerate the timeline. Which country should we prioritize after the initial six?

### 3. On-chain risk oracle — what's your biggest DeFi risk right now?

The v3.0 oracle is designed around the risks users actually face. What keeps you up at night?

- Liquidation risk on a lending protocol
- Impermanent loss on an LP position
- A contract upgrade changing the rules mid-game
- A protocol governance vote with bad outcomes
- Something else

What protocols are you most exposed to?

### 4. Mobile: what's the right approach?

Three real options, each with tradeoffs:

- **PWA** — no install, runs in the browser, File System Access API (limited iOS support today)
- **React Native** — native app, better mobile UX, more complex build/distribution
- **Tauri desktop companion** — not mobile, but a proper desktop app wrapper; simpler to ship cross-platform

What's your platform? What would you actually use?

### 5. Schema gaps

The `.vaultd` schema v1.2.1 has fields for thesis, invalidation hypothesis, risk events, and position metadata. What's missing from your real-world use case?

Some candidates that have come up:
- LP position details (tick range, pool address, current IL)
- Staking/yield fields (APR, unlock date, validator)
- NFT positions (floor price, collection, rarity tier)
- Multi-sig wallet references
- Something else entirely

---

## How to Contribute

**This Discussion:** Comment below with your answers to any of the questions above. You don't have to answer all five — one concrete answer is more useful than five vague ones.

**GitHub Issues:** If you've found a bug or have a specific feature request, [open an issue](https://github.com/Davincc77/vaultd/issues).

**Pull Requests:** If you want to build something from this roadmap, check `CONTRIBUTING.md` first. We'd rather align on design before you invest significant time.

**Email:** If you'd rather not post publicly, reach out at [Luxlearn@pm.me](mailto:Luxlearn@pm.me). Feedback shared privately can still inform decisions — it just can't be cited in the Discussion.

---

## RFC Process — How This Works

This RFC will remain open for comment. Major decisions (especially any that affect the `.vaultd` schema) will not be made until there has been at least two weeks for community response. Breaking schema changes always go through a full RFC cycle.

The goal is for `.vaultd` to become an open standard — something that other tools and developers can build on with confidence that the format isn't going to shift without warning. That only works if the community has real input into how it evolves.

Thank you for reading this far. Looking forward to the conversation.

— [@Davincc77](https://github.com/Davincc77)
