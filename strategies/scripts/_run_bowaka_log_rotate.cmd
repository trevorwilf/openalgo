@echo off
setlocal

set "OPENALGO_ROOT=E:\stocktradingsoftware\openalgo"
set "OPENALGO_PYTHON=%OPENALGO_ROOT%\.venv\Scripts\python.exe"

cd /d "%OPENALGO_ROOT%"

"%OPENALGO_PYTHON%" strategies\scripts\bowaka_log_rotate.py --max-mb 50 --keep 5 >> logs\maintenance_bowaka_rotate.log 2>&1
if errorlevel 1 exit /b %errorlevel%

"%OPENALGO_PYTHON%" strategies\scripts\bowaka_log_rotate.py --data-files --max-mb 200 --keep 3 >> logs\maintenance_bowaka_rotate.log 2>&1
exit /b %errorlevel%
