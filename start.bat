@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto missing
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0ui.py"
exit /b
:missing
echo Run install.bat first.
pause
