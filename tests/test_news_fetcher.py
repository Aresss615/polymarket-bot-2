from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from config import Article
from news_fetcher import fetch_google_news


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_success(mock_parse):
    entry = MagicMock()
    entry.get.side_effect = lambda k, d=None: {
        "title": "Markets rally on trade deal",
        "link": "https://news.google.com/1",
    }.get(k, d)
    entry.published_parsed = (2026, 4, 10, 12, 0, 0, 0, 0, 0)
    entry.source = {"title": "Bloomberg"}

    mock_parse.return_value = MagicMock(entries=[entry])
    articles = fetch_google_news()
    assert len(articles) == 1
    assert articles[0].title == "Markets rally on trade deal"


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_multiple_entries(mock_parse):
    entries = []
    for i, title in enumerate(["Headline A", "Headline B", "Headline C"]):
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None, t=title: {
            "title": t,
            "link": f"https://news.google.com/{t}",
        }.get(k, d)
        entry.published_parsed = (2026, 4, 10, 12, i, 0, 0, 0, 0)
        entry.source = {"title": "AP"}
        entries.append(entry)

    mock_parse.return_value = MagicMock(entries=entries)
    articles = fetch_google_news()
    assert len(articles) == 3
    assert articles[0].title == "Headline A"
    assert articles[2].title == "Headline C"


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_no_source(mock_parse):
    entry = MagicMock()
    entry.get.side_effect = lambda k, d=None: {
        "title": "Test headline",
        "link": "https://example.com",
    }.get(k, d)
    entry.published_parsed = None
    entry.source = None

    mock_parse.return_value = MagicMock(entries=[entry])
    articles = fetch_google_news()
    assert len(articles) == 1
    assert articles[0].source == "Google News"
    assert articles[0].published_at is None


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_failure(mock_parse):
    mock_parse.side_effect = Exception("parse error")
    articles = fetch_google_news()
    assert articles == []


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_deduplicates(mock_parse):
    entries = []
    for title in ["Same headline", "Same headline", "Different headline"]:
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None, t=title: {
            "title": t,
            "link": "https://example.com",
        }.get(k, d)
        entry.published_parsed = (2026, 4, 10, 12, 0, 0, 0, 0, 0)
        entry.source = {"title": "AP"}
        entries.append(entry)

    mock_parse.return_value = MagicMock(entries=entries)
    articles = fetch_google_news()
    assert len(articles) == 2
    titles = [a.title for a in articles]
    assert "Same headline" in titles
    assert "Different headline" in titles
