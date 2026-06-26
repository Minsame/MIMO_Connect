# -*- mode: python ; coding: utf-8 -*-
# MIMO_Connect PyInstaller spec - Windows GUI exe
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

datas = [("config.yaml", "."), (".env.example", ".")]
binaries = []
hiddenimports = [
    "platforms.feishu",
    "platforms.weixin",
    "voice.edge_tts",
    "agent.mimo_code",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "yaml",
    "httpx",
    "dotenv",
    "openai",
]

for pkg in ("lark_oapi", "langchain_openai", "edge_tts", "Crypto", "PySide6"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports += collect_submodules(pkg)

a = Analysis(
    ["app_main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "mypy", "black", "ruff"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MIMO_Connect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MIMO_Connect",
)
