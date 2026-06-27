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
from gui.i18n import t


class AppController:
    """组合托盘 + 引擎 + 日志 + 设置，构成常驻应用。"""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        self._runner: EngineRunner | None = None
        self._running = False
        self._settings_win: SettingsWindow | None = None
        self._pending_restart = False  # 设置保存后请求的引擎重启

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
        self.tray.notify(t("app_name"), t("notify_engine_started"))

    def _on_stopped(self) -> None:
        self._running = False
        self.tray.set_running(False)
        self.log_view.set_running(False)
        self.tray.notify(t("app_name"), t("notify_engine_stopped"))
        # 设置保存触发的重启：引擎停稳后再启动一次，应用新配置。
        if self._pending_restart:
            self._pending_restart = False
            self.start_engine()

    def _on_failed(self, msg: str) -> None:
        self._running = False
        self.tray.set_running(False)
        self.log_view.set_running(False)
        self.log_view.append_line(t("engine_error_prefix", msg=msg))
        self.log_view.show()
        self.tray.notify(t("notify_engine_failed"), msg)

    def show_logs(self) -> None:
        self.log_view.show()
        self.log_view.raise_()
        self.log_view.activateWindow()

    def show_settings(self) -> None:
        self._settings_win = SettingsWindow()
        self._settings_win.lang_changed.connect(self._on_lang_changed)
        self._settings_win.restart_requested.connect(self._on_settings_saved)
        self._settings_win.show()
        self._settings_win.raise_()
        self._settings_win.activateWindow()

    def _on_settings_saved(self) -> None:
        # 引擎未运行：新配置会在下次启动时自然生效，无需打扰用户。
        if not self._running:
            return
        from PySide6.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            None,
            t("restart_now_title"),
            t("restart_now_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._pending_restart = True
            self.stop_engine()  # 停稳后 _on_stopped 会自动重启

    def _on_lang_changed(self, _lang: str) -> None:
        # 设置面板切换语言后，刷新常驻托盘菜单文案。
        self.tray.retranslate()

    def quit(self) -> None:
        if self._runner and self._running:
            self._runner.stop()
            self._runner.wait(8000)
        self.app.quit()


def run_gui() -> int:
    # 首次运行：在 exe 同目录自动创建 .env / config.yaml（不覆盖已有）。
    config_io.ensure_runtime_files()
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
        QMessageBox.warning(None, t("tray_unavailable_title"), t("tray_unavailable_body"))

    ctx = AppController(app)
    ctx.start_engine()  # 配置完成后自动启动引擎
    return app.exec()
