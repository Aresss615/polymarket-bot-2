"""One-time setup: approve Polymarket CLOB exchange contracts to spend your USDC.

Run this once before live trading:
    python scripts/setup_allowances.py
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

pk = os.getenv("POLYMARKET_PRIVATE_KEY")
if not pk:
    print("ERROR: POLYMARKET_PRIVATE_KEY not set in .env")
    sys.exit(1)

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

funder = os.getenv("POLYMARKET_FUNDER") or None
client = ClobClient(
    "https://clob.polymarket.com",
    key=pk,
    chain_id=137,
    signature_type=2 if funder else 0,
    funder=funder,
)

print("Deriving API credentials...")
client.set_api_creds(client.create_or_derive_api_creds())

# Check current balance/allowance
print("\nChecking current balance and allowance...")
try:
    collateral = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    print(f"Collateral (USDC): {collateral}")
except Exception as e:
    print(f"Could not check collateral: {e}")

# Update allowance
print("\nUpdating allowances (sends on-chain transaction, needs MATIC for gas)...")
try:
    resp = client.update_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    print(f"Collateral allowance updated: {resp}")
except Exception as e:
    print(f"Error updating allowance: {e}")
    if "gas" in str(e).lower() or "insufficient" in str(e).lower():
        print("\nYou need MATIC/POL for gas fees on Polygon.")

print("\nDone. Restart the bot: TRADING_MODE=live python main.py")
