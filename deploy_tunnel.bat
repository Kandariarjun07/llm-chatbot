@echo off
REM Simple Cloudflare Tunnel launcher for SNTI Chatbot
REM Run this after starting your backend normally.

echo ===========================================
echo   SNTI AI Chatbot — Cloudflare Tunnel
echo ===========================================
echo.
echo This script exposes your local backend to the internet.
echo Your machine MUST stay ON for the URL to remain accessible.
echo.

REM Check if cloudflared is available
where cloudflared >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: cloudflared not found in PATH.
    echo.
    echo Install it first:
    echo   winget install --id Cloudflare.cloudflared
    echo   OR download from: https://github.com/cloudflare/cloudflared/releases
    pause
    exit /b 1
)

echo Starting Cloudflare Tunnel pointing to http://localhost:8000
echo.
echo Your public URL will appear below (usually https://*.trycloudflare.com)
echo.

cloudflared tunnel --url http://localhost:8000
