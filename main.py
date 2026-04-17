import signal
import sys
import threading
from pathlib import Path

from config import (
    ARBITRAGE_STRATEGY_MODE,
    BTC_NO_STRATEGY_MODE,
    EVENTS_JSONL,
    LIVE_DAILY_MAX_LOSS,
    LIVE_MAX_BET,
    LIVE_MAX_OPEN_EXPOSURE,
    LIVE_MIN_BET,
    LIVE_STARTING_BALANCE,
    MAX_EXPOSURE_PER_COIN,
    POLYMARKET_RELAYER_API_KEY,
    POLYMARKET_RELAYER_URL,
    POLYMARKET_WALLET_TYPE,
    RiskConfig,
    SIMULATION_DAILY_MAX_LOSS,
    SIMULATION_GLOBAL_COOLDOWN_MINUTES,
    SIMULATION_GLOBAL_LOSS_STREAK,
    SIMULATION_MAX_CONSECUTIVE_LOSSES,
    SIMULATION_MAX_DRAWDOWN_PCT,
    SIMULATION_MAX_EXPOSURE_PER_COIN,
    SIMULATION_MAX_OPEN_EXPOSURE,
    SIMULATION_MAX_OPEN_EXPOSURE_PCT,
    SIMULATION_MAX_POSITIONS_PER_COIN,
    SIMULATION_MAX_POSITIONS_PER_THESIS,
    SIMULATION_MAX_THESIS_EXPOSURE_PCT,
    SIMULATION_PER_COIN_COOLDOWN_MINUTES,
    SIMULATION_PER_COIN_LOSS_STREAK,
    SIMULATION_DAILY_REALIZED_LOSS_LIMIT_PCT,
    STRUCTURAL_ARB_STRATEGY_MODE,
    TRADES_JSONL,
    TRADING_MODE,
    UPDOWN_5M_STRATEGY_MODE,
    UPDOWN_15M_STRATEGY_MODE,
)
from engine import Engine
from dashboard import run_dashboard
from logger import init_csv, init_open_orders_csv
from monitor_server import start_monitor_server
from order_executor import PaperExecutor, SimulationExecutor, LiveExecutor
from risk_manager import RiskManager


def _validate_live_config():
    if POLYMARKET_RELAYER_API_KEY and "polymarket.com" not in POLYMARKET_RELAYER_URL:
        print(f"ERROR: POLYMARKET_RELAYER_URL '{POLYMARKET_RELAYER_URL}' does not contain 'polymarket.com'")
        sys.exit(1)
    if UPDOWN_15M_STRATEGY_MODE == "live":
        print("ERROR: UPDOWN_15M_STRATEGY_MODE is 'live' — 15m strategy must not be promoted to live")
        sys.exit(1)
    if ARBITRAGE_STRATEGY_MODE == "live":
        print("ERROR: ARBITRAGE_STRATEGY_MODE is 'live' — arbitrage strategy must not be promoted to live")
        sys.exit(1)


def build_risk_config(mode: str) -> RiskConfig:
    if mode == "live":
        live_defaults = RiskConfig()
        # Keep live percentage limits large enough to permit at least one
        # minimum-sized order on small bankrolls.
        live_floor_pct = min(1.0, LIVE_MIN_BET / max(LIVE_STARTING_BALANCE, LIVE_MIN_BET))
        return RiskConfig(
            daily_max_loss=LIVE_DAILY_MAX_LOSS,
            max_open_exposure=LIVE_MAX_OPEN_EXPOSURE,
            max_exposure_per_coin=min(MAX_EXPOSURE_PER_COIN, LIVE_MAX_OPEN_EXPOSURE),
            target_position_pct=max(live_defaults.target_position_pct, live_floor_pct),
            hard_position_cap_pct=max(live_defaults.hard_position_cap_pct, live_floor_pct),
            max_open_exposure_pct=max(live_defaults.max_open_exposure_pct, live_floor_pct),
            daily_realized_loss_limit_pct=max(
                live_defaults.daily_realized_loss_limit_pct,
                live_floor_pct,
            ),
            max_thesis_exposure_pct=max(live_defaults.max_thesis_exposure_pct, live_floor_pct),
            max_cluster_exposure_pct=max(live_defaults.max_cluster_exposure_pct, live_floor_pct),
        )
    if mode == "simulation":
        return RiskConfig(
            daily_max_loss=SIMULATION_DAILY_MAX_LOSS,
            max_open_exposure=SIMULATION_MAX_OPEN_EXPOSURE,
            max_consecutive_losses=SIMULATION_MAX_CONSECUTIVE_LOSSES,
            max_exposure_per_coin=SIMULATION_MAX_EXPOSURE_PER_COIN,
            max_drawdown_pct=SIMULATION_MAX_DRAWDOWN_PCT,
            hard_position_cap_pct=1.0,
            max_open_exposure_pct=SIMULATION_MAX_OPEN_EXPOSURE_PCT,
            daily_realized_loss_limit_pct=SIMULATION_DAILY_REALIZED_LOSS_LIMIT_PCT,
            per_coin_loss_streak=SIMULATION_PER_COIN_LOSS_STREAK,
            per_coin_cooldown_minutes=SIMULATION_PER_COIN_COOLDOWN_MINUTES,
            global_loss_streak=SIMULATION_GLOBAL_LOSS_STREAK,
            global_cooldown_minutes=SIMULATION_GLOBAL_COOLDOWN_MINUTES,
            max_positions_per_coin=SIMULATION_MAX_POSITIONS_PER_COIN,
            max_positions_per_thesis=SIMULATION_MAX_POSITIONS_PER_THESIS,
            max_thesis_exposure_pct=SIMULATION_MAX_THESIS_EXPOSURE_PCT,
        )
    return RiskConfig()


def main():
    init_csv()
    init_open_orders_csv()
    for jsonl_path in (TRADES_JSONL, EVENTS_JSONL):
        Path(jsonl_path).touch(exist_ok=True)

    # Select executor based on TRADING_MODE env var
    if TRADING_MODE == "simulation":
        executor = SimulationExecutor()
        print("Starting in SIMULATION mode (realistic fills with fees/slippage)")
    elif TRADING_MODE == "live":
        import os as _os
        pk = _os.getenv("POLYMARKET_PRIVATE_KEY")
        if not pk:
            print("ERROR: POLYMARKET_PRIVATE_KEY not set in .env")
            return
        funder = _os.getenv("POLYMARKET_FUNDER") or None
        print("\n*** LIVE TRADING MODE ***")
        print(f"This will use real money on Polymarket.")
        print(f"Max bet: ${LIVE_MAX_BET}, Daily loss limit: ${LIVE_DAILY_MAX_LOSS:.2f}")
        print("Type 'yes' to confirm:")
        if input().strip().lower() != "yes":
            print("Aborted.")
            return
        print(f"  5m={UPDOWN_5M_STRATEGY_MODE}  15m={UPDOWN_15M_STRATEGY_MODE}"
              f"  btc_no={BTC_NO_STRATEGY_MODE}  arbitrage={ARBITRAGE_STRATEGY_MODE}"
              f"  structural_arb={STRUCTURAL_ARB_STRATEGY_MODE}")
        print(f"  max_bet=${LIVE_MAX_BET}  daily_loss_limit=${LIVE_DAILY_MAX_LOSS:.2f}"
              f"  max_open_exposure=${LIVE_MAX_OPEN_EXPOSURE}"
              f"  max_exposure_per_coin=${min(MAX_EXPOSURE_PER_COIN, LIVE_MAX_OPEN_EXPOSURE)}")
        print(f"  relayer_url={POLYMARKET_RELAYER_URL}  wallet_type={POLYMARKET_WALLET_TYPE}"
              f"  live_balance=${LIVE_STARTING_BALANCE}")
        _validate_live_config()
        executor = LiveExecutor(private_key=pk, funder=funder)
        # Override bet sizing for $5 live test
        import config as _cfg
        _cfg.MAX_BET = LIVE_MAX_BET
        _cfg.MIN_BET = LIVE_MIN_BET
    else:
        executor = PaperExecutor()
        print("Starting in PAPER mode (instant fills, no fees)")

    # Live mode uses its tighter bankroll limits; paper/sim keep repo defaults.
    risk_manager = RiskManager(build_risk_config(TRADING_MODE))
    engine = Engine(executor=executor, risk_manager=risk_manager)
    engine.start_runtime_services()
    monitor_server = None
    try:
        monitor_server = start_monitor_server(engine)
        print(f"Web monitor available at {monitor_server.url}")
    except OSError as exc:
        print(f"Web monitor unavailable: {exc}")

    def shutdown(sig, frame):
        if monitor_server is not None:
            monitor_server.stop()
        engine.stop()
        print("\nShutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    # Start engine loop in background thread
    engine.running = True
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    # Run dashboard on main thread
    run_dashboard(engine)


if __name__ == "__main__":
    main()
