@echo off
REM ============================================================
REM _watchdog_openalgo.cmd
REM
REM Wraps `uv run app.py` in a restart loop. The bowaka strategy
REM cannot trade without OpenAlgo; for unattended operation we
REM auto-restart Flask if it dies for any reason (Python crash,
REM SQLite hiccup, port conflict, etc.).
REM
REM Caps at 10 restarts per launch. uv handles deps + venv.
REM
REM Logs flow to whichever stdout/stderr the parent redirected
REM into (typically logs\openalgo_dev.{out,err}.log).
REM ============================================================

setlocal enabledelayedexpansion

set "ROOT=E:\stocktradingsoftware\openalgo"

cd /d "%ROOT%"

REM Quote numeric vars so trailing whitespace can't corrupt the
REM GEQ comparison.
set "RETRIES=0"
set "MAX_RETRIES=10"

:loop
echo [watchdog %DATE% %TIME%] launching openalgo retry=!RETRIES!
uv run app.py
set "EC=!ERRORLEVEL!"
echo [watchdog %DATE% %TIME%] openalgo exited code=!EC!

REM 0 = normal SIGINT; treat any non-fatal exit as recoverable.
REM Operator can break out by killing the watchdog process directly.
if "!EC!"=="0" goto :end

REM Label-based dispatch on max-retries to avoid putting cmd-special
REM characters inside ``if (...)`` blocks. The previous
REM ``( %MAX_RETRIES% ) reached;`` pattern triggered cmd's parser to
REM close the if-block on a bare `)` mid-echo and emit
REM "<word> was unexpected at this time".
set /a RETRIES=!RETRIES! + 1
if !RETRIES! GEQ !MAX_RETRIES! goto :max_retries

echo [watchdog] restart in 30s, allow ports/sockets to clear
ping -n 31 127.0.0.1 > nul
goto :loop

:max_retries
echo [watchdog] ERROR: max restart count reached, giving up 1>&2
exit /b 13

:end
echo [watchdog %DATE% %TIME%] watchdog exiting cleanly final-code=!EC!
exit /b !EC!
