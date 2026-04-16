from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import (
    POLYMARKET_MARKET_WS_URL,
    POLYMARKET_RTDS_WS_URL,
    POLYMARKET_USER_WS_URL,
)
from state_cache import MARKET_CACHE, REFERENCE_CACHE

try:  # pragma: no cover - import is exercised indirectly
    import websocket
    WEBSOCKET_IMPORT_ERROR = ""
except Exception:  # pragma: no cover - dependency may not be installed in some environments
    websocket = None
    WEBSOCKET_IMPORT_ERROR = "websocket-client import failed"


WEBSOCKET_CLIENT_AVAILABLE = websocket is not None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _normalize_book_price(value: Any) -> float | None:
    price = _safe_float(value)
    if price is None or price <= 0:
        return None
    return price


def _normalize_reference_symbol(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    elif raw.endswith("usdt"):
        raw = raw[:-4]
    return raw.upper()


def _parse_timestamp(value: Any) -> float:
    parsed = _safe_float(value)
    if parsed is not None:
        # Normalize ms timestamps to seconds.
        return parsed / 1000.0 if parsed > 10_000_000_000 else parsed
    return time.time()


@dataclass(frozen=True)
class MarketEvent:
    event_type: str
    token_id: str
    market_slug: str = ""
    bids: list[Any] = field(default_factory=list)
    asks: list[Any] = field(default_factory=list)
    best_bid: float | None = None
    best_ask: float | None = None
    tick_size: float | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ReferenceEvent:
    symbol: str
    price: float
    chainlink: bool = False
    source: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class UserOrderEvent:
    order_id: str
    status: str
    raw_status: str = ""
    fill_size: float = 0.0
    fill_shares: float = 0.0
    fees: float = 0.0
    remaining_size: float | None = None
    remaining_shares: float | None = None
    token_id: str = ""
    market_slug: str = ""
    terminal: bool = False
    timestamp: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderEventSnapshot:
    order_id: str
    status: str = ""
    raw_status: str = ""
    fill_size: float = 0.0
    fill_shares: float = 0.0
    fees: float = 0.0
    remaining_size: float | None = None
    remaining_shares: float | None = None
    token_id: str = ""
    market_slug: str = ""
    terminal: bool = False
    updated_at: datetime = field(default_factory=_utc_now)
    raw: dict[str, Any] = field(default_factory=dict)


class OrderEventStore:
    def __init__(self):
        self._events: dict[str, OrderEventSnapshot] = {}
        self._lock = threading.Lock()

    def apply(self, event: UserOrderEvent) -> OrderEventSnapshot:
        with self._lock:
            current = self._events.get(event.order_id)
            if current is None:
                current = OrderEventSnapshot(order_id=event.order_id)
            current.status = event.status or current.status
            current.raw_status = event.raw_status or event.status or current.raw_status
            current.fill_size = max(current.fill_size, event.fill_size)
            current.fill_shares = max(current.fill_shares, event.fill_shares)
            current.fees = max(current.fees, event.fees)
            current.remaining_size = event.remaining_size if event.remaining_size is not None else current.remaining_size
            current.remaining_shares = event.remaining_shares if event.remaining_shares is not None else current.remaining_shares
            current.token_id = event.token_id or current.token_id
            current.market_slug = event.market_slug or current.market_slug
            current.terminal = event.terminal or current.terminal
            current.updated_at = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
            current.raw = event.raw or current.raw
            self._events[event.order_id] = current
            return current

    def snapshot(self, order_id: str) -> OrderEventSnapshot | None:
        with self._lock:
            snapshot = self._events.get(order_id)
            if snapshot is None:
                return None
            return OrderEventSnapshot(**snapshot.__dict__)


class _WebSocketWorker:
    def __init__(self, *, url: str, on_message, subscribe_payload_factory=None):
        self.url = url
        self.on_message = on_message
        self.subscribe_payload_factory = subscribe_payload_factory
        self._thread: threading.Thread | None = None
        self._app = None
        self._stop = threading.Event()

    def start(self) -> None:
        if websocket is None or self._thread is not None:
            return

        def _run():
            while not self._stop.is_set():
                try:
                    def _on_open(ws):
                        payload = self._subscription_payloads()
                        for item in payload:
                            try:
                                ws.send(json.dumps(item))
                            except Exception:
                                continue
                        def _ping_loop():
                            while not self._stop.is_set() and self._app is ws:
                                time.sleep(5.0)
                                if self._stop.is_set() or self._app is not ws:
                                    break
                                try:
                                    ws.send("PING")
                                except Exception:
                                    break
                        threading.Thread(
                            target=_ping_loop,
                            daemon=True,
                            name=f"ping:{self.url}",
                        ).start()

                    self._app = websocket.WebSocketApp(
                        self.url,
                        on_open=_on_open,
                        on_message=lambda _ws, msg: self.on_message(msg),
                    )
                    self._app.run_forever()
                except Exception:
                    time.sleep(1.0)
                else:
                    time.sleep(1.0)

        self._thread = threading.Thread(target=_run, daemon=True, name=f"ws:{self.url}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._app is not None:
            try:
                self._app.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._app = None

    def resubscribe(self) -> None:
        if self._app is None:
            return
        for payload in self._subscription_payloads():
            try:
                self._app.send(json.dumps(payload))
            except Exception:
                continue

    def _subscription_payloads(self) -> list[dict[str, Any]]:
        if self.subscribe_payload_factory is None:
            return []
        payload = self.subscribe_payload_factory()
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return [payload] if isinstance(payload, dict) else []

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class RuntimeDataPlane:
    def __init__(self):
        self.market_cache = MARKET_CACHE
        self.reference_cache = REFERENCE_CACHE
        self.order_store = OrderEventStore()
        self._market_tokens: set[str] = set()
        self._reference_symbols: set[str] = set()
        self._workers: list[_WebSocketWorker] = []
        self._market_worker: _WebSocketWorker | None = None
        self._rtds_worker: _WebSocketWorker | None = None
        self._user_worker: _WebSocketWorker | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._market_worker = _WebSocketWorker(
            url=POLYMARKET_MARKET_WS_URL,
            on_message=self.apply_market_message,
            subscribe_payload_factory=self._market_subscriptions,
        )
        self._rtds_worker = _WebSocketWorker(
            url=POLYMARKET_RTDS_WS_URL,
            on_message=self.apply_rtds_message,
            subscribe_payload_factory=self._rtds_subscriptions,
        )
        self._user_worker = _WebSocketWorker(
            url=POLYMARKET_USER_WS_URL,
            on_message=self.apply_user_message,
        )
        self._workers = [self._market_worker, self._rtds_worker, self._user_worker]
        for worker in self._workers:
            worker.start()
        self._running = True

    def stop(self) -> None:
        for worker in self._workers:
            worker.stop()
        self._workers = []
        self._market_worker = None
        self._rtds_worker = None
        self._user_worker = None
        self._running = False

    def diagnostics(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "websocket_client_available": WEBSOCKET_CLIENT_AVAILABLE,
            "websocket_import_error": WEBSOCKET_IMPORT_ERROR,
            "workers": {
                "market": self._market_worker.is_running() if self._market_worker is not None else False,
                "rtds": self._rtds_worker.is_running() if self._rtds_worker is not None else False,
                "user": self._user_worker.is_running() if self._user_worker is not None else False,
            },
            "market_feed_healthy": self.market_cache.feed_healthy(3.0),
            "reference_feed_healthy": self.reference_cache.feed_healthy(3.0),
        }

    def reference_stream_available(self) -> bool:
        return bool(
            WEBSOCKET_CLIENT_AVAILABLE
            and self._running
            and self._rtds_worker is not None
            and self._rtds_worker.is_running()
        )

    def market_stream_available(self) -> bool:
        return bool(
            WEBSOCKET_CLIENT_AVAILABLE
            and self._running
            and self._market_worker is not None
            and self._market_worker.is_running()
        )

    def set_market_tokens(self, token_ids: set[str] | list[str]) -> None:
        self._market_tokens = {str(token_id) for token_id in token_ids if token_id}
        if self._market_worker is not None:
            self._market_worker.resubscribe()

    def set_reference_symbols(self, symbols: set[str] | list[str]) -> None:
        self._reference_symbols = {str(symbol).upper() for symbol in symbols if symbol}
        if self._rtds_worker is not None:
            self._rtds_worker.resubscribe()

    def apply_market_message(self, payload: str | dict[str, Any]) -> None:
        for message in self._decode_messages(payload):
            if not message:
                continue

            event_type = str(message.get("event_type") or message.get("event") or message.get("type") or "").lower()
            token_id = str(message.get("asset_id") or message.get("token_id") or message.get("tokenId") or "")
            market_slug = str(message.get("market_slug") or message.get("market") or "")
            timestamp = _parse_timestamp(message.get("timestamp") or message.get("ts"))
            tick_size = _safe_float(message.get("tick_size"))
            payload_obj = message.get("payload") if isinstance(message.get("payload"), dict) else {}

            if event_type in {"book", "orderbook", "snapshot"} and token_id:
                self.market_cache.update_from_book(
                    token_id,
                    _as_list(_first_present(message.get("bids"), payload_obj.get("bids"))),
                    _as_list(_first_present(message.get("asks"), payload_obj.get("asks"))),
                    market_slug=market_slug,
                    source=event_type,
                    timestamp=timestamp,
                    tick_size=tick_size,
                )
                continue

            if event_type == "price_change":
                price_changes = message.get("price_changes")
                if not isinstance(price_changes, list):
                    price_changes = payload_obj.get("price_changes")
                if isinstance(price_changes, list) and price_changes:
                    for change in price_changes:
                        if not isinstance(change, dict):
                            continue
                        change_token_id = str(
                            change.get("asset_id")
                            or change.get("token_id")
                            or change.get("tokenId")
                            or token_id
                        )
                        if not change_token_id:
                            continue
                        change_market_slug = str(change.get("market_slug") or market_slug)
                        change_tick_size = _safe_float(
                            _first_present(change.get("tick_size"), tick_size)
                        )
                        best_bid = _normalize_book_price(
                            _first_present(change.get("best_bid"), change.get("bid"))
                        )
                        best_ask = _normalize_book_price(
                            _first_present(change.get("best_ask"), change.get("ask"))
                        )
                        changed_price = _normalize_book_price(change.get("price"))
                        side = str(change.get("side") or "").lower()
                        if changed_price is not None:
                            if side in {"buy", "bid"} and best_bid is None:
                                best_bid = changed_price
                            elif side in {"sell", "ask"} and best_ask is None:
                                best_ask = changed_price
                        self.market_cache.update_best_bid_ask(
                            change_token_id,
                            best_bid=best_bid,
                            best_ask=best_ask,
                            market_slug=change_market_slug,
                            source=event_type,
                            timestamp=timestamp,
                            tick_size=change_tick_size,
                        )
                    continue

            if event_type in {"best_bid_ask", "price_change"} and token_id:
                best_bid = _normalize_book_price(
                    _first_present(
                        message.get("best_bid"),
                        message.get("bid"),
                        payload_obj.get("best_bid"),
                        payload_obj.get("bid"),
                    )
                )
                best_ask = _normalize_book_price(
                    _first_present(
                        message.get("best_ask"),
                        message.get("ask"),
                        payload_obj.get("best_ask"),
                        payload_obj.get("ask"),
                    )
                )
                self.market_cache.update_best_bid_ask(
                    token_id,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    market_slug=market_slug,
                    source=event_type,
                    timestamp=timestamp,
                    tick_size=tick_size,
                )
                continue

            if event_type == "tick_size_change" and token_id and tick_size is not None:
                self.market_cache.update_tick_size(
                    token_id,
                    tick_size=tick_size,
                    market_slug=market_slug,
                    source=event_type,
                    timestamp=timestamp,
                )
                continue

            if event_type == "market_resolved" and token_id:
                self.market_cache.mark_resolved(token_id, timestamp=timestamp)

    def apply_rtds_message(self, payload: str | dict[str, Any]) -> None:
        for message in self._decode_messages(payload):
            if not message:
                continue

            event_type = str(message.get("event_type") or message.get("type") or "").lower()
            topic = str(message.get("topic") or "").lower()
            payload_obj = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            raw_symbol = payload_obj.get("symbol") or message.get("symbol") or message.get("asset") or ""
            symbol = _normalize_reference_symbol(raw_symbol)
            if not symbol:
                continue
            is_chainlink = "chainlink" in topic or "chainlink" in event_type or "/" in str(raw_symbol)
            source = "rtds_chainlink" if is_chainlink else "rtds"
            snapshot_points = payload_obj.get("data")
            if isinstance(snapshot_points, list):
                for point in snapshot_points:
                    if not isinstance(point, dict):
                        continue
                    point_price = _safe_float(point.get("value") or point.get("price"))
                    if point_price is None:
                        continue
                    point_ts = _parse_timestamp(
                        point.get("timestamp")
                        or payload_obj.get("timestamp")
                        or message.get("timestamp")
                        or message.get("price_time")
                        or message.get("ts")
                    )
                    self.reference_cache.update(
                        symbol,
                        point_price,
                        source=source,
                        chainlink=is_chainlink,
                        timestamp=point_ts,
                    )
                continue

            timestamp = _parse_timestamp(
                payload_obj.get("timestamp")
                or message.get("timestamp")
                or message.get("price_time")
                or message.get("ts")
            )
            price = _safe_float(
                payload_obj.get("value")
                or payload_obj.get("price")
                or message.get("price")
                or message.get("value")
            )
            if price is None:
                continue

            self.reference_cache.update(symbol, price, source=source, chainlink=is_chainlink, timestamp=timestamp)

    def apply_user_message(self, payload: str | dict[str, Any]) -> None:
        for message in self._decode_messages(payload):
            if not message:
                continue

            order_id = str(message.get("order_id") or message.get("id") or "")
            if not order_id:
                continue
            raw_status = str(message.get("status") or message.get("event_type") or message.get("type") or "")
            status = raw_status.lower()
            terminal = status in {"filled", "confirmed", "cancelled", "canceled", "failed", "rejected", "expired"}
            event = UserOrderEvent(
                order_id=order_id,
                status=status,
                raw_status=raw_status,
                fill_size=_safe_float(message.get("fill_size") or message.get("matched_amount") or 0.0, 0.0) or 0.0,
                fill_shares=_safe_float(message.get("fill_shares") or message.get("size_matched") or 0.0, 0.0) or 0.0,
                fees=_safe_float(message.get("fees") or message.get("fee_amount") or 0.0, 0.0) or 0.0,
                remaining_size=_safe_float(message.get("remaining_size")),
                remaining_shares=_safe_float(message.get("remaining_shares")),
                token_id=str(message.get("asset_id") or message.get("token_id") or ""),
                market_slug=str(message.get("market_slug") or message.get("market") or ""),
                terminal=terminal,
                timestamp=_parse_timestamp(message.get("timestamp") or message.get("ts")),
                raw=message,
            )
            self.order_store.apply(event)

    @staticmethod
    def _decode_messages(payload: str | dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        try:
            decoded = json.loads(payload)
        except Exception:
            return []
        if isinstance(decoded, dict):
            return [decoded]
        if isinstance(decoded, list):
            return [item for item in decoded if isinstance(item, dict)]
        return []

    def _market_subscriptions(self) -> dict[str, Any] | None:
        if not self._market_tokens:
            return None
        return {
            "assets_ids": sorted(self._market_tokens),
            "type": "market",
            "custom_feature_enabled": True,
        }

    def _rtds_subscriptions(self) -> dict[str, Any] | None:
        if not self._reference_symbols:
            return None
        chainlink_supported = {"BTC", "ETH", "SOL", "XRP"}
        subscriptions: list[dict[str, Any]] = [
            {
                "topic": "crypto_prices",
                "type": "update",
            }
        ]
        for symbol in sorted(self._reference_symbols.intersection(chainlink_supported)):
            subscriptions.append(
                {
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": json.dumps({"symbol": f"{symbol.lower()}/usd"}),
                }
            )
        return {
            "action": "subscribe",
            "subscriptions": subscriptions,
        }


RUNTIME_DATA_PLANE = RuntimeDataPlane()
