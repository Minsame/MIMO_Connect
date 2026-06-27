"""MIMO_Connect - Voice Coding Middleware

Full flow: Chat platform → Engine → MiMo Code CLI → Response → TTS/Text → Chat platform
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import Engine, get_platform, get_voice_provider  # noqa: E402

# Import adapters to trigger registration
import platforms.weixin  # noqa: E402,F401
import platforms.feishu  # noqa: E402,F401
import agent.mimo_code  # noqa: E402,F401
import voice.edge_tts  # noqa: E402,F401

logger = logging.getLogger("mimo_connect")


def setup_logging(config: Optional[dict[str, Any]] = None, log_file: str = "mimo_connect.log") -> None:
    level = "INFO"
    if config:
        level = config.get("logging", {}).get("level", "INFO")
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    import io
    handlers: list[logging.Handler] = []
    # windowed/onefile exe 可能没有控制台（sys.stderr 为 None），此时跳过控制台处理器。
    if getattr(sys, "stderr", None) is not None and getattr(sys.stderr, "buffer", None) is not None:
        stderr_utf8 = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        # 控制台处理器：TTY 下分级着色，非 TTY（文件/管道）退化为纯文本。
        console = logging.StreamHandler(stderr_utf8)
        try:
            from core.term import ColorFormatter, supports_color
            console.setFormatter(ColorFormatter(use_color=supports_color(stderr_utf8)))
        except Exception:
            console.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        handlers.append(console)
    if log_file:
        from logging.handlers import RotatingFileHandler
        from core import config_io
        log_path = config_io.PROJECT_ROOT / log_file
        fh = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))  # 文件始终纯文本
        handlers.append(fh)
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=handlers)


def load_config() -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
        config_path = _PROJECT_ROOT / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def _build_llm_client(config: dict):
    """Build a shared LLM client (currently used by intent router and segment rewriter).

    Returns None when no API key is available — callers should degrade gracefully.
    """
    llm_config = config.get("llm", {})
    provider = llm_config.get("active_provider", "deepseek")
    providers = llm_config.get("providers", {})
    provider_cfg = providers.get(provider, {})
    defaults = llm_config.get("defaults", {})

    base_url = provider_cfg.get("base_url", "")
    model = provider_cfg.get("model", "deepseek-v4-flash")
    temperature = defaults.get("temperature", 0)

    api_key = ""
    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
    elif provider == "siliconflow":
        api_key = os.getenv("SILICONFLOW_API_KEY", "")
    elif provider == "dashscope":
        api_key = os.getenv("DASHSCOPE_API_KEY", "")

    if not api_key:
        logger.warning("No API key found for middleware LLM; rule-based fallbacks will be used")
        return None, provider, model

    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            base_url=base_url if base_url else None,
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=temperature,
            timeout=10,
        )
        logger.info(f"Middleware LLM client: {provider}/{model}")
        return llm, provider, model
    except Exception as e:
        logger.warning(f"Failed to create middleware LLM client: {e}")
        return None, provider, model


def _build_intent_router(config: dict, llm=None, model: str = ""):
    """Build LLM intent router. Pass an existing llm client to share it."""
    from core.intent_router import LLMIntentRouter

    if llm is None:
        return LLMIntentRouter(llm_client=None)
    return LLMIntentRouter(llm_client=llm, model=model)


async def run(config_path: str = "config.yaml") -> None:
    config = load_config()
    setup_logging(config)

    # 启动横幅（仅命令行运行态打印到控制台；GUI 模式无 TTY 时自动纯文本/可忽略）。
    platform_name = os.getenv("MIMO_CONNECT_PLATFORM", os.getenv("MIMO_CONNECT_MODE", "weixin"))
    _work_dir_disp = os.getenv("MIMO_CONNECT_WORK_DIR", str(_PROJECT_ROOT))
    _model_disp = os.getenv("MIMO_CONNECT_MODEL", "")
    _mimo_path_disp = os.getenv("MIMO_CODE_PATH", "")
    try:
        from core.term import banner
        print(banner(platform_name, _work_dir_disp, _model_disp, _mimo_path_disp), file=sys.stderr, flush=True)
    except Exception:
        pass

    logger.info("MIMO_Connect starting...")

    # 1. Platform
    PlatformCls = get_platform(platform_name)
    if not PlatformCls:
        raise RuntimeError(f"Unknown platform: {platform_name}")
    if platform_name in ("feishu", "lark"):
        platform = PlatformCls(
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        )
    else:
        platform = PlatformCls(
            bot_id=os.getenv("WEIXIN_BOT_ID", ""),
            token=os.getenv("WEIXIN_TOKEN", ""),
        )

    # 2. Agent (MiMo Code)
    from core.registry import get_agent
    AgentCls = get_agent("mimo-code")
    if not AgentCls:
        raise RuntimeError("Unknown agent: mimo-code")
    agent_work_dir = Path(os.getenv("MIMO_CONNECT_WORK_DIR", str(_PROJECT_ROOT)))
    agent_model = os.getenv("MIMO_CONNECT_MODEL", "")  # e.g. "deepseek-v4-flash" or "xiaomi/mimo-v2.5-pro"
    agent = AgentCls(work_dir=agent_work_dir, llm_client=None, model=agent_model)
    logger.info(f"Agent work_dir: {agent_work_dir}, model: {agent_model or 'default'}")

    # 3. Middleware LLM client (shared by intent router, segment rewriter, progress summarizer)
    llm_client, _provider, _llm_model = _build_llm_client(config)

    # 3a. Intent Router (LLM-based)
    intent_router = _build_intent_router(config, llm=llm_client, model=_llm_model)

    # 4. Voice
    tts_config = config.get("tts", {})
    voice = None
    engine_name = tts_config.get("primary_engine", "mimo")
    VoiceCls = get_voice_provider(engine_name)
    if VoiceCls:
        mimo_cfg = tts_config.get("mimo", {})
        edge_cfg = tts_config.get("edge", {})
        win_cfg = tts_config.get("windows", {})
        if engine_name == "mimo":
            WinCls = get_voice_provider("windows")
            win_fallback = WinCls(
                voice_gender=win_cfg.get("voice_gender", "female"),
                rate=win_cfg.get("rate", 0),
                volume=win_cfg.get("volume", 100),
            ) if WinCls else None
            EdgeCls = get_voice_provider("edge-tts")
            edge_fallback = EdgeCls(
                voice=edge_cfg.get("voice", "zh-CN-XiaoxiaoNeural"),
                rate=edge_cfg.get("rate", "+0%"),
                volume=edge_cfg.get("volume", "+0%"),
            ) if EdgeCls else None
            if edge_fallback and win_fallback:
                edge_fallback._fallback = win_fallback
            voice = VoiceCls(
                api_url=mimo_cfg.get("api_url", "https://api.xiaomimimo.com/v1"),
                model=mimo_cfg.get("model", "mimo-v2.5-tts"),
                voice=mimo_cfg.get("voice", "mimo_default"),
                fallback=edge_fallback,
                timeout=5.0,
            )
        else:
            edge_cfg = tts_config.get("edge", {})
            voice = VoiceCls(voice=edge_cfg.get("voice", "zh-CN-XiaoxiaoNeural"))

    # 5. Engine
    engine = Engine(platform, agent, voice, intent_router, llm_client=llm_client)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if os.getenv("MIMO_CONNECT_DEBUG", "").lower() in ("1", "true", "yes"):
        loop.set_debug(True)
        loop.slow_callback_duration = 0.1  # log callbacks > 100ms
        logger.info("Asyncio debug mode enabled (slow_callback_duration=0.1s)")
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    # 引擎主循环与停止事件竞速：收到 SIGINT/SIGTERM（stop_event.set）后，
    # 主动取消引擎任务，让平台 poll 循环的 CancelledError 分支优雅退出，
    # 而不是干等阻塞调用返回。
    engine_task = asyncio.ensure_future(engine.start())
    stop_task = asyncio.ensure_future(stop_event.wait())
    try:
        done, pending = await asyncio.wait(
            {engine_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done and not engine_task.done():
            engine_task.cancel()
            try:
                await engine_task
            except asyncio.CancelledError:
                pass
        for task in pending:
            task.cancel()
        # 引擎自身异常需传播以便上报。
        if engine_task in done:
            engine_task.result()
    except KeyboardInterrupt:
        pass
    finally:
        await engine.stop()


def main():
    # Enable asyncio debug mode to detect event loop blocking
    debug = os.getenv("MIMO_CONNECT_DEBUG", "").lower() in ("1", "true", "yes")
    asyncio.run(run(), debug=debug)


if __name__ == "__main__":
    main()
