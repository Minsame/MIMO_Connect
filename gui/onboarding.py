"""首启分步引导向导（QWizard）。

步骤：欢迎 → 选择 LLM 并填写 key → 选择平台并填凭证 → 确认 mimo 路径/工作目录 → 完成。
完成后通过 core.config_io 写入 .env 与 config.yaml。

鲁棒性：每翻一页都会把已填字段写入本地草稿（core.config_io 的 .setup_draft.json），
中途关闭向导后重新打开会自动续填，无需从头再来。配置成功落盘后清除草稿。
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from core import config_io
from gui.i18n import t, current_lang, set_lang, LANG_LABELS
from gui.theme import Palette


def _make_watermark():
    """生成向导左侧品牌竖条（渐变 + 产品名），避免依赖外部图片资源。"""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

    w, h = 180, 520
    pix = QPixmap(w, h)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor("#2f6fed"))
    grad.setColorAt(1.0, QColor("#21429c"))
    painter.fillRect(0, 0, w, h, grad)

    # 品牌字母圆牌
    painter.setBrush(QColor(255, 255, 255, 38))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(28, 40, 64, 64)
    painter.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI", 30)
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(QRect(28, 40, 64, 64), Qt.AlignmentFlag.AlignCenter, "M")

    painter.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    painter.drawText(QRect(24, 128, w - 36, 60), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, "MIMO\nConnect")
    painter.setPen(QColor(255, 255, 255, 200))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(QRect(24, h - 96, w - 36, 80), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                     t("wiz_brand_sub"))
    painter.end()
    return pix


class WelcomePage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        self.setTitle(t("welcome_title"))
        self.setSubTitle(t("welcome_sub"))
        layout = QVBoxLayout(self)

        # 语言选择（首启即可切换，立即作用于整个向导）
        lang_row = QHBoxLayout()
        self.lbl_lang = QLabel(t("welcome_lang"))
        self.cmb_lang = QComboBox()
        for code, label in LANG_LABELS:
            self.cmb_lang.addItem(label, code)
        idx = self.cmb_lang.findData(current_lang())
        if idx >= 0:
            self.cmb_lang.setCurrentIndex(idx)
        lang_row.addWidget(self.lbl_lang)
        lang_row.addWidget(self.cmb_lang)
        lang_row.addStretch(1)
        layout.addLayout(lang_row)

        self.msg = QLabel(t("welcome_body"))
        self.msg.setWordWrap(True)
        layout.addWidget(self.msg)
        self.tip = None
        if draft:
            self.tip = QLabel(t("welcome_draft_tip"))
            self.tip.setWordWrap(True)
            self.tip.setStyleSheet("color: #1a7f37;")
            layout.addWidget(self.tip)

    def retranslate(self) -> None:
        self.setTitle(t("welcome_title"))
        self.setSubTitle(t("welcome_sub"))
        self.lbl_lang.setText(t("welcome_lang"))
        self.msg.setText(t("welcome_body"))
        if self.tip is not None:
            self.tip.setText(t("welcome_draft_tip"))


class LLMPage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        draft = draft or {}
        self.setTitle(t("p1_title"))
        self.setSubTitle(t("p1_sub"))
        self.form = form = QFormLayout(self)
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItems(list(config_io.PROVIDER_PRESETS.keys()))
        self.cmb_provider.currentTextChanged.connect(self._apply_preset)
        self.ed_base_url = QLineEdit()
        self.ed_model = QLineEdit()
        self.ed_api_key = QLineEdit()
        self.ed_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t("field_provider"), self.cmb_provider)
        form.addRow(t("field_base_url"), self.ed_base_url)
        form.addRow(t("field_model"), self.ed_model)
        form.addRow(t("field_api_key"), self.ed_api_key)
        # 先按草稿恢复提供商，再据此填默认 base_url/model，最后用草稿覆盖。
        if draft.get("llm_provider") in config_io.PROVIDER_PRESETS:
            self.cmb_provider.setCurrentText(draft["llm_provider"])
        self._apply_preset(self.cmb_provider.currentText())
        if draft.get("llm_base_url"):
            self.ed_base_url.setText(draft["llm_base_url"])
        if draft.get("llm_model"):
            self.ed_model.setText(draft["llm_model"])
        if draft.get("llm_api_key"):
            self.ed_api_key.setText(draft["llm_api_key"])
        # 注册字段，便于后续读取；api_key 必填。
        self.registerField("llm_provider", self.cmb_provider, "currentText")
        self.registerField("llm_base_url", self.ed_base_url)
        self.registerField("llm_model", self.ed_model)
        self.registerField("llm_api_key*", self.ed_api_key)

    def retranslate(self) -> None:
        self.setTitle(t("p1_title"))
        self.setSubTitle(t("p1_sub"))
        self.form.labelForField(self.cmb_provider).setText(t("field_provider"))
        self.form.labelForField(self.ed_base_url).setText(t("field_base_url"))
        self.form.labelForField(self.ed_model).setText(t("field_model"))
        self.form.labelForField(self.ed_api_key).setText(t("field_api_key"))

    def _apply_preset(self, provider: str) -> None:
        preset = config_io.PROVIDER_PRESETS.get(provider, {})
        self.ed_base_url.setText(preset.get("base_url", ""))
        self.ed_model.setText(preset.get("model", ""))


class PlatformPage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        draft = draft or {}
        self.setTitle(t("p2_title"))
        self.setSubTitle(t("p2_sub"))
        self.form = form = QFormLayout(self)
        self.cmb_platform = QComboBox()
        self.cmb_platform.addItems(["feishu", "weixin"])
        self.cmb_platform.currentTextChanged.connect(self._toggle)
        self.ed_feishu_id = QLineEdit()
        self.ed_feishu_secret = QLineEdit()
        self.ed_feishu_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.lbl_weixin = QLabel(t("p2_weixin_note"))
        self.lbl_weixin.setWordWrap(True)
        form.addRow(t("field_platform"), self.cmb_platform)
        form.addRow(t("field_feishu_id"), self.ed_feishu_id)
        form.addRow(t("field_feishu_secret"), self.ed_feishu_secret)
        form.addRow("", self.lbl_weixin)
        if draft.get("platform") in ("feishu", "weixin"):
            self.cmb_platform.setCurrentText(draft["platform"])
        if draft.get("feishu_app_id"):
            self.ed_feishu_id.setText(draft["feishu_app_id"])
        if draft.get("feishu_app_secret"):
            self.ed_feishu_secret.setText(draft["feishu_app_secret"])
        self.registerField("platform", self.cmb_platform, "currentText")
        self.registerField("feishu_id", self.ed_feishu_id)
        self.registerField("feishu_secret", self.ed_feishu_secret)
        self._toggle(self.cmb_platform.currentText())

    def retranslate(self) -> None:
        self.setTitle(t("p2_title"))
        self.setSubTitle(t("p2_sub"))
        self.lbl_weixin.setText(t("p2_weixin_note"))
        self.form.labelForField(self.cmb_platform).setText(t("field_platform"))
        self.form.labelForField(self.ed_feishu_id).setText(t("field_feishu_id"))
        self.form.labelForField(self.ed_feishu_secret).setText(t("field_feishu_secret"))

    def _toggle(self, platform: str) -> None:
        is_feishu = platform == "feishu"
        self.ed_feishu_id.setEnabled(is_feishu)
        self.ed_feishu_secret.setEnabled(is_feishu)
        self.lbl_weixin.setVisible(not is_feishu)

    def validatePage(self) -> bool:
        if self.cmb_platform.currentText() == "feishu":
            if not self.ed_feishu_id.text().strip() or not self.ed_feishu_secret.text().strip():
                return False
        return True


class RuntimePage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        draft = draft or {}
        self.setTitle(t("p3_title"))
        self.setSubTitle(t("p3_sub"))
        layout = QVBoxLayout(self)
        # 未检测到 mimo CLI 时，在表单上方给出醒目提醒。
        self.lbl_cli_warn = QLabel(t("p3_cli_warn"))
        self.lbl_cli_warn.setWordWrap(True)
        self.lbl_cli_warn.setStyleSheet("color: #b4690e;")
        layout.addWidget(self.lbl_cli_warn)
        self.form = form = QFormLayout()
        layout.addLayout(form)
        self.ed_mimo_path = QLineEdit()
        detected = config_io.find_mimo_cli()
        draft_cli = draft.get("mimo_code_path", "")
        if detected:
            self.lbl_cli_warn.setVisible(False)
            self.ed_mimo_path.setText(detected)
            self.ed_mimo_path.setPlaceholderText(t("p3_cli_detected_ph"))
        else:
            self.lbl_cli_warn.setVisible(True)
            self.ed_mimo_path.setPlaceholderText(t("p3_cli_blank_ph"))
        if draft_cli:
            self.ed_mimo_path.setText(draft_cli)
        self.ed_work_dir = QLineEdit()
        self.ed_work_dir.setText(
            draft.get("work_dir")
            or os.getenv("MIMO_CONNECT_WORK_DIR", str(config_io.PROJECT_ROOT))
        )
        self.ed_mimo_model = QLineEdit()
        if draft.get("agent_model"):
            self.ed_mimo_model.setText(draft["agent_model"])
        self.ed_mimo_key = QLineEdit()
        self.ed_mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        if draft.get("mimo_api_key"):
            self.ed_mimo_key.setText(draft["mimo_api_key"])
        form.addRow(t("field_mimo_path"), self.ed_mimo_path)
        form.addRow(t("field_work_dir"), self.ed_work_dir)
        form.addRow(t("field_mimo_model"), self.ed_mimo_model)
        form.addRow(t("field_mimo_key"), self.ed_mimo_key)
        self.registerField("mimo_path", self.ed_mimo_path)
        self.registerField("work_dir", self.ed_work_dir)
        self.registerField("mimo_model", self.ed_mimo_model)
        self.registerField("mimo_key", self.ed_mimo_key)


    def retranslate(self) -> None:
        self.setTitle(t("p3_title"))
        self.setSubTitle(t("p3_sub"))
        self.lbl_cli_warn.setText(t("p3_cli_warn"))
        self.form.labelForField(self.ed_mimo_path).setText(t("field_mimo_path"))
        self.form.labelForField(self.ed_work_dir).setText(t("field_work_dir"))
        self.form.labelForField(self.ed_mimo_model).setText(t("field_mimo_model"))
        self.form.labelForField(self.ed_mimo_key).setText(t("field_mimo_key"))


class OnboardingWizard(QWizard):
    """首启引导向导；accept() 时把字段写入 .env / config.yaml。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # 载入上次未完成的草稿，用于断点续填。
        self._draft = config_io.read_draft()
        self.setWindowTitle(t("wiz_title"))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoDefaultButton, False)
        self.resize(720, 520)
        # 左侧品牌竖条，让向导更有产品感。
        try:
            self.setPixmap(QWizard.WizardPixmap.WatermarkPixmap, _make_watermark())
        except Exception:
            pass
        self._welcome = WelcomePage(self._draft)
        self._pages = [
            self._welcome,
            LLMPage(self._draft),
            PlatformPage(self._draft),
            RuntimePage(self._draft),
        ]
        for page in self._pages:
            self.addPage(page)
        # 首启语言选择：切换即刷新整个向导
        self._welcome.cmb_lang.currentIndexChanged.connect(self._on_lang_changed)
        self.setButtonText(QWizard.WizardButton.FinishButton, t("wiz_finish"))
        self.setButtonText(QWizard.WizardButton.NextButton, t("wiz_next"))
        self.setButtonText(QWizard.WizardButton.BackButton, t("wiz_back"))
        self.setButtonText(QWizard.WizardButton.CancelButton, t("wiz_cancel"))
        # 每次离开一页时把已填字段写入草稿，支持中途关闭后续填。
        self.currentIdChanged.connect(self._persist_draft)

    def _on_lang_changed(self, _idx: int) -> None:
        code = self._welcome.cmb_lang.currentData()
        if not code:
            return
        set_lang(code, persist=True)
        self._retranslate_all()

    def _retranslate_all(self) -> None:
        self.setWindowTitle(t("wiz_title"))
        self.setButtonText(QWizard.WizardButton.FinishButton, t("wiz_finish"))
        self.setButtonText(QWizard.WizardButton.NextButton, t("wiz_next"))
        self.setButtonText(QWizard.WizardButton.BackButton, t("wiz_back"))
        self.setButtonText(QWizard.WizardButton.CancelButton, t("wiz_cancel"))
        for page in self._pages:
            if hasattr(page, "retranslate"):
                page.retranslate()

    def _persist_draft(self, _page_id: int = -1) -> None:
        """把当前已填字段快照写入本地草稿（空值不覆盖）。"""
        snapshot = {
            "llm_provider": self.field("llm_provider") or "",
            "llm_base_url": (self.field("llm_base_url") or "").strip(),
            "llm_model": (self.field("llm_model") or "").strip(),
            "llm_api_key": (self.field("llm_api_key") or "").strip(),
            "platform": self.field("platform") or "",
            "feishu_app_id": (self.field("feishu_id") or "").strip(),
            "feishu_app_secret": (self.field("feishu_secret") or "").strip(),
            "mimo_code_path": (self.field("mimo_path") or "").strip(),
            "work_dir": (self.field("work_dir") or "").strip(),
            "agent_model": (self.field("mimo_model") or "").strip(),
            "mimo_api_key": (self.field("mimo_key") or "").strip(),
        }
        config_io.write_draft({k: v for k, v in snapshot.items() if v})

    def accept(self) -> None:
        provider = self.field("llm_provider")
        preset = config_io.PROVIDER_PRESETS[provider]
        platform = self.field("platform")
        values = {
            preset["env_key"]: (self.field("llm_api_key") or "").strip(),
            "MIMO_API_KEY": (self.field("mimo_key") or "").strip(),
            "MIMO_CONNECT_PLATFORM": platform,
            "FEISHU_APP_ID": (self.field("feishu_id") or "").strip(),
            "FEISHU_APP_SECRET": (self.field("feishu_secret") or "").strip(),
            "MIMO_CODE_PATH": (self.field("mimo_path") or "").strip(),
            "MIMO_CONNECT_WORK_DIR": (self.field("work_dir") or "").strip(),
            "MIMO_CONNECT_MODEL": (self.field("mimo_model") or "").strip(),
        }
        config_io.write_env(values)
        config_io.sync_config_yaml(
            provider,
            (self.field("llm_base_url") or "").strip(),
            (self.field("llm_model") or "").strip(),
        )
        # 配置成功落盘后清除草稿。
        config_io.clear_draft()
        super().accept()
