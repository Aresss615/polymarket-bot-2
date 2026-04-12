import signal
import sys
import threading

from config import TRADING_MODE
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
        print("\n*** LIVE TRADING MODE ***")
        print("This will use real money on Polymarket.")
        print("Type 'yes' to confirm:")
        if input().strip().lower() != "yes":
            print("Aborted.")
            return
        executor = LiveExecutor()
    else:
        executor = PaperExecutor()
        print("Starting in PAPER mode (instant fills, no fees)")

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
