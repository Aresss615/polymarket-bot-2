from datetime import datetime

import feedparser
import requests

from config import NEWSAPI_URL, GOOGLE_NEWS_RSS_URL, NEWSAPI_KEY, Article


def fetch_newsapi(query: str = "politics OR economy OR world") -> list[Article]:
    try:
        resp = requests.get(
            f"{NEWSAPI_URL}/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 20,
                "apiKey": NEWSAPI_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = []
        for a in resp.json().get("articles", []):
            pub = None
            if a.get("publishedAt"):
                pub = datetime.fromisoformat(
                    a["publishedAt"].replace("Z", "+00:00")
                )
            articles.append(
                Article(
                    title=a.get("title", ""),
                    source=a.get("source", {}).get("name", ""),
                    url=a.get("url", ""),
                    published_at=pub,
                )
            )
        return articles
    except Exception:
        return []


def fetch_google_news(query: str = "politics economy world") -> list[Article]:
    try:
        url = f"{GOOGLE_NEWS_RSS_URL}?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:20]:
            pub = None
            if (
                hasattr(entry, "published_parsed")
                and entry.published_parsed
            ):
                pub = datetime(*entry.published_parsed[:6])
            source_name = "Google News"
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source_name = entry.source.get("title", "Google News")
            articles.append(
                Article(
                    title=entry.get("title", ""),
                    source=source_name,
                    url=entry.get("link", ""),
                    published_at=pub,
                )
            )
        return articles
    except Exception:
        return []


def fetch_all_news() -> list[Article]:
    articles = fetch_newsapi() + fetch_google_news()
    seen: set[str] = set()
    unique: list[Article] = []
    for a in articles:
        if a.title not in seen:
            seen.add(a.title)
            unique.append(a)
    return unique
