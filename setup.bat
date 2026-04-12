@echo off
echo Setting up Polymarket Bot...
python -m venv .venv
call .venv\Scripts\activate
pip install -e ".[dev]"
echo.
echo Setup complete. Copy .env.example to .env and fill in your keys.
echo Run: run.bat
