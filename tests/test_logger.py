from datetime import datetime, timezone

from config import Trade
from logger import init_csv, log_trade, read_trades, CSV_FIELDS


def _make_trade(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-above-84k",
        question="Will BTC be above $84,000?",
        strategy="level",
        side="YES",
        entry_price=0.65,
        size=10.0,
        confidence=0.95,
        reason="price is 2% above threshold",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_init_csv_creates_header(tmp_csv):
    init_csv(tmp_csv)
    content = tmp_csv.read_text()
    assert "timestamp" in content
    assert "market_slug" in content
    assert "strategy" in content


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
    assert "btc-above-84k" in lines[1]
    assert "level" in lines[1]
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
    original = _make_trade()
    log_trade(original, tmp_csv)
    trades = read_trades(tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_slug == "btc-above-84k"
    assert trades[0].side == "YES"
    assert trades[0].entry_price == 0.65
    assert trades[0].size == 10.0
    assert trades[0].confidence == 0.95


def test_csv_fields_match_trade():
    trade = _make_trade()
    for field in CSV_FIELDS:
        assert hasattr(trade, field), f"Trade missing field: {field}"
