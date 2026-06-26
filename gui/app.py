"""GUI 应用控制器：首启检测 → 引导页 / 托盘，统筹引擎、日志、设置窗口。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from core import config_io
from gui.engine_runner import EngineRunner, QtLogHandler
from gui.log_view import LogView
from gui.onboarding import OnboardingWizard
from gui.settings import SettingsWindow
from gui.tray import TrayController


class AppController:
    """组合托盘 + 引擎 + 日志 + 设置，构成常驻应用。"""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        self._runner: EngineRunner | None = None
        self._running = False
        self._settings_win: SettingsWindow | None = None

        self.log_view = LogView()
        self.log_handler = QtLogHandler()
        self.log_handler.record_emitted.connect(self.log_view.append_line)
        # 把 GUI 日志处理器挂到根 logger，捕获引擎全部日志。
        import logging
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.INFO)

        self.tray = TrayController(self)
        self.tray.show()
        self.tray.set_running(False)

    # ---- 托盘回调 ----
    def toggle_engine(self) -> None:
        if self._running:
            self.stop_engine()
        else:
            self.start_engine()

    def start_engine(self) -> None:
        if self._running:
            return
        self._runner = EngineRunner()
        self._runner.started_ok.connect(self._on_started)
        self._runner.stopped.connect(self._on_stopped)
        self._runner.failed.connect(self._on_failed)
        self._runner.start()

    def stop_engine(self) -> None:
        if self._runner and self._running:
            self._runner.stop()

    def _on_started(self) -> None:
        self._running = True
        self.tray.set_running(True)
        self.log_view.set_running(True)
        self.tray.notify("MIMO_Connect", "引擎已启动")

    def _on_stopped(self) -> None:
        self._running = False
        self.tray.set_running(False)
        self.log_view.set_running(False)
        self.tray.notify("MIMO_Connect", "引擎已停止")

    def _on_failed(self, msg: str) -> None:
        self._running = False
        self.tray.set_running(False)
        self.log_view.set_running(False)
        self.log_view.append_line(f"[引擎错误] {msg}")
        self.log_view.show()
        self.tray.notify("引擎启动失败", msg)

    def show_logs(self) -> None:
        self.log_view.show()
        self.log_view.raise_()
        self.log_view.activateWindow()

    def show_settings(self) -> None:
        self._settings_win = SettingsWindow()
        self._settings_win.show()
        self._settings_win.raise_()
        self._settings_win.activateWindow()

    def quit(self) -> None:
        if self._runner and self._running:
            self._runner.stop()
            self._runner.wait(8000)
        self.app.quit()


def run_gui() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MIMO_Connect")
    app.setQuitOnLastWindowClosed(False)  # 关窗口不退出，留在托盘
    # 应用统一设计系统（配色/字体/控件样式）。
    from gui.theme import apply_theme
    apply_theme(app)

    # 首启检测：未配置则先跑引导向导。
    if not config_io.is_configured():
        wizard = OnboardingWizard()
        if wizard.exec() != OnboardingWizard.DialogCode.Accepted:
            return 0  # 用户取消首次配置 → 退出
        # 让后续读取到刚写入的 .env
        from dotenv import load_dotenv
        load_dotenv(config_io.ENV_PATH, override=True)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            None, "托盘不可用",
            "当前系统未提供系统托盘。应用仍会运行，可手动打开日志窗口。",
        )

    ctx = AppController(app)
    ctx.start_engine()  # 配置完成后自动启动引擎
    return app.exec()
