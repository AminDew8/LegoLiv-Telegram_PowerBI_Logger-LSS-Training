@echo off
REM ============================================================
REM  Legoliv Data Logger - one-click installer (Windows 10/11)
REM  Installs: Python, Telegram Desktop, Power BI Desktop,
REM            and the Python libraries the bot needs.
REM  Safe to run again: anything already installed is skipped.
REM ============================================================
title Legoliv Data Logger - Installer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
echo.
pause
