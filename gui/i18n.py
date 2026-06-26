"""GUI 国际化（中文 / 英文）。

集中存放界面文案的双语映射，运行时按当前语言取串。
语言偏好与 CLI 共用，存于 .env 的 MIMO_CONNECT_LANG（见 core.config_io）。
"""

from __future__ import annotations

from core import config_io

_LANG = config_io.read_lang()


def current_lang() -> str:
    return _LANG


def set_lang(lang: str, persist: bool = True) -> None:
    """切换当前语言；persist=True 时写回 .env。"""
    global _LANG
    lang = (lang or "zh").strip().lower()
    if lang not in config_io.SUPPORTED_LANGS:
        lang = "zh"
    _LANG = lang
    if persist:
        try:
            config_io.write_lang(lang)
        except Exception:
            pass


def t(key: str, **kwargs: object) -> str:
    """取当前语言文案；缺失时回退英文再回退键名。带占位符时 format。"""
    table = _STRINGS.get(_LANG, _STRINGS["en"])
    text = table.get(key) or _STRINGS["en"].get(key) or key
    return text.format(**kwargs) if kwargs else text


# 语言下拉显示名（两种语言下都给出双语标签，避免误选）
LANG_LABELS = [("zh", "简体中文 / Chinese"), ("en", "English / 英文")]

_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "app_name": "MIMO_Connect",
        "btn_save": "保存",
        "btn_close": "关闭",
        "btn_cancel": "取消",
        "language": "语言",
        "tray_status_running": "状态：运行中",
        "tray_status_stopped": "状态：已停止",
        "tray_start": "启动引擎",
        "tray_stop": "停止引擎",
        "tray_logs": "查看日志",
        "tray_settings": "设置",
        "tray_quit": "退出",
        "notify_engine_started": "引擎已启动",
        "notify_engine_stopped": "引擎已停止",
        "notify_engine_failed": "引擎启动失败",
        "engine_error_prefix": "[引擎错误] {msg}",
        "tray_unavailable_title": "托盘不可用",
        "tray_unavailable_body": "当前系统未提供系统托盘。应用仍会运行，可手动打开日志窗口。",
        "log_window_title": "MIMO_Connect 运行日志",
        "log_search_ph": "搜索日志关键字…",
        "log_level": "级别",
        "log_autoscroll": "自动滚动",
        "log_open_file": "打开日志文件",
        "log_copy": "复制",
        "log_clear": "清空",
        "log_status_running": "运行中",
        "log_status_stopped": "已停止",
        "settings_title": "MIMO_Connect 设置",
        "settings_group_llm": "中间层 LLM（意图识别 / 段重写）",
        "settings_group_platform": "聊天平台",
        "settings_group_run": "运行配置",
        "field_provider": "提供商",
        "field_base_url": "API base_url",
        "field_model": "模型",
        "field_api_key": "API key",
        "field_platform": "平台",
        "field_feishu_id": "飞书 APP_ID",
        "field_feishu_secret": "飞书 APP_SECRET",
        "field_weixin_bot": "微信 BOT_ID",
        "field_weixin_token": "微信 TOKEN",
        "field_mimo_path": "mimo CLI 路径",
        "field_work_dir": "工作目录",
        "field_mimo_model": "MiMo 模型(可选)",
        "field_mimo_key": "MiMo TTS key(可选)",
        "settings_hint": "保存后需重启引擎方可生效（托盘菜单 → 停止/启动引擎）。",
        "settings_lang_restart": "语言已切换，部分界面需重新打开窗口后完全生效。",
        "missing_key_title": "缺少 API key",
        "missing_key_body": "请填写所选提供商的 API key。",
        "saved_title": "已保存",
        "saved_body": "配置已写入 .env。重启引擎后生效。",
        "wiz_title": "MIMO_Connect 首次配置",
        "wiz_finish": "完成并启动",
        "wiz_next": "下一步",
        "wiz_back": "上一步",
        "wiz_cancel": "取消",
        "wiz_brand_sub": "用飞书 / 微信\n驱动本地 MiMo Code",
        "welcome_title": "欢迎使用 MIMO_Connect",
        "welcome_sub": "用飞书 / 微信驱动本地 MiMo Code 编程。下面几步帮你完成首次配置。",
        "welcome_body": "这个向导将引导你设置：\n\n  1. 中间层 LLM（用于意图识别）\n  2. 聊天平台（飞书或微信）\n  3. 本地 mimo CLI 位置与工作目录\n\n全部配置会保存到项目的 .env 文件，随时可在设置中修改。",
        "welcome_lang": "界面语言",
        "welcome_draft_tip": "↻ 检测到上次未完成的配置，已为你预填先前填写的内容，可直接继续。",
        "p1_title": "第 1 步 · 中间层 LLM",
        "p1_sub": "选择一个提供商并填入 API key（用于意图识别与文本整理）。",
        "p2_title": "第 2 步 · 聊天平台",
        "p2_sub": "选择消息平台。飞书配置最简单，推荐新手使用。",
        "p2_weixin_note": "微信需扫码登录，首次启动时会自动弹出二维码。",
        "p3_title": "第 3 步 · 运行配置",
        "p3_sub": "确认本机 mimo CLI 位置与工作目录。",
        "p3_cli_warn": "⚠ 未自动检测到 mimo CLI。请手动填写其完整可执行文件路径；留空则运行时按系统 PATH 查找（可能启动失败）。",
        "p3_cli_detected_ph": "已自动检测",
        "p3_cli_blank_ph": "未检测到，留空则运行时按 PATH 查找",
    },
    "en": {
        "app_name": "MIMO_Connect",
        "btn_save": "Save",
        "btn_close": "Close",
        "btn_cancel": "Cancel",
        "language": "Language",
        "tray_status_running": "Status: Running",
        "tray_status_stopped": "Status: Stopped",
        "tray_start": "Start engine",
        "tray_stop": "Stop engine",
        "tray_logs": "View logs",
        "tray_settings": "Settings",
        "tray_quit": "Quit",
        "notify_engine_started": "Engine started",
        "notify_engine_stopped": "Engine stopped",
        "notify_engine_failed": "Engine failed to start",
        "engine_error_prefix": "[Engine error] {msg}",
        "tray_unavailable_title": "Tray unavailable",
        "tray_unavailable_body": "No system tray is available. The app still runs; open the log window manually.",
        "log_window_title": "MIMO_Connect Logs",
        "log_search_ph": "Search logs…",
        "log_level": "Level",
        "log_autoscroll": "Auto-scroll",
        "log_open_file": "Open log file",
        "log_copy": "Copy",
        "log_clear": "Clear",
        "log_status_running": "Running",
        "log_status_stopped": "Stopped",
        "settings_title": "MIMO_Connect Settings",
        "settings_group_llm": "Middleware LLM (intent / rewrite)",
        "settings_group_platform": "Chat platform",
        "settings_group_run": "Runtime",
        "field_provider": "Provider",
        "field_base_url": "API base_url",
        "field_model": "Model",
        "field_api_key": "API key",
        "field_platform": "Platform",
        "field_feishu_id": "Feishu APP_ID",
        "field_feishu_secret": "Feishu APP_SECRET",
        "field_weixin_bot": "Weixin BOT_ID",
        "field_weixin_token": "Weixin TOKEN",
        "field_mimo_path": "mimo CLI path",
        "field_work_dir": "Working directory",
        "field_mimo_model": "MiMo model (optional)",
        "field_mimo_key": "MiMo TTS key (optional)",
        "settings_hint": "Restart the engine to apply changes (tray menu -> Stop/Start engine).",
        "settings_lang_restart": "Language switched; reopen windows for it to fully apply.",
        "missing_key_title": "Missing API key",
        "missing_key_body": "Please enter the API key for the selected provider.",
        "saved_title": "Saved",
        "saved_body": "Configuration written to .env. Restart the engine to apply.",
        "wiz_title": "MIMO_Connect First-time Setup",
        "wiz_finish": "Finish & Launch",
        "wiz_next": "Next",
        "wiz_back": "Back",
        "wiz_cancel": "Cancel",
        "wiz_brand_sub": "Drive local MiMo Code\nfrom Feishu / Weixin",
        "welcome_title": "Welcome to MIMO_Connect",
        "welcome_sub": "Drive local MiMo Code coding from Feishu / Weixin. A few steps to finish first-time setup.",
        "welcome_body": "This wizard will help you set up:\n\n  1. Middleware LLM (for intent recognition)\n  2. Chat platform (Feishu or Weixin)\n  3. Local mimo CLI path & working directory\n\nAll settings are saved to the project .env and can be changed later in Settings.",
        "welcome_lang": "Interface language",
        "welcome_draft_tip": "↻ Found an unfinished setup; your previous entries are pre-filled so you can continue.",
        "p1_title": "Step 1 · Middleware LLM",
        "p1_sub": "Pick a provider and enter its API key (used for intent recognition and text shaping).",
        "p2_title": "Step 2 · Chat Platform",
        "p2_sub": "Choose a messaging platform. Feishu is the easiest and recommended for beginners.",
        "p2_weixin_note": "Weixin requires QR-code login; the QR code pops up on first launch.",
        "p3_title": "Step 3 · Runtime",
        "p3_sub": "Confirm the local mimo CLI path and working directory.",
        "p3_cli_warn": "⚠ mimo CLI not auto-detected. Enter its full executable path; leaving blank falls back to PATH at runtime (may fail to start).",
        "p3_cli_detected_ph": "Auto-detected",
        "p3_cli_blank_ph": "Not detected; blank = search PATH at runtime",
    },
}
