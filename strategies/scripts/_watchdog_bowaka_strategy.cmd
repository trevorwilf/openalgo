@echo off
REM ============================================================
REM _watchdog_bowaka_strategy.cmd
REM
REM Wraps the strategy in a restart loop so an unexpected crash
REM (network blip, transient broker error, etc.) doesn't leave
REM the user without coverage during the session.
REM
REM Exit codes that DO NOT trigger a restart:
REM   0  = clean shutdown (SIGINT / SIGTERM-equivalent)
REM   5  = handshake mismatch (config drift; needs operator fix)
REM   99 = L3 hard-kill flag dropped (operator intent)
REM
REM Any other exit code (including negative codes from a forced
REM kill) = wait 30s, retry. Caps at 10 restarts per launch -- past
REM that, give up so a config-broken script doesn't infinite-loop.
REM
REM stdout/stderr are inherited from the Start-Process redirect
REM -- running entries still go to logs\bowaka_strategy.{out,err}.log
REM and the strategy's own logger writes to
REM strategies\scripts\logs\bowaka_strategy.log.
REM ============================================================

setlocal enabledelayedexpansion

set "ROOT=E:\stocktradingsoftware\openalgo"
set "BOWAKA_DIR=%ROOT%\strategies\scripts"
set "PY=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [watchdog] ERROR: python not found at %PY% 1>&2
    exit /b 10
)
if not exist "%BOWAKA_DIR%\bowaka_strategy.py" (
    echo [watchdog] ERROR: bowaka_strategy.py not found 1>&2
    exit /b 11
)

REM ---- Required env (operator should preset OPENALGO_API_KEY).
if "%OPENALGO_API_KEY%"=="" (
    echo [watchdog] ERROR: OPENALGO_API_KEY must be set 1>&2
    exit /b 12
)
if "%HOST_SERVER%"==""               set "HOST_SERVER=http://127.0.0.1:5000"
if "%OPENALGO_STRATEGY_EXCHANGE%"=="" set "OPENALGO_STRATEGY_EXCHANGE=CRYPTO"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%BOWAKA_DIR%"

REM Quote both numeric vars so trailing whitespace can't corrupt
REM the GEQ comparison further down.
set "RETRIES=0"
set "MAX_RETRIES=10"

:loop
echo [watchdog %DATE% %TIME%] launching bowaka_strategy retry=!RETRIES!
"%PY%" bowaka_strategy.py --config bowaka_strategy.yaml
set "EC=!ERRORLEVEL!"
echo [watchdog %DATE% %TIME%] bowaka exited code=!EC!

REM Exit-code dispatch via labels -- avoids putting cmd-special
REM characters inside ``if (...)`` blocks (the previous `( %MAX_RETRIES% ) reached;`
REM pattern triggered ``reached was unexpected at this time`` because
REM cmd's parser closed the if-block on the bare `)` mid-echo).
if "!EC!"=="0"  goto :end
if "!EC!"=="5"  goto :end
if "!EC!"=="99" goto :end

set /a RETRIES=!RETRIES! + 1
if !RETRIES! GEQ !MAX_RETRIES! goto :max_retries

echo [watchdog] restart in 30s
REM timeout /t with /nobreak doesn't accept Ctrl-C; use ping as a sleep.
ping -n 31 127.0.0.1 > nul
goto :loop

:max_retries
echo [watchdog] ERROR: max restart count reached, giving up 1>&2
exit /b 13

:end
echo [watchdog %DATE% %TIME%] watchdog exiting cleanly final-code=!EC!
exit /b !EC!
