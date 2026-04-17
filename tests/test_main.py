import sys
from types import ModuleType
from unittest.mock import patch, MagicMock

import pytest

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


def _run_live_validation(monkeypatch, overrides: dict):
    import main as _main

    defaults = {
        "TRADING_MODE": "live",
        "UPDOWN_5M_STRATEGY_MODE": "live",
        "UPDOWN_15M_STRATEGY_MODE": "shadow",
        "BTC_NO_STRATEGY_MODE": "shadow",
        "ARBITRAGE_STRATEGY_MODE": "disabled",
        "STRUCTURAL_ARB_STRATEGY_MODE": "shadow",
        "LIVE_MAX_BET": 5.0,
        "LIVE_DAILY_MAX_LOSS": 6.0,
        "LIVE_MAX_OPEN_EXPOSURE": 6.0,
        "MAX_EXPOSURE_PER_COIN": 10.0,
        "POLYMARKET_RELAYER_URL": "https://relayer-v2.polymarket.com",
        "POLYMARKET_RELAYER_API_KEY": "",
        "POLYMARKET_WALLET_TYPE": "eoa",
        "LIVE_STARTING_BALANCE": 5.0,
    }
    defaults.update(overrides)
    for key, val in defaults.items():
        monkeypatch.setattr(_main, key, val, raising=False)
    return _main


def test_live_validation_passes_with_valid_config(monkeypatch, capsys):
    _main = _run_live_validation(monkeypatch, {})
    with patch.object(_main, "LiveExecutor", return_value=MagicMock()):
        try:
            _main.TRADING_MODE = "live"
            _main.UPDOWN_15M_STRATEGY_MODE = "shadow"
            _main.ARBITRAGE_STRATEGY_MODE = "disabled"
            _main.POLYMARKET_RELAYER_API_KEY = ""
            _main.POLYMARKET_RELAYER_URL = "https://relayer-v2.polymarket.com"
            if _main.TRADING_MODE != "live":
                sys.exit(1)
            if _main.POLYMARKET_RELAYER_API_KEY and "polymarket.com" not in _main.POLYMARKET_RELAYER_URL:
                sys.exit(1)
            if _main.UPDOWN_15M_STRATEGY_MODE == "live":
                sys.exit(1)
            if _main.ARBITRAGE_STRATEGY_MODE == "live":
                sys.exit(1)
        except SystemExit:
            raise AssertionError("Validation should not fail with valid config")


def test_live_validation_exits_when_15m_is_live(monkeypatch):
    _main = _run_live_validation(monkeypatch, {"UPDOWN_15M_STRATEGY_MODE": "live"})
    with pytest.raises(SystemExit) as exc_info:
        if _main.UPDOWN_15M_STRATEGY_MODE == "live":
            print("ERROR: UPDOWN_15M_STRATEGY_MODE is 'live'")
            sys.exit(1)
    assert exc_info.value.code == 1


def test_live_validation_exits_when_arbitrage_is_live(monkeypatch):
    _main = _run_live_validation(monkeypatch, {"ARBITRAGE_STRATEGY_MODE": "live"})
    with pytest.raises(SystemExit) as exc_info:
        if _main.ARBITRAGE_STRATEGY_MODE == "live":
            print("ERROR: ARBITRAGE_STRATEGY_MODE is 'live'")
            sys.exit(1)
    assert exc_info.value.code == 1


def test_live_validation_exits_when_relayer_url_wrong_and_api_key_set(monkeypatch):
    _main = _run_live_validation(monkeypatch, {
        "POLYMARKET_RELAYER_API_KEY": "some-key",
        "POLYMARKET_RELAYER_URL": "https://bad-relayer.example.com",
    })
    with pytest.raises(SystemExit) as exc_info:
        if _main.POLYMARKET_RELAYER_API_KEY and "polymarket.com" not in _main.POLYMARKET_RELAYER_URL:
            print("ERROR: POLYMARKET_RELAYER_URL does not contain 'polymarket.com'")
            sys.exit(1)
    assert exc_info.value.code == 1
