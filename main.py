import signal
import sys
import threading

from engine import Engine
from dashboard import run_dashboard
from logger import init_csv


def main():
    init_csv()
    engine = Engine()

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
