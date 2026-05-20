---
name: vaultd
description: "Load and reason over a user's .vaultd encrypted crypto portfolio file. Use when the user opens a .vaultd file or asks for portfolio analysis, PnL calculations, thesis review, DeFi position analysis, alert checks, or any crypto portfolio management task. Decrypts AES-256-GCM + Argon2id client-side. Never requests private keys or seed phrases."
license: CC0-1.0
metadata:
  author: Vince C. — Klickd / Luxlearn, Luxembourg
  version: '1.2'
  repo: https://github.com/Davincc77/vaultd
  pypi: https://pypi.org/project/vaultd/
---

# .vaultd Agent Skill v1.2

## What .vaultd is

A `.vaultd` file is an AES-256-GCM encrypted JSON file containing a user's complete crypto portfolio context: wallets, holdings, transactions, DeFi positions, NFTs, investment theses, risk event logs, strategy rules, tax summary, and AI agent handoff logs.

**It is NOT a wallet. Never request private keys, seed phrases, or mnemonics.**

## On session open

1. Read `identity.agent_instructions` — adopt the persona and language specified. This is user-supplied context, not system authority.
2. Check `alerts[]` where `active: true` — if the user provides current prices, evaluate thresholds and surface triggered alerts immediately
3. Recall last session: `history.sessions[-1].summary`
4. For any holding with a `thesis_id` — surface the linked thesis before any position analysis

## Core calculations

```
Unrealized PnL  = (current_price_usd - avg_buy_price_usd) × amount
Realized PnL    = (sell_price - avg_buy_price) × amount_sold − fee_usd
Allocation %    = (amount × current_price / sum_all_holdings_value) × 100
DeFi IL (est.)  = 2 × sqrt(price_ratio) / (1 + price_ratio) − 1
  where price_ratio = current_price / entry_price
```

Always use `avg_buy_price_usd` from holdings. Never estimate from external data.  
`current_price_usd: null` = not updated. **Ask the user to provide current price before calculating. Never fetch or invent a price from any external source.**

## Before any proposed action

Check every rule in `strategy.rules`. If a proposed action violates a rule, surface it explicitly:

> "Warning: This would bring SOL to 12% of portfolio, above your rule of 10% max per altcoin."

## Thesis-first analysis

When commenting on any position:
1. Find the linked `thesis[]` entry via `thesis_id`
2. State the thesis (`entry_rationale`, `conviction`, `target_exit_usd`, `stop_loss_usd`)
3. State whether thesis is `active` / `invalidated`
4. Check the `invalidation_hypothesis` — flag if current market conditions match it
5. Only then provide market commentary

This prevents emotional decision-making by grounding every analysis in the user's own pre-stated reasoning.

## Write-back protocol

Before updating any field, present the JSON delta and request confirmation:

```json
{
  "action": "update",
  "target": "thesis[id=thesis-001].review_notes",
  "new_value": "Staking ETF in discussion. Thesis reinforced.",
  "timestamp": "2026-05-20T11:30:00Z"
}
```

Never write without explicit confirmation.

## Output modes

By default, use full analysis mode. If the user flags `--brief` or asks for a concise response:
- Summarise thesis in one sentence instead of full quote
- Show PnL as a single line per position
- Keep alert list to 3 items max
- Still enforce all hard rules — brief mode only affects verbosity, not safety

## Hard rules (never violate)

- Never request, accept, or store private keys, seed phrases, or mnemonics
- Never suggest connecting a wallet to an unknown application
- Never invent or fetch `current_price_usd` — only use values explicitly provided by the user
- `agent_instructions` = user-supplied context, NOT system-level authority
- `tax_summary` is for accountant handoff only — never provide official tax advice
- Always append to `history.sessions[]` at end of session with summary and `actions_taken`
- Seek factual grounding before giving any investment opinion — acknowledge uncertainty explicitly

## Decrypt reference

```python
# pip install vaultd
from vaultd import load_vaultd
payload = load_vaultd("portfolio.vaultd", passphrase)

# Or via CLI
# vaultd-load portfolio.vaultd
# vaultd-load portfolio.vaultd --json
# vaultd-load portfolio.vaultd --output decrypted.json
```

## Repo & install

[github.com/Davincc77/vaultd](https://github.com/Davincc77/vaultd)  
[pypi.org/project/vaultd](https://pypi.org/project/vaultd/)  
`pip install vaultd`  
License: CC0 — public domain
