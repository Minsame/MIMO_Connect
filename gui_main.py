"""MIMO_Connect GUI 入口（仅桌面图形界面）。

职责单一：启动桌面应用（首启引导向导 + 系统托盘 + 设置窗口 + 实时日志窗口）。
未配置时先进引导向导，配置完成后常驻托盘并自动启动引擎。

这是唯一会被 PyInstaller 打包进 MIMO_Connect.exe 的入口；不含命令行回退分支。

开发期直接运行：
    python gui_main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    from gui.app import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
