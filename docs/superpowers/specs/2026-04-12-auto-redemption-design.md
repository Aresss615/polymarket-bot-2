# Auto-Redemption of Winning Positions

**Date:** 2026-04-12  
**Status:** Approved

## Problem

Winning positions on Polymarket require the user to manually visit the website to claim payouts. The bot should do this automatically after detecting a win.

## Approach

Use existing `eth-account` and `eth-abi` deps (already installed via py-clob-client) plus `requests` to call `redeemPositions()` on the Polygon ConditionalTokens contract. Zero new dependencies.

## Contract Details

- **CTF Exchange (Polygon):** `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- **USDC.e (Polygon):** `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
- **Function:** `redeemPositions(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] indexSets)`
- **indexSets:** `[1]` for YES (outcome 0), `[2]` for NO (outcome 1)

## Changes

### `config.py` — Trade dataclass
Add two fields:
- `condition_id: str | None = None` — hex condition ID from Market, needed for on-chain call
- `redeemed: bool = False` — True after successful redemption tx

### `order_executor.py` — LiveExecutor
Add `redeem_position(condition_id: str, side: str) -> bool` method:
1. Encode calldata via `eth_abi.encode`
2. Fetch nonce + gas price from Polygon RPC via `requests`
3. Sign tx with `eth-account` using `POLYMARKET_PRIVATE_KEY`
4. Submit via `eth_sendRawTransaction`
5. Return True on success, False on failure (failures are logged, not raised)

### `engine.py`
1. Pass `condition_id=signal.market.condition_id` when constructing Trade objects
2. After marking a trade `won` in `settle_trades()`, call `self.executor.redeem_position(trade.condition_id, trade.side)` and set `trade.redeemed = True` on success

### `config.py` — env
Add `POLYGON_RPC_URL` (default: `https://polygon-rpc.com`)

### `.env.example`
Document `POLYGON_RPC_URL` as optional with default.

## Error Handling

- Redemption failures log to activity log but do not alter trade settlement status
- `trade.redeemed = False` on failure — field is available for future retry logic
- Paper/Simulation executors: `redeem_position()` is a no-op returning True

## Out of Scope

- Retry loop for failed redemptions
- Batch redemption
