@echo off
call .venv\Scripts\activate

if "%1"=="live" (
    set TRADING_MODE=live
    echo Starting in LIVE mode...
) else if "%1"=="sim" (
    set TRADING_MODE=simulation
    echo Starting in SIMULATION mode...
) else (
    set TRADING_MODE=paper
    echo Starting in PAPER mode...
)

python main.py
