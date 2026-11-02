@echo off
rem Run the rows of the plan sheet whose date is today: generate, check and upload to Q-mate.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m qmate_agent schedule %*
pause
