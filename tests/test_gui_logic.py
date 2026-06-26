"""GUI 逻辑无头单测：theme / log_view / settings / onboarding。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 not installed; skip GUI tests")

from core import config_io


def test_theme_qss_has_core_selectors(qapp):
    from gui import theme

    qss = theme.app_qss()
    for sel in ("QWidget", "QPushButton", "QLineEdit", "QGroupBox", 'role="primary"'):
        assert sel in qss


def test_theme_apply_and_set_role(qapp):
    from PySide6.QtWidgets import QPushButton
    from gui import theme

    theme.apply_theme(qapp)
    assert qapp.styleSheet()
    btn = QPushButton("x")
    theme.set_role(btn, "primary")
    assert btn.property("role") == "primary"

def test_logview_level_parsing(qapp):
    from gui.log_view import LogView

    lv = LogView()
    assert lv._parse_level("12:00:00 [INFO] x: hi") == "INFO"
    assert lv._parse_level("12:00:00 [WARNING] x: hi") == "WARNING"
    assert lv._parse_level("12:00:00 [ERROR] x: boom") == "ERROR"
    assert lv._parse_level("12:00:00 [CRITICAL] x: dead") == "CRITICAL"
    assert lv._parse_level("no level here") == "INFO"


def test_logview_counts_increment(qapp):
    from gui.log_view import LogView

    lv = LogView()
    lv.append_line("t [INFO] a: 1")
    lv.append_line("t [INFO] a: 2")
    lv.append_line("t [WARNING] a: w")
    lv.append_line("t [ERROR] a: e")
    assert lv._counts_map == {"INFO": 2, "WARNING": 1, "ERROR": 1}


def test_logview_level_filter_passes(qapp):
    from gui.log_view import LogView

    lv = LogView()
    assert lv._passes("INFO", "t [INFO] a: x")
    lv._on_level_changed("ERROR")
    assert not lv._passes("INFO", "t [INFO] a: x")
    assert not lv._passes("WARNING", "t [WARNING] a: x")
    assert lv._passes("ERROR", "t [ERROR] a: x")
    assert lv._passes("CRITICAL", "t [CRITICAL] a: x")


def test_logview_text_filter(qapp):
    from gui.log_view import LogView

    lv = LogView()
    lv._on_filter_changed("Model not found")
    assert lv._passes("ERROR", "t [ERROR] agent: Model not found: x")
    assert not lv._passes("ERROR", "t [ERROR] agent: something else")
    lv._on_filter_changed("FEISHU")
    assert lv._passes("INFO", "t [INFO] platforms.feishu: connected")


def test_logview_clear_resets(qapp):
    from gui.log_view import LogView

    lv = LogView()
    lv.append_line("t [ERROR] a: e")
    lv._clear()
    assert lv._counts_map == {"INFO": 0, "WARNING": 0, "ERROR": 0}
    assert len(lv._buffer) == 0


def test_logview_set_running_status(qapp):
    from gui.log_view import LogView

    lv = LogView()
    lv.set_running(True)
    assert lv._status.text() == "\u8fd0\u884c\u4e2d"
    lv.set_running(False)
    assert lv._status.text() == "\u5df2\u505c\u6b62"


def test_logview_buffer_capped(qapp):
    from gui.log_view import LogView

    lv = LogView()
    for i in range(LogView.MAX_LINES + 50):
        lv.append_line(f"t [INFO] a: {i}")
    assert len(lv._buffer) == LogView.MAX_LINES

def test_settings_loads_env(qapp, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    config_io.write_env(
        {
            "DEEPSEEK_API_KEY": "sk-deep",
            "MIMO_CONNECT_PLATFORM": "feishu",
            "FEISHU_APP_ID": "app123",
            "FEISHU_APP_SECRET": "secret456",
            "MIMO_CODE_PATH": "/usr/bin/mimo",
            "MIMO_CONNECT_WORK_DIR": "/work",
        },
        env,
    )
    monkeypatch.setattr(config_io, "ENV_PATH", env)
    from gui.settings import SettingsWindow

    win = SettingsWindow()
    assert win.cmb_provider.currentText() == "deepseek"
    assert win.ed_api_key.text() == "sk-deep"
    assert win.cmb_platform.currentText() == "feishu"
    assert win.ed_feishu_id.text() == "app123"
    assert win.ed_mimo_path.text() == "/usr/bin/mimo"
    assert win.ed_work_dir.text() == "/work"


def test_settings_save_roundtrip(qapp, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "llm:\n  active_provider: deepseek\n  providers:\n    deepseek:\n      base_url: x\n      model: y\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_io, "ENV_PATH", env)
    monkeypatch.setattr(config_io, "CONFIG_PATH", cfg)
    import gui.settings as settings_mod
    # 拦截成功弹窗，避免模态对话框在无头环境阻塞。
    monkeypatch.setattr(settings_mod.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(settings_mod.QMessageBox, "warning", lambda *a, **k: None)
    from gui.settings import SettingsWindow

    win = SettingsWindow()
    win.cmb_provider.setCurrentText("deepseek")
    win.ed_api_key.setText("sk-new")
    win.ed_base_url.setText("https://api.deepseek.com")
    win.ed_model.setText("deepseek-chat")
    win.cmb_platform.setCurrentText("feishu")
    win.ed_feishu_id.setText("fid")
    win.ed_feishu_secret.setText("fsec")
    win.ed_mimo_path.setText("/bin/mimo")
    win.ed_work_dir.setText("/w")
    win._save()

    saved = config_io.read_env(env)
    assert saved["DEEPSEEK_API_KEY"] == "sk-new"
    assert saved["MIMO_CONNECT_PLATFORM"] == "feishu"
    assert saved["FEISHU_APP_ID"] == "fid"
    assert saved["MIMO_CODE_PATH"] == "/bin/mimo"


def test_settings_save_requires_api_key(qapp, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(config_io, "ENV_PATH", env)
    import gui.settings as settings_mod
    from gui.settings import SettingsWindow

    called = {"warn": False}
    monkeypatch.setattr(
        settings_mod.QMessageBox, "warning",
        lambda *a, **k: called.__setitem__("warn", True),
    )
    win = SettingsWindow()
    win.ed_api_key.setText("")
    win._save()
    assert called["warn"] is True
    assert not env.exists()

def test_onboarding_has_four_pages(qapp, tmp_path, monkeypatch):
    # 隔离草稿路径，避免构造向导时的自动存盘写到真实项目目录。
    monkeypatch.setattr(config_io, "DRAFT_PATH", tmp_path / ".setup_draft.json")
    from gui.onboarding import OnboardingWizard

    wiz = OnboardingWizard()
    assert len(wiz.pageIds()) == 4


def test_onboarding_prefills_from_draft(qapp, tmp_path, monkeypatch):
    draft = tmp_path / ".setup_draft.json"
    monkeypatch.setattr(config_io, "DRAFT_PATH", draft)
    config_io.write_draft(
        {
            "llm_provider": "openai",
            "llm_api_key": "sk-draft",
            "platform": "feishu",
            "feishu_app_id": "draft-id",
            "mimo_code_path": "/draft/mimo",
        },
        draft,
    )
    from gui.onboarding import LLMPage, PlatformPage, RuntimePage

    d = config_io.read_draft(draft)
    llm = LLMPage(d)
    assert llm.cmb_provider.currentText() == "openai"
    assert llm.ed_api_key.text() == "sk-draft"
    plat = PlatformPage(d)
    assert plat.cmb_platform.currentText() == "feishu"
    assert plat.ed_feishu_id.text() == "draft-id"
    rt = RuntimePage(d)
    assert rt.ed_mimo_path.text() == "/draft/mimo"


def test_onboarding_accept_writes_env_and_clears_draft(qapp, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    draft = tmp_path / ".setup_draft.json"
    cfg.write_text(
        "llm:\n  active_provider: deepseek\n  providers:\n    deepseek: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_io, "ENV_PATH", env)
    monkeypatch.setattr(config_io, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config_io, "DRAFT_PATH", draft)
    config_io.write_draft({"x": "1"}, draft)

    from gui.onboarding import OnboardingWizard

    wiz = OnboardingWizard()
    wiz.setField("llm_provider", "deepseek")
    wiz.setField("llm_api_key", "sk-zzz")
    wiz.setField("llm_base_url", "https://api.deepseek.com")
    wiz.setField("llm_model", "deepseek-chat")
    wiz.setField("platform", "feishu")
    wiz.setField("feishu_id", "fid")
    wiz.setField("feishu_secret", "fsec")
    wiz.setField("mimo_path", "/bin/mimo")
    wiz.setField("work_dir", "/w")
    wiz.setField("mimo_model", "")
    wiz.setField("mimo_key", "")
    wiz.accept()

    saved = config_io.read_env(env)
    assert saved["DEEPSEEK_API_KEY"] == "sk-zzz"
    assert saved["MIMO_CONNECT_PLATFORM"] == "feishu"
    assert saved["FEISHU_APP_ID"] == "fid"
    assert config_io.read_draft(draft) == {}


def test_tray_make_icon_nonnull(qapp):
    from gui.tray import make_icon

    icon = make_icon("#2f9e44")
    assert not icon.isNull()
