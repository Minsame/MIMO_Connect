"""MIMO_Connect 首次启动部署向导。

交互式收集首次运行所需的全部信息，并写入 .env，同时把 LLM 的
base_url / model 同步到 config.yaml 的 active_provider 配置：

  - LLM 提供商、API base_url、API key、模型名
  - 自动检索本机 mimo CLI 位置（写入 MIMO_CODE_PATH）
  - 运行平台（推荐 feishu；weixin 走扫码登录并记录 token/bot_id）
  - MiMo TTS key
  - MiMo Code 工作目录

启动时会先检测系统语言（中文则首条提示用中文，否则用英文），
随后由用户选择向导语言（中文 / 英文）。

用法（通常由 first_run.bat 调用，也可单独运行）：
    python scripts/first_run_setup.py            # 缺 .env 时引导
    python scripts/first_run_setup.py --force    # 强制重新配置
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from core import config_io  # noqa: E402  (after sys.path tweak)

ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# 当前向导语言（"zh" / "en"），由 choose_language() 设定
LANG = "zh"

# 全部交互文案的中英双语映射
MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        "title": "  MIMO_Connect 首次启动部署向导",
        "required": "  ! 该项必填，请输入。",
        "choose_one": "  ! 请输入 {opts} 之一。",
        "env_exists": ".env 已存在：{path}",
        "reconfigure_q": "是否重新配置？",
        "kept_env": "已保留现有 .env，跳过向导。",
        "step1_title": "[1/5] 中间件 LLM（用于意图识别/状态分类）",
        "choose_provider": "  选择提供商",
        "api_base_url": "  API base_url",
        "model_name": "  模型名称",
        "api_key": "  API key",
        "step2_title": "[2/5] 检索本机 mimo CLI 位置",
        "cli_detected": "  √ 已自动检测到：{path}",
        "cli_confirm": "  确认 mimo CLI 路径（回车采用检测值）",
        "cli_not_detected": "  ! 未自动检测到 mimo CLI。",
        "cli_hint": "    若已安装，请手动填写其完整路径；留空则运行时按 PATH 查找。",
        "cli_path": "  mimo CLI 路径",
        "step3_title": "[3/5] 运行平台（聊天通道）",
        "platform_feishu": "  feishu - 飞书机器人（推荐，WebSocket 长连接，配置简单）",
        "platform_weixin": "  weixin - 微信 iLink Bot（需扫码登录）",
        "choose_channel": "  选择通道",
        "feishu_app_id": "  飞书 FEISHU_APP_ID",
        "feishu_app_secret": "  飞书 FEISHU_APP_SECRET",
        "weixin_intro": "  即将打开微信扫码登录，请用手机微信扫描下方链接对应的二维码。",
        "weixin_start_q": "  现在开始扫码登录？",
        "weixin_ok": "  √ 登录成功，已记录 bot_id={bot_id}",
        "weixin_incomplete": "  ! 扫码未完成。可稍后重新运行向导，或先填空，首次启动时会自动再次弹出二维码。",
        "weixin_skipped": "  已跳过扫码，首次启动 MIMO_Connect 时会自动弹出二维码登录。",
        "weixin_load_err": "  ! 无法加载微信扫码模块（{e}）。",
        "weixin_dep_hint": "    请确认依赖已安装（pip install -r requirements.txt）。",
        "weixin_cancelled": "\n  已取消扫码。",
        "weixin_login_err": "  ! 扫码登录出错：{e}",
        "step4_title": "[4/5] MiMo TTS 语音合成（可选，留空则后续仅文字）",
        "mimo_api_key": "  MIMO_API_KEY",
        "step5_title": "[5/5] MiMo Code 工作目录",
        "work_dir": "  工作目录",
        "agent_model": "  MiMo Code 模型（MIMO_CONNECT_MODEL，可留空用默认）",
        "env_header": "# MIMO_Connect 配置（由 first_run_setup.py 生成）",
        "env_header2": "# 如需修改，可直接编辑本文件或重新运行 python scripts/first_run_setup.py --force",
        "yaml_no_pyyaml": "  ! 未安装 pyyaml，跳过 config.yaml 同步（不影响 .env）。",
        "yaml_no_config": "  ! 未找到 config.yaml，跳过同步。",
        "yaml_synced": "  √ 已同步 config.yaml：active_provider={provider}, model={model}",
        "about_to_write": "  即将写入以下配置：",
        "confirm_write": "确认写入？",
        "write_cancelled": "已取消，未写入任何文件。",
        "env_written": "  √ 已写入 {path}",
        "done": "配置完成！现在可以启动：",
        "interrupted": "\n已中断。",
        "draft_found": "  检测到上次未完成的配置草稿，已为你预填先前填写的内容。",
        "draft_resume_hint": "    直接回车采用草稿值，或重新输入覆盖。中途退出会自动保存进度。",
        "draft_saved": "\n  已保存当前进度，下次启动可继续填写。",
    # LLM connection test & model selection
    "models_fetched": "  \u2713 Fetched {count} available models:",
    "model_number": "  Enter number or type model name directly",
    "llm_test_ok": "  \u2713 LLM connection test passed",
    "llm_test_fail": "  \u00d7 Connection test failed: {msg}",
    "llm_test_hint": "  Hint: you can continue and modify in settings later",
    "mimo_model_detected": "  Detected your MiMo CLI model: {model}",
    "reuse_mimo_model": "  Use this model in MIMO_Connect too?",
    "mimo_model_reused": "  \u2713 Set MIMO_CONNECT_MODEL={model}",
    "mimo_model_declined": "  Skipped, can be modified in settings later",
    "mimo_model_not_detected": "  Could not detect MiMo CLI model",

    },
    "en": {
        "title": "  MIMO_Connect First-Run Setup Wizard",
        "required": "  ! This field is required.",
    # LLM \u8fde\u63a5\u6d4b\u8bd5 & \u6a21\u578b\u9009\u62e9
    "models_fetched": "  \u2713 \u5df2\u83b7\u53d6 {count} \u4e2a\u53ef\u7528\u6a21\u578b\uff1a",
    "model_number": "  \u8bf7\u8f93\u5165\u7f16\u53f7\u6216\u76f4\u63a5\u8f93\u5165\u6a21\u578b\u540d",
    "llm_test_ok": "  \u2713 LLM \u8fde\u63a5\u6d4b\u8bd5\u901a\u8fc7",
    "llm_test_fail": "  \u00d7 \u8fde\u63a5\u6d4b\u8bd5\u5931\u8d25\uff1a{msg}",
    "llm_test_hint": "  \u63d0\u793a\uff1a\u53ef\u7ee7\u7eed\u914d\u7f6e\uff0c\u540e\u7eed\u5728\u8bbe\u7f6e\u4e2d\u4fee\u6539",
    "mimo_model_detected": "  \u68c0\u6d4b\u5230\u4f60\u7684 MiMo CLI \u914d\u7f6e\u4e86\u6a21\u578b\uff1a{model}",
    "reuse_mimo_model": "  \u5728 MIMO_Connect \u4e2d\u4e5f\u4f7f\u7528\u6b64\u6a21\u578b\uff1f",
    "mimo_model_reused": "  \u2713 \u5df2\u8bbe\u4e3a MIMO_CONNECT_MODEL={model}",
    "mimo_model_declined": "  \u5df2\u8df3\u8fc7\uff0c\u7a0d\u540e\u53ef\u5728\u8bbe\u7f6e\u4e2d\u4fee\u6539",
    "mimo_model_not_detected": "  \u672a\u68c0\u6d4b\u5230 MiMo CLI \u5f53\u524d\u6a21\u578b",

        "choose_one": "  ! Please enter one of {opts}.",
        "env_exists": ".env already exists: {path}",
        "reconfigure_q": "Reconfigure?",
        "kept_env": "Kept existing .env, skipping wizard.",
        "step1_title": "[1/5] Middleware LLM (intent recognition / status classification)",
        "choose_provider": "  Select provider",
        "api_base_url": "  API base_url",
        "model_name": "  Model name",
        "api_key": "  API key",
        "step2_title": "[2/5] Locating local mimo CLI",
        "cli_detected": "  √ Auto-detected: {path}",
        "cli_confirm": "  Confirm mimo CLI path (Enter to accept detected)",
        "cli_not_detected": "  ! mimo CLI not auto-detected.",
        "cli_hint": "    If installed, enter its full path; leave blank to search PATH at runtime.",
        "cli_path": "  mimo CLI path",
        "step3_title": "[3/5] Runtime platform (chat channel)",
        "platform_feishu": "  feishu - Feishu bot (recommended, WebSocket long connection, easy setup)",
        "platform_weixin": "  weixin - Weixin iLink Bot (QR-code login required)",
        "choose_channel": "  Select channel",
        "feishu_app_id": "  Feishu FEISHU_APP_ID",
        "feishu_app_secret": "  Feishu FEISHU_APP_SECRET",
        "weixin_intro": "  About to open Weixin QR login; scan the QR code for the link below with your phone.",
        "weixin_start_q": "  Start QR login now?",
        "weixin_ok": "  √ Login succeeded, recorded bot_id={bot_id}",
        "weixin_incomplete": "  ! QR scan not completed. Rerun the wizard later, or leave blank; the QR code will pop up again on first launch.",
        "weixin_skipped": "  Skipped QR login; the QR code will pop up automatically on first MIMO_Connect launch.",
        "weixin_load_err": "  ! Failed to load Weixin QR module ({e}).",
        "weixin_dep_hint": "    Please ensure dependencies are installed (pip install -r requirements.txt).",
        "weixin_cancelled": "\n  QR login cancelled.",
        "weixin_login_err": "  ! QR login error: {e}",
        "step4_title": "[4/5] MiMo TTS speech synthesis (optional, leave blank for text-only)",
        "mimo_api_key": "  MIMO_API_KEY",
        "step5_title": "[5/5] MiMo Code working directory",
        "work_dir": "  Working directory",
        "agent_model": "  MiMo Code model (MIMO_CONNECT_MODEL, leave blank for default)",
        "env_header": "# MIMO_Connect config (generated by first_run_setup.py)",
        "env_header2": "# To change, edit this file directly or rerun python scripts/first_run_setup.py --force",
        "yaml_no_pyyaml": "  ! pyyaml not installed, skipping config.yaml sync (does not affect .env).",
        "yaml_no_config": "  ! config.yaml not found, skipping sync.",
        "yaml_synced": "  √ Synced config.yaml: active_provider={provider}, model={model}",
        "about_to_write": "  About to write the following config:",
        "confirm_write": "Confirm write?",
        "write_cancelled": "Cancelled, nothing written.",
        "env_written": "  √ Written to {path}",
        "done": "Setup complete! You can now start with:",
        "interrupted": "\nInterrupted.",
        "draft_found": "  Found an unfinished setup draft; your previous entries are pre-filled.",
        "draft_resume_hint": "    Press Enter to accept a draft value, or type to overwrite. Progress auto-saves on exit.",
        "draft_saved": "\n  Progress saved; you can continue next time you launch.",
    },
}

# 各提供商默认 base_url / 模型，便于用户直接回车采用
PROVIDER_PRESETS = {
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "anthropic": {
        "env_key": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-20250514",
    },
    "siliconflow": {
        "env_key": "SILICONFLOW_API_KEY",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V4-Flash",
    },
    "dashscope": {
        "env_key": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "deepseek-ai/DeepSeek-V4-Flash",
    },
}


def t(key: str, **kwargs: object) -> str:
    """按当前语言取文案；带占位符时做 format。"""
    text = MESSAGES[LANG].get(key, MESSAGES["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text


def detect_system_lang() -> str:
    """检测系统界面语言，返回 "zh" 或 "en"。"""
    # Windows 优先用用户界面语言 ID（中文主语言 ID 为 0x04）
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if (lang_id & 0xFF) == 0x04:
                return "zh"
        except Exception:
            pass

    # 回退：locale + 环境变量
    blob = ""
    try:
        import locale

        blob += (locale.getdefaultlocale()[0] or "") + " "
    except Exception:
        pass
    blob += os.environ.get("LANG", "") + " " + os.environ.get("LC_ALL", "")
    blob = blob.lower()
    if "zh" in blob or "chinese" in blob:
        return "zh"
    return "en"


def choose_language() -> str:
    """检测系统语言并让用户选择向导语言，返回 "zh" / "en"。"""
    sys_lang = detect_system_lang()
    if sys_lang == "zh":
        prompt = "请选择向导语言 / Select wizard language (zh/en)"
    else:
        prompt = "Select wizard language / 请选择向导语言 (zh/en)"
    while True:
        try:
            val = input(f"{prompt} [{sys_lang}]: ").strip().lower()
        except EOFError:
            return sys_lang
        if not val:
            return sys_lang
        if val in ("zh", "en"):
            return val
        print("  ! Please enter zh or en. / 请输入 zh 或 en。")


def _hr() -> None:
    print("=" * 52)


def ask(prompt: str, default: str = "") -> str:
    """提示输入；回车采用默认值。"""
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def ask_required(prompt: str, default: str = "") -> str:
    while True:
        val = ask(prompt, default)
        if val:
            return val
        print(t("required"))


def ask_choice(prompt: str, choices: list[str], default: str) -> str:
    opts = "/".join(choices)
    while True:
        val = ask(f"{prompt} ({opts})", default).lower()
        if val in choices:
            return val
        print(t("choose_one", opts=opts))



def test_llm_connection(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url.rstrip('/'), api_key=api_key, timeout=15)
        resp = client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': 'test'}],
            max_tokens=5
        )
        return True, ''
    except Exception as e:
        return False, str(e)


def fetch_available_models(base_url: str, api_key: str) -> list[str]:
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url.rstrip('/'), api_key=api_key, timeout=15)
        models = client.models.list()
        return sorted([m.id for m in models])
    except Exception:
        return []


def ask_model_selection(prompt: str, default: str, base_url: str, api_key: str) -> str:
    models = fetch_available_models(base_url, api_key)
    if models:
        print('  ✓ 已获取 %d 个可用模型：' % len(models))
        display = models[:50]
        for i, m in enumerate(display, 1):
            print('    %3d. %s' % (i, m))
        if len(models) > 50:
            print('    ... 还有 %d 个（直接输入模型名也可）' % (len(models)-50))
        while True:
            idx = ask('  请输入编号或模型名', default)
            if idx.isdigit() and 1 <= int(idx) <= len(display):
                return display[int(idx)-1]
            if idx in models or idx:
                return idx
            print('  请选择 1-%d' % len(display))
    # fallback to manual input
    while True:
        val = ask(prompt, default)
        if val:
            return val
        print('  请输入模型名称')

def find_mimo_cli() -> str | None:
    """检索本机 mimo CLI 可执行文件位置。"""
    path = shutil.which("mimo")
    if path:
        return path
    candidates = [
        Path(os.path.expanduser("~/AppData/Roaming/npm")) / "mimo.cmd",
        Path(os.path.expanduser("~/AppData/Roaming/npm")) / "mimo.ps1",
        Path(os.path.expanduser("~/AppData/Roaming/npm")) / "mimo",
        Path(os.path.expanduser("~/.local/bin")) / "mimo",
        Path("/usr/local/bin/mimo"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def weixin_qr_login() -> tuple[str, str] | None:
    """触发微信 iLink 扫码登录，返回 (bot_token, bot_id)。

    复用 platforms/weixin.py 的 qr_login：请求二维码、打印扫码链接、
    轮询确认状态。失败或超时返回 None。
    """
    import asyncio

    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        import httpx  # noqa: F401
        from platforms.weixin import qr_login
    except Exception as e:
        print(t("weixin_load_err", e=e))
        print(t("weixin_dep_hint"))
        return None

    async def _run() -> tuple[str, str] | None:
        import httpx
        transport = httpx.AsyncHTTPTransport(proxy=None, retries=1)
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(15.0)) as client:
            result = await qr_login(client)
            if result:
                return result["bot_token"], result["bot_id"]
            return None

    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        print(t("weixin_cancelled"))
        return None
    except Exception as e:
        print(t("weixin_login_err", e=e))
        return None


def write_env(values: dict[str, str]) -> None:
    """把键值对写入 .env（空值不写）。"""
    lines = [
        t("env_header"),
        t("env_header2"),
        "",
    ]
    for key, val in values.items():
        if val:
            lines.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_config_yaml(provider: str, base_url: str, model: str) -> None:
    """把所选提供商写入 config.yaml 的 active_provider，并更新其 base_url/model。

    仅做最小化文本修改，避免引入额外依赖且保留注释/格式。
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except Exception:
        print(t("yaml_no_pyyaml"))
        return

    if not CONFIG_PATH.exists():
        print(t("yaml_no_config"))
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    llm = data.setdefault("llm", {})
    llm["active_provider"] = provider
    providers = llm.setdefault("providers", {})
    pcfg = providers.setdefault(provider, {})
    pcfg["base_url"] = base_url
    pcfg["model"] = model

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(t("yaml_synced", provider=provider, model=model))


def main() -> int:
    global LANG
    force = "--force" in sys.argv

    # 已保存过语言偏好则沿用，否则询问，并立即写回 .env 供 GUI/后续复用。
    saved_lang = config_io.read_env().get("MIMO_CONNECT_LANG", "").strip().lower()
    if saved_lang in ("zh", "en"):
        LANG = saved_lang
    else:
        LANG = choose_language()
    try:
        config_io.write_lang(LANG)
    except Exception:
        pass

    _hr()
    print(t("title"))
    _hr()

    if ENV_PATH.exists() and not force:
        print(t("env_exists", path=ENV_PATH))
        if ask_choice(t("reconfigure_q"), ["y", "n"], "n") != "y":
            print(t("kept_env"))
            return 0
    print()

    # 载入上次未完成的草稿（若有），用于断点续填。
    draft = config_io.read_draft()
    if draft:
        print(t("draft_found"))
        print(t("draft_resume_hint"))
        print()

    def d(key: str, fallback: str = "") -> str:
        """取草稿值作为默认，没有则用 fallback。"""
        return draft.get(key, "") or fallback

    def save(key: str, val: str) -> None:
        """把刚填的值写入本地草稿，立即持久化以支持中途退出。"""
        if val:
            draft[key] = val
            config_io.write_draft({key: val})

    # ---- 1. LLM 提供商 ----
    print(t("step1_title"))
    provider = ask_choice(
        t("choose_provider"), list(PROVIDER_PRESETS.keys()), d("llm_provider", "deepseek")
    )
    preset = PROVIDER_PRESETS[provider]
    save("llm_provider", provider)
    base_url = ask_required(t("api_base_url"), d("llm_base_url", preset["base_url"]))
    save("llm_base_url", base_url)
    model = ask_model_selection(t("model_name"), d("llm_model", preset["model"]), base_url, api_key)
    save("llm_model", model)
    api_key = ask_required(t("api_key"), d("llm_api_key"))
    # 测试 LLM 连接
    ok, err = test_llm_connection(base_url, api_key, model)
    if ok:
        print('  ✓ LLM 连接测试通过')
    else:
        print('  × 连接测试失败：%s' % err)
        print('  提示：可继续配置，后续在设置中修改')
    save("llm_api_key", api_key)
    print()

    # ---- 2. 检索 mimo CLI ----
    print(t("step2_title"))
    detected = find_mimo_cli()
    draft_cli = d("mimo_code_path")
    if detected:
        print(t("cli_detected", path=detected))
        mimo_code_path = ask(t("cli_confirm"), draft_cli or detected)
    else:
        print(t("cli_not_detected"))
        print(t("cli_hint"))
        mimo_code_path = ask(t("cli_path"), draft_cli)
    save("mimo_code_path", mimo_code_path)

    # ---- 2b. 检测 MiMo CLI 模型 ----
    mimo_model = ""
    if mimo_code_path:
        try:
            import subprocess
            result = subprocess.run([mimo_code_path, "--model"], capture_output=True, text=True, timeout=10)
            raw = result.stdout.strip() or result.stderr.strip()
            if raw and "error" not in raw.lower() and "not found" not in raw.lower():
                mimo_model = raw
        except Exception:
            pass
    if mimo_model:
        print('  检测到 MiMo CLI 配置了模型：%s' % mimo_model)
        if ask_choice('  在 MIMO_Connect 中也使用此模型？', ['y', 'n'], 'y') == 'y':
            print('  ✓ 已设为 MIMO_CONNECT_MODEL=%s' % mimo_model)
            draft['agent_model'] = mimo_model
            save('agent_model', mimo_model)
        else:
            print('  已跳过，稍后可在设置中修改')
    else:
        print('  未检测到 MiMo CLI 当前模型（可能未配置）')
    print()

    # ---- 3. 运行平台 ----
    print(t("step3_title"))
    print(t("platform_feishu"))
    print(t("platform_weixin"))
    platform = ask_choice(t("choose_channel"), ["feishu", "weixin"], d("platform", "feishu"))
    save("platform", platform)
    weixin_token = weixin_bot_id = feishu_app_id = feishu_app_secret = ""
    if platform == "feishu":
        feishu_app_id = ask_required(t("feishu_app_id"), d("feishu_app_id"))
        save("feishu_app_id", feishu_app_id)
        feishu_app_secret = ask_required(t("feishu_app_secret"), d("feishu_app_secret"))
        save("feishu_app_secret", feishu_app_secret)
    else:
        print(t("weixin_intro"))
        if ask_choice(t("weixin_start_q"), ["y", "n"], "y") == "y":
            result = weixin_qr_login()
            if result:
                weixin_token, weixin_bot_id = result
                save("weixin_bot_id", weixin_bot_id)
                save("weixin_token", weixin_token)
                print(t("weixin_ok", bot_id=weixin_bot_id))
            else:
                print(t("weixin_incomplete"))
        else:
            print(t("weixin_skipped"))
    print()

    # ---- 4. MiMo TTS ----
    print(t("step4_title"))
    mimo_api_key = ask(t("mimo_api_key"), d("mimo_api_key"))
    save("mimo_api_key", mimo_api_key)
    print()

    # ---- 5. 工作目录 ----
    print(t("step5_title"))
    default_work_dir = os.getenv("MIMO_CONNECT_WORK_DIR", str(PROJECT_ROOT))
    work_dir = ask_required(t("work_dir"), d("work_dir", default_work_dir))
    save("work_dir", work_dir)
    agent_model = ask(t("agent_model"), d("agent_model"))
    save("agent_model", agent_model)
    print()

    env_values = {
        preset["env_key"]: api_key,
        "MIMO_API_KEY": mimo_api_key,
        "MIMO_CONNECT_PLATFORM": platform,
        "WEIXIN_BOT_ID": weixin_bot_id,
        "WEIXIN_TOKEN": weixin_token,
        "FEISHU_APP_ID": feishu_app_id,
        "FEISHU_APP_SECRET": feishu_app_secret,
        "MIMO_CODE_PATH": mimo_code_path,
        "MIMO_CONNECT_WORK_DIR": work_dir,
        "MIMO_CONNECT_MODEL": agent_model,
        "MIMO_CONNECT_LANG": LANG,
    }

    _hr()
    print(t("about_to_write"))
    for k, v in env_values.items():
        if not v:
            continue
        shown = v if k not in (preset["env_key"], "MIMO_API_KEY", "FEISHU_APP_SECRET", "WEIXIN_TOKEN") else (v[:6] + "***")
        print(f"    {k} = {shown}")
    _hr()
    if ask_choice(t("confirm_write"), ["y", "n"], "y") != "y":
        print(t("write_cancelled"))
        return 1

    write_env(env_values)
    print(t("env_written", path=ENV_PATH))
    sync_config_yaml(provider, base_url, model)
    # 配置成功落盘后清除草稿。
    config_io.clear_draft()

    print()
    print(t("done"))
    print("    mmc            (Windows GUI)  |  ./mmc  (Linux/macOS CLI)")
    print("    python gui_main.py   or   python cli_main.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(MESSAGES[LANG]["interrupted"])
        print(MESSAGES[LANG].get("draft_saved", ""))
        raise SystemExit(130)
