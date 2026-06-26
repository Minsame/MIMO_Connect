@echo off
chcp 65001 >nul
title MIMO_Connect 一键安装并启动
chdir /d "%~dp0"

echo ============================================
echo   MIMO_Connect 一键安装并启动（新手专用）
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

REM ---- 4. 检查 .env ----
if not exist ".env" (
    echo [警告] 没有找到 .env 配置文件！
    if exist ".env.example" (
        echo 已根据 .env.example 生成一份 .env，请打开它填入真实的 API 密钥后再启动。
        copy ".env.example" ".env" >nul
        notepad ".env"
        echo 填好并保存 .env 后，请重新双击本脚本。
        pause
        exit /b 1
    ) else (
        echo 请向开发者索取 .env 文件并放到本目录后重试。
        pause
        exit /b 1
    )
)

REM ---- 启动 ----
echo [4/4] 启动 MIMO_Connect ...
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
