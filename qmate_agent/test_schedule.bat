@echo off
rem Trial run: row 2 of the plan sheet, with the browser shown. Count and status come from the sheet.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m qmate_agent schedule --row 2 --headed
pause
