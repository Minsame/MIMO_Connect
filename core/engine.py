"""MIMO_Connect Engine - Central orchestrator.

Routes platform messages, middleware commands, intent classification,
agent events, voice generation, and replies.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import logging
from pathlib import Path
from typing import Any, Optional

from .interfaces import (
    Agent, AgentSession, Event, EventType, Intent, IntentRouter, IntentType,
    Message, Platform, Reply, VoiceProvider,
)

logger = logging.getLogger(__name__)

# Patterns that indicate rich content — should NOT be auto-voiced
_RICH_PATTERNS = re.compile(
    r"(?:```[\s\S]*?```"           # code blocks
    r"|^\|.+\|$"                    # table rows
    r"|^#{1,6}\s"                   # headings
    r"|!\[.*?\]\(.*?\)"             # images
    r"|^>\s"                        # blockquotes
    r"|^\- \[[ x]\]"               # task lists
    r")",
    re.MULTILINE,
)


def _is_rich_text(text: str) -> bool:
    """Check if text contains rich formatting (code blocks, tables, etc.)."""
    return bool(_RICH_PATTERNS.search(text))


def _strip_for_voice(text: str) -> str:
    """Strip markdown/code formatting for TTS. Returns plain text."""
    # Remove segment tags first ([TEXT], [CODE:python], [MD], [TABLE])
    from core.segment_parser import strip_tags
    text = strip_tags(text) or text
    # Remove code blocks entirely
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Keep inline code text (e.g. English identifiers) but drop the backticks,
    # so TTS can still pronounce the word instead of dropping it silently.
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove markdown links, keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove images
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove headings markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    # Remove table formatting
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"^[-:]+$", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class SessionState:
    """Tracks state for a user's interaction session."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.session: Optional[AgentSession] = None
        self.pending_options: list[dict] = []
        self.last_agent_text: str = ""
        self.last_reply_content: str = ""
        self.conversation_history: list[dict] = []
        self.wants_voice: bool = False
        self.detail_mode: bool = False
        self.prev_detail_mode: bool = False
        self.last_status: str = ""
        self.status_history: list[str] = []
        self.task_start_ts: float = 0.0
        self.last_user_task: str = ""
        self.pending_work_dir: str = ""
        self.sent_agent_text: str = ""
        self._middleware_notices: list[str] = []
        self.lock = asyncio.Lock()

    def add_history(self, role: str, content: str) -> None:
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

    def get_context(self) -> str:
        lines = []
        for msg in self.conversation_history[-10:]:
            lines.append(f"{msg['role']}: {msg['content'][:500]}")
        return "\n".join(lines)


class Engine:
    """Central orchestrator for MIMO_Connect."""

    def __init__(
        self,
        platform: Platform,
        agent: Agent,
        voice: Optional[VoiceProvider] = None,
        intent_router: Optional[IntentRouter] = None,
        llm_client=None,
    ):
        self._platform = platform
        self._agent = agent
        self._voice = voice
        self._intent_router = intent_router
        self._llm_client = llm_client
        from core.segment_rewriter import SegmentRewriter
        from core.progress_summarizer import ProgressSummarizer
        from core.voice_condenser import VoiceCondenser
        self._segment_rewriter = SegmentRewriter(llm_client=llm_client)
        self._progress_summarizer = ProgressSummarizer(llm_client=llm_client)
        self._voice_condenser = VoiceCondenser(llm_client=llm_client)
        self._sessions: dict[str, SessionState] = {}
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info(
            f"MIMO_Connect Engine starting: platform={self._platform.name()}, "
            f"agent={self._agent.name()}, voice={self._voice.name() if self._voice else 'none'}, "
            f"intent_router={'enabled' if self._intent_router else 'disabled'}, "
            f"segment_rewriter={'enabled' if self._segment_rewriter.available() else 'disabled'}, "
            f"progress_summarizer={'enabled' if self._progress_summarizer.available() else 'disabled'}"
        )
        await self._platform.start(self._handle_message)

    async def stop(self) -> None:
        self._running = False
        for state in self._sessions.values():
            if state.session:
                await state.session.close()
        self._sessions.clear()
        await self._agent.stop()
        await self._platform.stop()
        logger.info("MIMO_Connect Engine stopped")

    def _get_state(self, user_id: str) -> SessionState:
        if user_id not in self._sessions:
            self._sessions[user_id] = SessionState(user_id)
        return self._sessions[user_id]

    # ─── Message dispatch ────────────────────────────────────────────────

    async def _handle_message(self, msg: Message) -> None:
        state = self._get_state(msg.from_user)
        async with state.lock:
            state.add_history("user", msg.content)
            logger.info(f"Message from {msg.from_user}: {msg.content[:80]}")

            command_reply = await self._handle_middleware_command(msg.content, state)
            if command_reply:
                await self._send_platform_reply(command_reply, state, msg.context_token)
                return

            progress_reply = self._handle_progress_query(msg.content, state)
            if progress_reply:
                await self._send_platform_reply(progress_reply, state, msg.context_token)
                return

            # If pending options exist but session is dead, the task failed (e.g. permission exit)
            if state.pending_options and (not state.session or not state.session.alive()):
                state.pending_options = []
                await self._send_platform_reply(
                    Reply(content="上一个任务因权限问题已终止（CLI 自动拒绝了目录访问）。已用 `--dangerously-skip-permissions` 重试。"),
                    state,
                    msg.context_token,
                )

            # Check for pending options: let LLM classify before local matching
            if state.pending_options and self._intent_router:
                # LLM first: classify what user wants
                try:
                    intent = await self._intent_router.classify(
                        msg.content,
                        context=state.get_context(),
                        pending_options=state.pending_options or None,
                    )
                    logger.info(f"Pending options intent classified: {intent.type.value} (conf={intent.confidence:.2f})")
                    
                    if intent.type in (IntentType.SELECT_OPTION, IntentType.APPROVE, IntentType.REJECT):
                        reply = await self._dispatch(intent, state, msg.content)
                        if reply:
                            await self._send_platform_reply(reply, state, msg.context_token)
                        else:
                            # dispatch handled it
                            pass
                        return
                except Exception as e:
                    logger.warning(f"LLM intent classification failed for option selection: {e}, falling back to local match")
                    state._middleware_notices.append("⚠ 中间层 LLM 不可用，选项识别已降级为规则匹配。")
            
            # If LLM failed or no intent router, fallback to local matching
            if state.pending_options:
                number_reply = await self._match_digit_option(msg.content.strip(), state)
                if number_reply:
                    await self._send_platform_reply(number_reply, state, msg.context_token)
                    return

            if self._is_cli_command(msg.content):
                reply = await self._send_to_agent(msg.content.strip(), state)
                if reply:
                    await self._send_platform_reply(reply, state, msg.context_token)
                return

            intent = await self._classify(msg.content, state)
            logger.info(f"Intent: {intent.type.value} (conf={intent.confidence:.2f})")
            reply = await self._dispatch(intent, state, msg.content)

            if reply:
                await self._send_platform_reply(reply, state, msg.context_token)
            else:
                logger.info(f"Agent task completed (reply already sent): {msg.content[:80]}")

    async def _handle_middleware_command(self, text: str, state: SessionState) -> Optional[Reply]:
        command = text.strip().lower()
        if command == "/show":
            if state.detail_mode:
                return Reply(content="当前已是细节展示模式。")
            state.detail_mode = True
            return Reply(content="已开启细节展示模式：会每 3 秒聚合推送 MiMo Code 的用户可见文本。")
        if command == "/hide":
            if not state.detail_mode:
                return Reply(content="当前已是精简展示模式。")
            state.detail_mode = False
            return Reply(content="已关闭细节展示模式：只推送开头两句和最终回复。")
        if command == "/help":
            return Reply(content=self._get_help_text())
        if command == "/connect":
            return Reply(content="请在终端运行 `mimo providers` 完成配置，配置完成后重启中间层。")
        if command == "/model":
            return self._handle_model_query()
        if command.startswith("/model "):
            model_name = text.strip()[7:].strip()
            return self._handle_model_switch(model_name, state)
        if command == "/models":
            return await self._handle_models_list()
        if command in ("/abort", "/stop"):
            return await self._handle_abort(state)
        return None

    def _is_cli_command(self, text: str) -> bool:
        command = text.strip()
        return command.startswith("/") and command.split(maxsplit=1)[0].lower() not in {"/show", "/hide", "/help", "/connect", "/model", "/models", "/abort", "/stop"}

    def _get_help_text(self) -> str:
        """Return middleware help text."""
        return (
            "## MIMO_Connect 中间层命令\n\n"
            "- `/show` — 开启细节展示模式（每 3 秒聚合推送）\n"
            "- `/hide` — 关闭细节展示模式（只推送开头和结尾）\n"
            "- `/model` — 查看当前使用的模型\n"
            "- `/model <名称>` — 切换到指定模型（如 `/model deepseek-v4-flash`）\n"
            "- `/models` — 列出所有可用模型\n"
            "- `/abort` — 打断当前正在执行的任务\n"
            "- `/connect` — 配置 API 提供商（需在终端操作）\n"
            "- `/help` — 显示本帮助信息\n\n"
            "其他输入将作为正常对话发送给 MiMo Code。"
        )

    def _handle_model_query(self) -> Reply:
        """Return current model info."""
        if hasattr(self._agent, 'get_model'):
            model = self._agent.get_model()
            if model:
                return Reply(content=f"当前模型：`{model}`")
        return Reply(content="当前模型：使用 MiMo Code 默认配置（未指定 `-m` 参数）")

    def _handle_model_switch(self, model_name: str, state: SessionState) -> Reply:
        """Switch to a new model. Applies on next session start; never kills a running task."""
        if not hasattr(self._agent, 'set_model'):
            return Reply(content="当前 Agent 不支持切换模型。")

        # Validate model name format (provider/model or just model)
        if not model_name or len(model_name) > 100:
            return Reply(content="模型名称无效。格式：`provider/model` 或 `model`，如 `deepseek-v4-flash`。")

        # Set the new model for future sessions. We intentionally do NOT close
        # the current session here: closing would taskkill a task that may be
        # running. The new model takes effect when the next session starts
        # (i.e. after the current task ends or the session is otherwise reset).
        self._agent.set_model(model_name)

        if state.session and state.session.alive():
            return Reply(content=f"已设置模型 `{model_name}`。当前任务继续使用旧模型运行，下次新对话时生效。")
        return Reply(content=f"已切换到模型 `{model_name}`。下次对话将使用新模型。")

    async def _handle_models_list(self) -> Reply:
        """List available models via the agent adapter."""
        models = await self._agent.list_models()
        if not models:
            return Reply(content="找不到可用模型，请确认 MiMo Code CLI 已安装并在 PATH 中。")
        body = "\n".join(models)
        return Reply(content=f"## 可用模型\n\n```\n{body}\n```\n\n使用 `/model <名称>` 切换模型。")

    async def _handle_abort(self, state: SessionState) -> Reply:
        """Abort the currently running agent task, preserving session context."""
        if not state.session or not state.session.alive():
            return Reply(content="当前没有正在运行的任务。")
        await state.session.abort()
        state.pending_options = []
        logger.info(f"Agent task aborted for {state.user_id}")
        return Reply(content="已打断当前操作。")

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        """Whether the text reads as a question/inquiry rather than a command.

        Used to stop a misclassified INTERRUPT from killing a running task
        when the user is merely asking *why* something stopped or *what* is
        happening (e.g. "为什么停了"、"是不是卡住了"、"现在到哪了").
        """
        if not text:
            return False
        s = text.strip()
        if s.endswith(("?", "？")):
            return True
        markers = ("吗", "嘛", "呢", "为什么", "为啥", "怎么", "咋", "是不是",
                   "什么情况", "怎么回事", "到哪", "好了没", "完了没")
        return any(m in s for m in markers)

    def _handle_progress_query(self, text: str, state: SessionState) -> Optional[Reply]:
        if not state.session or not state.session.alive():
            return None
        if hasattr(state.session, "running") and not state.session.running():
            return None
        if not any(word in text for word in ("进度", "状态", "到哪", "现在", "在干嘛", "什么情况")):
            return None
        status = state.last_status or "MiMo Code 正在运行，但暂时没有新的状态输出。"
        return Reply(content=f"当前状态：{status}")

    async def _send_platform_reply(self, reply: Reply, state: SessionState, context_token: str = "") -> bool:
        # Format-tag normalization: if the reply text lacks any segment tag,
        # ask the middleware LLM to add tags so the platform can route to the
        # right Feishu message type. This is awaited inline, so when multiple
        # replies are emitted in sequence, the rewrite of an earlier reply
        # always completes before the next reply is sent — preserving order.
        await self._normalize_segment_tags(reply, state)

        # Attach any pending middleware LLM degradation notices. Flushed after
        # normalization so notices raised during the rewrite step (e.g. the
        # rewriter being unavailable) are delivered on this same reply.
        if state._middleware_notices:
            notice = "\n\n---\n" + "\n".join(state._middleware_notices)
            reply.content = reply.content + notice
            state._middleware_notices.clear()

        state.add_history("assistant", reply.content)
        state.last_reply_content = reply.content
        reply.metadata["from_user"] = state.user_id
        logger.info(f"Reply to {state.user_id}: {reply.content[:100]}...")
        return await self._platform.send_reply(reply, context_token)

    async def _normalize_segment_tags(self, reply: Reply, state: SessionState) -> None:
        """Ensure reply.content has at least one [TEXT]/[MD]/[CODE]/[TABLE] tag.

        - Skip when reply has options (those use a fixed plain-text layout).
        - Skip when content already contains any tag (parse_segments handles it).
        - Otherwise call the rewriter once; on any failure, prepend [TEXT]
          so the platform falls back to a plain text message cleanly.
        """
        from core.segment_parser import has_any_tag

        if reply.metadata.get("has_options"):
            return
        content = reply.content or ""
        if not content.strip():
            return
        if has_any_tag(content):
            return

        # Fast local detection: check for obvious markdown patterns
        local_tagged = self._local_tag_detection(content)
        if local_tagged:
            logger.info("Segment rewrite: local detection added tags")
            reply.content = local_tagged
            return

        rewritten = await self._segment_rewriter.rewrite(content)
        if rewritten and has_any_tag(rewritten):
            logger.info("Segment rewrite OK (added tags)")
            reply.content = rewritten
            return
        # Rewriter timed out / unavailable / failed: forward the original
        # content directly as MD (parsed as markdown) instead of showing any
        # error. TEXT is folded into MD, so this loses no formatting.
        logger.info("Segment rewrite unavailable/failed; forwarding original as [MD]")
        # Only flag degradation when a rewriter LLM was actually configured but
        # failed. With no client configured the [MD] fallback is the normal
        # path, not a degradation, so we stay silent.
        if self._segment_rewriter.available():
            state._middleware_notices.append("⚠ 中间层 LLM 不可用，格式标注已降级。")
        reply.content = "[MD]\n" + content

    @staticmethod
    def _local_tag_detection(content: str) -> str | None:
        """Fast local detection of markdown patterns without LLM call."""
        import re
        lines = content.splitlines()
        has_table = False
        has_heading = False
        has_code_block = False
        has_list = False
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Table detection: line starts with | and has at least 2 |
            if line.startswith('|') and line.count('|') >= 2:
                has_table = True
            # Heading detection: line starts with #
            elif re.match(r'^#{1,6}\s+', line):
                has_heading = True
            # Code block detection: line starts with ```
            elif line.startswith('```'):
                has_code_block = True
            # List detection: line starts with - or * or numbered
            elif re.match(r'^[-*]\s+', line) or re.match(r'^\d+\.\s+', line):
                has_list = True
            i += 1
        
        # If we detected markdown features, tag as MD
        if has_table or has_heading or has_code_block or has_list:
            return f"[MD]\n{content}"
        return None

    @staticmethod
    def _extract_prior_categories(history: list[str]) -> list[str]:
        """Pick distinct category= values from earlier status lines.

        The summarizer only sees the latest event, so this gives it a
        quick context bundle: e.g. ['reading_files', 'modifying_files'].
        Excludes the very last entry since that's the 'current event'.
        """
        seen: list[str] = []
        for line in history[:-1]:
            for chunk in line.split(","):
                chunk = chunk.strip()
                if chunk.startswith("category="):
                    cat = chunk[len("category="):].strip()
                    if cat and cat not in seen:
                        seen.append(cat)
                    break
        return seen

    async def _classify(self, text: str, state: SessionState) -> Intent:
        """Classify user intent using LLM router."""
        if self._intent_router:
            try:
                return await self._intent_router.classify(
                    text,
                    context=state.get_context(),
                    pending_options=state.pending_options or None,
                )
            except Exception as e:
                logger.error(f"Intent classification failed: {e}")
                state._middleware_notices.append("⚠ 中间层 LLM 不可用，意图识别已降级为规则匹配。")

        return Intent(type=IntentType.CHAT, payload=text)

    async def _dispatch(self, intent: Intent, state: SessionState, original_text: str) -> Optional[Reply]:
        """Route intent while preserving original user text for MiMo."""

        # ── Voice mode toggles (middleware-only, no agent) ──
        if intent.type == IntentType.VOICE_ON:
            state.wants_voice = True
            return Reply(content="已切换到语音模式。")

        if intent.type == IntentType.VOICE_OFF:
            state.wants_voice = False
            return Reply(content="已切换到文字模式。")

        if intent.type == IntentType.VOICE_LAST:
            return await self._voice_last_reply(state)

        # ── Option selection ──
        if intent.type == IntentType.SELECT_OPTION and state.pending_options:
            return await self._handle_option_select(intent, state, original_text)

        if intent.type == IntentType.APPROVE and state.pending_options:
            return await self._handle_option_approve(intent, state)

        if intent.type == IntentType.REJECT and state.pending_options:
            state.pending_options = []
            return Reply(content="已取消。")

        if state.pending_options and intent.type in (IntentType.CODE_TASK, IntentType.CHAT):
            return await self._handle_custom_option_input(original_text, state)

        # ── Interrupt ──
        if intent.type == IntentType.INTERRUPT:
            # Defense-in-depth: a question about stopping ("为什么停了"、
            # "是不是卡住了") is NOT a stop command. If the text reads as a
            # question, don't kill the task — forward it to MiMo to answer.
            if self._looks_like_question(original_text):
                logger.info(f"INTERRUPT intent overridden: text reads as a question -> chat: {original_text[:40]}")
                payload = original_text.strip()
                if payload:
                    return await self._send_to_agent(payload, state)
                return None
            if state.session:
                await state.session.close()
                state.session = None
            state.pending_options = []
            return Reply(content="已中断当前操作。")

        # ── Code task / Chat → forward to agent ──
        payload = original_text.strip()
        if not payload:
            return None
        return await self._send_to_agent(payload, state)

    # ─── Voice helpers ───────────────────────────────────────────────────

    async def _build_voice_text(self, text: str, options: Optional[list[dict]] = None) -> str:
        """Produce concise spoken text for TTS.

        - Condense the body via the middleware LLM (falls back to a
          markdown-stripped version when the LLM is unavailable/fails).
        - When the reply carries selectable options, append them as spoken
          "选项一……选项二……" so a voice-only user can hear the choices.
        """
        condensed = await self._voice_condenser.condense(text)
        spoken = condensed or _strip_for_voice(text)
        if not condensed:
            state._middleware_notices.append("⚠ 中间层 LLM 不可用，语音摘要已降级为原文朗读。")
        spoken = spoken.strip()
        if options:
            spoken = self._append_options_for_voice(spoken, options)
        return spoken.strip()

    @staticmethod
    def _append_options_for_voice(spoken: str, options: list[dict]) -> str:
        _ZH_NUM = "一二三四五六七八九十"
        parts = [spoken] if spoken else []
        parts.append("请选择以下选项：")
        for i, opt in enumerate(options):
            label = opt.get("description") or opt.get("label", "")
            if str(label).startswith("__MIMO_CONNECT_"):
                label = opt.get("label", "")
            label = _strip_for_voice(str(label)).strip()
            if not label or label.startswith("__MIMO_CONNECT_"):
                continue
            ordinal = _ZH_NUM[i] if i < len(_ZH_NUM) else str(i + 1)
            parts.append(f"选项{ordinal}，{label}。")
        return "\n".join(parts)

    async def _voice_last_reply(self, state: SessionState) -> Optional[Reply]:
        """Generate voice from the last agent reply."""
        text = state.last_reply_content or state.last_agent_text
        if not text:
            return Reply(content="没有可以朗读的回复。")

        voice_text = await self._build_voice_text(text)
        if not voice_text:
            return Reply(content="上一条回复没有可朗读的文本内容。")

        voice_path = await self._generate_voice(voice_text, state.user_id)
        if voice_path:
            return Reply(content=text, voice_path=voice_path)
        return Reply(content="语音生成失败。")

    # ─── Option handling ─────────────────────────────────────────────────

    async def _handle_option_select(self, intent: Intent, state: SessionState, original_text: str) -> Optional[Reply]:
        """User selected an option by number or text."""
        idx = intent.option_index
        if 0 <= idx < len(state.pending_options):
            selected = state.pending_options[idx]
            label = selected.get("description") or selected.get("label", "")
            state.pending_work_dir = selected.get("work_dir", "")
            state.pending_options = []
            return await self._handle_option_payload(label, state)

        matched = self._match_option_by_text(intent.payload, state.pending_options)
        state.pending_options = []
        if matched:
            return await self._handle_option_payload(matched, state)

        return await self._send_to_agent(original_text, state)

    async def _handle_option_approve(self, intent: Intent, state: SessionState) -> Optional[Reply]:
        """User approved — if single option, select it; otherwise ask which."""
        if len(state.pending_options) == 1:
            selected = state.pending_options[0]
            label = selected.get("description") or selected.get("label", "")
            state.pending_work_dir = selected.get("work_dir", "")
            state.pending_options = []
            return await self._handle_option_payload(label, state)

        permission_option = next(
            (opt for opt in state.pending_options if opt.get("description") == "__MIMO_CONNECT_APPROVE_WORKDIR__"),
            None,
        )
        if permission_option:
            state.pending_work_dir = permission_option.get("work_dir", "")
        state.pending_options = []
        if permission_option:
            return await self._handle_option_payload("__MIMO_CONNECT_APPROVE_WORKDIR__", state)
        return Reply(content="已确认。")

    async def _handle_custom_option_input(self, payload: str, state: SessionState) -> Optional[Reply]:
        if any(opt.get("description") == "__MIMO_CONNECT_APPROVE_WORKDIR__" for opt in state.pending_options):
            return Reply(content="请先选择是否允许 MiMo Code 切换工作目录，或回复“拒绝”。")
        state.pending_options = []
        return await self._send_to_agent(payload, state)

    async def _handle_option_payload(self, payload: str, state: SessionState) -> Optional[Reply]:
        if payload == "__MIMO_CONNECT_REJECT_PERMISSIONS__":
            return Reply(content="已拒绝授权。")
        if payload.startswith("__MIMO_CONNECT_APPROVE_WORKDIR__::"):
            state.pending_work_dir = payload.split("::", 1)[1]
            return await self._approve_workdir_and_retry(state)
        if payload == "__MIMO_CONNECT_APPROVE_WORKDIR__":
            return await self._approve_workdir_and_retry(state)
        if payload.startswith("__MIMO_CONNECT_SWITCH_MODEL__::"):
            model = payload.split("::", 1)[1]
            return await self._switch_model_and_retry(model, state)
        return await self._send_to_agent(payload, state)

    async def _approve_workdir_and_retry(self, state: SessionState) -> Optional[Reply]:
        work_dir = state.pending_work_dir
        state.pending_work_dir = ""
        if not work_dir:
            return Reply(content="授权失败：没有解析到可切换的目录。")
        if not state.session:
            return Reply(content="授权失败：当前没有可重试的 MiMo Code 会话。")
        if hasattr(state.session, "set_work_dir"):
            state.session.set_work_dir(work_dir)
        if hasattr(state.session, "rerun_last"):
            await state.session.rerun_last()
            return await self._collect_agent_events(state)
        return Reply(content="授权失败：当前 Agent 不支持重试。")

    async def _switch_model_and_retry(self, model: str, state: SessionState) -> Optional[Reply]:
        """Switch the agent model for future sessions.

        The middleware does NOT manage MiMo Code's session files or memory.
        Setting the model here only affects the next time MiMo CLI starts
        a new session. Existing sessions and MiMo-managed files are left
        untouched.
        """
        if not model:
            return Reply(content="模型切换失败：未指定模型名称。")

        if hasattr(self._agent, "set_model"):
            self._agent.set_model(model)
            logger.info(f"Agent model set to: {model} (takes effect on next new session)")

        # The middleware does NOT clear MiMo Code session files or kill
        # running sessions. MiMo Code manages its own memory and session
        # lifecycle. The new model will be used when MiMo CLI next starts
        # a fresh session (e.g. after the current task ends).
        if state.session and state.session.alive():
            return Reply(content=f"已设置模型为 `{model}`。当前任务继续运行，下次新会话时生效。")
        return Reply(content=f"已切换到模型：`{model}`。下次对话将使用新模型。")
    async def _match_digit_option(self, user_input: str, state: SessionState) -> Optional[Reply]:
        """Match digit 1/2 for permission approval before LLM classification."""
        if not state.pending_options:
            return None
        
        lower = user_input.strip().lower()
        
        # Handle permission approve/reject by keyword
        approve_words = {"1", "一", "允许", "同意", "yes", "y", "允许", "准许", "是"}
        reject_words = {"2", "二", "不允许", "拒绝", "no", "n", "不允许", "否", "不"}
        
        # Check if any approve word present → approve first option (which is always allow)
        has_approve = any(word in lower for word in approve_words)
        has_reject = any(word in lower for word in reject_words)
        
        if has_approve and len(state.pending_options) >= 1:
            selected = state.pending_options[0]
            state.pending_work_dir = selected.get("work_dir", "")
            state.pending_options = []
            result = await self._handle_option_payload("__MIMO_CONNECT_APPROVE_WORKDIR__", state)
            logger.info(f"Digit approval matched: approve -> {state.pending_work_dir}")
            return result
        
        if has_reject:
            state.pending_options = []
            state.pending_work_dir = ""
            logger.info("Digit approval matched: reject")
            return Reply(content="已拒绝授权。")
        
        # Match any number to option index
        match = re.search(r'([123456789]\d*)', lower)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(state.pending_options):
                selected = state.pending_options[idx]
                label = selected.get("description") or selected.get("label", "")
                state.pending_work_dir = selected.get("work_dir", "")
                state.pending_options = []
                logger.info(f"Digit approval matched: index={idx} → {label[:30]}")
                return await self._handle_option_payload(label, state)
        
        # Still check if entire input is just one character that is 1 or 2
        if len(lower) == 1:
            if lower == "1" and len(state.pending_options) >= 1:
                selected = state.pending_options[0]
                state.pending_work_dir = selected.get("work_dir", "")
                state.pending_options = []
                logger.info(f"Single char matched: 1 → approve {state.pending_work_dir}")
                return await self._handle_option_payload("__MIMO_CONNECT_APPROVE_WORKDIR__", state)
            if lower == "2":
                state.pending_options = []
                state.pending_work_dir = ""
                logger.info("Single char matched: 2 → reject")
                return Reply(content="已拒绝授权。")
        
        logger.info(f"No digit match for '{user_input}' → going to LLM classification")
        return None

    def _match_option_by_text(self, user_input: str, options: list[dict]) -> Optional[str]:
        """Try to match user text to an option label."""
        lower = user_input.lower()
        for opt in options:
            label = opt.get("label", "").lower()
            if lower in label or label in lower:
                state_work_dir = opt.get("work_dir", "")
                if state_work_dir:
                    return f"__MIMO_CONNECT_APPROVE_WORKDIR__::{state_work_dir}"
                return opt.get("description") or opt.get("label", "")
        return None

    # ─── Agent communication ─────────────────────────────────────────────

    async def _send_to_agent(self, prompt: str, state: SessionState) -> Optional[Reply]:
        """Send prompt to MiMo Code. Collector runs as background task so lock is released."""
        if not state.session or not state.session.alive():
            logger.info(f"Starting new agent session for {state.user_id}")
            state.session = await self._agent.start_session(f"vvm2_{state.user_id}")

        try:
            logger.info(f"Sending to agent: {prompt[:100]}")
            state.last_user_task = prompt
            state.prev_detail_mode = state.detail_mode
            await state.session.send(prompt)
            asyncio.create_task(self._run_collector(state))
            return None

        except Exception as e:
            logger.error(f"Agent processing failed: {e}")
            return Reply(content=f"处理失败: {e}")

    async def _run_collector(self, state: SessionState) -> None:
        """Background wrapper: collector returns are dropped by create_task,
        so any Reply it returns (options/permission/error branches) must be
        sent here explicitly."""
        try:
            reply = await self._collect_agent_events(state)
        except Exception as e:
            logger.error(f"Collector failed: {e}")
            reply = Reply(content=f"处理失败: {e}")
        if reply is not None:
            await self._send_platform_reply(reply, state)

    async def _collect_agent_events(self, state: SessionState) -> Optional[Reply]:
        if not state.session:
            return Reply(content="Agent 会话不存在")

        response_text = ""
        sent_text = ""
        first_chunks: list[str] = []
        detail_buffer: list[str] = []
        last_detail_flush = asyncio.get_event_loop().time()
        
        # Hide mode progress heartbeat tracking
        last_progress_report = asyncio.get_event_loop().time()
        state.task_start_ts = last_progress_report
        # Reset status history for this task so heartbeat reflects only this run
        state.status_history = []
        current_progress_interval = 60.0  # start at 1 minute
        max_progress_interval = 300.0  # max 5 minutes

        async for event in state.session.events():
            if event is None:
                await asyncio.sleep(0)
                sent_text, last_detail_flush = await self._check_mode_switch(
                    state, response_text, sent_text, first_chunks, detail_buffer, last_detail_flush
                )
                continue

            logger.debug(f"Agent event: {event.type} - {event.content[:50] if event.content else ''}")
            
            # Yield to event loop periodically to handle new user messages (like /show)
            await asyncio.sleep(0)

            # If session was aborted, exit collector silently
            if hasattr(state.session, '_aborting') and state.session._aborting:
                logger.info("Collector exiting: task was aborted")
                return None

            # Detect mode switch on every event iteration
            sent_text, last_detail_flush = await self._check_mode_switch(
                state, response_text, sent_text, first_chunks, detail_buffer, last_detail_flush
            )

            # Recovery is handled inside the session (adapter layer) which
            # restarts in-place on the SAME event queue. The engine must not
            # restart concurrently: swapping state.session here while this
            # iterator stays bound to the old queue orphans the old process
            # and causes status churn. session.alive() now stays True while
            # the task runs, so this branch is effectively disabled.
            if not state.session.alive():
                if hasattr(state.session, '_aborting') and state.session._aborting:
                    return None
                logger.warning("MiMo session reported not-alive; ending collector")
                break

            if event.type == EventType.TEXT_CHUNK:
                text = event.content.strip()
                if not text:
                    continue
                response_text += text
                state.last_agent_text = response_text
                logger.info(f"MiMo visible text from {state.user_id}: {text}")

                if state.detail_mode:
                    detail_buffer.append(text)
                    now = asyncio.get_event_loop().time()
                    if now - last_detail_flush >= 3.0:
                        flushed = await self._flush_detail_buffer(detail_buffer, state)
                        sent_text += flushed
                        last_detail_flush = now
                        last_progress_report = now
                else:
                    if not sent_text and len(first_chunks) < 2:
                        first_chunks.append(text)
                    # Send opening immediately on first chunk in hide mode
                    if first_chunks and not sent_text:
                        opening = "\n\n".join(first_chunks).strip()
                        await self._send_platform_reply(await self._make_reply(opening, state), state)
                        sent_text = opening
                        last_progress_report = asyncio.get_event_loop().time()

            elif event.type == EventType.STATUS:
                state.last_status = event.content
                if event.content:
                    state.status_history.append(event.content)
                    # Cap history size to keep prompt small
                    if len(state.status_history) > 30:
                        state.status_history = state.status_history[-30:]

            elif event.type == EventType.PERMISSION_REQUEST:
                options = self._extract_permission_options(event)
                if options:
                    await self._flush_detail_buffer(detail_buffer, state)
                    state.pending_options = options
                    combined = response_text + "\n\n" + event.content if response_text else event.content
                    return await self._make_reply(combined, state, has_options=True)

            elif event.type == EventType.DONE:
                break

            elif event.type == EventType.ERROR:
                if hasattr(state.session, '_aborting') and state.session._aborting:
                    return None
                await self._flush_detail_buffer(detail_buffer, state)
                logger.error(f"Agent error: {event.content}")
                return Reply(content=f"错误: {event.content}")
            
            # Progress heartbeat for hide mode
            # Skip if agent just emitted a restart status (avoids duplicate notifications)
            now = asyncio.get_event_loop().time()
            if (not state.detail_mode
                and now - last_progress_report >= current_progress_interval
                and not (event.type == EventType.STATUS and "无响应" in (event.content or ""))):
                # Report progress with LLM-generated readable description.
                # Input: only the LATEST status line + small context bundle so
                # the middleware LLM (DeepSeek) can interpret a bare event.
                elapsed = int(now - (state.task_start_ts or last_progress_report))
                prior_cats = self._extract_prior_categories(state.status_history)
                result = await self._progress_summarizer.summarize(
                    latest_status=state.last_status,
                    user_task=state.last_user_task,
                    prior_categories=prior_cats,
                    elapsed_sec=elapsed,
                )
                if result.ok:
                    progress_text = f"当前进度：{result.text}"
                else:
                    # Retries exhausted (or no LLM): tell the user the actual cause
                    # plus the raw status as fallback per design rule #3.
                    raw = state.last_status or "MiMo 正在处理中"
                    if result.error:
                        progress_text = (
                            f"当前进度（中间层 LLM 暂时不可用，已重试 3 次）：{raw}\n"
                            f"原因：{result.error}"
                        )
                    else:
                        progress_text = f"当前进度：{raw}"
                await self._send_platform_reply(Reply(content=progress_text), state)
                # Increase interval for next report
                current_progress_interval = min(current_progress_interval + 60.0, max_progress_interval)
                last_progress_report = now
            
            # Always yield after processing each event to keep event loop responsive
            await asyncio.sleep(0)

        flushed = await self._flush_detail_buffer(detail_buffer, state)
        sent_text += flushed

        if not response_text:
            return Reply(content="Agent 无响应")

        state.last_agent_text = response_text
        logger.info(f"MiMo full visible reply for {state.user_id}:\n{response_text}")
        option_content, detected_options = self._extract_options_from_text(response_text)
        if detected_options:
            state.pending_options = detected_options
            return await self._make_reply(option_content or response_text, state, has_options=True)

        unsent = self._remove_sent_prefix(response_text, sent_text)
        if unsent:
            reply = await self._make_reply(unsent, state)
            await self._send_platform_reply(reply, state)
            state.sent_agent_text = response_text

        return None

    def _remove_sent_prefix(self, text: str, sent_text: str) -> str:
        if not sent_text:
            return text.strip()
        compact_text = re.sub(r"\s+", "", text)
        compact_sent = re.sub(r"\s+", "", sent_text)
        if not compact_text.startswith(compact_sent):
            return text.strip()
        text_index = 0
        sent_index = 0
        while text_index < len(text) and sent_index < len(sent_text):
            if sent_text[sent_index].isspace():
                sent_index += 1
            elif text[text_index].isspace():
                text_index += 1
            elif text[text_index] == sent_text[sent_index]:
                text_index += 1
                sent_index += 1
            else:
                break
        return text[text_index:].strip()

    async def _check_mode_switch(
        self,
        state: SessionState,
        response_text: str,
        sent_text: str,
        first_chunks: list[str],
        detail_buffer: list[str],
        last_detail_flush: float,
    ) -> tuple[str, float]:
        """Check for mode switch and flush accordingly. Returns (sent_text, last_detail_flush)."""
        if state.detail_mode == state.prev_detail_mode:
            return sent_text, last_detail_flush

        state.prev_detail_mode = state.detail_mode
        if state.detail_mode:
            # Switched to show: flush all unsent accumulated text
            unsent = self._remove_sent_prefix(response_text, sent_text)
            if unsent:
                await self._send_platform_reply(await self._make_reply(unsent, state), state)
                sent_text = response_text
                state.sent_agent_text = response_text
            last_detail_flush = asyncio.get_event_loop().time()
            logger.info("Mode switch: hide -> show, flushed unsent text")
        else:
            # Switched to hide: send any unsent first_chunks as opening
            if first_chunks and not sent_text:
                opening = "\n\n".join(first_chunks).strip()
                await self._send_platform_reply(await self._make_reply(opening, state), state)
                sent_text = opening
            logger.info("Mode switch: show -> hide")

        return sent_text, last_detail_flush

    async def _flush_detail_buffer(self, buffer: list[str], state: SessionState) -> str:
        if not buffer:
            return ""
        content = "\n\n".join(buffer).strip()
        buffer.clear()
        if content:
            await self._send_platform_reply(await self._make_reply(content, state), state)
        return content

    # ─── Reply construction ──────────────────────────────────────────────

    async def _make_reply(
        self,
        content: str,
        state: SessionState,
        has_options: bool = False,
    ) -> Reply:
        """Build a reply with optional voice.

        Rules:
        - Rich text (code blocks, tables) → text only, no auto-voice
        - Plain text + voice mode on → attach voice AND shorten the displayed
          text to the same condensed body (voice and text both stay brief)
        - Options + voice mode on → attach voice to options text; the body
          shown above the options is condensed too
        - User explicitly asked for voice → always attach
        """
        metadata: dict[str, Any] = {}
        voice_path: Optional[str] = None
        display_content = content

        if has_options:
            metadata["has_options"] = True
            metadata["options"] = state.pending_options

        is_rich = _is_rich_text(content)

        # Voice generation when voice mode is on:
        # - Options reply → always voice (read body + spoken option list)
        # - Plain text → condense then voice
        # - Rich text without options → text only (per design constraint)
        if state.wants_voice and self._voice and self._voice.is_available():
            if has_options:
                # Condense the body once; reuse it for both the spoken text
                # (with options appended) and the displayed body so the
                # chat message stays short too.
                condensed_body = await self._voice_condenser.condense(content)
                spoken_body = condensed_body or _strip_for_voice(content)
                if not condensed_body:
                    state._middleware_notices.append("⚠ 中间层 LLM 不可用，语音摘要已降级。")
                if condensed_body:
                    display_content = condensed_body
                voice_text = self._append_options_for_voice(spoken_body.strip(), state.pending_options)
                if voice_text:
                    voice_path = await self._generate_voice(voice_text, state.user_id)
            elif not is_rich:
                condensed = await self._voice_condenser.condense(content)
                voice_text = condensed or _strip_for_voice(content)
                if not condensed:
                    state._middleware_notices.append("⚠ 中间层 LLM 不可用，语音摘要已降级。")
                # Shorten the displayed text to match the spoken summary so the
                # user reads a brief reply instead of the full body (issue 2).
                if condensed:
                    display_content = condensed
                if voice_text:
                    voice_path = await self._generate_voice(voice_text.strip(), state.user_id)

        return Reply(content=display_content, voice_path=voice_path, metadata=metadata)

    # ─── Option extraction ───────────────────────────────────────────────

    def _extract_permission_options(self, event: Event) -> list[dict]:
        """Extract options from a permission_request event."""
        options = []
        data = event.data or {}

        # Try structured options from event data
        for opt in data.get("options", []):
            if isinstance(opt, dict):
                options.append({
                    "label": opt.get("label", opt.get("description", "")),
                    "description": opt.get("description", opt.get("label", "")),
                    "work_dir": opt.get("work_dir", ""),
                })
            elif isinstance(opt, str):
                options.append({"label": opt, "description": opt})

        # If no structured options, parse from content text
        if not options and event.content:
            _, options = self._extract_options_from_text(event.content)

        return options

    def _extract_options_from_text(self, text: str) -> tuple[str, list[dict]]:
        """Extract fixed-format options after '请选择:' or '请选择：'.

        Strict matching to avoid false positives when the marker appears in
        prose (e.g. when MiMo explains option-parsing logic): the marker must
        sit at the start of a line, and the lines following it must be an
        enumerated list (digit / letter / CJK-numeral prefixed)."""
        enum_re = re.compile(r"^\s*(?:\d+|[A-Za-z]|[一二三四五六七八九十]+)[.)、]\s*\S")
        lines = text.split("\n")
        marker_line = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped in ("请选择：", "请选择:") or stripped.endswith(("请选择：", "请选择:")):
                marker_line = i
        if marker_line is None:
            return text, []

        after_lines = lines[marker_line + 1:]
        options = []
        for line in after_lines:
            item = line.strip()
            if not item:
                if options:
                    break
                continue
            if not enum_re.match(line):
                break
            item = re.sub(r"^\s*(?:\d+|[A-Za-z]|[一二三四五六七八九十]+)[.)、\s]+", "", item).strip()
            item = re.sub(r"^[-*]\s+", "", item).strip()
            if item:
                options.append({"label": item, "description": item})

        if not options:
            return text, []

        before = "\n".join(lines[:marker_line])
        before_marker = lines[marker_line].rsplit("请选择", 1)[0]
        before = (before + "\n" + before_marker).strip()
        return before, options

    # ─── Voice generation ────────────────────────────────────────────────

    async def _generate_voice(self, text: str, user_id: str) -> Optional[str]:
        if not self._voice:
            return None
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = str(Path(tmpdir) / f"reply_{user_id}.ogg")
                result = await self._voice.synthesize(text, output_path)
                if result:
                    import shutil
                    persistent = str(Path(tempfile.gettempdir()) / f"vvm2_voice_{user_id}.ogg")
                    shutil.copy2(result, persistent)
                    return persistent
        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
        return None

    # ─── File sending ────────────────────────────────────────────────────

    async def _try_send_local_file(self, user_input: str, state: SessionState) -> Optional[Reply]:
        """Try to send a local file to the user.
        
        Searches for a file path in:
        1. The current user input (e.g. '把 hello.txt 发给我')
        2. The last agent reply (e.g. MiMo CLI said '文件已创建: /path/file')
        """
        if not any(word in user_input for word in ("发文件", "发给我", "发送文件", "传给我")):
            return None
        import re as _re
        path_pattern = r"[\w.\/:\-一-鿿]+"
        root = Path.cwd()
        
        # Collect candidates from both user input and last agent reply
        sources = [user_input]
        if state.last_agent_text:
            sources.append(state.last_agent_text)
        
        for source in sources:
            candidates = _re.findall(path_pattern, source)
            for candidate in candidates:
                path = Path(candidate)
                if not path.is_absolute():
                    path = root / candidate
                if path.is_file() and hasattr(self._platform, 'send_local_file'):
                    ok = await self._platform.send_local_file(state.user_id, str(path))
                    return Reply(content=f"文件已发送：{path.name}" if ok else f"文件发送失败：{path.name}")
        return None

