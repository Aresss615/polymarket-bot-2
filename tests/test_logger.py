from datetime import datetime, timezone

from config import Trade
from logger import init_csv, log_trade, read_trades, CSV_FIELDS


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
    original = _make_trade(status="won", payout=16.67)
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
