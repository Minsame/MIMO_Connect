@echo off
chcp 65001 >nul
title MIMO_Connect
chdir /d "%~dp0"

REM 统一启动器（Windows）。默认启动 GUI（首次未配置自动进引导向导）。
REM   mmc              启动 GUI（托盘 + 设置 + 日志）
REM   mmc --cli        命令行模式（持续打印日志）
REM   mmc --force-setup 强制重新配置（命令行向导）

if exist ".venv\Scripts\pythonw.exe" (
    set "PYW=.venv\Scripts\pythonw.exe"
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PYW=pythonw"
    set "PY=python"
)

echo %* | findstr /C:"--cli" >nul
if %errorlevel%==0 (
    "%PY%" cli_main.py %*
) else (
    echo %* | findstr /C:"--force-setup" >nul
    if %errorlevel%==0 (
        "%PY%" cli_main.py %*
    ) else (
        start "" "%PYW%" gui_main.py %*
    )
)
