@echo off
chcp 65001 >nul
title MIMO_Connect - Voice Coding Middleware
chdir /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo [MIMO_Connect] starting with %PY% main.py
echo [MIMO_Connect] cwd = %CD%
echo.

%PY% main.py
set "EC=%ERRORLEVEL%"

echo.
if "%EC%"=="0" (
    echo [MIMO_Connect] exited cleanly.
) else (
    echo [MIMO_Connect] exited with code %EC%.
)
pause
