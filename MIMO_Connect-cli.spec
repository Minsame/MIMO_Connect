# -*- mode: python ; coding: utf-8 -*-
# MIMO_Connect CLI 独立可执行 spec（命令行版，跨平台）。
#
# 设计：
#   - 入口 cli_main.py（纯命令行，不含任何 GUI/PySide6 依赖）
#   - onefile：单个可执行文件；首次运行自动在同目录创建 .env / config.yaml / 日志
#   - 在 Linux 上打包 → 得到 Linux 可执行（./MIMO_Connect-cli）
#     在 Windows 上打包 → 得到 MIMO_Connect-cli.exe
#   - 体积远小于 GUI 版（不含 Qt）
from PyInstaller.utils.hooks import collect_submodules, collect_all
import sys as _sys

block_cipher = None

datas = [("config.yaml", "."), (".env.example", ".")]
binaries = []
hiddenimports = [
    "platforms.feishu",
    "platforms.weixin",
    "voice.edge_tts",
    "agent.mimo_code",
    "yaml",
    "httpx",
    "dotenv",
    "openai",
]

# 业务依赖（无 GUI）。Crypto 仅微信平台需要，按平台收集。
_pkgs = ["lark_oapi", "langchain_openai", "edge_tts", "Crypto"]
for pkg in _pkgs:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports += collect_submodules(pkg)

# Windows 专有 TTS 依赖仅在 Windows 收集，避免 Linux 打包报错。
if _sys.platform == "win32":
    hiddenimports += ["win32com", "win32com.client", "pythoncom", "pywintypes"]

# 排除全部 GUI 与无关大件。
excludes = [
    "tkinter", "pytest", "mypy", "black", "ruff", "pandas", "matplotlib",
    "PySide6", "shiboken6", "PyQt5", "PyQt6",
]

a = Analysis(
    ["cli_main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MIMO_Connect-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
