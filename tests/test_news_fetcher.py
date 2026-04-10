from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from news_fetcher import fetch_newsapi, fetch_google_news, fetch_all_news


SAMPLE_NEWSAPI_RESPONSE = {
    "status": "ok",
    "articles": [
        {
            "title": "Fed raises rates by 0.25%",
            "source": {"name": "Reuters"},
            "url": "https://reuters.com/1",
            "publishedAt": "2026-04-10T12:00:00Z",
        },
        {
            "title": "Inflation hits 3%",
            "source": {"name": "AP"},
            "url": "https://ap.com/2",
            "publishedAt": "2026-04-10T11:00:00Z",
        },
    ],
}


@patch("news_fetcher.requests.get")
def test_fetch_newsapi_success(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = SAMPLE_NEWSAPI_RESPONSE
    mock_get.return_value = resp

    articles = fetch_newsapi()
    assert len(articles) == 2
    assert articles[0].title == "Fed raises rates by 0.25%"
    assert articles[0].source == "Reuters"
    assert articles[1].title == "Inflation hits 3%"


@patch("news_fetcher.requests.get")
def test_fetch_newsapi_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    articles = fetch_newsapi()
    assert articles == []


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
def test_fetch_google_news_failure(mock_parse):
    mock_parse.side_effect = Exception("parse error")
    articles = fetch_google_news()
    assert articles == []


@patch("news_fetcher.fetch_google_news")
@patch("news_fetcher.fetch_newsapi")
def test_fetch_all_news_deduplicates(mock_newsapi, mock_google):
    from config import Article

    a1 = Article(title="Same headline", source="Reuters", url="https://a.com", published_at=None)
    a2 = Article(title="Same headline", source="Google", url="https://b.com", published_at=None)
    a3 = Article(title="Different headline", source="AP", url="https://c.com", published_at=None)

    mock_newsapi.return_value = [a1]
    mock_google.return_value = [a2, a3]

    articles = fetch_all_news()
    assert len(articles) == 2
    titles = [a.title for a in articles]
    assert "Same headline" in titles
    assert "Different headline" in titles
