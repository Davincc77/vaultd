# .vaultd

> **"Not your keys, not your data. Not your file, not your context."**

[![License: CC0-1.0](https://img.shields.io/badge/License-CC0_1.0-lightgrey.svg)](https://creativecommons.org/publicdomain/zero/1.0/)
[![Format version: 1.1](https://img.shields.io/badge/format-v1.1-00D4FF)]()
[![Based on: .klickd v3.0](https://img.shields.io/badge/based_on-.klickd_v3.0-6366F1)](https://github.com/Davincc77/klickdskill)
[![Envelope: AES-256-GCM](https://img.shields.io/badge/encryption-AES--256--GCM-FFB800)]()
[![KDF: Argon2id](https://img.shields.io/badge/KDF-Argon2id-FFB800)]()

---

Every crypto portfolio tool tracks **what** you hold.  
None track **why**.

Your entry rationale, your invalidation hypothesis, your decision during the last crash at 3am — that context lives in your head, or scattered across Discord DMs, Notion pages, and spreadsheets you'll never open again.

**`.vaultd` stores both.**

A single encrypted file — on your device, never on any server — that carries your full portfolio context: wallets, holdings, transactions, DeFi positions, NFTs, and the reasoning behind every decision. Load it into GPT, Claude, Gemini, Grok, or any model that reads JSON. Your AI picks up exactly where you left off.

---

## What it solves

| Tool | What it does | What it misses |
|---|---|---|
| Zapper / DeBank / Zerion | Live on-chain portfolio reading | No thesis, no decision memory, third-party servers |
| Spreadsheets | Full flexibility | Not encrypted, not AI-readable, not portable |
| Exchange CSV exports | Transaction history | No context, incompatible formats |
| AI chat (GPT / Claude / etc.) | Portfolio analysis | No persistent context between sessions or models |

`.vaultd` fills the gap: **encrypted, local, portable, AI-native portfolio context.**

---

## Technical facts (v1.1)

| Property | Value |
|---|---|
| Encryption | AES-256-GCM |
| Key derivation | Argon2id m=65536 / t=3 / p=1 |
| AAD canonicalization | RFC 8785 JCS — 5 fields, deterministic |
| Envelope | Based on `.klickd` v3.0 |
| Format | JSON, UTF-8 |
| Extension | `.vaultd` |
| MIME type | `application/vnd.vaultd+json` |
| License | CC0 1.0 Universal (public domain) |
| SDK required | None |

---

## Payload blocks

| Block | Description | v1.1 |
|---|---|---|
| `identity` | Alias, language, risk profile, agent instructions | — |
| `wallets[]` | Public addresses only — never private keys | — |
| `holdings[]` | Asset, amount, avg buy price, thesis link | — |
| `transactions[]` | Full ledger — buy/sell/swap/bridge/stake/airdrop/nft | — |
| `defi_positions[]` | Protocol, pair, APY at entry, IL estimate | — |
| `nfts[]` | Collection, utility, hold reason | — |
| `pnl` | Realized / unrealized, best/worst trade | — |
| `watchlist[]` | Draft thesis for potential entries | — |
| `strategy` | Personal rules, DCA config, max allocations | — |
| `journal[]` | Market notes, monthly reviews, sentiment log | — |
| `history` | AI session log | — |
| `thesis[]` | Per-position investment thesis, invalidation hypothesis, exit targets | ★ |
| `risk_events[]` | Decision log during market stress — action, rationale, outcome, lesson | ★ |
| `alerts[]` | Personal threshold rules — agent checks on every session open | ★ |
| `tax_summary` | Taxable events log, jurisdiction-aware, for accountant handoff | ★ |
| `agent_handoffs[]` | Log of context passed to other AI models | ★ |

---

## The thesis block — why it matters

```json
{
  "id": "thesis-001",
  "asset": "ETH",
  "conviction": "high",
  "time_horizon": "18_months",
  "entry_rationale": "L2 flywheel acceleration. EIP-4844. Spot ETF catalyst.",
  "target_exit_usd": 6000.00,
  "stop_loss_usd": 1800.00,
  "invalidation_hypothesis": "If L2s migrate to alternative DA layers and ETH fees collapse durably.",
  "last_reviewed": "2026-05-01",
  "review_notes": "ETF approved. Thesis holds. Next catalyst: staking ETF.",
  "status": "active"
}
```

When ETH drops 20% at 3am, the agent reads your thesis back to you before you panic sell.

---

## Quickstart

```bash
pip install cryptography argon2-cffi

# Create a new .vaultd file
python scripts/save_vaultd.py --payload examples/example_v11_full.json --output portfolio.vaultd

# Read it back
python scripts/load_vaultd.py portfolio.vaultd
```

---

## What .vaultd is NOT

- **Not a wallet** — cannot sign transactions
- **Not a keystore** — private keys must never enter this file
- **Not a live tracker** — prices are manual, no blockchain connection
- **Not a tax filing tool** — `tax_summary` is for accountant handoff only
- **Not a cloud service** — zero server, zero automatic sync

---

## Relationship to .klickd

`.vaultd` is a domain extension of the [`.klickd` v3.0 format](https://github.com/Davincc77/klickdskill).  
It uses an identical cryptographic envelope (`AES-256-GCM + Argon2id`) with `domain: "crypto"` and adds the `vaultd_version` field plus five crypto-specific payload blocks.

Any `.klickd` v3.0-compatible reader can open a `.vaultd` file (the domain field is advisory).

---

## Repository structure

```
vaultd/
├── README.md               This file
├── SPEC.md                 Technical specification v1.1
├── SKILL.md                Agent skill file — load into any AI agent
├── CHANGELOG.md            Version history
├── CONTRIBUTING.md         How to contribute
├── SECURITY.md             Threat model + responsible disclosure
├── LICENSE                 CC0 1.0 Universal
├── schemas/
│   └── vaultd_v11.json     JSON Schema for payload validation
├── examples/
│   └── example_v11_full.json   Full example payload (unencrypted)
├── scripts/
│   ├── save_vaultd.py      Reference encrypt script
│   └── load_vaultd.py      Reference decrypt script
└── tests/
    └── test_vectors.py     Test vectors
```

---

## License

**CC0 1.0 Universal — public domain.**  
No restrictions. No attribution required. Copy, fork, implement, commercialise freely.

---

## Academic / format reference

> Vince C. (Klickd / Luxlearn, Luxembourg). *".vaultd: An Open Encrypted File Format for Portable AI Crypto Portfolio Context"*. 2026.

---

## Contact

Security / responsible disclosure: **Luxlearn@pm.me**  
Based on `.klickd`: [github.com/Davincc77/klickdskill](https://github.com/Davincc77/klickdskill)

---

*`.vaultd` — not your keys, not your data. not your file, not your context.*
