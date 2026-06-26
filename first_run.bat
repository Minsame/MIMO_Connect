@echo off
chcp 65001 >nul
title MIMO_Connect 首次启动一键部署
chdir /d "%~dp0"

echo ============================================
echo   MIMO_Connect 首次启动一键部署（新手专用）
echo ============================================
echo.

REM ---- 1. 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Python。
    echo 请先到 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本，
    echo 安装时务必勾选 "Add Python to PATH"，然后重新双击本脚本。
    echo.
    pause
    exit /b 1
)
echo [1/4] 已检测到 Python：
python --version
echo.

REM ---- 2. 创建虚拟环境（已存在则跳过）----
if exist ".venv\Scripts\python.exe" (
    echo [2/4] 虚拟环境已存在，跳过创建。
) else (
    echo [2/4] 正在创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
    echo 创建完成。
)
echo.

set "PY=.venv\Scripts\python.exe"

REM ---- 3. 安装依赖 ----
echo [3/4] 正在安装依赖（首次可能需要几分钟）...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install --no-cache-dir -r requirements.txt
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请把上面的红色报错发给开发者。
    pause
    exit /b 1
)
echo 依赖安装完成。
echo.

REM ---- 4. 运行首次部署向导（询问 LLM / 检索 mimo / 平台凭据等）----
echo [4/4] 进入首次部署向导 ...
echo ============================================
"%PY%" scripts\first_run_setup.py
if errorlevel 1 (
    echo.
    echo [提示] 向导未完成或已取消，可重新双击本脚本继续。
    pause
    exit /b 1
)
echo.

REM ---- 启动 ----
echo 启动 MIMO_Connect ...
echo ============================================
echo.
"%PY%" main.py
set "EC=%ERRORLEVEL%"

echo.
if "%EC%"=="0" (
    echo [MIMO_Connect] 已正常退出。
) else (
    echo [MIMO_Connect] 退出，错误码 %EC%。
)
pause
