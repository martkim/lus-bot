@echo off
title PASSION MATE - Cloudflare Tunnel
color 0B

echo ==========================================================
echo [ Cloudflare Secure Tunnel ]
echo ==========================================================
echo.
echo Bypassing ngrok issues and starting Cloudflare tunnel...
echo Preparing tunnel...
echo.

python start-cloudflared.py

echo.
echo Tunnel closed.
pause
