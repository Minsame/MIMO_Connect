"""GUI 测试共享夹具：无头 Qt + 单例 QApplication。

- 强制 offscreen 平台，使 PySide6 测试可在无显示器/CI 环境运行。
- 提供进程级唯一的 QApplication（Qt 要求全进程仅一个）。
- 未安装 PySide6 时，依赖该夹具的测试整体跳过，不影响其余测试。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    pyside = pytest.importorskip("PySide6", reason="PySide6 未安装，跳过 GUI 测试")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # 不在此处 quit，保持会话级单例，避免重复创建/销毁导致崩溃。
