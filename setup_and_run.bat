@echo off
title Passport Photo Studio Setup

echo ============================================
echo   Passport Photo Studio  First-Time Setup
echo ============================================
echo.

:: Check Python (try venv first)
set "PYTHON_CMD=venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found.
        echo Please install Python 3.10 or newer from https://www.python.org/downloads/
        echo Make sure to tick "Add Python to PATH" during install.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

echo [1/3] Python found. Creating virtual environment...
if not exist "venv" (
    %PYTHON_CMD% -m venv venv
)

echo [2/3] Installing libraries (this may take a few minutes on first run)...
call venv\Scripts\activate.bat
%PYTHON_CMD% -m pip install --upgrade pip --quiet
%PYTHON_CMD% -m pip install -r requirements.txt --quiet

echo [3/3] Launching app...
echo.
venv\Scripts\python.exe main.py

pause