from datetime import datetime

import feedparser

from config import GOOGLE_NEWS_RSS_URL, Article


def fetch_google_news(query: str = "politics economy world") -> list[Article]:
    try:
        url = f"{GOOGLE_NEWS_RSS_URL}?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        seen: set[str] = set()
        articles: list[Article] = []
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            if title in seen:
                continue
            seen.add(title)

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
                    title=title,
                    source=source_name,
                    url=entry.get("link", ""),
                    published_at=pub,
                )
            )
        return articles
    except Exception:
        return []
