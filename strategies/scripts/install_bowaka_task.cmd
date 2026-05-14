@echo off
REM ============================================================
REM install_bowaka_task.cmd
REM
REM Imports / overwrites the BowakaPrefilter Task Scheduler entry
REM from the canonical XML at this directory.
REM
REM REQUIRES ELEVATION: right-click this .cmd and choose
REM   "Run as administrator"   (or run from an elevated CMD/PS).
REM
REM Why: schtasks /create /f against an existing task triggers
REM UAC even when the task is user-owned.
REM
REM Current schedule (per BowakaPrefilter.xml):
REM   - 2:00 AM Mountain Time, Mon-Fri
REM   - On failure: retry every 15 minutes, up to 16 attempts
REM     (4-hour recovery window for transient DNS / Alpaca outages)
REM ============================================================

setlocal

set "XML=%~dp0BowakaPrefilter.xml"

if not exist "%XML%" (
    echo ERROR: %XML% not found 1>&2
    exit /b 2
)

echo Importing BowakaPrefilter from %XML% ...
schtasks /create /tn "BowakaPrefilter" /xml "%XML%" /f
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
    echo.
    echo Import failed (exit code %EC%^).
    echo Most common cause: not running as administrator.
    echo Right-click this .cmd and choose "Run as administrator".
    exit /b %EC%
)

echo.
echo Done. New schedule:
schtasks /query /tn "BowakaPrefilter" /fo LIST | findstr /R "TaskName Next.Run Last.Run Last.Result Status"
echo.
echo (Run ``schtasks /query /tn BowakaPrefilter /xml`` to see the full task definition.)
exit /b 0
