@echo off
set "OPENALGO_API_KEY=63055836291b041d0c4d75b23a30ce73fd1ac1247e214507fbfd4d2754721745"
set "HOST_SERVER=http://127.0.0.1:5000"
set "OPENALGO_STRATEGY_EXCHANGE=CRYPTO"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "E:\stocktradingsoftware\openalgo\strategies\scripts"
"E:\stocktradingsoftware\openalgo\.venv\Scripts\python.exe" bowaka_strategy.py --config bowaka_strategy.yaml