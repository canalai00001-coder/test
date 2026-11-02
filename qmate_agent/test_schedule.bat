@echo off
rem Trial run: row 2 of the plan sheet, 5 manuscripts only, with the browser shown.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m qmate_agent schedule --row 2 --count 5 --headed
pause
