@echo off
chcp 65001 >nul
title MIMO_Connect
chdir /d "%~dp0"

REM 统一启动器（Windows）。默认启动 GUI（首次未配置自动进引导向导）。
REM   mmc            启动 GUI（托盘 + 设置 + 日志）
REM   mmc --cli      命令行模式（持续打印日志）
REM   mmc --force-setup  强制重新配置

if exist ".venv\Scripts\pythonw.exe" (
    set "PYW=.venv\Scripts\pythonw.exe"
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PYW=pythonw"
    set "PY=python"
)

REM 含 --cli 时用带控制台的 python 以便看日志；否则用 pythonw 静默启动 GUI。
echo %* | findstr /C:"--cli" >nul
if %errorlevel%==0 (
    "%PY%" app_main.py %*
) else (
    start "" "%PYW%" app_main.py %*
)
