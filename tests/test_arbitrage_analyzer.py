from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from config import Market, Article, Signal, ARBITRAGE_CONFIDENCE_THRESHOLD
from arbitrage_analyzer import analyze_headlines


def _make_market(slug, question, yes_price=0.5, no_price=0.5):
    return Market(
        condition_id=f"0x{slug}",
        question=question,
        slug=slug,
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, no_price],
        token_ids=[f"0x{slug}_yes", f"0x{slug}_no"],
        end_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        active=True,
    )


def _make_article(title):
    return Article(
        title=title,
        source="Reuters",
        url="https://example.com",
        published_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )


@patch("arbitrage_analyzer.anthropic.Anthropic")
def test_analyze_headlines_match(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"slug": "fed-rate-hike", "side": "YES", "confidence": 0.95, "reason": "headline confirms rate hike"}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    market = _make_market("fed-rate-hike", "Will the Fed raise rates in April 2026?")
    article = _make_article("Federal Reserve raises rates by 0.25% in April meeting")

    signals = analyze_headlines([article], [market])
    assert len(signals) == 1
    assert signals[0].side == "YES"
    assert signals[0].confidence == 0.95
    assert signals[0].strategy == "arbitrage"
    assert signals[0].market.slug == "fed-rate-hike"


@patch("arbitrage_analyzer.anthropic.Anthropic")
def test_analyze_headlines_no_match(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="")]
    mock_client.messages.create.return_value = mock_response

    market = _make_market("fed-rate-hike", "Will the Fed raise rates?")
    article = _make_article("Weather forecast: sunny tomorrow")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.anthropic.Anthropic")
def test_analyze_headlines_filters_low_confidence(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"slug": "fed-rate-hike", "side": "YES", "confidence": 0.60, "reason": "maybe"}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    market = _make_market("fed-rate-hike", "Will the Fed raise rates?")
    article = _make_article("Fed considering rate options")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.anthropic.Anthropic")
def test_analyze_headlines_multiple_matches(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=(
                '{"slug": "market-a", "side": "YES", "confidence": 0.90, "reason": "confirmed A"}\n'
                '{"slug": "market-b", "side": "NO", "confidence": 0.88, "reason": "confirmed B"}'
            )
        )
    ]
    mock_client.messages.create.return_value = mock_response

    markets = [
        _make_market("market-a", "Will A happen?"),
        _make_market("market-b", "Will B happen?"),
    ]
    articles = [_make_article("A confirmed"), _make_article("B denied")]

    signals = analyze_headlines(articles, markets)
    assert len(signals) == 2


def test_analyze_headlines_empty_inputs():
    signals = analyze_headlines([], [])
    assert signals == []


@patch("arbitrage_analyzer.anthropic.Anthropic")
def test_analyze_headlines_ignores_unknown_slug(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"slug": "nonexistent-market", "side": "YES", "confidence": 0.95, "reason": "test"}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    market = _make_market("real-market", "Real question?")
    article = _make_article("Some headline")

    signals = analyze_headlines([article], [market])
    assert signals == []
