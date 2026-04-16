from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

import requests

from config import (
    APP_CONFIG,
    BookLevel,
    BookSnapshot,
    CLOB_API_URL,
    ExecutionQuote,
    Market,
    MarketDataConfig,
)


def _safe_float(value, default: float = 0.0) -> float:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class MarketMetadataCache:
    def __init__(self):
        self._by_slug: dict[str, Market] = {}
        self._lock = Lock()

    def upsert_many(self, markets: list[Market]) -> None:
        with self._lock:
            for market in markets:
                self._by_slug[market.slug] = market

    def get(self, slug: str) -> Market | None:
        with self._lock:
            return self._by_slug.get(slug)

    def resolve(self, slug: str, timeout: float | None = None) -> Market | None:
        cached = self.get(slug)
        if cached is not None:
            return cached

        resp = requests.get(
            f"{APP_CONFIG.market_data.gamma_api_url}/markets",
            params={"slug": slug},
            timeout=timeout or APP_CONFIG.market_data.metadata_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None

        row = data[0]
        market = Market(
            condition_id=row.get("conditionId", ""),
            question=row.get("question", ""),
            slug=row.get("slug", slug),
            outcomes=_parse_json_list(row.get("outcomes", ["Yes", "No"])),
            outcome_prices=[_safe_float(v) for v in _parse_json_list(row.get("outcomePrices", []))],
            token_ids=_parse_json_list(row.get("clobTokenIds", [])),
            end_date=_parse_end_date(row.get("endDate")),
            active=bool(row.get("active", True)),
        )
        self.upsert_many([market])
        return market


def _parse_json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        import json

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return []


def _parse_end_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _orderbook_depth_usd(levels: list[BookLevel], max_levels: int = 5) -> float:
    return sum(level.price * level.size for level in levels[:max_levels])


@dataclass
class _TokenMetadata:
    tick_size: float
    min_order_size: float


class ClobMarketDataClient:
    def __init__(self, clob_client=None, config: MarketDataConfig | None = None):
        self.config = config or APP_CONFIG.market_data
        self._client = clob_client
        self._metadata: dict[str, _TokenMetadata] = {}
        self._quotes: dict[str, ExecutionQuote] = {}
        self._active_token_ids: set[str] = set()
        self._lock = Lock()

    def subscribe_tokens(self, token_ids: list[str]) -> None:
        with self._lock:
            self._active_token_ids.update(token_id for token_id in token_ids if token_id)

    def active_token_ids(self) -> set[str]:
        with self._lock:
            return set(self._active_token_ids)

    def get_book_snapshot(self, token_id: str) -> BookSnapshot | None:
        if not token_id:
            return None

        summary = None
        if self._client is not None:
            try:
                summary = self._client.get_order_book(token_id)
            except Exception:
                summary = None

        if summary is None:
            try:
                resp = requests.get(
                    f"{CLOB_API_URL}/book",
                    params={"token_id": token_id},
                    timeout=self.config.quote_timeout_seconds,
                )
                resp.raise_for_status()
                summary = resp.json()
            except Exception:
                return None

        bids_raw = getattr(summary, "bids", None) or summary.get("bids", [])
        asks_raw = getattr(summary, "asks", None) or summary.get("asks", [])
        bids = [BookLevel(price=_safe_float(level.price if hasattr(level, "price") else level.get("price")), size=_safe_float(level.size if hasattr(level, "size") else level.get("size"))) for level in bids_raw]
        asks = [BookLevel(price=_safe_float(level.price if hasattr(level, "price") else level.get("price")), size=_safe_float(level.size if hasattr(level, "size") else level.get("size"))) for level in asks_raw]

        tick_size = _safe_float(getattr(summary, "tick_size", None) or summary.get("tick_size"), 0.01)
        min_order_size = _safe_float(
            getattr(summary, "min_order_size", None) or summary.get("min_order_size"),
            0.1,
        )
        best_bid = bids[0].price if bids else 0.0
        best_ask = asks[0].price if asks else 0.0
        depth = _orderbook_depth_usd(asks or bids)

        snapshot = BookSnapshot(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            bids=bids,
            asks=asks,
            tick_size=tick_size,
            min_order_size=min_order_size,
            depth_usd=depth,
            source="clob",
            fetched_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._metadata[token_id] = _TokenMetadata(tick_size=tick_size, min_order_size=min_order_size)
        return snapshot

    def get_execution_quote(self, token_id: str, side: str) -> ExecutionQuote | None:
        snapshot = self.get_book_snapshot(token_id)
        if snapshot is None:
            return None

        midpoint = (
            (snapshot.best_bid + snapshot.best_ask) / 2.0
            if snapshot.best_bid and snapshot.best_ask
            else snapshot.best_ask or snapshot.best_bid
        )
        quote = ExecutionQuote(
            token_id=token_id,
            side=side,
            best_bid=snapshot.best_bid,
            best_ask=snapshot.best_ask,
            tick_size=snapshot.tick_size,
            midpoint=midpoint,
            depth_usd=snapshot.depth_usd,
            fetched_at=snapshot.fetched_at,
        )
        with self._lock:
            self._quotes[token_id] = quote
        return quote

    def get_cached_quote(self, token_id: str) -> ExecutionQuote | None:
        with self._lock:
            return self._quotes.get(token_id)
