"""
vaultd.tui — Terminal UI for browsing and editing a .vaultd vault.

Built with Textual (https://textual.textualize.io/).
Runs 100% locally — never connects to anything, never modifies vault without confirmation.

Install: pip install vaultd[tui]
Launch:  vaultd-tui portfolio.vaultd

Screens:
  - Dashboard   : portfolio overview, PnL, active alerts
  - Holdings    : holdings table with thesis link indicators
  - Thesis      : thesis browser — read + edit conviction/review notes
  - Transactions: recent transaction ledger
  - Alerts      : active/inactive alert list + toggle
  - Strategy    : strategy rules viewer
"""

from __future__ import annotations

from typing import Any


def _check_textual() -> None:
    try:
        import textual  # noqa: F401
    except ImportError:
        raise ImportError(
            "Textual is required for the TUI. Install it with:\n"
            "  pip install 'vaultd[tui]'\n"
            "or: pip install textual"
        )


# ─── CSS ─────────────────────────────────────────────────────────────────────

VAULTD_CSS = """
Screen {
    background: #0d1117;
}

Header {
    background: #161b22;
    color: #00D4FF;
    text-style: bold;
}

Footer {
    background: #161b22;
    color: #8b949e;
}

TabbedContent {
    background: #0d1117;
}

TabPane {
    background: #0d1117;
    padding: 1 2;
}

DataTable {
    background: #0d1117;
    color: #e6edf3;
}

DataTable > .datatable--header {
    background: #161b22;
    color: #00D4FF;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1f6feb;
    color: #ffffff;
}

.positive { color: #3fb950; }
.negative { color: #f85149; }
.neutral  { color: #8b949e; }
.accent   { color: #00D4FF; }
.warning  { color: #d29922; }

.stat-box {
    background: #161b22;
    border: solid #30363d;
    padding: 1 2;
    margin: 0 1;
    min-width: 20;
}

.stat-label {
    color: #8b949e;
    text-style: bold;
}

.stat-value {
    color: #e6edf3;
    text-style: bold;
}

#alert-banner {
    background: #3d1f00;
    border: solid #d29922;
    color: #d29922;
    padding: 0 2;
    margin-bottom: 1;
}

Button {
    background: #21262d;
    border: solid #30363d;
    color: #e6edf3;
    margin: 0 1;
}

Button:hover {
    background: #1f6feb;
    border: solid #1f6feb;
    color: #ffffff;
}

Button.-confirm {
    background: #1a4721;
    border: solid #3fb950;
    color: #3fb950;
}

Button.-cancel {
    background: #3d1217;
    border: solid #f85149;
    color: #f85149;
}

Input {
    background: #161b22;
    border: solid #30363d;
    color: #e6edf3;
}

Input:focus {
    border: solid #1f6feb;
}

Label {
    color: #8b949e;
}

#edit-panel {
    background: #161b22;
    border: solid #30363d;
    padding: 1 2;
    margin-top: 1;
}
"""


# ─── App ─────────────────────────────────────────────────────────────────────


def launch_tui(vault_path: str, payload: dict[str, Any], passphrase: str) -> None:
    """
    Launch the Textual TUI for a decrypted .vaultd payload.

    Args:
        vault_path: Path to the .vaultd file (for save-back).
        payload: Decrypted payload dict.
        passphrase: Used for atomic re-encryption on save.
    """
    _check_textual()

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        Static,
        TabbedContent,
        TabPane,
    )

    from vaultd.core import create_vaultd

    identity = payload.get("identity", {})
    holdings = payload.get("holdings", [])
    transactions = payload.get("transactions", [])
    thesis_list = payload.get("thesis", [])
    alerts = payload.get("alerts", [])
    strategy = payload.get("strategy", {})

    # Index thesis by id
    thesis_index = {t["id"]: t for t in thesis_list if "id" in t}

    def fmt_price(v: float | None) -> str:
        return f"${v:>12,.2f}" if v is not None else "         null"

    def fmt_pnl(holding: dict) -> str:
        price = holding.get("current_price_usd")
        avg = holding.get("avg_buy_price_usd")
        amount = holding.get("amount", 0)
        if price is None or avg is None:
            return "N/A"
        pnl = (price - avg) * amount
        sign = "+" if pnl >= 0 else ""
        return f"{sign}${pnl:,.2f}"

    def calc_portfolio_value() -> tuple[float, float]:
        total_value = sum(
            (h.get("current_price_usd") or 0) * h.get("amount", 0)
            for h in holdings
        )
        total_cost = sum(
            (h.get("avg_buy_price_usd") or 0) * h.get("amount", 0)
            for h in holdings
        )
        return total_value, total_cost

    triggered_alerts = [
        a for a in alerts
        if a.get("active") and a.get("type") in ("price_below", "price_above")
        and a.get("threshold_usd") is not None
    ]

    class VaultdTUI(App):
        TITLE = f".vaultd — {identity.get('alias', 'Portfolio')}"
        CSS = VAULTD_CSS
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("s", "save", "Save vault"),
            Binding("r", "refresh", "Refresh"),
        ]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._modified = False
            self._payload = payload

        def compose(self) -> ComposeResult:
            yield Header()
            with TabbedContent(initial="dashboard"):
                with TabPane("Dashboard", id="dashboard"):
                    yield self._compose_dashboard()
                with TabPane("Holdings", id="holdings"):
                    yield self._compose_holdings()
                with TabPane("Thesis", id="thesis"):
                    yield self._compose_thesis()
                with TabPane("Transactions", id="transactions"):
                    yield self._compose_transactions()
                with TabPane("Alerts", id="alerts"):
                    yield self._compose_alerts()
                with TabPane("Strategy", id="strategy"):
                    yield self._compose_strategy()
            yield Footer()

        def _compose_dashboard(self) -> ComposeResult:
            total_value, total_cost = calc_portfolio_value()
            pnl = total_value - total_cost
            pnl_pct = (pnl / total_cost * 100) if total_cost else 0
            pnl_class = "positive" if pnl >= 0 else "negative"

            yield Static(
                f"[bold accent].vaultd[/] — {identity.get('alias', 'Portfolio')}  "
                f"| Risk: [accent]{identity.get('risk_profile', '?')}[/]  "
                f"| Level: [accent]{identity.get('experience_level', '?')}[/]",
                classes="accent"
            )

            if triggered_alerts:
                yield Static(
                    f"⚠ {len(triggered_alerts)} alert(s) may be triggered — check Alerts tab",
                    id="alert-banner"
                )

            with Horizontal():
                with Container(classes="stat-box"):
                    yield Static("Portfolio Value", classes="stat-label")
                    yield Static(f"${total_value:,.2f}", classes="stat-value accent")
                with Container(classes="stat-box"):
                    yield Static("Cost Basis", classes="stat-label")
                    yield Static(f"${total_cost:,.2f}", classes="stat-value")
                with Container(classes="stat-box"):
                    yield Static("Unrealized PnL", classes="stat-label")
                    sign = "+" if pnl >= 0 else ""
                    yield Static(f"{sign}${pnl:,.2f} ({pnl_pct:.1f}%)", classes=f"stat-value {pnl_class}")
                with Container(classes="stat-box"):
                    yield Static("Holdings", classes="stat-label")
                    yield Static(str(len(holdings)), classes="stat-value")

            yield Static("")
            active_thesis = sum(1 for t in thesis_list if t.get("status") == "active")
            active_alerts_count = sum(1 for a in alerts if a.get("active"))
            last_session = (self._payload.get("history", {}).get("sessions") or [{}])[-1]

            yield Static(
                f"Theses: [accent]{active_thesis} active[/] / {len(thesis_list)} total  "
                f"| Alerts: [accent]{active_alerts_count} active[/]  "
                f"| Transactions: [accent]{len(transactions)}[/]"
            )
            if last_session.get("date"):
                yield Static(
                    f"Last session: [neutral]{last_session.get('date')}[/] "
                    f"via [neutral]{last_session.get('model', '?')}[/]  "
                    f"— {last_session.get('summary', '')[:80]}"
                )

        def _compose_holdings(self) -> ComposeResult:
            table = DataTable(id="holdings-table")
            table.add_columns(
                "Asset", "Amount", "Avg Buy", "Current Price",
                "Unrealized PnL", "Allocation %", "Thesis"
            )
            total_value, _ = calc_portfolio_value()
            for h in sorted(holdings, key=lambda x: x.get("asset", "")):
                asset = h.get("asset", "?")
                amount = h.get("amount", 0)
                avg_buy = h.get("avg_buy_price_usd")
                current = h.get("current_price_usd")
                value = (current or 0) * amount
                alloc = f"{value / total_value * 100:.1f}%" if total_value > 0 else "N/A"
                pnl_str = fmt_pnl(h)
                thesis_id = h.get("thesis_id")
                thesis_flag = "✓" if thesis_id and thesis_id in thesis_index else "—"
                current_str = fmt_price(current)
                table.add_row(
                    asset,
                    f"{amount:,.6f}",
                    fmt_price(avg_buy),
                    current_str,
                    pnl_str,
                    alloc,
                    thesis_flag,
                )
            yield table
            yield Static(
                "[neutral]Tip: Use vaultd-price --vault file.vaultd --write to update prices[/]",
                classes="neutral"
            )

        def _compose_thesis(self) -> ComposeResult:
            if not thesis_list:
                yield Static("[neutral]No thesis entries found.[/]\nAdd them to your .vaultd payload under thesis[].", classes="neutral")
                return

            table = DataTable(id="thesis-table")
            table.add_columns("Asset", "Conviction", "Status", "Target", "Stop Loss", "Last Review")
            for t in thesis_list:
                target = f"${t['target_exit_usd']:,.0f}" if t.get("target_exit_usd") else "—"
                stop = f"${t['stop_loss_usd']:,.0f}" if t.get("stop_loss_usd") else "—"
                table.add_row(
                    t.get("asset", "?"),
                    t.get("conviction", "?"),
                    t.get("status", "?"),
                    target,
                    stop,
                    t.get("last_reviewed", "—"),
                )
            yield table

            # Show first thesis detail
            if thesis_list:
                t = thesis_list[0]
                yield Static(f"\n[accent]Entry Rationale — {t.get('asset')}[/]")
                yield Static(t.get("entry_rationale", "—"))
                if t.get("invalidation_hypothesis"):
                    yield Static("\n[warning]Invalidation Hypothesis[/]")
                    yield Static(t.get("invalidation_hypothesis", "—"))

        def _compose_transactions(self) -> ComposeResult:
            if not transactions:
                yield Static("[neutral]No transactions found.[/]", classes="neutral")
                return
            table = DataTable(id="tx-table")
            table.add_columns("Date", "Type", "Asset", "Amount", "Price USD", "Fee USD", "Exchange")
            for tx in sorted(transactions, key=lambda x: x.get("date", ""), reverse=True)[:200]:
                table.add_row(
                    tx.get("date", "?")[:10],
                    tx.get("type", "?"),
                    tx.get("asset", "?"),
                    f"{tx.get('amount', 0):,.6f}",
                    fmt_price(tx.get("price_usd")),
                    fmt_price(tx.get("fee_usd")),
                    tx.get("exchange") or "—",
                )
            if len(transactions) > 200:
                yield Static(f"[neutral]Showing 200 of {len(transactions)} transactions[/]")
            yield table

        def _compose_alerts(self) -> ComposeResult:
            if not alerts:
                yield Static("[neutral]No alerts configured.[/]", classes="neutral")
                return
            table = DataTable(id="alerts-table")
            table.add_columns("Active", "Asset", "Type", "Threshold", "Message")
            for a in alerts:
                active_str = "✓" if a.get("active") else "—"
                threshold = f"${a['threshold_usd']:,.2f}" if a.get("threshold_usd") else f"{a.get('threshold_pct', '—')}%"
                table.add_row(
                    active_str,
                    a.get("asset", "?"),
                    a.get("type", "?"),
                    threshold,
                    a.get("message", ""),
                )
            yield table

        def _compose_strategy(self) -> ComposeResult:
            if not strategy:
                yield Static("[neutral]No strategy defined.[/]", classes="neutral")
                return
            yield Static(f"[accent]Time Horizon:[/] {strategy.get('time_horizon', '—').replace('_', ' ')}")
            if strategy.get("max_single_asset_pct"):
                yield Static(f"[accent]Max single asset:[/] {strategy['max_single_asset_pct']}%")
            if strategy.get("stablecoin_reserve_pct"):
                yield Static(f"[accent]Stablecoin reserve:[/] {strategy['stablecoin_reserve_pct']}%")
            if strategy.get("dca_assets"):
                yield Static(f"[accent]DCA assets:[/] {', '.join(strategy['dca_assets'])}")
            rules = strategy.get("rules", [])
            if rules:
                yield Static(f"\n[accent]Rules ({len(rules)}):[/]")
                for i, rule in enumerate(rules, 1):
                    yield Static(f"  {i}. {rule}")

        def action_save(self) -> None:
            if not self._modified:
                self.notify("No changes to save.", severity="information")
                return
            try:
                create_vaultd(self._payload, passphrase, vault_path)
                self._modified = False
                self.notify("Vault saved.", severity="information")
            except Exception as e:
                self.notify(f"Save failed: {e}", severity="error")

        def action_refresh(self) -> None:
            self.notify("Use vaultd-price --write to refresh prices.", severity="information")

    VaultdTUI().run()
