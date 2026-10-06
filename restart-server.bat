@echo off
setlocal
title PASSION MATE - 서버 재시작
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM 서버(uvicorn)를 내리고 워치독이 새 코드로 되살리게 한다.
REM
REM 왜 필요한가: 백엔드는 --reload 없이 돌아서 .py를 고쳐도 재시작 전까지 반영되지
REM 않는다. 그런데 이 서버는 작업 스케줄러가 S4U로 띄워서 **세션 0**에 있고,
REM 로그인 세션에서 일반 권한으로는 종료가 안 된다. 그래서 이 스크립트는 관리자
REM 권한을 요청한다.
REM
REM 내리기만 하면 된다. system_service.py(워치독)가 5분 주기로 포트를 확인하다
REM 죽어 있으면 알아서 다시 띄운다. 여기서는 그 시간을 기다리지 않고 바로
REM 띄워주되, 실패해도 워치독이 받쳐준다.
REM ---------------------------------------------------------------------------

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo 관리자 권한이 필요합니다. 권한을 요청합니다...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   PASSION MATE 서버 재시작
echo ============================================================
echo.

echo [1/3] 포트 8088을 쓰는 프로세스를 찾습니다...
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8088 .*LISTENING"') do (
    set "FOUND=1"
    echo       PID %%P 종료
    taskkill /PID %%P /F >nul 2>&1
)
if not defined FOUND echo       (실행 중인 서버가 없습니다)

echo.
echo [2/3] 서버를 다시 띄웁니다...
start "" /B python -m uvicorn main:app --host 0.0.0.0 --port 8088 >> logs\server_out.log 2>> logs\server_err.log

echo.
echo [3/3] 응답을 확인합니다...
set "OK="
for /L %%i in (1,1,15) do (
    if not defined OK (
        timeout /t 2 /nobreak >nul
        curl -s -o nul -m 3 http://127.0.0.1:8088/ && set "OK=1"
    )
)

echo.
if defined OK (
    echo 성공 - 서버가 새 코드로 응답합니다.
    echo 커리큘럼 덮어쓰기 루프가 제거된 코드가 적용되었습니다.
) else (
    echo 아직 응답이 없습니다. 워치독이 5분 안에 다시 띄웁니다.
    echo 상태는 logs\server_err.log 와 logs\monitor_log.txt 에서 확인하세요.
)

echo.
pause
