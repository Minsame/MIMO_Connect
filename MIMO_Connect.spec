# -*- mode: python ; coding: utf-8 -*-
# MIMO_Connect PyInstaller spec - Windows GUI onefile exe (精简版)
#
# 设计：
#   - 入口 gui_main.py（纯 GUI，不含 CLI 分支）
#   - onefile：单个 MIMO_Connect.exe，运行时自解压到临时目录
#   - 仅收 PySide6 必需模块（Core/Gui/Widgets），排除 WebEngine/Quick/QML/3D/
#     Multimedia/Pdf/Designer 等重型组件，体积从 ~720MB 砍到百MB级
#   - .env / config.yaml / 日志固定在 exe 同目录（见 core.config_io 的 sys.frozen 分支）
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

datas = [("config.yaml", "."), (".env.example", ".")]
binaries = []
hiddenimports = [
    "platforms.feishu",
    "platforms.weixin",
    "voice.edge_tts",
    "agent.mimo_code",
    "gui.i18n",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "yaml",
    "httpx",
    "dotenv",
    "openai",
    # 仅 GUI 实际用到的 PySide6 子模块
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "shiboken6",
]

# 收集业务依赖（不含 PySide6，PySide6 走精确白名单以排除重型 Qt 模块）
for pkg in ("lark_oapi", "langchain_openai", "edge_tts", "Crypto"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports += collect_submodules(pkg)

# 显式排除 Qt 重型组件与其它无关大件，大幅缩减体积
excludes = [
    "tkinter", "pytest", "mypy", "black", "ruff", "pandas", "matplotlib",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtQuickControls2", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.Qt3DInput", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtScxml",
    "PySide6.QtRemoteObjects", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtSvgWidgets", "PySide6.QtNetworkAuth", "PySide6.QtWebView",
]

a = Analysis(
    ["gui_main.py"],
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

# 进一步剔除被 collect_all 顺带拖入的 Qt 大文件（按文件名过滤）
_QT_HEAVY = (
    "qtwebengine", "webengine", "opengl32sw", "avcodec", "avformat", "avutil",
    "swscale", "swresample", "qt6quick", "qt6qml", "qt63d", "qt6multimedia",
    "qt6pdf", "qt6designer", "qt6charts", "qt6datavis", "qt6sql", "d3dcompiler",
    "qt6quick3d", "qt6shadertools", "qt6spatialaudio", "qt6sensors", "qt6location",
)


def _keep(name):
    low = name.lower()
    return not any(tok in low for tok in _QT_HEAVY)


a.binaries = [x for x in a.binaries if _keep(x[0])]
a.datas = [x for x in a.datas if _keep(x[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MIMO_Connect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
