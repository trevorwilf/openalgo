@echo off
REM ============================================================
REM run_bowaka_prefilter.bat
REM
REM Reads Alpaca credentials from OpenAlgo's .env file and runs
REM the Bowaka prefilter. Invoked by the BowakaPrefilter
REM scheduled task at 2:00 AM Mountain Time on weekdays (well
REM before the 09:30 ET NYSE open). On failure the task retries
REM every 15 minutes for up to 16 attempts = 4-hour recovery
REM window — see strategies/scripts/BowakaPrefilter.xml.
REM
REM Expected .env keys (priority order, first match wins):
REM     ALPACA_API_KEY_ID      / ALPACA_API_SECRET_KEY
REM     ALPACA_API_KEY         / ALPACA_API_SECRET
REM     BROKER_API_KEY         / BROKER_API_SECRET
REM
REM If your OpenAlgo install uses BROKER_API_KEY for a non-Alpaca
REM broker, add an explicit ALPACA_API_KEY / ALPACA_API_SECRET
REM pair to your .env to disambiguate.
REM ============================================================

setlocal enabledelayedexpansion

REM === Paths (edit these if you move things) ===
set "ENV_FILE=E:\stocktradingsoftware\openalgo\.env"
set "BOWAKA_DIR=E:\stocktradingsoftware\openalgo\strategies\scripts"
REM Project-local venv where alpaca-py + pandas + pandas_market_calendars
REM are already installed. The system Python at C:\Python312 doesn't
REM carry the SDK; using ``uv run`` here is also fine but adds startup
REM latency to every cron tick.
set "PYTHON_EXE=E:\stocktradingsoftware\openalgo\.venv\Scripts\python.exe"

REM === Sanity checks ===
if not exist "%ENV_FILE%" (
    echo ERROR: .env not found at %ENV_FILE% 1>&2
    exit /b 14
)
if not exist "%BOWAKA_DIR%\bowaka_prefilter.py" (
    echo ERROR: bowaka_prefilter.py not found in %BOWAKA_DIR% 1>&2
    exit /b 11
)
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found at %PYTHON_EXE% 1>&2
    echo Run "uv sync" from %BOWAKA_DIR%\..\.. to create the venv. 1>&2
    exit /b 10
)

REM === Parse .env ===
REM Handles: comment lines (#...), spaces around =, single/double-quoted
REM values, blank lines.
set "ALPACA_API_KEY_ID="
set "ALPACA_API_SECRET_KEY="

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    set "_key=%%A"
    set "_val=%%B"

    REM Strip all spaces from key (keys can't legally contain spaces)
    set "_key=!_key: =!"

    REM Strip leading whitespace from value
    if defined _val (
        for /f "tokens=* delims= " %%V in ("!_val!") do set "_val=%%V"
    )

    REM Strip surrounding double quotes
    if defined _val (
        if "!_val:~0,1!"=="""" if "!_val:~-1!"=="""" set "_val=!_val:~1,-1!"
    )

    REM Strip surrounding single quotes
    if defined _val (
        if "!_val:~0,1!"=="'" if "!_val:~-1!"=="'" set "_val=!_val:~1,-1!"
    )

    REM === Match against keys we care about, with priority ===
    REM Highest priority: explicit ALPACA_API_KEY_ID — always wins.
    REM Lower priority: ALPACA_API_KEY, then BROKER_API_KEY, only if
    REM nothing higher has set the value yet.
    if /i "!_key!"=="ALPACA_API_KEY_ID"      set "ALPACA_API_KEY_ID=!_val!"
    if /i "!_key!"=="ALPACA_API_KEY"         if not defined ALPACA_API_KEY_ID set "ALPACA_API_KEY_ID=!_val!"
    if /i "!_key!"=="BROKER_API_KEY"         if not defined ALPACA_API_KEY_ID set "ALPACA_API_KEY_ID=!_val!"

    if /i "!_key!"=="ALPACA_API_SECRET_KEY"  set "ALPACA_API_SECRET_KEY=!_val!"
    if /i "!_key!"=="ALPACA_API_SECRET"      if not defined ALPACA_API_SECRET_KEY set "ALPACA_API_SECRET_KEY=!_val!"
    if /i "!_key!"=="BROKER_API_SECRET"      if not defined ALPACA_API_SECRET_KEY set "ALPACA_API_SECRET_KEY=!_val!"
)

REM === Validate ===
if "%ALPACA_API_KEY_ID%"=="" (
    echo ERROR: No Alpaca API key found in %ENV_FILE% 1>&2
    echo Looked for: ALPACA_API_KEY_ID, ALPACA_API_KEY, BROKER_API_KEY 1>&2
    exit /b 12
)
if "%ALPACA_API_SECRET_KEY%"=="" (
    echo ERROR: No Alpaca API secret found in %ENV_FILE% 1>&2
    echo Looked for: ALPACA_API_SECRET_KEY, ALPACA_API_SECRET, BROKER_API_SECRET 1>&2
    exit /b 13
)

REM === Export to environment for the python child ===
REM ``setlocal`` already scoped the parsed values; child processes
REM inherit the current environment, so a fresh ``set`` here is enough.
REM Without this step the parsed values would die at end-of-script and
REM bowaka_prefilter.py would still see "ALPACA_API_KEY_ID and
REM ALPACA_API_SECRET_KEY must be set in env".
set "ALPACA_API_KEY_ID=%ALPACA_API_KEY_ID%"
set "ALPACA_API_SECRET_KEY=%ALPACA_API_SECRET_KEY%"

REM Mask key for logging — show first 4 chars only
set "_keymask=%ALPACA_API_KEY_ID:~0,4%..."
echo Loaded Alpaca credentials from .env (key starts with %_keymask%)

REM === Run ===
REM Force UTF-8 on stdout so log messages with non-ASCII characters
REM (em-dashes, arrows, currency symbols) flow through cmd's cp1252
REM console without raising UnicodeEncodeError mid-run.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%BOWAKA_DIR%"
"%PYTHON_EXE%" bowaka_prefilter.py --config bowaka_prefilter.yaml
exit /b %ERRORLEVEL%
