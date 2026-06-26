"""Feishu/Lark platform adapter for MIMO_Connect.

Uses lark-oapi SDK with WebSocket long connection for receiving events.
Sends messages via REST API with tenant_access_token auto-management.
Supports text and audio messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from core.interfaces import Message, MessageType, Platform, Reply
from core.registry import register_platform
from core.segment_parser import (
    SEG_CODE,
    SEG_MD,
    SEG_TABLE,
    SEG_TEXT,
    Segment,
    parse_segments,
    strip_tags,
)

logger = logging.getLogger(__name__)


class FeishuPlatform(Platform):
    """Feishu/Lark bot platform adapter.

    Connects via WebSocket (lark-oapi SDK) to receive messages.
    Sends replies via Feishu Open API.
    """

    def __init__(self, app_id: str = "", app_secret: str = "", base_url: str = "https://open.feishu.cn"):
        self._app_id = app_id or os.getenv("FEISHU_APP_ID", "")
        self._app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")
        self._base_url = base_url.rstrip("/")
        self._handler: Optional[Callable[[Message], Any]] = None
        self._client: Any = None  # lark_oapi.Client (REST)
        self._ws_client: Any = None  # lark_oapi.ws.Client
        self._ws_thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._recent_msg_meta: dict[str, dict[str, str]] = {}

    def name(self) -> str:
        return "feishu"

    async def start(self, handler: Callable[[Message], Any]) -> None:
        self._handler = handler
        self._loop = asyncio.get_running_loop()

        if not self._app_id or not self._app_secret:
            raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET are required. Set them in .env")

        try:
            import lark_oapi as lark  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError("请先安装 lark-oapi: pip install lark-oapi") from e

        self._client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        self._running = True
        logger.info(f"FeishuPlatform starting WebSocket connection (app_id={self._app_id[:8]}...)")

        ready = threading.Event()

        def _run_ws():
            import lark_oapi as lark  # type: ignore[import-not-found]
            import lark_oapi.ws.client as ws_mod  # type: ignore[import-not-found]
            from lark_oapi.ws import Client as WSClient  # type: ignore[import-not-found]

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ws_mod.loop = loop

            def on_message(data: Any) -> None:
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._handle_event(data), self._loop)

            event_handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(on_message)
                .build()
            )

            self._ws_client = WSClient(
                self._app_id,
                self._app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO,
            )

            ready.set()
            try:
                self._ws_client.start()
            except Exception as e:
                logger.error(f"WSClient.start() error: {e}")
            finally:
                loop.close()

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True, name="feishu-ws")
        self._ws_thread.start()
        ready.wait(timeout=15)

        if not self._ws_client:
            raise RuntimeError("Feishu WSClient failed to initialize")

        # start() blocks until disconnect, so we just wait on the thread
        try:
            while self._running and self._ws_thread.is_alive():
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("FeishuPlatform cancelled")
        finally:
            await self.stop()

    async def _handle_event(self, data: Any) -> None:
        try:
            event = data.event
            raw_msg = event.message
            sender = event.sender

            sender_type = getattr(sender, "sender_type", "user")
            if sender_type == "bot":
                return

            content, msg_type = self._extract_content(raw_msg)
            if not content:
                return

            sender_id = (
                getattr(sender.sender_id, "open_id", "")
                or getattr(sender.sender_id, "user_id", "")
                or ""
            )

            message_id = getattr(raw_msg, "message_id", "")
            chat_id = getattr(raw_msg, "chat_id", "")
            chat_type = getattr(raw_msg, "chat_type", "")

            self._recent_msg_meta[sender_id] = {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": chat_type,
            }

            msg = Message(
                id=message_id,
                content=content,
                msg_type=msg_type,
                from_user=sender_id,
                to_user=chat_id,
                raw=data.raw if hasattr(data, "raw") else {},
                metadata={
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                },
            )

            logger.info(f"Feishu received from {sender_id} ({chat_type}): {content[:80]}")

            if self._handler:
                asyncio.create_task(self._handler(msg))

        except Exception as e:
            logger.error(f"Feishu event handling failed: {e}", exc_info=True)

    def _extract_content(self, raw_msg: Any) -> tuple[str, MessageType]:
        msg_type = getattr(raw_msg, "message_type", "")
        content_str = getattr(raw_msg, "content", "") or ""

        if msg_type == "text":
            try:
                text = json.loads(content_str).get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                text = content_str.strip()
            return text, MessageType.TEXT

        if msg_type == "audio":
            try:
                content_obj = json.loads(content_str)
                text = content_obj.get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                text = ""
            if text:
                return text, MessageType.VOICE
            return "[语音消息]", MessageType.VOICE

        if msg_type == "image":
            return "[图片]", MessageType.IMAGE

        if msg_type == "file":
            try:
                content_obj = json.loads(content_str)
                file_name = content_obj.get("file_name", "")
            except (json.JSONDecodeError, AttributeError):
                file_name = ""
            return f"[文件: {file_name}]" if file_name else "[文件]", MessageType.FILE

        if msg_type == "post":
            try:
                content_obj = json.loads(content_str)
                texts = []
                for lang_content in content_obj.values():
                    if isinstance(lang_content, dict):
                        for para in lang_content.get("content", []):
                            for elem in para:
                                if elem.get("tag") == "text":
                                    texts.append(elem.get("text", ""))
                    elif isinstance(lang_content, list):
                        for para in lang_content:
                            for elem in para:
                                if elem.get("tag") == "text":
                                    texts.append(elem.get("text", ""))
                text = " ".join(texts).strip()
                if text:
                    return text, MessageType.TEXT
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
            return "[富文本]", MessageType.TEXT

        if msg_type == "interactive":
            return "[卡片消息]", MessageType.TEXT

        return "", MessageType.TEXT

    async def send_reply(self, reply: Reply, context_token: str = "") -> bool:
        user_id = reply.metadata.get("from_user", "")
        meta = self._recent_msg_meta.get(user_id, {})
        message_id = reply.metadata.get("message_id") or meta.get("message_id", "")
        chat_id = reply.metadata.get("chat_id") or meta.get("chat_id", "")

        if not chat_id:
            logger.error(f"Cannot send reply: no chat_id for user {user_id}")
            return False

        if reply.voice_path:
            ok = await self._send_audio(message_id, chat_id, reply.voice_path)
            if ok:
                # When the reply carries selectable options, also send the
                # text version so the user can read the choices, not only
                # hear them. For non-option voice replies, audio is enough.
                if reply.metadata.get("options"):
                    await self._send_options_text(message_id, chat_id, reply)
                return True
            logger.warning("Feishu audio reply failed, falling back to text")

        if reply.content:
            content = reply.content
            options = reply.metadata.get("options") or []
            if options:
                return await self._send_options_text(message_id, chat_id, reply)
            return await self._send_segments(message_id, chat_id, content)

        return False

    async def _send_options_text(self, message_id: str, chat_id: str, reply: Reply) -> bool:
        """Render an options reply as a plain numbered text message."""
        cleaned = strip_tags(reply.content)
        options = reply.metadata.get("options") or []
        lines = [cleaned, "", "请选择："]
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}. {opt.get('label', opt.get('description', ''))}")
        return await self._send_text(message_id, chat_id, "\n".join(lines))

    async def _send_segments(self, message_id: str, chat_id: str, content: str) -> bool:
        """Split tagged content into segments and send each with the right Feishu msg_type.

        - TEXT  -> plain text message
        - MD    -> interactive card with lark_md
        - CODE  -> interactive card with a code-formatted block (lark_md fenced)
        - TABLE -> interactive card with lark_md (Feishu cards render pipe tables in lark_md poorly,
                   but it's still better than raw text; falls back to text on send failure)
        Reply target (message_id) is only used for the FIRST segment so that subsequent
        messages don't all attach to the same reply thread. All segments share chat_id.
        """
        segments = parse_segments(content)
        logger.info(f"Parsed {len(segments)} segments: {[f'{s.kind}({s.lang})' for s in segments]}")
        if not segments:
            return await self._send_text(message_id, chat_id, strip_tags(content) or content)

        any_ok = False
        first = True
        for seg in segments:
            reply_to = message_id if first else ""
            ok = await self._send_segment(reply_to, chat_id, seg)
            if ok:
                any_ok = True
            first = False
        return any_ok

    async def _send_segment(self, message_id: str, chat_id: str, seg: Segment) -> bool:
        if seg.kind == SEG_TEXT:
            return await self._send_text(message_id, chat_id, seg.content)
        if seg.kind == SEG_CODE:
            # Use Feishu card code_block element for proper code rendering
            return await self._send_code_block(message_id, chat_id, seg.lang or "", seg.content)
        # SEG_MD and SEG_TABLE both use lark_md card; table degrades to text on failure.
        ok = await self._send_card(message_id, chat_id, seg.content)
        if ok:
            return True
        return await self._send_text(message_id, chat_id, seg.content)

    async def _send_card(self, message_id: str, chat_id: str, lark_md_content: str) -> bool:
        try:
            from lark_oapi.api.im.v1 import (  # type: ignore[import-not-found]
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )

            # Use Card JSON 2.0 for full markdown support (headings, tables, etc.)
            # Requires Feishu client 7.20+
            card = {
                "schema": "2.0",
                "config": {"wide_screen_mode": True},
                "body": {
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": lark_md_content,
                        }
                    ]
                },
            }
            content = json.dumps(card, ensure_ascii=False)

            if message_id:
                req = (
                    ReplyMessageRequest.builder()
                    .message_id(message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content)
                        .msg_type("interactive")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.reply, req)
            else:
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .content(content)
                        .msg_type("interactive")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

            if not resp.success():
                logger.error(f"Feishu card send failed: code={resp.code}, msg={resp.msg}")
                return False
            return True
        except Exception as e:
            logger.error(f"Feishu card send exception: {e}", exc_info=True)
            return False

    async def _send_text(self, message_id: str, chat_id: str, text: str) -> bool:
        try:
            from lark_oapi.api.im.v1 import (  # type: ignore[import-not-found]
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )

            content = json.dumps({"text": text}, ensure_ascii=False)

            if message_id:
                req = (
                    ReplyMessageRequest.builder()
                    .message_id(message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content)
                        .msg_type("text")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.reply, req)
            else:
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .content(content)
                        .msg_type("text")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

            if not resp.success():
                logger.error(f"Feishu send text failed: code={resp.code}, msg={resp.msg}")
                return False

            logger.info(f"Feishu text sent to {chat_id}")
            return True

        except Exception as e:
            logger.error(f"Feishu send text error: {e}", exc_info=True)
            return False

    async def _send_code_block(self, message_id: str, chat_id: str, language: str, code: str) -> bool:
        """Send code using Feishu card markdown component with code fences."""
        try:
            from lark_oapi.api.im.v1 import (  # type: ignore[import-not-found]
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )

            # Use Card JSON 2.0 with markdown component for code blocks
            code_content = f"```{language}\n{code}\n```" if language else f"```\n{code}\n```"

            card = {
                "schema": "2.0",
                "config": {"wide_screen_mode": True},
                "body": {
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": code_content,
                        }
                    ]
                },
            }
            content = json.dumps(card, ensure_ascii=False)

            if message_id:
                req = (
                    ReplyMessageRequest.builder()
                    .message_id(message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content)
                        .msg_type("interactive")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.reply, req)
            else:
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .content(content)
                        .msg_type("interactive")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

            if not resp.success():
                logger.error(f"Feishu code_block send failed: code={resp.code}, msg={resp.msg}")
                # Fallback to plain text
                fallback = f"```{language}\n{code}\n```" if language else f"```\n{code}\n```"
                return await self._send_text(message_id, chat_id, fallback)

            logger.info(f"Feishu code_block sent to {chat_id}")
            return True

        except Exception as e:
            logger.error(f"Feishu code_block send error: {e}", exc_info=True)
            # Fallback to plain text
            fallback = f"```{language}\n{code}\n```" if language else f"```\n{code}\n```"
            return await self._send_text(message_id, chat_id, fallback)

    async def _send_audio(self, message_id: str, chat_id: str, file_path: str) -> bool:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"Audio file not found: {file_path}")
            return False

        try:
            from lark_oapi.api.im.v1 import (  # type: ignore[import-not-found]
                CreateFileRequest,
                CreateFileRequestBody,
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )

            file_type = self._detect_file_type(path)
            with open(path, "rb") as f:
                upload_req = (
                    CreateFileRequest.builder()
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(path.name)
                        .file(f)
                        .build()
                    )
                    .build()
                )
                upload_resp = await asyncio.to_thread(self._client.im.v1.file.create, upload_req)

            if not upload_resp.success():
                logger.error(f"Feishu upload audio failed: code={upload_resp.code}, msg={upload_resp.msg}")
                return False

            file_key = upload_resp.data.file_key
            content = json.dumps({"file_key": file_key}, ensure_ascii=False)

            if message_id:
                req = (
                    ReplyMessageRequest.builder()
                    .message_id(message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content)
                        .msg_type("audio")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.reply, req)
            else:
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .content(content)
                        .msg_type("audio")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

            if not resp.success():
                logger.error(f"Feishu send audio failed: code={resp.code}, msg={resp.msg}")
                return False

            logger.info(f"Feishu audio sent to {chat_id}: {path.name}")
            return True

        except Exception as e:
            logger.error(f"Feishu send audio error: {e}", exc_info=True)
            return False

    def _detect_file_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in (".opus", ".ogg", ".mp3", ".wav", ".m4a", ".aac"):
            return "opus"
        if suffix in (".mp4", ".mov", ".avi"):
            return "mp4"
        return "stream"

    async def send_local_file(self, user_id: str, file_path: str) -> bool:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return False

        meta = self._recent_msg_meta.get(user_id, {})
        chat_id = meta.get("chat_id", "")
        if not chat_id:
            logger.error(f"Cannot send file: no chat_id for user {user_id}")
            return False

        suffix = path.suffix.lower()
        if suffix in (".opus", ".ogg", ".mp3", ".wav", ".m4a", ".aac"):
            return await self._send_audio("", chat_id, file_path)

        try:
            from lark_oapi.api.im.v1 import (  # type: ignore[import-not-found]
                CreateFileRequest,
                CreateFileRequestBody,
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            with open(path, "rb") as f:
                upload_req = (
                    CreateFileRequest.builder()
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type("stream")
                        .file_name(path.name)
                        .file(f)
                        .build()
                    )
                    .build()
                )
                upload_resp = await asyncio.to_thread(self._client.im.v1.file.create, upload_req)

            if not upload_resp.success():
                logger.error(f"Feishu upload file failed: code={upload_resp.code}, msg={upload_resp.msg}")
                return False

            file_key = upload_resp.data.file_key
            content = json.dumps({"file_key": file_key}, ensure_ascii=False)

            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .content(content)
                    .msg_type("file")
                    .build()
                )
                .build()
            )
            resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

            if not resp.success():
                logger.error(f"Feishu send file failed: code={resp.code}, msg={resp.msg}")
                return False

            logger.info(f"Feishu file sent to {chat_id}: {path.name}")
            return True

        except Exception as e:
            logger.error(f"Feishu send file error: {e}", exc_info=True)
            return False

    async def stop(self) -> None:
        self._running = False
        if self._ws_client:
            try:
                await asyncio.to_thread(self._ws_client.stop)
            except Exception:
                pass
        logger.info("FeishuPlatform stopped")


register_platform("feishu", FeishuPlatform)
register_platform("lark", FeishuPlatform)
