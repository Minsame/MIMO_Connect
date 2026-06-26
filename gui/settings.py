"""设置窗口：编辑 LLM / 平台 / mimo 路径等，保存回 .env 与 config.yaml。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import config_io
from gui.theme import set_role
from gui.i18n import t, current_lang, set_lang, LANG_LABELS


class SettingsWindow(QWidget):
    """非向导式的设置面板，供运行期随时调整配置。"""

    lang_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings_title"))
        self.resize(560, 520)
        self._env = config_io.read_env()
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ---- 语言分组 ----
        lang_box = QGroupBox(t("language"), self)
        lang_form = QFormLayout(lang_box)
        self.cmb_lang = QComboBox()
        for code, label in LANG_LABELS:
            self.cmb_lang.addItem(label, code)
        idx = self.cmb_lang.findData(current_lang())
        if idx >= 0:
            self.cmb_lang.setCurrentIndex(idx)
        lang_form.addRow(t("language"), self.cmb_lang)
        layout.addWidget(lang_box)

        # ---- LLM 分组 ----
        llm_box = QGroupBox(t("settings_group_llm"), self)
        llm_form = QFormLayout(llm_box)
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItems(list(config_io.PROVIDER_PRESETS.keys()))
        self.cmb_provider.currentTextChanged.connect(self._on_provider_changed)
        self.ed_base_url = QLineEdit()
        self.ed_model = QLineEdit()
        self.ed_api_key = QLineEdit()
        self.ed_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        llm_form.addRow(t("field_provider"), self.cmb_provider)
        llm_form.addRow(t("field_base_url"), self.ed_base_url)
        llm_form.addRow(t("field_model"), self.ed_model)
        llm_form.addRow(t("field_api_key"), self.ed_api_key)
        layout.addWidget(llm_box)

        # ---- 平台分组 ----
        plat_box = QGroupBox(t("settings_group_platform"), self)
        plat_form = QFormLayout(plat_box)
        self.cmb_platform = QComboBox()
        self.cmb_platform.addItems(["feishu", "weixin"])
        self.cmb_platform.currentTextChanged.connect(self._on_platform_changed)
        self.ed_feishu_id = QLineEdit()
        self.ed_feishu_secret = QLineEdit()
        self.ed_feishu_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_weixin_bot = QLineEdit()
        self.ed_weixin_token = QLineEdit()
        self.ed_weixin_token.setEchoMode(QLineEdit.EchoMode.Password)
        plat_form.addRow(t("field_platform"), self.cmb_platform)
        plat_form.addRow(t("field_feishu_id"), self.ed_feishu_id)
        plat_form.addRow(t("field_feishu_secret"), self.ed_feishu_secret)
        plat_form.addRow(t("field_weixin_bot"), self.ed_weixin_bot)
        plat_form.addRow(t("field_weixin_token"), self.ed_weixin_token)
        layout.addWidget(plat_box)

        # ---- 运行分组 ----
        run_box = QGroupBox(t("settings_group_run"), self)
        run_form = QFormLayout(run_box)
        self.ed_mimo_path = QLineEdit()
        self.ed_work_dir = QLineEdit()
        self.ed_mimo_model = QLineEdit()
        self.ed_mimo_key = QLineEdit()
        self.ed_mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        run_form.addRow(t("field_mimo_path"), self.ed_mimo_path)
        run_form.addRow(t("field_work_dir"), self.ed_work_dir)
        run_form.addRow(t("field_mimo_model"), self.ed_mimo_model)
        run_form.addRow(t("field_mimo_key"), self.ed_mimo_key)
        layout.addWidget(run_box)

        self.lbl_hint = QLabel(t("settings_hint"), self)
        set_role(self.lbl_hint, "hint")
        layout.addWidget(self.lbl_hint)

        bar = QHBoxLayout()
        bar.addStretch(1)
        btn_save = QPushButton(t("btn_save"), self)
        btn_save.clicked.connect(self._save)
        set_role(btn_save, "primary")
        btn_close = QPushButton(t("btn_close"), self)
        btn_close.clicked.connect(self.close)
        bar.addWidget(btn_save)
        bar.addWidget(btn_close)
        layout.addLayout(bar)

    def _on_provider_changed(self, provider: str) -> None:
        preset = config_io.PROVIDER_PRESETS.get(provider, {})
        # 仅在字段为空时填充预设，避免覆盖用户已填内容。
        if not self.ed_base_url.text().strip():
            self.ed_base_url.setText(preset.get("base_url", ""))
        if not self.ed_model.text().strip():
            self.ed_model.setText(preset.get("model", ""))

    def _on_platform_changed(self, platform: str) -> None:
        is_feishu = platform in ("feishu", "lark")
        self.ed_feishu_id.setEnabled(is_feishu)
        self.ed_feishu_secret.setEnabled(is_feishu)
        self.ed_weixin_bot.setEnabled(not is_feishu)
        self.ed_weixin_token.setEnabled(not is_feishu)

    def _load_values(self) -> None:
        env = self._env
        # 推断当前 provider：哪个 key 有值就选哪个。
        provider = "deepseek"
        for name, preset in config_io.PROVIDER_PRESETS.items():
            if env.get(preset["env_key"]):
                provider = name
                break
        self.cmb_provider.setCurrentText(provider)
        preset = config_io.PROVIDER_PRESETS[provider]
        self.ed_base_url.setText(preset.get("base_url", ""))
        self.ed_model.setText(preset.get("model", ""))
        self.ed_api_key.setText(env.get(preset["env_key"], ""))

        platform = env.get("MIMO_CONNECT_PLATFORM", "feishu").lower()
        if platform == "lark":
            platform = "feishu"
        self.cmb_platform.setCurrentText(platform if platform in ("feishu", "weixin") else "feishu")
        self.ed_feishu_id.setText(env.get("FEISHU_APP_ID", ""))
        self.ed_feishu_secret.setText(env.get("FEISHU_APP_SECRET", ""))
        self.ed_weixin_bot.setText(env.get("WEIXIN_BOT_ID", ""))
        self.ed_weixin_token.setText(env.get("WEIXIN_TOKEN", ""))
        self.ed_mimo_path.setText(env.get("MIMO_CODE_PATH", ""))
        self.ed_work_dir.setText(env.get("MIMO_CONNECT_WORK_DIR", ""))
        self.ed_mimo_model.setText(env.get("MIMO_CONNECT_MODEL", ""))
        self.ed_mimo_key.setText(env.get("MIMO_API_KEY", ""))
        self._on_platform_changed(self.cmb_platform.currentText())

    def _save(self) -> None:
        provider = self.cmb_provider.currentText()
        preset = config_io.PROVIDER_PRESETS[provider]
        api_key = self.ed_api_key.text().strip()
        if not api_key:
            QMessageBox.warning(self, t("missing_key_title"), t("missing_key_body"))
            return
        platform = self.cmb_platform.currentText()
        values = {
            preset["env_key"]: api_key,
            "MIMO_API_KEY": self.ed_mimo_key.text().strip(),
            "MIMO_CONNECT_PLATFORM": platform,
            "FEISHU_APP_ID": self.ed_feishu_id.text().strip(),
            "FEISHU_APP_SECRET": self.ed_feishu_secret.text().strip(),
            "WEIXIN_BOT_ID": self.ed_weixin_bot.text().strip(),
            "WEIXIN_TOKEN": self.ed_weixin_token.text().strip(),
            "MIMO_CODE_PATH": self.ed_mimo_path.text().strip(),
            "MIMO_CONNECT_WORK_DIR": self.ed_work_dir.text().strip(),
            "MIMO_CONNECT_MODEL": self.ed_mimo_model.text().strip(),
            "MIMO_CONNECT_LANG": self.cmb_lang.currentData() or current_lang(),
        }
        config_io.write_env(values)
        config_io.sync_config_yaml(provider, self.ed_base_url.text().strip(), self.ed_model.text().strip())
        new_lang = self.cmb_lang.currentData() or current_lang()
        lang_switched = new_lang != current_lang()
        if lang_switched:
            set_lang(new_lang, persist=False)  # .env 已含 MIMO_CONNECT_LANG，无需重复写
            self.lang_changed.emit(new_lang)
        QMessageBox.information(self, t("saved_title"), t("saved_body"))
        self.close()
