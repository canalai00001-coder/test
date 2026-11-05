@echo off
rem Open the operation screen (runs in this PC only). Keep this window open while you use it.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m qmate_agent.app
pause
