@echo off
title PASSION MATE - NGROK TUNNEL
color 0D

echo ==========================================================
echo [ngrok 보안 터널 접속기]
echo ==========================================================
echo.
echo ngrok 인증 토큰이 성공적으로 적용되었습니다.
echo ngrok 터널을 시작합니다... (포트 8088)

:: 프로젝트 폴더에 다운로드된 ngrok.exe를 직접 실행합니다
call ngrok.exe http 8088

echo.
echo 터널이 종료되었습니다.
pause
