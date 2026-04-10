from datetime import datetime, timezone, timedelta

from config import Market, LevelMarket, Signal, LEVEL_CLEARANCE_PCT, LEVEL_WINDOW_MINUTES
from level_analyzer import parse_level_market, find_level_markets, analyze_level_opportunity


# --- parse_level_market tests ---


def test_parse_btc_above(sample_market):
    """sample_market question: 'Will BTC be above $84,000 at 5pm ET on April 10?'"""
    lm = parse_level_market(sample_market)
    assert lm is not None
    assert lm.coin == "BTC"
    assert lm.threshold == 84000.0
    assert lm.direction == "above"
    assert lm.expiry == sample_market.end_date


def test_parse_eth_below():
    m = Market(
        condition_id="0x1",
        question="Will ETH be below $1,800 at 12pm ET on April 11?",
        slug="eth-below-1800",
        outcomes=["Yes", "No"],
        outcome_prices=[0.3, 0.7],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 11, 16, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is not None
    assert lm.coin == "ETH"
    assert lm.threshold == 1800.0
    assert lm.direction == "below"


def test_parse_sol_with_decimals():
    m = Market(
        condition_id="0x2",
        question="Will SOL be above $130.50 at 3pm ET?",
        slug="sol-above-130",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 19, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is not None
    assert lm.coin == "SOL"
    assert lm.threshold == 130.50


def test_parse_non_level_market(sample_non_level_market):
    """'Will the Fed raise rates in April?' — not a level market."""
    lm = parse_level_market(sample_non_level_market)
    assert lm is None


def test_parse_no_end_date():
    m = Market(
        condition_id="0x3",
        question="Will BTC be above $80,000 at 5pm ET?",
        slug="btc-80k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=None,
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is None


def test_parse_with_comma_in_price():
    m = Market(
        condition_id="0x4",
        question="Will BTC be above $100,000 at 5pm ET?",
        slug="btc-100k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is not None
    assert lm.threshold == 100000.0


# --- find_level_markets tests ---


def test_find_level_markets(sample_market, sample_non_level_market):
    results = find_level_markets([sample_market, sample_non_level_market])
    assert len(results) == 1
    assert results[0].coin == "BTC"


def test_find_level_markets_empty():
    assert find_level_markets([]) == []


# --- analyze_level_opportunity tests ---


def test_signal_yes_when_price_above_threshold(sample_level_market):
    """BTC at $86,000 is 2.4% above $84,000 threshold — should signal YES."""
    now = sample_level_market.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 86000.0, now=now)
    assert signal is not None
    assert signal.side == "YES"
    assert signal.strategy == "level"
    assert signal.confidence > 0


def test_signal_no_when_price_below_threshold(sample_level_market):
    """BTC at $82,000 is 2.4% below $84,000 threshold — should signal NO."""
    now = sample_level_market.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 82000.0, now=now)
    assert signal is not None
    assert signal.side == "NO"


def test_no_signal_when_too_close_to_threshold(sample_level_market):
    """BTC at $84,500 is only 0.6% above $84,000 — below 1.5% clearance."""
    now = sample_level_market.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 84500.0, now=now)
    assert signal is None


def test_no_signal_when_too_far_from_expiry(sample_level_market):
    """More than 10 minutes to expiry — too early."""
    now = sample_level_market.expiry - timedelta(minutes=30)
    signal = analyze_level_opportunity(sample_level_market, 86000.0, now=now)
    assert signal is None


def test_no_signal_after_expiry(sample_level_market):
    """Market already expired."""
    now = sample_level_market.expiry + timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 86000.0, now=now)
    assert signal is None


def test_below_direction_yes():
    """'Will ETH be below $2000' — ETH at $1900 should signal YES."""
    m = Market(
        condition_id="0x5",
        question="Will ETH be below $2,000 at 5pm ET?",
        slug="eth-below-2k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = LevelMarket(market=m, coin="ETH", threshold=2000.0, direction="below", expiry=m.end_date)
    now = lm.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(lm, 1900.0, now=now)
    assert signal is not None
    assert signal.side == "YES"


def test_below_direction_no():
    """'Will ETH be below $2000' — ETH at $2100 should signal NO."""
    m = Market(
        condition_id="0x6",
        question="Will ETH be below $2,000 at 5pm ET?",
        slug="eth-below-2k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = LevelMarket(market=m, coin="ETH", threshold=2000.0, direction="below", expiry=m.end_date)
    now = lm.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(lm, 2100.0, now=now)
    assert signal is not None
    assert signal.side == "NO"
