@echo off
title PASSION MATE - Auto Restart LocalTunnel
color 0B

echo ==========================================================
echo [로컬터널(LocalTunnel) 자동 복구 접속기]
echo.
echo "no tunnel here :(" 에러 방지를 위해, 터널이 끊기더라도
echo 5초 뒤에 자동으로 서버에 재접속하도록 체계화되었습니다.
echo ==========================================================
echo.

:loop
echo [진행중] 로컬터널 서버(포트 3000)를 외부로 개방합니다...
call npx localtunnel --port 3000

echo.
echo [경고] 로컬터널 연결이 끊어졌거나 서버가 응답하지 않습니다!
echo 5초 뒤에 자동으로 재접속을 시도합니다...
timeout /t 5 >nul
goto loop
