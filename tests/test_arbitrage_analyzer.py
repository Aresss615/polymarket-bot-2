from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone

from groq import RateLimitError

from config import Market, Article, Signal, ARBITRAGE_CONFIDENCE_THRESHOLD
from arbitrage_analyzer import analyze_headlines, _call_groq


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


def _mock_groq_response(text):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = text
    return mock_response


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_match(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "fed-rate-hike", "side": "YES", "confidence": 0.95, "reason": "headline confirms rate hike"}'
    )

    market = _make_market("fed-rate-hike", "Will the Fed raise rates in April 2026?")
    article = _make_article("Federal Reserve raises rates by 0.25% in April meeting")

    signals = analyze_headlines([article], [market])
    assert len(signals) == 1
    assert signals[0].side == "YES"
    assert signals[0].confidence == 0.95
    assert signals[0].strategy == "arbitrage"
    assert signals[0].market.slug == "fed-rate-hike"


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_no_match(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response("")

    market = _make_market("fed-rate-hike", "Will the Fed raise rates?")
    article = _make_article("Weather forecast: sunny tomorrow")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_filters_low_confidence(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "fed-rate-hike", "side": "YES", "confidence": 0.60, "reason": "maybe"}'
    )

    market = _make_market("fed-rate-hike", "Will the Fed raise rates?")
    article = _make_article("Fed considering rate options")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_multiple_matches(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "market-a", "side": "YES", "confidence": 0.90, "reason": "confirmed A"}\n'
        '{"slug": "market-b", "side": "NO", "confidence": 0.88, "reason": "confirmed B"}'
    )

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


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_ignores_unknown_slug(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "nonexistent-market", "side": "YES", "confidence": 0.95, "reason": "test"}'
    )

    market = _make_market("real-market", "Real question?")
    article = _make_article("Some headline")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_call_groq_falls_back_on_rate_limit(mock_groq_cls):
    """When 70B returns 429, should retry with 8B."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {}
    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=rate_limit_response,
        body=None,
    )

    success_response = _mock_groq_response(
        '{"slug": "test", "side": "YES", "confidence": 0.90, "reason": "fallback worked"}'
    )

    mock_client.chat.completions.create.side_effect = [
        rate_limit_error,
        success_response,
    ]

    result = _call_groq(mock_client, "test prompt")
    assert result == '{"slug": "test", "side": "YES", "confidence": 0.90, "reason": "fallback worked"}'

    calls = mock_client.chat.completions.create.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["model"] == "llama-3.3-70b-versatile"
    assert calls[1].kwargs["model"] == "llama-3.1-8b-instant"


@patch("arbitrage_analyzer.groq.Groq")
def test_call_groq_returns_empty_on_total_failure(mock_groq_cls):
    """When both models fail, should return empty string."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {}
    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=rate_limit_response,
        body=None,
    )

    mock_client.chat.completions.create.side_effect = rate_limit_error

    result = _call_groq(mock_client, "test prompt")
    assert result == ""
