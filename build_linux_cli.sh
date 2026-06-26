#!/usr/bin/env bash
# 在 Linux（或 WSL）上把 CLI 版打包成单个独立可执行文件。
#
# 产物：dist/MIMO_Connect-cli  —— 直接 ./MIMO_Connect-cli 运行，无需安装 Python。
# 首次运行会在可执行同目录自动创建 .env / config.yaml / 日志，并进入命令行引导。
#
# 前置：Python 3.10+，且系统已装 pip 与编译工具。Debian/Ubuntu 一次性准备：
#   sudo apt-get update
#   sudo apt-get install -y python3-pip python3-venv python3-dev build-essential
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"

echo "[1/4] 创建打包用虚拟环境 .build-venv ..."
"$PY" -m venv .build-venv
source .build-venv/bin/activate

echo "[2/4] 安装运行依赖（不含 GUI）..."
pip install --upgrade pip
# CLI 版无需 PySide6/pywin32；只装运行所需。
pip install langchain langchain-openai langchain-core openai numpy soundfile \
    lark-oapi pycryptodome pydantic pydantic-settings python-dotenv pyyaml \
    edge-tts httpx loguru

echo "[3/4] 安装 PyInstaller ..."
pip install pyinstaller

echo "[4/4] 打包 ..."
pyinstaller MIMO_Connect-cli.spec --noconfirm --distpath dist --workpath build

deactivate
echo
echo "完成：dist/MIMO_Connect-cli"
echo "运行：./dist/MIMO_Connect-cli   （首次会自动建配置并进入引导）"
