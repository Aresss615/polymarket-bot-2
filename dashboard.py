import time

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def make_dashboard(engine) -> Layout:
    layout = Layout()

    # --- Header ---
    trade_count = len(engine.trades)
    header_text = (
        f"Polymarket Paper Trading Bot  |  "
        f"Balance: ${engine.balance:,.2f}  |  "
        f"Trades: {trade_count}  |  "
        f"Markets: {len(engine.markets)}  |  "
        f"Status: {engine.status}"
    )
    header = Panel(Text(header_text, style="bold white"), style="blue")

    # --- Level Markets Table ---
    level_table = Table(title="Crypto Level Markets", expand=True)
    level_table.add_column("Question", max_width=55, no_wrap=True)
    level_table.add_column("YES", justify="right", width=8)
    level_table.add_column("NO", justify="right", width=8)
    level_table.add_column("Expiry", width=18)

    for m in engine.markets:
        q = m.question.lower()
        if "above" not in q and "below" not in q:
            continue
        yes_p = f"${m.outcome_prices[0]:.2f}" if m.outcome_prices else "-"
        no_p = f"${m.outcome_prices[1]:.2f}" if len(m.outcome_prices) > 1 else "-"
        expiry = m.end_date.strftime("%m/%d %H:%M UTC") if m.end_date else "-"
        level_table.add_row(m.question[:55], yes_p, no_p, expiry)
        if level_table.row_count >= 12:
            break

    # --- Recent Trades Table ---
    trades_table = Table(title="Recent Trades", expand=True)
    trades_table.add_column("Time", width=10)
    trades_table.add_column("Strategy", width=10)
    trades_table.add_column("Market", max_width=35, no_wrap=True)
    trades_table.add_column("Side", width=6)
    trades_table.add_column("Price", justify="right", width=8)
    trades_table.add_column("Conf", justify="right", width=6)
    trades_table.add_column("Reason", max_width=40, no_wrap=True)

    for t in engine.trades[-15:]:
        side_style = "green" if t.side == "YES" else "red"
        trades_table.add_row(
            t.timestamp.strftime("%H:%M:%S"),
            t.strategy,
            t.market_slug[:35],
            Text(t.side, style=side_style),
            f"${t.entry_price:.2f}",
            f"{t.confidence:.0%}",
            t.reason[:40],
        )

    layout.split_column(
        Layout(header, size=3),
        Layout(level_table, ratio=1),
        Layout(trades_table, ratio=1),
    )
    return layout


def run_dashboard(engine):
    with Live(make_dashboard(engine), refresh_per_second=1, screen=True) as live:
        while engine.running:
            live.update(make_dashboard(engine))
            time.sleep(1)
