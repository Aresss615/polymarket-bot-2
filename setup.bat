@echo off
echo Setting up Polymarket Bot...

where py >nul 2>nul
if %ERRORLEVEL%==0 (
	py -m venv .venv
) else (
	python -m venv .venv
)

if not exist .venv\Scripts\python.exe (
	echo Failed to create virtual environment.
	exit /b 1
)

.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install requests groq feedparser rich python-dotenv py-clob-client web3 pytest

if %ERRORLEVEL% neq 0 (
	echo Dependency installation failed.
	exit /b 1
)

echo.
echo Setup complete. Copy .env.example to .env and fill in your keys.
echo Run: run.bat
