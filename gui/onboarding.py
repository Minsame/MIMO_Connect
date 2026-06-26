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
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from core import config_io
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
                     "用飞书 / 微信\n驱动本地 MiMo Code")
    painter.end()
    return pix


class WelcomePage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        self.setTitle("欢迎使用 MIMO_Connect")
        self.setSubTitle("用飞书 / 微信驱动本地 MiMo Code 编程。下面几步帮你完成首次配置。")
        layout = QVBoxLayout(self)
        msg = QLabel(
            "这个向导将引导你设置：\n\n"
            "  1. 中间层 LLM（用于意图识别）\n"
            "  2. 聊天平台（飞书或微信）\n"
            "  3. 本地 mimo CLI 位置与工作目录\n\n"
            "全部配置会保存到项目的 .env 文件，随时可在设置中修改。"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)
        if draft:
            tip = QLabel(
                "↻ 检测到上次未完成的配置，已为你预填先前填写的内容，可直接继续。"
            )
            tip.setWordWrap(True)
            tip.setStyleSheet("color: #1a7f37;")
            layout.addWidget(tip)


class LLMPage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        draft = draft or {}
        self.setTitle("第 1 步 · 中间层 LLM")
        self.setSubTitle("选择一个提供商并填入 API key（用于意图识别与文本整理）。")
        form = QFormLayout(self)
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItems(list(config_io.PROVIDER_PRESETS.keys()))
        self.cmb_provider.currentTextChanged.connect(self._apply_preset)
        self.ed_base_url = QLineEdit()
        self.ed_model = QLineEdit()
        self.ed_api_key = QLineEdit()
        self.ed_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("提供商", self.cmb_provider)
        form.addRow("API base_url", self.ed_base_url)
        form.addRow("模型", self.ed_model)
        form.addRow("API key", self.ed_api_key)
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

    def _apply_preset(self, provider: str) -> None:
        preset = config_io.PROVIDER_PRESETS.get(provider, {})
        self.ed_base_url.setText(preset.get("base_url", ""))
        self.ed_model.setText(preset.get("model", ""))


class PlatformPage(QWizardPage):
    def __init__(self, draft: dict[str, str] | None = None) -> None:
        super().__init__()
        draft = draft or {}
        self.setTitle("第 2 步 · 聊天平台")
        self.setSubTitle("选择消息平台。飞书配置最简单，推荐新手使用。")
        form = QFormLayout(self)
        self.cmb_platform = QComboBox()
        self.cmb_platform.addItems(["feishu", "weixin"])
        self.cmb_platform.currentTextChanged.connect(self._toggle)
        self.ed_feishu_id = QLineEdit()
        self.ed_feishu_secret = QLineEdit()
        self.ed_feishu_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.lbl_weixin = QLabel("微信需扫码登录，首次启动时会自动弹出二维码。")
        self.lbl_weixin.setWordWrap(True)
        form.addRow("平台", self.cmb_platform)
        form.addRow("飞书 APP_ID", self.ed_feishu_id)
        form.addRow("飞书 APP_SECRET", self.ed_feishu_secret)
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
        self.setTitle("第 3 步 · 运行配置")
        self.setSubTitle("确认本机 mimo CLI 位置与工作目录。")
        layout = QVBoxLayout(self)
        # 未检测到 mimo CLI 时，在表单上方给出醒目提醒。
        self.lbl_cli_warn = QLabel(
            "⚠ 未自动检测到 mimo CLI。请手动填写其完整可执行文件路径；"
            "留空则运行时按系统 PATH 查找（可能启动失败）。"
        )
        self.lbl_cli_warn.setWordWrap(True)
        self.lbl_cli_warn.setStyleSheet("color: #b4690e;")
        layout.addWidget(self.lbl_cli_warn)
        form = QFormLayout()
        layout.addLayout(form)
        self.ed_mimo_path = QLineEdit()
        detected = config_io.find_mimo_cli()
        draft_cli = draft.get("mimo_code_path", "")
        if detected:
            self.lbl_cli_warn.setVisible(False)
            self.ed_mimo_path.setText(detected)
            self.ed_mimo_path.setPlaceholderText("已自动检测")
        else:
            self.lbl_cli_warn.setVisible(True)
            self.ed_mimo_path.setPlaceholderText("未检测到，留空则运行时按 PATH 查找")
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
        form.addRow("mimo CLI 路径", self.ed_mimo_path)
        form.addRow("工作目录", self.ed_work_dir)
        form.addRow("MiMo 模型(可选)", self.ed_mimo_model)
        form.addRow("MiMo TTS key(可选)", self.ed_mimo_key)
        self.registerField("mimo_path", self.ed_mimo_path)
        self.registerField("work_dir", self.ed_work_dir)
        self.registerField("mimo_model", self.ed_mimo_model)
        self.registerField("mimo_key", self.ed_mimo_key)


class OnboardingWizard(QWizard):
    """首启引导向导；accept() 时把字段写入 .env / config.yaml。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # 载入上次未完成的草稿，用于断点续填。
        self._draft = config_io.read_draft()
        self.setWindowTitle("MIMO_Connect 首次配置")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoDefaultButton, False)
        self.resize(720, 520)
        # 左侧品牌竖条，让向导更有产品感。
        try:
            self.setPixmap(QWizard.WizardPixmap.WatermarkPixmap, _make_watermark())
        except Exception:
            pass
        self.addPage(WelcomePage(self._draft))
        self.addPage(LLMPage(self._draft))
        self.addPage(PlatformPage(self._draft))
        self.addPage(RuntimePage(self._draft))
        self.setButtonText(QWizard.WizardButton.FinishButton, "完成并启动")
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.setButtonText(QWizard.WizardButton.BackButton, "上一步")
        self.setButtonText(QWizard.WizardButton.CancelButton, "取消")
        # 每次离开一页时把已填字段写入草稿，支持中途关闭后续填。
        self.currentIdChanged.connect(self._persist_draft)

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
