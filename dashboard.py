import re
import time

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import STRATEGY_VERSION, TRADING_MODE
from strategy_eval import compute_patch_stats

# Extract coin ticker from updown slugs like "btc-updown-5m-123"
_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)


def _extract_coin(slug: str) -> str | None:
    m = _COIN_RE.match(slug)
    return m.group(1).upper() if m else None


def _fmt_pnl(pnl: float) -> Text:
    if pnl >= 0:
        return Text(f"+${pnl:.2f}", style="green")
    return Text(f"-${abs(pnl):.2f}", style="red")


def make_dashboard(engine) -> Layout:
    layout = Layout()

    # --- Header: current-version stats only ---
    v_trades = [t for t in engine.trades if t.strategy_version == STRATEGY_VERSION]
    pending = sum(1 for t in v_trades if t.status == "pending")
    v_settled = [t for t in v_trades if t.status in ("won", "lost")]
    v_wins = sum(1 for t in v_settled if t.status == "won")
    v_losses = len(v_settled) - v_wins
    pnl = sum(t.payout - t.size for t in v_settled)
    pnl_style = "green" if pnl >= 0 else "red"
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    wr_str = f"{v_wins/len(v_settled):.0%}" if v_settled else "—"

    patch = compute_patch_stats(engine.trades)

    header_text = Text()
    mode_label = {"paper": "[PAPER]", "simulation": "[SIM]", "live": "[LIVE]"}.get(TRADING_MODE, "[?]")
    mode_style = {"paper": "dim", "simulation": "yellow", "live": "bold red"}.get(TRADING_MODE, "dim")
    header_text.append(f"{mode_label} ", style=mode_style)
    header_text.append("Polymarket Bot", style="bold white")
    header_text.append(f"  |  Balance: ${engine.balance:,.2f}", style="bold white")
    header_text.append(f"  |  v{STRATEGY_VERSION} P&L: {pnl_str}", style=f"bold {pnl_style}")
    header_text.append(f" ({v_wins}W/{v_losses}L {wr_str})", style="white")
    header_text.append(f"  |  Pending: {pending}", style="bold white")
    header_text.append(f"  |  Tick: {engine.tick_count}", style="dim")
    header_text.append(f"  |  {engine.status}", style="dim")
    header = Panel(header_text, style="blue")

    # --- Patch Stats + 15m Mode Panel ---
    mode = getattr(engine, "mode_15m", None)

    stats_text = Text()
    stats_text.append(f"Patch v{STRATEGY_VERSION}", style="bold white")
    stats_text.append(f"  Trades: {patch.settled_trades}/{patch.total_trades}")
    if patch.settled_trades > 0:
        stats_text.append(f"  WR: {patch.win_rate:.0%}")
        pf_str = f"{patch.profit_factor:.1f}" if patch.profit_factor != float("inf") else "∞"
        stats_text.append(f"  PF: {pf_str}")
        stats_text.append(f"  Exp: ${patch.expectancy:.2f}/trade")
    stats_text.append("\n")

    if mode:
        if mode.tightened:
            mode_style = "yellow"
        elif mode.enabled:
            mode_style = "green"
        else:
            mode_style = "red"
        stats_text.append("15m: ", style="bold white")
        stats_text.append(mode.reason, style=mode_style)
    else:
        stats_text.append("15m: awaiting first tick", style="dim")

    stats_panel = Panel(stats_text, title="Strategy", border_style="cyan")

    # --- Risk Panel ---
    risk_text = Text()
    rm = getattr(engine, "risk_manager", None)
    if rm:
        open_exp = sum(t.size for t in engine.trades if t.status == "pending")
        daily_pnl = rm.daily_pnl
        daily_style = "green" if daily_pnl >= 0 else "red"
        daily_str = f"+${daily_pnl:.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):.2f}"
        risk_text.append("Daily P&L: ", style="bold white")
        risk_text.append(daily_str, style=daily_style)
        risk_text.append(f"  |  Exposure: ${open_exp:.2f}/${rm.config.max_open_exposure:.2f}", style="white")
        streak = rm.consecutive_losses
        streak_style = "red" if streak >= 3 else "white"
        risk_text.append(f"  |  Loss streak: {streak}", style=streak_style)
        if rm.kill_switch_active:
            risk_text.append("  |  KILL SWITCH: ON", style="bold red")
    else:
        risk_text.append("Risk manager not initialized", style="dim")
    risk_panel = Panel(risk_text, title="Risk", border_style="yellow")

    # --- Per-Coin Breakdown Table (current patch only) ---
    coin_table = Table(title=f"Per-Coin (v{STRATEGY_VERSION})", expand=True)
    coin_table.add_column("Coin", width=5)
    coin_table.add_column("Trades", justify="right", width=6)
    coin_table.add_column("WR", justify="right", width=5)
    coin_table.add_column("PF", justify="right", width=5)
    coin_table.add_column("P/L", justify="right", width=8)

    # Gather coins from current-patch updown trades
    patch_trades = [t for t in engine.trades if t.strategy_version == STRATEGY_VERSION and t.strategy == "updown"]
    coins = sorted({_extract_coin(t.market_slug) for t in patch_trades if _extract_coin(t.market_slug)})

    for coin in coins:
        coin_trades = [t for t in patch_trades if _extract_coin(t.market_slug) == coin]
        settled = [t for t in coin_trades if t.status in ("won", "lost")]
        wins = sum(1 for t in settled if t.status == "won")
        losses = len(settled) - wins
        gross_profit = sum(t.payout - t.size for t in settled if t.status == "won")
        gross_loss = sum(t.size for t in settled if t.status == "lost")
        net = gross_profit - gross_loss
        wr = f"{wins / len(settled):.0%}" if settled else "—"
        pf = f"{gross_profit / gross_loss:.1f}" if gross_loss > 0 else ("∞" if gross_profit > 0 else "—")
        coin_table.add_row(coin, str(len(settled)), wr, pf, _fmt_pnl(net))

    if not coins:
        coin_table.add_row("—", "—", "—", "—", Text("—", style="dim"))

    # --- UpDown Markets Table ---
    updown_table = Table(title="Crypto UpDown Markets", expand=True)
    updown_table.add_column("Slug", max_width=35, no_wrap=True)
    updown_table.add_column("Coin", width=5)
    updown_table.add_column("Int", width=4)
    updown_table.add_column("Secs", justify="right", width=5)
    updown_table.add_column("UP", justify="right", width=8)
    updown_table.add_column("DOWN", justify="right", width=8)

    for udm in engine.updown_markets_found[:15]:
        m = udm.market
        if udm.up_outcome_index == 0:
            up_p = f"${m.outcome_prices[0]:.2f}" if m.outcome_prices else "-"
            down_p = f"${m.outcome_prices[1]:.2f}" if len(m.outcome_prices) > 1 else "-"
        else:
            down_p = f"${m.outcome_prices[0]:.2f}" if m.outcome_prices else "-"
            up_p = f"${m.outcome_prices[1]:.2f}" if len(m.outcome_prices) > 1 else "-"
        updown_table.add_row(
            m.slug[:35], udm.coin, f"{udm.interval_minutes}m",
            str(udm.seconds_to_close), up_p, down_p,
        )

    if not engine.updown_markets_found:
        updown_table.add_row("No updown markets closing soon", "-", "-", "-", "-", "-")

    # --- Trades Table ---
    trades_table = Table(title="Trades", expand=True)
    trades_table.add_column("Time", width=8)
    trades_table.add_column("Market", max_width=28, no_wrap=True)
    trades_table.add_column("Type", width=4)
    trades_table.add_column("Side", width=4)
    trades_table.add_column("Entry", justify="right", width=6)
    trades_table.add_column("Size", justify="right", width=6)
    trades_table.add_column("Result", width=8)
    trades_table.add_column("P/L", justify="right", width=8)
    trades_table.add_column("Reason", max_width=32, no_wrap=True)

    for t in engine.trades[-15:]:
        side_style = "green" if t.side == "YES" else "red"
        market_type = getattr(t, 'market_type', '5m')

        if t.status == "won":
            result_text = Text("WIN", style="bold green")
            pl = t.payout - t.size
            pl_text = Text(f"+${pl:.2f}", style="green")
        elif t.status == "lost":
            result_text = Text("LOSS", style="bold red")
            pl_text = Text(f"-${t.size:.2f}", style="red")
        else:
            result_text = Text("...", style="dim")
            pl_text = Text("—", style="dim")

        trades_table.add_row(
            t.timestamp.strftime("%H:%M:%S"),
            t.market_slug[:28],
            market_type,
            Text(t.side, style=side_style),
            f"${t.entry_price:.2f}",
            f"${t.size:.2f}",
            result_text,
            pl_text,
            t.reason[:32],
        )

    if not engine.trades:
        trades_table.add_row("—", "No trades yet", "—", "—", "—", "—", "—", "—", "Waiting...")

    # --- Activity Log ---
    log_lines = list(engine.activity_log)[-18:]
    log_text = "\n".join(log_lines) if log_lines else "Waiting for first tick..."
    log_panel = Panel(log_text, title="Activity Log", border_style="dim")

    # --- Layout Assembly ---
    # Top: header (3 lines)
    # Middle: strategy panel (3 lines)
    # Body: left (markets + trades) | right (coin stats + activity log)
    layout.split_column(
        Layout(header, size=3),
        Layout(stats_panel, size=4),
        Layout(risk_panel, size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(updown_table, ratio=1),
        Layout(trades_table, ratio=1),
    )
    layout["right"].split_column(
        Layout(coin_table, ratio=1),
        Layout(log_panel, ratio=2),
    )
    return layout


def run_dashboard(engine):
    with Live(make_dashboard(engine), refresh_per_second=1, screen=True) as live:
        while engine.running:
            live.update(make_dashboard(engine))
            time.sleep(1)
