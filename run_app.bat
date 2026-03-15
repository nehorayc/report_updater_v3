@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Report Updater v3 - Launcher
echo ========================================

:: Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found in .venv directory.
    echo Please ensure you have created the environment and installed requirements:
    echo 1. python -m venv .venv
    echo 2. .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: Activate the virtual environment
echo [INFO] Activating virtual environment...
call ".venv\Scripts\activate.bat"

:: Run the streamlit app
echo [INFO] Launching Streamlit application...
python -m streamlit run app.py

:: Keep window open if the app closes or crashes
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] The application closed unexpectedly (Error Code: %ERRORLEVEL%).
) else (
    echo.
    echo [INFO] Application closed normally.
)

pause
endlocal
