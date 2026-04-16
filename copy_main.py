import signal
import sys

from config import APP_CONFIG
from copy_trading import CopyTradingBot
from order_executor import PaperExecutor, SimulationExecutor


def main():
    target_wallet = APP_CONFIG.copy_trading.target_wallet
    if not target_wallet:
        print("ERROR: COPY_TARGET_WALLET is not set.")
        return

    executor = PaperExecutor() if APP_CONFIG.copy_trading.dry_run else SimulationExecutor()
    print(
        f"Starting copy-trading bot for {target_wallet} "
        f"({'dry-run' if APP_CONFIG.copy_trading.dry_run else 'simulation'})"
    )
    bot = CopyTradingBot(target_wallet=target_wallet, executor=executor)

    def shutdown(sig, frame):
        bot.stop()
        summary = bot.finalize_session()
        print(
            "\nCopy session summary: "
            f"settled={summary['overall']['settled_trades']}, "
            f"WR={summary['overall']['win_rate']:.1%}, "
            f"PnL=${summary['overall']['net_pnl']:+.2f}"
        )
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    bot.run()


if __name__ == "__main__":
    main()

