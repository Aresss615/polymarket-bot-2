import sys
from types import ModuleType

from config import (
    LIVE_DAILY_MAX_LOSS,
    LIVE_MAX_OPEN_EXPOSURE,
    LIVE_MIN_BET,
    LIVE_STARTING_BALANCE,
    MAX_EXPOSURE_PER_COIN,
    SIMULATION_DAILY_MAX_LOSS,
    SIMULATION_MAX_OPEN_EXPOSURE,
)

dashboard_stub = ModuleType("dashboard")
dashboard_stub.run_dashboard = lambda engine: None
sys.modules.setdefault("dashboard", dashboard_stub)

from main import build_risk_config


def test_build_risk_config_uses_live_limits():
    config = build_risk_config("live")

    assert config.daily_max_loss == LIVE_DAILY_MAX_LOSS
    assert config.max_open_exposure == LIVE_MAX_OPEN_EXPOSURE
    assert config.max_exposure_per_coin == min(MAX_EXPOSURE_PER_COIN, LIVE_MAX_OPEN_EXPOSURE)


def test_build_risk_config_live_allows_one_min_bet_on_small_bankroll():
    config = build_risk_config("live")

    assert config.hard_position_cap_pct * LIVE_STARTING_BALANCE >= LIVE_MIN_BET
    assert config.max_open_exposure_pct * LIVE_STARTING_BALANCE >= LIVE_MIN_BET
    assert config.max_thesis_exposure_pct * LIVE_STARTING_BALANCE >= LIVE_MIN_BET
    assert config.max_cluster_exposure_pct * LIVE_STARTING_BALANCE >= LIVE_MIN_BET
    assert config.daily_realized_loss_limit_pct * LIVE_STARTING_BALANCE >= LIVE_MIN_BET


def test_build_risk_config_keeps_repo_defaults_for_non_live():
    live_config = build_risk_config("live")
    paper_config = build_risk_config("paper")

    assert paper_config.daily_max_loss != live_config.daily_max_loss
    assert paper_config.max_open_exposure != live_config.max_open_exposure


def test_build_risk_config_uses_relaxed_simulation_limits():
    config = build_risk_config("simulation")

    assert config.daily_max_loss == SIMULATION_DAILY_MAX_LOSS
    assert config.max_open_exposure == SIMULATION_MAX_OPEN_EXPOSURE
    assert config.hard_position_cap_pct == 1.0
    assert config.max_open_exposure_pct > 1.0
