"""实时日志窗口：状态头栏 + 分级着色 + 搜索/过滤的滚动日志面板。"""

from __future__ import annotations

import html
import os
import subprocess
import sys
from collections import deque

from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.theme import MONO_FAMILY, Palette, set_role

_LEVELS = ("ALL", "DEBUG", "INFO", "WARNING", "ERROR")
_LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 3}


class LogView(QWidget):
    """只读滚动日志面板：分级着色、级别过滤、关键字搜索、自动滚动开关。"""

    MAX_LINES = 5000  # 内存中保留的最大行数，避免长跑膨胀

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MIMO_Connect 运行日志")
        self.resize(880, 560)

        # 原始日志缓冲（用于过滤/搜索时重渲染）
        self._buffer: deque[tuple[str, str]] = deque(maxlen=self.MAX_LINES)
        self._counts_map = {"INFO": 0, "WARNING": 0, "ERROR": 0}
        self._min_level = "ALL"
        self._filter_text = ""
        self._autoscroll = True

        self._build_ui()

    # ---- UI 组装 ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

        self._text = QTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.setFont(QFont("Consolas", 10))
        self._text.document().setMaximumBlockCount(self.MAX_LINES)
        self._text.setStyleSheet(
            f"QTextEdit {{ background: {Palette.log_bg}; color: {Palette.log_fg};"
            f" border: none; padding: 8px; font-family: {MONO_FAMILY}; }}"
        )
        root.addWidget(self._text, 1)

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {Palette.surface}; border-bottom: 1px solid {Palette.border}; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 10, 14, 10)

        self._dot = QLabel("\u25cf")
        self._dot.setStyleSheet(f"color: {Palette.neutral}; font-size: 14px;")
        self._status = QLabel("已停止")
        set_role(self._status, "title")
        title = QLabel("MIMO_Connect 运行日志")
        title.setStyleSheet("color: #5b6470;")

        self._counts = QLabel("")
        self._counts.setStyleSheet("color: #5b6470;")
        self._counts.setTextFormat(Qt.TextFormat.RichText)

        lay.addWidget(self._dot)
        lay.addWidget(self._status)
        lay.addSpacing(8)
        lay.addWidget(title)
        lay.addStretch(1)
        lay.addWidget(self._counts)
        return bar

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {Palette.surface_alt}; border-bottom: 1px solid {Palette.border}; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索日志关键字…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_filter_changed)
        self._search.setMaximumWidth(280)

        lvl_label = QLabel("级别")
        lvl_label.setStyleSheet("color: #5b6470;")
        self._cmb_level = QComboBox()
        self._cmb_level.addItems(_LEVELS)
        self._cmb_level.setCurrentText("ALL")
        self._cmb_level.currentTextChanged.connect(self._on_level_changed)

        self._chk_autoscroll = QCheckBox("自动滚动")
        self._chk_autoscroll.setChecked(True)
        self._chk_autoscroll.toggled.connect(self._on_autoscroll_toggled)

        btn_open = QPushButton("打开日志文件")
        btn_open.clicked.connect(self._open_log_file)
        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(self._copy_all)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._clear)

        lay.addWidget(self._search)
        lay.addWidget(lvl_label)
        lay.addWidget(self._cmb_level)
        lay.addStretch(1)
        lay.addWidget(self._chk_autoscroll)
        lay.addWidget(btn_open)
        lay.addWidget(btn_copy)
        lay.addWidget(btn_clear)
        return bar

    # ---- 对外接口 ----
    def set_running(self, running: bool) -> None:
        """同步顶部状态指示（由 AppController 调用）。"""
        if running:
            self._dot.setStyleSheet(f"color: {Palette.success}; font-size: 14px;")
            self._status.setText("运行中")
        else:
            self._dot.setStyleSheet(f"color: {Palette.neutral}; font-size: 14px;")
            self._status.setText("已停止")

    def append_line(self, line: str) -> None:
        level = self._parse_level(line)
        self._buffer.append((level, line))
        if level in self._counts_map:
            self._counts_map[level] += 1
        if self._passes(level, line):
            self._render_line(level, line)
        self._update_counts()

    # ---- 过滤/搜索 ----
    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self._rerender()

    def _on_level_changed(self, level: str) -> None:
        self._min_level = level
        self._rerender()

    def _on_autoscroll_toggled(self, on: bool) -> None:
        self._autoscroll = on
        if on:
            self._scroll_to_end()

    def _passes(self, level: str, line: str) -> bool:
        if self._min_level != "ALL":
            if _LEVEL_RANK.get(level, 1) < _LEVEL_RANK.get(self._min_level, 0):
                return False
        if self._filter_text and self._filter_text not in line.lower():
            return False
        return True

    def _rerender(self) -> None:
        self._text.clear()
        for level, line in self._buffer:
            if self._passes(level, line):
                self._render_line(level, line)

    def _render_line(self, level: str, line: str) -> None:
        color = {
            "DEBUG": Palette.log_debug,
            "INFO": Palette.log_info,
            "WARNING": Palette.log_warn,
            "ERROR": Palette.log_error,
            "CRITICAL": Palette.log_error,
        }.get(level, Palette.log_fg)
        safe = html.escape(line)
        self._text.append(f'<span style="color:{color};">{safe}</span>')
        if self._autoscroll:
            self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_counts(self) -> None:
        c = self._counts_map
        self._counts.setText(
            f"INFO {c['INFO']}   "
            f"<span style='color:{Palette.warning}'>WARN {c['WARNING']}</span>   "
            f"<span style='color:{Palette.danger}'>ERR {c['ERROR']}</span>"
        )

    @staticmethod
    def _parse_level(line: str) -> str:
        # 格式形如 "12:00:00 [INFO] name: msg"
        for lvl in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"):
            if f"[{lvl}]" in line:
                return lvl
        return "INFO"

    # ---- 工具按钮 ----
    def _copy_all(self) -> None:
        self._text.selectAll()
        self._text.copy()
        cursor = self._text.textCursor()
        cursor.clearSelection()
        self._text.setTextCursor(cursor)

    def _clear(self) -> None:
        self._text.clear()
        self._buffer.clear()
        self._counts_map = {"INFO": 0, "WARNING": 0, "ERROR": 0}
        self._update_counts()

    def _open_log_file(self) -> None:
        from core import config_io

        log_path = config_io.PROJECT_ROOT / "mimo_connect.log"
        if not log_path.exists():
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(log_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])
        except Exception:
            pass
