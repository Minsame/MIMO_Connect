"""MIMO_Connect GUI 统一设计系统。

集中定义配色、字号、间距与全局 QSS，所有窗口共用同一套视觉语言，
确保引导向导、设置面板、日志窗口风格一致（浅色、克制、工具感）。
"""

from __future__ import annotations


class Palette:
    """中性偏冷的浅色工具型配色（避免单一色相主导）。"""

    # 背景层次
    bg = "#f4f6f8"          # 窗口底色
    surface = "#ffffff"      # 卡片/输入框面
    surface_alt = "#eef1f5"  # 次级面（表头、分隔带）
    border = "#d9dee5"       # 描边

    # 文本
    text = "#1c2430"         # 主文本
    text_muted = "#5b6470"   # 次级文本/提示

    # 品牌主色与状态色
    primary = "#2f6fed"      # 主操作蓝
    primary_hover = "#2a63d6"
    primary_press = "#2455bd"
    success = "#1a7f37"      # 运行中/成功
    warning = "#b4690e"      # 提醒
    danger = "#c2384a"       # 错误
    neutral = "#868e96"      # 已停止/禁用

    # 终端/日志面板（深色，与浅色 chrome 对比，便于长时间阅读）
    log_bg = "#0f141b"
    log_fg = "#d7dde6"
    log_info = "#7fb2ff"
    log_warn = "#e0a13a"
    log_error = "#ff6b78"
    log_debug = "#7a8696"
    log_time = "#5f6b7a"


FONT_FAMILY = "Segoe UI, Microsoft YaHei UI, PingFang SC, Helvetica, Arial, sans-serif"
MONO_FAMILY = "Consolas, Cascadia Mono, Menlo, Monaco, monospace"


def app_qss() -> str:
    """返回应用级 QSS，挂到 QApplication 上，统一所有窗口外观。"""
    p = Palette
    return f"""
    QWidget {{
        background: {p.bg};
        color: {p.text};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}
    QLabel {{ background: transparent; }}
    QLabel[role="title"] {{ font-size: 17px; font-weight: 600; }}
    QLabel[role="subtitle"] {{ color: #5b6470; }}
    QLabel[role="hint"] {{ color: #5b6470; font-size: 12px; }}
    QLabel[role="warn"] {{ color: {p.warning}; }}
    QLabel[role="ok"] {{ color: {p.success}; }}

    QGroupBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        margin-top: 14px;
        padding: 12px 12px 10px 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {p.text};
    }}

    QLineEdit, QComboBox, QPlainTextEdit {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {p.primary};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p.primary}; }}
    QLineEdit:disabled, QComboBox:disabled {{
        background: {p.surface_alt};
        color: {p.neutral};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}

    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 6px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{ background: {p.surface_alt}; }}
    QPushButton:pressed {{ background: {p.border}; }}
    QPushButton[role="primary"] {{
        background: {p.primary};
        color: #ffffff;
        border: 1px solid {p.primary};
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
    QPushButton[role="primary"]:pressed {{ background: {p.primary_press}; border-color: {p.primary_press}; }}

    QCheckBox {{ spacing: 6px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #c2c9d2; border-radius: 5px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: #aab2bd; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def apply_theme(app) -> None:
    """把统一 QSS 应用到 QApplication。"""
    app.setStyleSheet(app_qss())


def set_role(widget, role: str) -> None:
    """给控件打 role 动态属性（驱动 QSS 选择器），并刷新样式。"""
    widget.setProperty("role", role)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
