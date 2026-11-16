@echo off
rem Open the operation screen (runs in this PC only). Keep this window open while you use it.
cd /d "%~dp0"
if not exist service_account.json if exist ..\qmate_agent\service_account.json copy ..\qmate_agent\service_account.json service_account.json >nul
if exist ..\qmate_agent\.venv\Scripts\activate.bat (
  call ..\qmate_agent\.venv\Scripts\activate.bat
) else (
  if not exist .venv\Scripts\activate.bat (
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
    python -m playwright install chromium
  ) else (
    call .venv\Scripts\activate.bat
  )
)
python -m hitomane_agent.app
pause
