@echo off
REM ============================================================
REM  Starts the Legoliv Telegram bot.
REM  Uses legobot.exe if it is in this folder, otherwise Python.
REM  Keep this window OPEN during class. Close it to stop the bot.
REM ============================================================
title Legoliv Data Logger - Bot
cd /d "%~dp0"
if exist "%~dp0legobot.exe" (
    "%~dp0legobot.exe"
    goto :end
)
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
    echo Python is not installed. Double-click INSTALL.bat first.
    pause
    exit /b 1
)
%PY% "%~dp0legobot.py"
:end
echo.
echo Bot stopped.
pause
