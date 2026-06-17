@echo off
title Passport Photo Studio Setup

echo ============================================
echo   Passport Photo Studio  First-Time Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Please install Python 3.10 or newer from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Python found. Creating virtual environment...
if not exist "venv" (
    python -m venv venv
)

echo [2/3] Installing libraries (this may take a few minutes on first run)...
call venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo [3/3] Launching app...
echo.
python main.py

pause
