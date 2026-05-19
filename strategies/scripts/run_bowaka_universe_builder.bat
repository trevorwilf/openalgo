@echo off
REM Bowaka v2 universe builder wrapper (Windows).
setlocal
cd /d "%~dp0\..\.."
set "PY=%~dp0\..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "CFG=%BOWAKA_V2_UNIVERSE_CFG%"
if "%CFG%"=="" set "CFG=strategies\scripts\bowaka_universe_builder.yaml"
"%PY%" strategies\scripts\bowaka_universe_builder.py --config "%CFG%" %*
endlocal
