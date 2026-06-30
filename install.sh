#!/usr/bin/env bash
# MIMO_Connect 一键安装（Linux / macOS，源码运行方式）。
#
# 行为：
#   1. 探测系统 Python，>= 3.10 直接用；否则尝试用系统包管理器安装。
#   2. 在项目内建隔离虚拟环境 .venv 并安装运行依赖（不含 GUI / 开发工具）。
#   3. 装好后打印启动方式。
#
# 用法：bash install.sh
#       bash install.sh --run   # 装完直接启动（首次会进入分步引导）
#       MMC_PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple bash install.sh   # 国内镜像加速
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 判断给定 python 是否 >= 3.10。
py_ok() {
  local py="$1"
  command -v "$py" >/dev/null 2>&1 || return 1
  "$py" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >/dev/null 2>&1
}

# 1) 找一个合适的 Python。
PY=""
for cand in python3 python python3.13 python3.12 python3.11 python3.10; do
  if py_ok "$cand"; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  echo "[install] 未发现 Python >= 3.10，尝试用系统包管理器安装 ..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python python-pip
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python3-pip
  elif command -v brew >/dev/null 2>&1; then
    brew install python
  else
    echo "[install] 无法自动安装：未识别的包管理器。" >&2
    echo "          请手动安装 Python >= 3.10 后重新运行本脚本。" >&2
    exit 1
  fi
  for cand in python3 python; do
    if py_ok "$cand"; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "[install] 安装后仍未找到 Python >= 3.10，请检查系统环境。" >&2
    exit 1
  fi
fi

echo "[install] 使用 Python：$("$PY" --version 2>&1) ($(command -v "$PY"))"

# venv 模块可用性检查（部分发行版需单独装 python3-venv）。
# 注意：如果系统装了非发行版自带版本（如 Python 3.14），对应的 python3.X-venv
# 包可能在源里不存在。此时用 --without-pip 创建 venv 再手动 bootstrap pip。
if ! "$PY" -m venv --help >/dev/null 2>&1; then
  echo "[install] 当前 Python 缺少 venv 模块，尝试安装 ..."
  if command -v apt-get >/dev/null 2>&1; then
    # 尝试安装匹配版本的 venv 包（如 python3.14-venv），失败则装通用版
    PY_VER=$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    sudo apt-get install -y "python${PY_VER}-venv" 2>/dev/null || sudo apt-get install -y python3-venv 2>/dev/null || true
  fi
fi

# 2) 建虚拟环境并装运行依赖（与 CLI 打包一致，不含 PySide6 / 开发工具）。

# 用 get-pip.py 给 venv 手动安装 pip（不依赖 ensurepip）。
# 用法：bootstrap_pip <venv_python> [pip_mirror]
bootstrap_pip() {
  local venv_py="$1"
  local mirror="${2:-}"
  local get_pip="/tmp/mmc_get-pip.py"
  echo "[install] 下载 get-pip.py 安装 pip ..."
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$get_pip"; then
      echo "[install] 错误：curl 下载 get-pip.py 失败，请检查网络连接。" >&2
      echo "          也可手动下载 https://bootstrap.pypa.io/get-pip.py 后重试。" >&2
      return 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget -q -O "$get_pip" https://bootstrap.pypa.io/get-pip.py; then
      echo "[install] 错误：wget 下载 get-pip.py 失败，请检查网络连接。" >&2
      echo "          也可手动下载 https://bootstrap.pypa.io/get-pip.py 后重试。" >&2
      return 1
    fi
  else
    echo "[install] 错误：系统未安装 curl 或 wget，无法下载 get-pip.py。" >&2
    echo "          请安装其一：sudo apt install curl（或 wget）后重试。" >&2
    return 1
  fi
  if [ -n "$mirror" ]; then
    if ! "$venv_py" "$get_pip" -i "$mirror"; then
      echo "[install] 错误：get-pip.py 执行失败，pip 安装未成功。" >&2
      rm -f "$get_pip"
      return 1
    fi
  else
    if ! "$venv_py" "$get_pip"; then
      echo "[install] 错误：get-pip.py 执行失败，pip 安装未成功。" >&2
      rm -f "$get_pip"
      return 1
    fi
  fi
  rm -f "$get_pip"
}

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "[install] 创建虚拟环境 .venv ..."
  PIP_MIRROR=""
  if [ -n "${MMC_PIP_MIRROR:-}" ]; then PIP_MIRROR="$MMC_PIP_MIRROR"; fi
  # 标准 venv 创建（带 pip）；失败或创建后无 pip 则走兜底。
  if ! "$PY" -m venv .venv 2>/dev/null; then
    echo "[install] 标准 venv 创建失败，改用 --without-pip 模式 ..."
    rm -rf .venv
    if ! "$PY" -m venv --without-pip .venv 2>/dev/null; then
      echo "[install] 错误：虚拟环境创建失败。" >&2
      echo "" >&2
      echo "  可能原因与解决办法：" >&2
      echo "    1) 缺少 venv 模块 — Debian/Ubuntu 请执行：sudo apt install python3-venv" >&2
      echo "    2) Python 版本非系统自带（如 3.14），无对应 venv 包 — 请装系统默认 python3" >&2
      echo "    3) 磁盘空间不足或权限问题 — 检查当前目录可写权限" >&2
      echo "" >&2
      echo "  解决后重新运行：bash install.sh" >&2
      exit 1
    fi
    bootstrap_pip "$ROOT/.venv/bin/python" "$PIP_MIRROR" || exit 1
  fi
  # venv 命令成功但可能没带 pip（ensurepip 不可用时静默生成无 pip 的 venv）。
  if ! "$ROOT/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "[install] venv 中缺少 pip，用 get-pip.py 补装 ..."
    bootstrap_pip "$ROOT/.venv/bin/python" "$PIP_MIRROR" || exit 1
  fi
fi
VENV_PY="$ROOT/.venv/bin/python"

echo "[install] 升级 pip 并安装运行依赖 ..."
PIP_ARGS=()
if [ -n "${MMC_PIP_MIRROR:-}" ]; then PIP_ARGS=(-i "$MMC_PIP_MIRROR"); fi
"$VENV_PY" -m pip install --upgrade pip "${PIP_ARGS[@]}"
"$VENV_PY" -m pip install "${PIP_ARGS[@]}" \
  langchain-openai langchain-core openai \
  lark-oapi pycryptodome python-dotenv pyyaml \
  edge-tts httpx

# 确保启动器可执行（git 拉取后可能丢失 +x 位）。
chmod +x mmc 2>/dev/null || true

# 软链 mmc 到用户级 bin，实现任意目录直接 `mmc` 启动。
# mmc 脚本内部会解析软链回真实项目目录，因此 .venv / cli_main.py 仍能定位。
LINK_DIR="$HOME/.local/bin"
LINK_PATH="$LINK_DIR/mmc"
LINKED=0
mkdir -p "$LINK_DIR"
if ln -sf "$ROOT/mmc" "$LINK_PATH" 2>/dev/null; then
  LINKED=1
fi

echo
echo "============================================================"
echo "  安装完成。"
if [ "$LINKED" = "1" ]; then
  echo "  已软链到：$LINK_PATH"
  case ":$PATH:" in
    *":$LINK_DIR:"*)
      echo "  启动方式（任意目录）："
      echo "    mmc                 # 首次进入分步引导，之后直接运行"
      echo "    mmc --force-setup   # 重新配置"
      ;;
    *)
      echo "  注意：$LINK_DIR 不在 PATH 中。请加入后即可任意目录运行 mmc："
      echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
      echo "  在此之前可用： $ROOT/mmc"
      ;;
  esac
else
  echo "  启动方式："
  echo "    ./mmc                 # 首次进入分步引导，之后直接运行"
  echo "    ./mmc --force-setup   # 重新配置"
fi
echo "  配置与日志目录：\${MIMO_CONNECT_HOME:-\${XDG_CONFIG_HOME:-~/.config}/mimo_connect}"
echo "============================================================"

# 3) 可选：装完直接运行。
if [ "${1:-}" = "--run" ]; then
  echo "[install] 立即启动 ..."
  exec "$VENV_PY" cli_main.py
fi
