"""系统托盘控制器：图标 + 右键菜单（设置 / 日志 / 启停 / 退出）。"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon(color: str = "#2f6fed") -> QIcon:
    """生成圆角方形托盘图标（带状态色点），避免依赖外部资源文件。"""
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 圆角方底
    painter.setBrush(QColor("#21429c"))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    # 字母 M
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(26)
    painter.setFont(font)
    painter.drawText(pix.rect(), 0x0084, "M")  # AlignCenter
    # 右下状态色点
    painter.setPen(QColor(0, 0, 0, 0))
    painter.setBrush(QColor(color))
    painter.drawEllipse(40, 40, 18, 18)
    painter.end()
    return QIcon(pix)


class TrayController(QObject):
    """封装 QSystemTrayIcon 与菜单，回调由 app 注入。"""

    def __init__(self, app_ctx) -> None:
        super().__init__()
        self._ctx = app_ctx
        self._icon_running = make_icon("#2f9e44")  # 绿色=运行中
        self._icon_stopped = make_icon("#868e96")  # 灰色=已停止
        self.tray = QSystemTrayIcon(self._icon_stopped)
        self.tray.setToolTip("MIMO_Connect")
        self._build_menu()
        self.tray.activated.connect(self._on_activated)

    def _build_menu(self) -> None:
        menu = QMenu()
        self.act_status = QAction("状态：已停止")
        self.act_status.setEnabled(False)
        self.act_toggle = QAction("启动引擎")
        self.act_toggle.triggered.connect(self._ctx.toggle_engine)
        self.act_logs = QAction("查看日志")
        self.act_logs.triggered.connect(self._ctx.show_logs)
        self.act_settings = QAction("设置")
        self.act_settings.triggered.connect(self._ctx.show_settings)
        act_quit = QAction("退出")
        act_quit.triggered.connect(self._ctx.quit)

        menu.addAction(self.act_status)
        menu.addSeparator()
        menu.addAction(self.act_toggle)
        menu.addAction(self.act_logs)
        menu.addAction(self.act_settings)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)

    def _on_activated(self, reason) -> None:
        # 双击托盘 → 打开日志窗口
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._ctx.show_logs()

    def set_running(self, running: bool) -> None:
        if running:
            self.tray.setIcon(self._icon_running)
            self.act_status.setText("状态：运行中")
            self.act_toggle.setText("停止引擎")
        else:
            self.tray.setIcon(self._icon_stopped)
            self.act_status.setText("状态：已停止")
            self.act_toggle.setText("启动引擎")

    def notify(self, title: str, message: str) -> None:
        self.tray.showMessage(title, message, self._icon_running, 4000)

    def show(self) -> None:
        self.tray.show()
