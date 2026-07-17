@echo off
REM Watchdog for the v2 intraday scanner. Restart-loops the scanner
REM if it dies during the session. Scanner exits 0 at scanner_end;
REM the watchdog respects that.

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
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%ROOT%"

set "RETRIES=0"
set "MAX_RETRIES=10"

:loop
echo [scanner-watchdog %DATE% %TIME%] launching bowaka_intraday_scanner retry=!RETRIES!
for /f %%t in ('powershell -nop -c "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "T0=%%t"
"%PY%" strategies\scripts\bowaka_intraday_scanner.py --config "%CFG%"
set "EC=!ERRORLEVEL!"
for /f %%t in ('powershell -nop -c "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "T1=%%t"
set /a RUNTIME=!T1! - !T0!
echo [scanner-watchdog %DATE% %TIME%] scanner exited code=!EC! runtime=!RUNTIME!s

if "!EC!"=="0"  goto :end
if "!EC!"=="5"  goto :end
if "!EC!"=="99" goto :end

REM A run that survived 600s+ was healthy - reset the crash budget.
if !RUNTIME! GEQ 600 set "RETRIES=0"

set /a RETRIES=!RETRIES! + 1
if !RETRIES! GEQ !MAX_RETRIES! goto :max_retries

echo [scanner-watchdog] restart in 30s
ping -n 31 127.0.0.1 > nul
goto :loop

:max_retries
echo [scanner-watchdog] ERROR: max restart count reached 1>&2
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
> "%ROOT%\logs\bowaka_watchdog_gaveup.flag" echo {"task": "bowaka_v2_scanner_watchdog", "at": "%DATE% %TIME%", "retries": !RETRIES!}
exit /b 13

:end
echo [scanner-watchdog %DATE% %TIME%] exiting cleanly final-code=!EC!
exit /b !EC!
