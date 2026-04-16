import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from config import LEDGER_JSONL, LedgerEvent, OrderResult, RunSession, Trade


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def append_event(event: LedgerEvent, path: Path = LEDGER_JSONL) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event), default=_json_default) + "\n")


def log_trade_opened(
    trade: Trade,
    order_result: OrderResult | None = None,
    executor_type: str = "paper",
    path: Path = LEDGER_JSONL,
) -> None:
    payload = {
        "trade": asdict(trade),
        "executor_type": executor_type,
    }
    if order_result is not None:
        payload["order_result"] = asdict(order_result)

    append_event(
        LedgerEvent(
            event_type="trade_opened",
            timestamp=datetime.now(timezone.utc),
            session_id=trade.session_id,
            trade_id=trade.trade_id,
            payload=payload,
        ),
        path=path,
    )


def log_order_update(
    trade: Trade,
    order_result: OrderResult,
    stage: str = "submitted",
    path: Path = LEDGER_JSONL,
) -> None:
    append_event(
        LedgerEvent(
            event_type="order_update",
            timestamp=datetime.now(timezone.utc),
            session_id=trade.session_id,
            trade_id=trade.trade_id,
            payload={
                "stage": stage,
                "trade": asdict(trade),
                "order_result": asdict(order_result),
            },
        ),
        path=path,
    )


def log_trade_settled(trade: Trade, path: Path = LEDGER_JSONL) -> None:
    append_event(
        LedgerEvent(
            event_type="trade_settled",
            timestamp=datetime.now(timezone.utc),
            session_id=trade.session_id,
            trade_id=trade.trade_id,
            payload={"trade": asdict(trade)},
        ),
        path=path,
    )


def log_risk_block(
    market_slug: str,
    reason: str,
    session_id: str = "",
    trade_id: str = "",
    path: Path = LEDGER_JSONL,
) -> None:
    append_event(
        LedgerEvent(
            event_type="risk_block",
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
            trade_id=trade_id,
            payload={"market_slug": market_slug, "reason": reason},
        ),
        path=path,
    )


def log_session_summary(
    session: RunSession,
    summary: dict,
    path: Path = LEDGER_JSONL,
) -> None:
    append_event(
        LedgerEvent(
            event_type="session_summary",
            timestamp=datetime.now(timezone.utc),
            session_id=session.session_id,
            payload={"session": asdict(session), "summary": summary},
        ),
        path=path,
    )


def load_events(path: Path = LEDGER_JSONL) -> list[dict]:
    if not path.exists():
        return []

    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def load_trade_state(path: Path = LEDGER_JSONL) -> dict[str, dict]:
    trade_state: dict[str, dict] = {}
    for event in load_events(path):
        trade_id = event.get("trade_id", "")
        payload = event.get("payload", {})
        trade_payload = payload.get("trade")
        if not trade_id and trade_payload:
            trade_id = trade_payload.get("trade_id", "")
        if not trade_id:
            continue

        if event.get("event_type") == "trade_opened" and trade_payload:
            trade_state[trade_id] = trade_payload
        elif event.get("event_type") == "order_update":
            current = trade_state.setdefault(trade_id, {})
            current.update(trade_payload or {})
            current["order_result"] = payload.get("order_result", {})
        elif event.get("event_type") == "trade_settled" and trade_payload:
            current = trade_state.setdefault(trade_id, {})
            current.update(trade_payload)

    return trade_state

