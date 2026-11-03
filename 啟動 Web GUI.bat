@echo off
chcp 65001 >nul
cd /d "%~dp0"
python wcat_web_gui.py %*
pause
