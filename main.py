import signal
import sys
import threading

from config import TRADING_MODE, DAILY_MAX_LOSS, LIVE_MAX_BET, LIVE_MIN_BET
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
        print(f"Max bet: ${LIVE_MAX_BET}, Daily loss limit: ${DAILY_MAX_LOSS:.2f}")
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

    # Use the standard risk profile for all modes; live keeps only bet-size overrides above.
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
