import time

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def make_dashboard(engine) -> Layout:
    layout = Layout()

    # --- Header ---
    pending = sum(1 for t in engine.trades if t.status == "pending")
    pnl = engine.total_pnl
    pnl_style = "green" if pnl >= 0 else "red"
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    wr_str = f"{engine.win_rate:.0%}" if engine.settled_count > 0 else "—"

    header_text = Text()
    header_text.append("Polymarket Paper Bot", style="bold white")
    header_text.append(f"  |  Balance: ${engine.balance:,.2f}", style="bold white")
    header_text.append(f"  |  P/L: {pnl_str}", style=f"bold {pnl_style}")
    header_text.append(f"  |  W/L: {engine.wins}/{engine.losses} ({wr_str})", style="bold white")
    header_text.append(f"  |  Pending: {pending}", style="bold white")
    header_text.append(f"  |  Tick: {engine.tick_count}", style="dim")
    header_text.append(f"  |  {engine.status}", style="dim")
    header = Panel(header_text, style="blue")

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
    trades_table.add_column("Side", width=4)
    trades_table.add_column("Entry", justify="right", width=6)
    trades_table.add_column("Size", justify="right", width=6)
    trades_table.add_column("Result", width=8)
    trades_table.add_column("P/L", justify="right", width=8)
    trades_table.add_column("Reason", max_width=32, no_wrap=True)

    for t in engine.trades[-15:]:
        side_style = "green" if t.side == "YES" else "red"

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
            Text(t.side, style=side_style),
            f"${t.entry_price:.2f}",
            f"${t.size:.2f}",
            result_text,
            pl_text,
            t.reason[:32],
        )

    if not engine.trades:
        trades_table.add_row("—", "No trades yet", "—", "—", "—", "—", "—", "Waiting...")

    # --- Activity Log ---
    log_lines = list(engine.activity_log)[-18:]
    log_text = "\n".join(log_lines) if log_lines else "Waiting for first tick..."
    log_panel = Panel(log_text, title="Activity Log", border_style="dim")

    layout.split_column(
        Layout(header, size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=2),
        Layout(log_panel, name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(updown_table, ratio=1),
        Layout(trades_table, ratio=1),
    )
    return layout


def run_dashboard(engine):
    with Live(make_dashboard(engine), refresh_per_second=1, screen=True) as live:
        while engine.running:
            live.update(make_dashboard(engine))
            time.sleep(1)
