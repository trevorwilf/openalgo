@echo off
REM ============================================================
REM _watchdog_bowaka_v2_strategy.cmd
REM
REM v2 strategy watchdog. Restart-loops the v2 consumer process so
REM an unexpected crash (network blip, transient broker error)
REM doesn't leave the operator without coverage during the session.
REM
REM Exit codes that DO NOT trigger a restart:
REM   0  = clean shutdown
REM   5  = config error (e.g., live env without SIP feed)
REM   99 = L3 hard-kill flag dropped (operator intent)
REM
REM Caps at 10 restarts per launch. uv handles deps + venv.
REM ============================================================

setlocal enabledelayedexpansion

set "ROOT=E:\stocktradingsoftware\openalgo"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "CFG=%BOWAKA_V2_CFG%"
if "%CFG%"=="" set "CFG=%ROOT%\strategies\scripts\bowaka_v2_config.yaml"

if "%OPENALGO_API_KEY%"=="" (
    echo [watchdog] ERROR: OPENALGO_API_KEY must be set 1>&2
    exit /b 12
)
if "%HOST_SERVER%"=="" set "HOST_SERVER=http://127.0.0.1:5000"
if "%OPENALGO_STRATEGY_EXCHANGE%"=="" set "OPENALGO_STRATEGY_EXCHANGE=CRYPTO"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%ROOT%"

set "RETRIES=0"
set "MAX_RETRIES=10"

:loop
echo [watchdog %DATE% %TIME%] launching bowaka_v2_strategy retry=!RETRIES!
"%PY%" strategies\scripts\bowaka_v2_strategy.py --config "%CFG%"
set "EC=!ERRORLEVEL!"
echo [watchdog %DATE% %TIME%] bowaka_v2 exited code=!EC!

if "!EC!"=="0"  goto :end
if "!EC!"=="5"  goto :end
if "!EC!"=="99" goto :end

set /a RETRIES=!RETRIES! + 1
if !RETRIES! GEQ !MAX_RETRIES! goto :max_retries

echo [watchdog] restart in 30s
ping -n 31 127.0.0.1 > nul
goto :loop

:max_retries
echo [watchdog] ERROR: max restart count reached, giving up 1>&2
exit /b 13

:end
echo [watchdog %DATE% %TIME%] watchdog exiting cleanly final-code=!EC!
exit /b !EC!
