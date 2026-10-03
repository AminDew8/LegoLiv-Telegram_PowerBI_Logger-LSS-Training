@echo off
REM Builds a single-file legobot.exe (no Python needed on the target PC).
REM Run this on a PC that has Python (INSTALL.bat installs it).
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
    echo Python is not installed. Double-click INSTALL.bat first.
    pause
    exit /b 1
)
%PY% -m pip install --upgrade pyinstaller -r requirements.txt
%PY% -m PyInstaller --onefile --console --clean --name legobot legobot.py
if exist dist\legobot.exe (
    copy /y dist\legobot.exe legobot.exe >nul
    echo.
    echo DONE. legobot.exe is now in this folder.
) else (
    echo.
    echo BUILD FAILED - see the messages above.
)
pause
