import json

import groq

from config import (
    Market,
    Article,
    Signal,
    ARBITRAGE_CONFIDENCE_THRESHOLD,
    GROQ_PRIMARY_MODEL,
    GROQ_FALLBACK_MODEL,
)


def _call_groq(client: groq.Groq, prompt: str) -> str:
    """Call Groq with 70B primary, fall back to 8B on rate limit."""
    for model in [GROQ_PRIMARY_MODEL, GROQ_FALLBACK_MODEL]:
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""
        except groq.RateLimitError:
            continue
        except Exception:
            return ""
    return ""


def analyze_headlines(
    articles: list[Article], markets: list[Market]
) -> list[Signal]:
    if not articles or not markets:
        return []

    headlines = "\n".join(
        f"- {a.title} ({a.source})" for a in articles[:10]
    )
    market_list = "\n".join(
        f"- [{m.slug}] {m.question} (YES: {m.outcome_prices[0]:.2f}, NO: {m.outcome_prices[1]:.2f})"
        for m in markets[:20]
        if len(m.outcome_prices) >= 2
    )

    prompt = (
        "You are a news-to-prediction-market matcher. Your ONLY job is reading "
        "comprehension — determining if a headline definitively resolves a "
        "prediction market question.\n\n"
        f"HEADLINES:\n{headlines}\n\n"
        f"OPEN MARKETS:\n{market_list}\n\n"
        "For each headline that CLEARLY and DEFINITIVELY resolves a market "
        "question, output a JSON line:\n"
        '{"slug": "market-slug", "side": "YES or NO", "confidence": 0.0-1.0, '
        '"reason": "brief explanation"}\n\n'
        "Rules:\n"
        "- Only match if the headline DIRECTLY answers the market question\n"
        "- confidence must be >= 0.85 to include\n"
        "- Do NOT predict or speculate — only match confirmed facts\n"
        "- If no headlines resolve any markets, output nothing\n"
        "- Output ONLY JSON lines, no other text"
    )

    client = groq.Groq()
    text = _call_groq(client, prompt)

    signals = []
    market_by_slug = {m.slug: m for m in markets}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            slug = data.get("slug", "")
            market = market_by_slug.get(slug)
            if not market:
                continue
            confidence = float(data.get("confidence", 0))
            if confidence < ARBITRAGE_CONFIDENCE_THRESHOLD:
                continue
            signals.append(
                Signal(
                    market=market,
                    strategy="arbitrage",
                    side=data.get("side", "YES"),
                    confidence=confidence,
                    reason=data.get("reason", ""),
                    bucket="news_experimental",
                    expected_value=-0.05,
                )
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    return signals
