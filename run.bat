@echo off
setlocal
cd /d "%~dp0"

echo Starting Report Updater v3...

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please create it first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m streamlit run app.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Application crashed.
)

pause
endlocal

