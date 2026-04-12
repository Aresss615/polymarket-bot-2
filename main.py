import signal
import sys
import threading

from config import TRADING_MODE, MAX_BET, DAILY_MAX_LOSS, RiskConfig, LIVE_MAX_BET, LIVE_MIN_BET
from engine import Engine
from dashboard import run_dashboard
from logger import init_csv
from order_executor import PaperExecutor, SimulationExecutor, LiveExecutor
from risk_manager import RiskManager


def main():
    init_csv()

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
        print(f"Max bet: ${LIVE_MAX_BET}, Daily loss limit: $2.00")
        print("Type 'yes' to confirm:")
        if input().strip().lower() != "yes":
            print("Aborted.")
            return
        executor = LiveExecutor(private_key=pk, funder=funder)
        # Override bet sizing for $5 live test
        import config as _cfg
        _cfg.MAX_BET = LIVE_MAX_BET
        _cfg.MIN_BET = LIVE_MIN_BET
    else:
        executor = PaperExecutor()
        print("Starting in PAPER mode (instant fills, no fees)")

    if TRADING_MODE == "live":
        risk_config = RiskConfig(
            daily_max_loss=2.0,
            max_open_exposure=3.0,
            max_consecutive_losses=3,
            max_exposure_per_coin=2.0,
        )
        risk_manager = RiskManager(risk_config)
    else:
        risk_manager = RiskManager()
    engine = Engine(executor=executor, risk_manager=risk_manager)

    def shutdown(sig, frame):
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
