@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
if not exist "logs" mkdir "logs"
python run_daily.py >> "logs\daily.log" 2>&1
