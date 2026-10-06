@echo off
setlocal enabledelayedexpansion
title PASSION MATE - Restart Server
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM Stops uvicorn so the watchdog starts it again with the current code.
REM The backend runs without --reload, so edits do nothing until a restart.
REM
REM This script only KILLS. It does not start the server itself.
REM
REM Why: the first version ran "start /B python -m uvicorn ...", which attaches
REM the child to this console. Closing the window after the pause killed the
REM server with it, and the site went down until the watchdog noticed
REM (2026-10-07). system_service.py already starts uvicorn the right way --
REM detached, no console, in session 0 -- and checks the port every 5 minutes.
REM Letting it do that is both simpler and more reliable than repeating it here.
REM
REM Needs elevation: a scheduled task starts the server S4U, so it lives in
REM session 0 and a normal logged-in session cannot kill it (access denied).
REM
REM This file is ASCII only on purpose. cmd.exe reads .bat in the console
REM codepage (949 on Korean Windows), so UTF-8 Korean comments become garbage
REM lines that cmd tries to execute. That broke the first version too.
REM ---------------------------------------------------------------------------

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   PASSION MATE - Restart Server
echo ============================================================
echo.

echo [1/2] Stopping the process on port 8088...
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8088 .*LISTENING"') do (
    set "FOUND=1"
    echo       killing PID %%P
    taskkill /PID %%P /F
)
if not defined FOUND echo       nothing was running on 8088

echo.
echo [2/2] Waiting for the watchdog to start it again...
echo       (it checks every 5 minutes, so this can take a few minutes)
set "OK="
for /L %%i in (1,1,60) do (
    if not defined OK (
        timeout /t 6 /nobreak >nul
        curl -s -o nul -m 3 http://127.0.0.1:8088/ && set "OK=1"
    )
)

echo.
if defined OK (
    echo SUCCESS - the server is answering again, now running the current code.
) else (
    echo Still no response. Check these:
    echo   logs\monitor_log.txt     - watchdog cycle
    echo   logs\server_err.log      - startup errors
    echo   Get-Process pythonw      - the watchdog itself must be running
)

echo.
echo You can close this window now. The server does not depend on it.
pause
