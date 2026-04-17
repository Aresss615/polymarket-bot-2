from datetime import datetime, timezone

from config import OpenOrder, Trade
from logger import (
    CSV_FIELDS,
    init_csv,
    init_open_orders_csv,
    log_trade,
    read_open_orders,
    read_trades,
    save_open_orders,
)


def _make_trade(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        strategy="updown",
        side="YES",
        entry_price=0.60,
        size=10.0,
        confidence=0.95,
        reason="BTC implied UP at 60%",
        end_date=datetime(2026, 4, 10, 12, 5, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Trade(**defaults)


def _make_open_order(**overrides):
    defaults = dict(
        order_id="order-123",
        created_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        condition_id="0xbtc",
        token_id="0xtoken",
        strategy="updown",
        side="YES",
        confidence=0.95,
        reason="test reason",
        end_date=datetime(2026, 4, 10, 12, 5, tzinfo=timezone.utc),
        market_type="5m",
        strategy_version=9,
        executor_type="LiveExecutor",
        limit_price=0.58,
        requested_size=2.90,
        requested_shares=5.0,
        reserved_size=1.74,
        confirmed_fill_size=1.16,
        confirmed_fill_shares=2.0,
        confirmed_fees=0.01,
        status="partial",
        raw_status="live",
    )
    defaults.update(overrides)
    return OpenOrder(**defaults)


def test_init_csv_creates_header(tmp_csv):
    init_csv(tmp_csv)
    content = tmp_csv.read_text()
    assert "timestamp" in content
    assert "market_slug" in content
    assert "status" in content
    assert "payout" in content


def test_init_csv_idempotent(tmp_csv):
    init_csv(tmp_csv)
    init_csv(tmp_csv)
    lines = tmp_csv.read_text().strip().split("\n")
    assert len(lines) == 1  # only one header


def test_log_trade_writes_row(tmp_csv):
    trade = _make_trade()
    log_trade(trade, tmp_csv)
    lines = tmp_csv.read_text().strip().split("\n")
    assert len(lines) == 2  # header + 1 trade
    assert "btc-updown-5m-123" in lines[1]
    assert "updown" in lines[1]
    assert "YES" in lines[1]


def test_log_multiple_trades(tmp_csv):
    log_trade(_make_trade(market_slug="trade-1"), tmp_csv)
    log_trade(_make_trade(market_slug="trade-2"), tmp_csv)
    lines = tmp_csv.read_text().strip().split("\n")
    assert len(lines) == 3  # header + 2 trades


def test_read_trades_empty(tmp_csv):
    trades = read_trades(tmp_csv)
    assert trades == []


def test_read_trades_roundtrip(tmp_csv):
    original = _make_trade(
        status="won",
        payout=16.67,
        condition_id="0xcondition",
        order_id="order-abc",
        executor_type="LiveExecutor",
        redemption_status="pending",
        redemption_tx_id="redeem-123",
        redemption_tx_hash="0xhash",
        redemption_error="",
        redemption_updated_at=datetime(2026, 4, 10, 12, 6, tzinfo=timezone.utc),
    )
    log_trade(original, tmp_csv)
    trades = read_trades(tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_slug == "btc-updown-5m-123"
    assert trades[0].side == "YES"
    assert trades[0].entry_price == 0.60
    assert trades[0].size == 10.0
    assert trades[0].status == "won"
    assert abs(trades[0].payout - 16.67) < 0.01
    assert trades[0].end_date == original.end_date
    assert trades[0].condition_id == "0xcondition"
    assert trades[0].order_id == "order-abc"
    assert trades[0].executor_type == "LiveExecutor"
    assert trades[0].redemption_status == "pending"
    assert trades[0].redemption_tx_id == "redeem-123"
    assert trades[0].redemption_tx_hash == "0xhash"
    assert trades[0].redemption_updated_at == datetime(2026, 4, 10, 12, 6, tzinfo=timezone.utc)


def test_csv_fields_match_trade():
    trade = _make_trade()
    for field in CSV_FIELDS:
        assert hasattr(trade, field), f"Trade missing field: {field}"


def test_read_trades_legacy_csv_without_end_date(tmp_csv):
    tmp_csv.write_text(
        "timestamp,market_slug,question,strategy,side,entry_price,size,confidence,reason,status,payout\n"
        "2026-04-10T12:00:00+00:00,btc-updown-5m-123,BTC Up or Down?,updown,YES,0.6000,10.00,0.95,test,pending,0.00\n"
    )
    trades = read_trades(tmp_csv)
    assert len(trades) == 1
    assert trades[0].end_date is None
    assert trades[0].condition_id == ""
    assert trades[0].order_id == ""
    assert trades[0].executor_type == ""
    assert trades[0].redemption_status == ""
    assert trades[0].redemption_tx_id == ""
    assert trades[0].redemption_tx_hash == ""
    assert trades[0].redemption_error == ""
    assert trades[0].redemption_updated_at is None


def test_read_trades_cp1252_fallback(tmp_csv):
    raw = (
        "timestamp,market_slug,question,strategy,side,entry_price,size,confidence,reason,status,payout\n"
        "2026-04-10T12:00:00+00:00,btc-updown-5m-123,BTC Up or Down?,updown,YES,0.6000,10.00,0.95,"
        "Trader’s note,pending,0.00\n"
    )
    tmp_csv.write_bytes(raw.encode("cp1252"))

    trades = read_trades(tmp_csv)

    assert len(trades) == 1
    assert "Trader" in trades[0].reason


def test_market_type_field_round_trip(tmp_csv):
    """Trade with market_type persists through CSV write/read."""
    from logger import log_trade, read_trades
    from config import Trade
    from datetime import datetime, timezone

    trade = Trade(
        timestamp=datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-15m-123",
        question="BTC Up or Down?",
        strategy="updown",
        side="YES",
        entry_price=0.75,
        size=2.00,
        confidence=0.80,
        reason="test reason",
        market_type="15m",
    )
    log_trade(trade, path=tmp_csv)
    trades = read_trades(path=tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_type == "15m"


def test_market_type_defaults_to_5m(tmp_csv):
    """Old CSV rows without market_type default to '5m'."""
    from logger import read_trades
    import csv

    # Write a row without the market_type column
    with open(tmp_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "market_slug", "question", "strategy", "side",
            "entry_price", "size", "confidence", "reason", "status", "payout", "end_date",
        ])
        writer.writerow([
            "2026-04-10T12:00:00+00:00", "btc-updown-5m-123", "BTC?", "updown", "YES",
            "0.75", "2.00", "0.80", "reason", "won", "2.67", "2026-04-10T12:05:00+00:00",
        ])

    trades = read_trades(path=tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_type == "5m"


def test_init_open_orders_csv_creates_header(tmp_path):
    path = tmp_path / "open_orders.csv"
    init_open_orders_csv(path)
    content = path.read_text()
    assert "order_id" in content
    assert "reserved_size" in content
    assert "confirmed_fill_size" in content


def test_open_orders_roundtrip(tmp_path):
    path = tmp_path / "open_orders.csv"
    original = _make_open_order()

    save_open_orders([original], path)
    orders = read_open_orders(path)

    assert len(orders) == 1
    assert orders[0].order_id == original.order_id
    assert orders[0].market_slug == original.market_slug
    assert orders[0].reserved_size == original.reserved_size
    assert orders[0].confirmed_fill_size == original.confirmed_fill_size
    assert orders[0].executor_type == original.executor_type
    assert orders[0].status == "partial"


def test_read_open_orders_empty(tmp_path):
    path = tmp_path / "missing_open_orders.csv"
    assert read_open_orders(path) == []
