from __future__ import annotations

from dataclasses import dataclass, field

from config import STRATEGY_MODE_SHADOW


@dataclass(frozen=True)
class ShadowResearchOpportunity:
    module_name: str
    coin: str
    thesis: str
    strategy_mode: str = STRATEGY_MODE_SHADOW
    production_candidate: bool = False
    can_emit_live_orders: bool = False
    metrics: dict[str, float | str | None] = field(default_factory=dict)


def wallet_flow_opportunity(
    *,
    coin: str,
    meta_order_size: float | None = None,
    lead_score: float | None = None,
    wallet_cluster: str = "",
) -> ShadowResearchOpportunity:
    return ShadowResearchOpportunity(
        module_name="wallet_flow",
        coin=coin.upper(),
        thesis="cluster nearby same-direction wallet fills into a single meta-order",
        metrics={
            "meta_order_size": meta_order_size,
            "lead_score": lead_score,
            "wallet_cluster": wallet_cluster,
        },
    )


def relative_value_opportunity(
    *,
    spread_name: str,
    residual_edge: float | None = None,
    partial_fill_asymmetry: float | None = None,
    stressed_ev: float | None = None,
) -> ShadowResearchOpportunity:
    base_coin = spread_name.split("-", 1)[0].upper()
    return ShadowResearchOpportunity(
        module_name="relative_value",
        coin=base_coin,
        thesis=spread_name,
        metrics={
            "residual_edge": residual_edge,
            "partial_fill_asymmetry": partial_fill_asymmetry,
            "stressed_ev": stressed_ev,
        },
    )


def high_probability_opportunity(
    *,
    coin: str,
    contract_price: float,
    maker_ev: float | None = None,
    taker_ev: float | None = None,
) -> ShadowResearchOpportunity:
    return ShadowResearchOpportunity(
        module_name="high_probability",
        coin=coin.upper(),
        thesis="evaluate 0.80-0.90 contracts in shadow only",
        metrics={
            "contract_price": contract_price,
            "maker_ev": maker_ev,
            "taker_ev": taker_ev,
        },
    )


__all__ = [
    "ShadowResearchOpportunity",
    "wallet_flow_opportunity",
    "relative_value_opportunity",
    "high_probability_opportunity",
]
