"""MiMo Code CLI Agent Adapter for MIMO_Connect.

Streams MiMo Code output via --format stream-json, filtering tool calls
and internal details. Only surfaces final text replies, options, and errors.
Falls back to direct LLM chat when CLI is not available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional

from core.interfaces import Agent, AgentSession, Event, EventType
from core.registry import register_agent

logger = logging.getLogger(__name__)


def _find_mimo_cli() -> Optional[str]:
    """Locate the mimo CLI executable.

    Resolution order: explicit MIMO_CODE_PATH env var (set by the first-run
    setup wizard) -> PATH -> npm global dir.
    """
    configured = os.getenv("MIMO_CODE_PATH", "").strip()
    if configured and os.path.exists(configured):
        return configured
    path = shutil.which("mimo")
    if path:
        return path
    # Fall back to common npm global install locations per platform.
    if os.name == "nt":
        search_dirs = [os.path.expanduser("~/AppData/Roaming/npm")]
        names = ["mimo.cmd", "mimo.ps1", "mimo.exe", "mimo"]
    else:
        search_dirs = [
            os.path.expanduser("~/.npm-global/bin"),
            os.path.expanduser("~/.local/bin"),
            "/usr/local/bin",
            "/usr/bin",
            "/opt/homebrew/bin",  # macOS (Apple Silicon)
        ]
        names = ["mimo"]
    for d in search_dirs:
        for cmd in names:
            candidate = os.path.join(d, cmd)
            if os.path.exists(candidate):
                return candidate
    return None


# Format injection prompt: tells MiMo to tag each output segment by content type
# so the middleware can route segments to the proper Feishu message type.
_FORMAT_INSTRUCTION = (
    "\n\n[格式要求] 回复必须分段标注。每段首行写标签（独占一行），正文紧随其后：\n"
    "[TEXT] 纯文字对话  [MD] markdown格式  [CODE:语言] 代码  [TABLE] 表格\n"
    "标签必写，不可省略。不同类型必须分开标注，不可混在同一段。"
)



# Event types from mimo run --format stream-json
# NOTE: step_finish is handled explicitly (not skipped) so we can read its
# `reason` and classify the step's text as interstitial narration
# (reason="tool-calls") vs the final user-facing answer (reason="stop").
_SKIP_TYPES = frozenset({
    "tool_result", "tool_call",
    "thinking", "reasoning",
    "system", "session_config",
    "step_start",
})

# Phrases in text events that indicate internal/status messages, not user-facing output
_STATUS_PATTERNS = re.compile(
    r"^(?:>|…|\.\.\.).*(?:build|thinking|processing|running|compiling)",
    re.IGNORECASE,
)


class MiMoSession(AgentSession):
    """An active MiMo Code session with streaming output."""

    def __init__(self, session_id: str, work_dir: str = "", llm_client=None, model: str = "", agent_ref=None):
        self._logical_session_id = session_id
        self._session_id = ""
        self._work_dir = work_dir or os.getcwd()
        self._llm_client = llm_client
        self._model = model
        self._agent_ref = agent_ref  # Reference to parent MiMoAgent for list_models()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._alive = False
        self._closed = False
        self._aborting = False
        self._cli_cmd = self._find_cli()
        self._last_prompt = ""
        self._permission_requested = False
        self._emitted_permissions: set[str] = set()
        # Per-step text buffer. MiMo emits interstitial "what I'll do next"
        # narration as type=text events on steps that end with reason
        # "tool-calls"; only the step ending with reason "stop" carries the
        # final user-facing answer. We buffer text per step and decide at
        # step_finish whether to surface it as the answer (stop) or demote it
        # to a STATUS progress line (tool-calls), so narration never leaks
        # into — or prefixes — the final reply.
        self._step_text_buffer: list[str] = []
        self._session_store = Path(__file__).resolve().parents[2] / ".mimocode" / "mimo_connect_sessions"
        self._legacy_session_store = Path(__file__).resolve().parents[2] / ".mimocode" / "vvm2_sessions"
        self._load_session_id()
        self._last_stdout_time: float = 0.0
        self._consecutive_timeouts: int = 0
        self._max_consecutive_timeouts: int = 3  # Kill after 3 consecutive 60s timeouts (3 min)
        self._restart_count: int = 0
        self._max_restarts: int = 5  # Stop restarting after 5 consecutive attempts

    def _load_session_id(self) -> None:
        # Try new store first, then legacy store
        for store in [self._session_store, self._legacy_session_store]:
            path = store / f"{self._logical_session_id}.txt"
            if path.exists():
                self._session_id = path.read_text(encoding="utf-8").strip()
                if self._session_id:
                    logger.info(f"MiMo status: restored session={self._session_id} from {store.name}")
                    # Migrate to new store if reading from legacy
                    if store == self._legacy_session_store:
                        self._save_session_id()
                    return

    def _save_session_id(self) -> None:
        if self._session_id:
            self._session_store.mkdir(parents=True, exist_ok=True)
            path = self._session_store / f"{self._logical_session_id}.txt"
            path.write_text(self._session_id, encoding="utf-8")

    def _find_cli(self) -> Optional[str]:
        return _find_mimo_cli()

    async def send(self, prompt: str) -> None:
        while not self._events.empty():
            self._events.get_nowait()

        if self._task and not self._task.done():
            logger.warning("MiMo is still running; terminating previous task")
            await self.close()
            self._closed = False

        self._aborting = False
        logger.info("Scheduling MiMo task")
        self._last_prompt = prompt
        self._step_text_buffer = []
        injected_prompt = prompt + _FORMAT_INSTRUCTION
        self._task = asyncio.create_task(self._run_mimo(injected_prompt))

    def set_work_dir(self, path: str) -> None:
        self._work_dir = self._resolve_allowed_dir(path) or path

    async def rerun_last(self) -> None:
        if self._last_prompt:
            await self.send(self._last_prompt)
        else:
            await self._events.put(Event(type=EventType.ERROR, content="没有可重试的上一条指令"))

    async def _run_mimo(self, prompt: str) -> None:
        if not self._cli_cmd:
            logger.warning("No CLI found, falling back to LLM chat")
            await self._llm_chat(prompt)
            return

        try:
            self._alive = True
            self._permission_requested = False
            self._emitted_permissions.clear()
            args = [self._cli_cmd, "run", "--format", "json", "--dangerously-skip-permissions"]
            if self._model:
                args.extend(["-m", self._model])
            if self._session_id:
                args.extend(["--session", self._session_id])
            args.append(prompt)
            logger.info(f"Launching MiMo CLI: {' '.join(args[:6])}... (cwd={self._work_dir}, session={self._session_id or 'new'}, model={self._model or 'default'})")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._work_dir,
            )
            self._process = process
            logger.info(f"MiMo status: running pid={process.pid}, cwd={self._work_dir}, session={self._session_id or 'new'}")

            assert process.stdout is not None
            line_count = 0
            self._last_stdout_time = asyncio.get_event_loop().time()
            self._consecutive_timeouts = 0
            stderr_task = asyncio.create_task(self._read_stderr(process))
            while True:
                try:
                    raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=60.0)
                    self._consecutive_timeouts = 0  # Reset on any output
                    self._last_stdout_time = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        self._consecutive_timeouts += 1
                        elapsed = int(asyncio.get_event_loop().time() - self._last_stdout_time)
                        logger.warning(f"MiMo process pid={process.pid} has no stdout for {elapsed}s (timeout #{self._consecutive_timeouts}/{self._max_consecutive_timeouts})")
                        
                        if self._consecutive_timeouts >= self._max_consecutive_timeouts:
                            self._restart_count += 1
                            if self._restart_count > self._max_restarts:
                                logger.error(f"MiMo process pid={process.pid} stuck and exceeded {self._max_restarts} restarts; giving up")
                                await self._terminate_process_tree(process.pid)
                                try:
                                    await asyncio.wait_for(process.wait(), timeout=5.0)
                                except asyncio.TimeoutError:
                                    pass
                                self._alive = False
                                await self._events.put(Event(
                                    type=EventType.ERROR,
                                    content=f"MiMo CLI 多次重启仍无响应，已停止（重启 {self._max_restarts} 次）。"
                                ))
                                return
                            logger.error(f"MiMo process pid={process.pid} stuck for {elapsed}s, killing and restarting (#{self._restart_count}/{self._max_restarts})...")
                            await self._events.put(Event(
                                type=EventType.STATUS,
                                content=f"MiMo CLI 无响应 {elapsed} 秒，正在重启..."
                            ))
                            await self._terminate_process_tree(process.pid)
                            try:
                                await asyncio.wait_for(process.wait(), timeout=5.0)
                            except asyncio.TimeoutError:
                                await self._terminate_process_tree(process.pid)
                            self._alive = False
                            # Re-launch with same prompt
                            self._consecutive_timeouts = 0
                            logger.info(f"Restarting MiMo CLI with same prompt...")
                            await self._events.put(Event(
                                type=EventType.STATUS,
                                content="MiMo CLI 已重启，正在重新执行..."
                            ))
                            # Use a new process launch
                            new_process = await asyncio.create_subprocess_exec(
                                *args,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                cwd=self._work_dir,
                            )
                            process = new_process
                            self._process = process
                            self._alive = True
                            self._step_text_buffer = []
                            self._last_stdout_time = asyncio.get_event_loop().time()
                            stderr_task.cancel()
                            stderr_task = asyncio.create_task(self._read_stderr(process))
                            logger.info(f"MiMo CLI restarted: pid={process.pid}")
                            continue
                        continue
                    break
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                line_count += 1
                logger.debug(f"MiMo stdout [{line_count}]: {line[:200]}")
                await self._process_line(line)
                if self._permission_requested and process.returncode is None:
                    await self._terminate_process_tree(process.pid)
                    break

            await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            self._alive = False
            logger.info(f"MiMo status: exited code={process.returncode}, stdout_lines={line_count}, session={self._session_id or 'unknown'}")

            if process.returncode != 0:
                if not self._permission_requested:
                    await self._events.put(Event(type=EventType.ERROR, content=f"mimo run exited with {process.returncode}"))
                return

            # Defensive: if the final step never emitted reason="stop" (so the
            # buffered text was not surfaced), flush it now as the answer
            # rather than silently dropping the user's reply.
            if self._step_text_buffer:
                leftover = "\n".join(self._step_text_buffer).strip()
                self._step_text_buffer = []
                if leftover:
                    await self._events.put(Event(type=EventType.TEXT_CHUNK, content=leftover))

            await self._events.put(Event(type=EventType.DONE))

        except Exception as e:
            self._alive = False
            logger.error(f"Failed to run MiMo: {e}", exc_info=True)
            await self._events.put(Event(type=EventType.ERROR, content=str(e)))

    async def _read_stderr(self, process: asyncio.subprocess.Process) -> None:
        if not process.stderr:
            return
        buffer = ""
        while True:
            raw_chunk = await process.stderr.read(4096)
            if not raw_chunk:
                break
            chunk = raw_chunk.decode("utf-8", errors="replace")
            buffer = (buffer + chunk)[-8000:]
            cleaned = self._clean_ansi(buffer).strip()
            if cleaned:
               logger.warning(f"MiMo stderr: {cleaned[:500]}")
               event = self._parse_stderr_permission(cleaned)
               if event:
                   permission = event.data.get("permission", "")
                   if permission not in self._emitted_permissions:
                       self._emitted_permissions.add(permission)
                       self._permission_requested = True
                       await self._events.put(event)
                       if process.returncode is None:
                           await self._terminate_process_tree(process.pid)
                       buffer = ""
                       break
               else:
                   # Non-permission stderr (e.g. model errors, Bun crashes):
                   # forward as ERROR so the user sees it instead of a silent
                   # "Agent 无响应" timeout.
                   await self._events.put(
                       Event(type=EventType.ERROR, content=f"MiMo stderr: {cleaned[:500]}")
                   )
                   buffer = ""

    def _resolve_allowed_dir(self, text: str) -> str:
        paths = re.findall(r"[A-Za-z]:\\[^,);]+|/[^,);]+", text)
        candidates = []
        for raw_path in paths:
            path = raw_path.strip().rstrip("* ").rstrip("\\/")
            if path:
                candidates.append(path)
        for path in candidates:
            if os.path.isdir(path):
                return path
        return candidates[0] if candidates else ""

    def _parse_stderr_permission(self, line: str) -> Optional[Event]:
        line = self._clean_ansi(line)
        match = re.search(r"permission requested:\s*(.*?)(?:;\s*auto-rejecting|$)", line, re.IGNORECASE)
        if not match:
            return None
        permission = match.group(1).strip()
        allowed_dir = self._resolve_allowed_dir(permission)
        content = f"MiMo Code 请求访问：{permission}\n是否将工作目录切换到该目录并重试？"
        return Event(
            type=EventType.PERMISSION_REQUEST,
            content=content,
            data={
                "source": "stderr",
                "permission": permission,
                "allowed_dir": allowed_dir,
                "options": [
                    {"label": f"允许目录：{allowed_dir or permission}", "description": "__MIMO_CONNECT_APPROVE_WORKDIR__", "work_dir": allowed_dir},
                    {"label": "拒绝", "description": "__MIMO_CONNECT_REJECT_PERMISSIONS__"},
                ],
            },
        )

    async def _process_line(self, line: str) -> None:
        """Process a single JSON line from the stream."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            cleaned = self._clean_ansi(line)
            event = self._parse_stderr_permission(cleaned)
            if event:
                permission = event.data.get("permission", "")
                if permission not in self._emitted_permissions:
                    self._emitted_permissions.add(permission)
                    self._permission_requested = True
                    await self._events.put(event)
                return
            if cleaned and not _STATUS_PATTERNS.match(cleaned):
                await self._events.put(Event(type=EventType.TEXT_CHUNK, content=cleaned))
            return

        # Capture session ID
        if data.get("sessionID"):
            new_session_id = data["sessionID"]
            if new_session_id != self._session_id:
                self._session_id = new_session_id
                self._save_session_id()
                logger.info(f"MiMo status: session={self._session_id}")

        msg_type = data.get("type", "")

        if msg_type == "tool_use":
            self._log_tool_use(data)
            return

        # Handle CLI error events (e.g. model not found)
        if msg_type == "error":
            await self._handle_cli_error(data)
            return

        # step_finish carries the reason this step ended. Flush the buffered
        # step text accordingly: reason "stop" → final answer (TEXT_CHUNK);
        # anything else (e.g. "tool-calls") → interstitial narration, demoted
        # to a STATUS line so it informs progress without polluting the reply.
        if msg_type == "step_finish":
            self._flush_step_text(data)
            return

        # Skip internal event types (tool results, thinking, etc.)
        if msg_type in _SKIP_TYPES:
            return

        # Handle permission/tool approval requests as option events
        if msg_type == "permission_request":
            await self._events.put(Event(
                type=EventType.PERMISSION_REQUEST,
                content=data.get("message", ""),
                data=data,
            ))
            return

        # Handle text output — buffer per step; do not emit yet. The
        # step_finish reason decides whether this text is the final answer
        # or interstitial narration.
        text = self._extract_text(data)
        if text:
            self._step_text_buffer.append(text)

    def _flush_step_text(self, data: dict) -> None:
        """Emit buffered step text based on the step_finish reason.

        reason == "stop"  → final user-facing answer → TEXT_CHUNK.
        otherwise (e.g. "tool-calls") → interstitial narration → STATUS only,
        so it never leaks into or prefixes the final reply.
        """
        if not self._step_text_buffer:
            return
        text = "\n".join(self._step_text_buffer).strip()
        self._step_text_buffer = []
        if not text:
            return
        part = data.get("part", {}) if isinstance(data, dict) else {}
        reason = part.get("reason", "") if isinstance(part, dict) else ""
        if reason == "stop":
            try:
                self._events.put_nowait(Event(type=EventType.TEXT_CHUNK, content=text))
            except Exception:
                pass
        else:
            try:
                self._events.put_nowait(Event(
                    type=EventType.STATUS,
                    content=f"category=narration, note={text[:120]}",
                ))
            except Exception:
                pass

    async def _handle_cli_error(self, data: dict) -> None:
        """Handle CLI error events (e.g. model not found).

       For model-related errors, fetch available models and emit an options
       event so the user can select a different model.
       """
        raw_error = data.get("error", {})
        # MiMo CLI may emit error as a string or a dict; guard against both.
        if isinstance(raw_error, str):
            error_msg = raw_error
        elif isinstance(raw_error, dict):
            error_data = raw_error.get("data", {})
            error_msg = error_data.get("message", raw_error.get("message", "Unknown error"))
        else:
            # Fallback: treat the whole data["error"] as string representation
            error_msg = str(raw_error) if raw_error else "Unknown error"

        # Also check top-level "message" if error field was empty/unhelpful
        if error_msg in ("", "Unknown error", "{}", "None"):
            error_msg = data.get("message", error_msg)

        logger.error(f"MiMo CLI error: {error_msg}")

        # Check if this is a model-related error
        model_error_patterns = [
            "model not found",
            "model not available",
            "providermodelnotfounderror",
            "invalid model",
            "model does not exist",
        ]
        is_model_error = any(p in error_msg.lower() for p in model_error_patterns)

        if is_model_error:
            # Clear the forwarded model so MiMo CLI falls back to its
            # own default. The middleware does not store or manage MiMo
            # Code's model selection; it only forwards user requests.
            rolled_back = ""
            if self._agent_ref:
                # Clear the -m flag so next mimo run uses CLI default
                self._agent_ref._model = ""
                rolled_back = "已恢复使用 MiMo Code 默认模型。"
                logger.info("Cleared forwarded model due to model error; MiMo CLI will use default")
            # Fetch available models
            models = await self._agent_ref.list_models() if self._agent_ref else []
            if not models:
                # Try direct CLI call
                cli = self._find_cli()
                if cli:
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            cli, "models",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                        if proc.returncode == 0:
                            models = [ln.strip() for ln in out.decode("utf-8", errors="replace").splitlines() if ln.strip()]
                    except Exception:
                        pass

            if models:
                # Build options list
                options = [
                    {"label": m, "description": f"__MIMO_CONNECT_SWITCH_MODEL__::{m}"}
                    for m in models
                ]
                content = f"模型错误：{error_msg}"
                if rolled_back:
                    content += f"\n{rolled_back}"
                content += "\n\n请选择要切换的模型："
                await self._events.put(Event(
                    type=EventType.PERMISSION_REQUEST,
                    content=content,
                    data={
                        "source": "model_error",
                        "permission": error_msg,
                        "options": options,
                    },
                ))
            else:
                content = f"模型错误：{error_msg}"
                if rolled_back:
                    content += f"\n{rolled_back}"
                content += "\n（无法获取可用模型列表）"
                await self._events.put(Event(
                    type=EventType.ERROR,
                    content=content,
                ))
        else:
            # Non-model error, emit as regular error
            await self._events.put(Event(
                type=EventType.ERROR,
                content=f"MiMo CLI 错误：{error_msg}",
            ))

    def _log_tool_use(self, data: dict) -> None:
        part = data.get("part", {}) if isinstance(data, dict) else {}
        state = part.get("state", {}) if isinstance(part, dict) else {}
        tool = part.get("tool", "unknown") if isinstance(part, dict) else "unknown"
        status = state.get("status", "unknown") if isinstance(state, dict) else "unknown"
        call_id = part.get("callID", "") if isinstance(part, dict) else ""
        title = part.get("title", "") if isinstance(part, dict) else ""
        time_info = state.get("time", {}) if isinstance(state, dict) else {}
        duration = ""
        if isinstance(time_info, dict) and time_info.get("start") and time_info.get("end"):
            duration = f", duration={time_info['end'] - time_info['start']}ms"
        category = self._tool_category(tool)
        # Log input summary (file path, command prefix, etc.)
        input_summary = self._summarize_tool_input(tool, part.get("input", {}))
        summary = f"category={category}, tool={tool}, status={status}, call_id={call_id[:12]}, title={title[:80]}{duration}"
        if input_summary:
            summary += f", input={input_summary}"
        logger.info(f"MiMo status: {summary}")
        try:
            self._events.put_nowait(Event(type=EventType.STATUS, content=summary))
        except Exception:
            pass

    @staticmethod
    def _summarize_tool_input(tool: str, inp: dict) -> str:
        """Extract a short summary of tool input for logging (no secrets)."""
        if not isinstance(inp, dict):
            return ""
        if tool in ("read", "glob", "grep"):
            return inp.get("file_path", inp.get("pattern", ""))[:120]
        if tool in ("write", "edit"):
            return inp.get("file_path", "")[:120]
        if tool in ("bash", "shell", "terminal"):
            cmd = inp.get("command", "")
            return cmd[:80] if cmd else ""
        if tool == "task":
            return inp.get("description", "")[:80]
        return ""

    def _tool_category(self, tool: str) -> str:
        if tool in ("read", "glob", "grep", "ls"):
            return "reading_files"
        if tool in ("write", "edit"):
            return "modifying_files"
        if tool in ("bash", "shell", "terminal"):
            return "running_command"
        if tool == "task":
            return "subagent_task"
        return "using_tool"

    def _extract_text(self, data: dict) -> str:
        """Extract user-facing text from a stream event, skipping tool-related content."""
        # Direct text field
        if "text" in data and isinstance(data["text"], str):
            text = data["text"].strip()
            if text and not _STATUS_PATTERNS.match(text):
                return text

        # Part field (mimo CLI uses this)
        part = data.get("part", {})
        if isinstance(part, dict):
            if part.get("type") == "text" and part.get("text"):
                return part["text"].strip()

        # Message content array
        message = data.get("message", {})
        if isinstance(message, dict):
            content_list = message.get("content", [])
            if isinstance(content_list, list):
                text_parts = []
                for block in content_list:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            t = block.get("text", "").strip()
                            if t:
                                text_parts.append(t)
                    elif isinstance(block, str):
                        text_parts.append(block.strip())
                if text_parts:
                    return "\n".join(text_parts).strip()

        return ""

    def _clean_ansi(self, text: str) -> str:
        text = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line and not line.startswith("> build ·")]
        return "\n".join(lines).strip()

    async def _llm_chat(self, prompt: str) -> None:
        """Direct LLM chat fallback when CLI is not available."""
        if not self._llm_client:
            await self._events.put(Event(type=EventType.TEXT_CHUNK, content="抱歉，CLI 未安装且 LLM 不可用。"))
            await self._events.put(Event(type=EventType.DONE))
            return

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            messages = [
                SystemMessage(content="你是一个友好的AI助手。用简洁的中文回答用户问题。"),
                HumanMessage(content=prompt),
            ]
            response = await self._llm_client.ainvoke(messages)
            await self._events.put(Event(type=EventType.TEXT_CHUNK, content=response.content))
            await self._events.put(Event(type=EventType.DONE))
        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            await self._events.put(Event(type=EventType.ERROR, content=f"LLM 调用失败: {e}"))

    def events(self) -> AsyncIterator[Event]:
        return self._EventIterator(self)

    class _EventIterator:
        def __init__(self, session):
            self._session = session
            self._exhausted = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            while not self._exhausted:
                try:
                    event = await asyncio.wait_for(self._session._events.get(), timeout=1.0)
                    if event.type in (EventType.DONE, EventType.ERROR):
                        self._exhausted = True
                    return event
                except asyncio.TimeoutError:
                    task_done = bool(self._session._task and self._session._task.done())
                    if task_done and self._session._events.empty():
                        self._exhausted = True
                        raise StopAsyncIteration
                    # Yield None so the caller can do housekeeping (mode switch, etc.)
                    return None
            raise StopAsyncIteration

    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def alive(self) -> bool:
        if self._closed:
            return False
        # Restart/recovery is handled entirely inside _run_mimo (adapter layer).
        # The engine must NOT restart concurrently: doing so swaps state.session
        # while the engine's event iterator stays bound to the old queue, which
        # orphans the old process (nobody can close it) and causes status churn.
        # As long as the task is running (or events remain buffered), report alive.
        return True

    async def _terminate_process_tree(self, pid: int) -> None:
        if os.name == "nt":
            proc = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(pid), "/T", "/F",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info(f"MiMo status: taskkill tree pid={pid}, code={proc.returncode}")
        elif self._process:
            self._process.terminate()

    async def _cancel_task(self) -> None:
        """Cancel the running _run_mimo coroutine and wait for it to unwind.

        Awaiting is essential: a fire-and-forget cancel() leaves a window where
        the coroutine may have just spawned a replacement process but not yet
        stored its handle, orphaning that process."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"MiMo task raised during cancel: {e}")

    async def _kill_process(self) -> None:
        """Force-kill the current process and its whole tree, with a tree-kill
        fallback (NOT single-process kill) so node grandchildren never leak."""
        if not (self._process and self._process.returncode is None):
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()
            await self._terminate_process_tree(self._process.pid)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"MiMo process pid={self._process.pid} survived taskkill; retrying tree kill")
                await self._terminate_process_tree(self._process.pid)
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.error(f"MiMo process pid={self._process.pid} could not be killed")
        except Exception as e:
            logger.warning(f"Failed to kill MiMo process: {e}")

    async def close(self) -> None:
        self._closed = True
        self._alive = False
        await self._cancel_task()
        await self._kill_process()

    async def abort(self) -> None:
        """Abort current task but preserve session ID for resume.

        Unlike close(), this keeps _closed=False and the session ID intact
        so the next send() re-launches a process with the same session.
        """
        self._aborting = True
        self._alive = False
        await self._cancel_task()
        await self._kill_process()
        # Clear event queue
        while not self._events.empty():
            try:
                self._events.get_nowait()
            except Exception:
                break
        logger.info(f"MiMo session aborted (session={self._session_id} preserved)")

class MiMoAgent(Agent):
    """MiMo Code CLI agent adapter."""

    def __init__(self, work_dir: str = "", llm_client=None, model: str = ""):
        self._work_dir = work_dir
        self._llm_client = llm_client
        self._model = model
        self._sessions: list[MiMoSession] = []
    def name(self) -> str:
        return "mimo-code"

    def set_llm_client(self, client) -> None:
        self._llm_client = client

    def set_model(self, model: str) -> None:
        """Set the model forwarded to MiMo CLI via -m flag."""
        self._model = model
        logger.info(f"MiMo CLI model forwarded to: {model or "(default)"}")
        """Get the current model."""
        return self._model

    async def list_models(self) -> list[str]:
        """Return available model names by running `mimo models`."""
        cli = _find_mimo_cli()
        if not cli:
            return []
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "models",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                text = out.decode("utf-8", errors="replace").strip()
                return [ln.strip() for ln in text.splitlines() if ln.strip()]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
        return []

    async def start_session(self, session_id: str, work_dir: str = "") -> AgentSession:
        session = MiMoSession(session_id, work_dir or self._work_dir, self._llm_client, self._model, agent_ref=self)
        self._sessions.append(session)
        return session

    async def stop(self) -> None:
        for session in list(self._sessions):
            await session.close()
        self._sessions.clear()


register_agent("mimo-code", MiMoAgent)
