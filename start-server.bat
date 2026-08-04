@echo off
title PASSION MATE SERVER
cd /d "%~dp0"
color 0F

echo ============================================================
echo   PASSION MATE SERVER STARTING...
echo ============================================================
echo.

echo [1/2] Installing requirements...
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo.
    echo Failed to install using 'python'. Trying 'py' command...
    py -m pip install -r requirements.txt --quiet
)

echo.
echo [2/2] Starting uvicorn server...
echo ============================================================
python -m uvicorn main:app --host 0.0.0.0 --port 8088 --reload
if %errorlevel% neq 0 (
    echo.
    echo Failed to start with 'python'. Trying 'py' command...
    py -m uvicorn main:app --host 0.0.0.0 --port 8088 --reload
)

echo.
echo ============================================================
echo Server stopped or crashed. Please read the error message above.
echo ============================================================
pause
