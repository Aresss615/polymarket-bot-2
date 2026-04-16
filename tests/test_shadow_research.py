from shadow_research import (
    high_probability_opportunity,
    relative_value_opportunity,
    wallet_flow_opportunity,
)


def test_wallet_flow_opportunity_is_shadow_only():
    opportunity = wallet_flow_opportunity(
        coin="BTC",
        meta_order_size=1250.0,
        lead_score=0.82,
        wallet_cluster="wallet-alpha",
    )

    assert opportunity.module_name == "wallet_flow"
    assert opportunity.can_emit_live_orders is False
    assert opportunity.production_candidate is False
    assert opportunity.strategy_mode == "shadow"


def test_relative_value_and_high_probability_stay_non_live():
    relval = relative_value_opportunity(
        spread_name="BTC-SOL",
        residual_edge=0.03,
        partial_fill_asymmetry=0.01,
        stressed_ev=0.004,
    )
    high_prob = high_probability_opportunity(
        coin="SOL",
        contract_price=0.86,
        maker_ev=0.006,
        taker_ev=-0.002,
    )

    assert relval.module_name == "relative_value"
    assert relval.can_emit_live_orders is False
    assert high_prob.module_name == "high_probability"
    assert high_prob.can_emit_live_orders is False
