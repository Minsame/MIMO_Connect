"""WeChat iLink Platform Adapter for MIMO_Connect.

Handles WeChat iLink Bot API for message receiving and sending.
Clean rewrite based on CC-Connect's platform adapter pattern.
"""

from __future__ import annotations

import sys
import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import struct
import uuid
from pathlib import Path
from typing import Any, Callable, Optional, cast

import httpx
from Crypto.Cipher import AES  # type: ignore[import-not-found]

from core.interfaces import Message, MessageType, Platform, Reply
from core.registry import register_platform
from core.segment_parser import strip_tags

logger = logging.getLogger(__name__)

# ─── iLink Constants ─────────────────────────────────────────────────────────

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.2.0"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0  # 131328

EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
EP_SEND_TYPING = "ilink/bot/sendtyping"
EP_GET_UPLOAD_URL = "ilink/bot/getuploadurl"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

MSG_TYPE_USER = 1
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2

ITEM_TEXT = 1
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

UPLOAD_MEDIA_FILE = 3

MAX_MESSAGE_LENGTH = 2048


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _random_uin() -> str:
    value = struct.unpack(">I", secrets.token_bytes(4))[0]
    return base64.b64encode(str(value).encode()).decode("ascii")


def _pkcs7_pad(data: bytes) -> bytes:
    pad = AES.block_size - (len(data) % AES.block_size)
    return data + bytes([pad]) * pad


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(_pkcs7_pad(data))


def _aes_padded_size(size: int) -> int:
    return ((size + AES.block_size) // AES.block_size) * AES.block_size


def _format_aes_key_for_api(key: bytes) -> str:
    return base64.b64encode(key.hex().encode()).decode()


def _headers(token: Optional[str], body: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Content-Length": str(len(body.encode())),
        "X-WECHAT-UIN": _random_uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _api_post(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict[str, Any],
    token: Optional[str] = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    body = json.dumps({**payload, "base_info": {"channel_version": CHANNEL_VERSION}}, ensure_ascii=False, separators=(",", ":"))
    url = f"{ILINK_BASE_URL}/{endpoint}"
    hdrs = _headers(token, body)
    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(_curl_post, url, body, hdrs, timeout),
            timeout=timeout + 5,
        )
        if not resp or not resp.strip():
            return {"ret": -1, "msgs": []}
        return json.loads(resp)
    except asyncio.TimeoutError:
        if EP_GET_UPDATES in endpoint:
            return {"ret": -1, "msgs": []}
        raise RuntimeError(f"iLink POST {endpoint} timed out after {timeout}s")
    except RuntimeError as e:
        if "curl exit 28" in str(e) and EP_GET_UPDATES in endpoint:
            return {"ret": -1, "msgs": []}
        raise


def _curl_bin() -> str:
    """Resolve the curl executable across platforms.

    Windows 10+ ships `curl.exe`; Linux/macOS use `curl`. Prefer whatever is on
    PATH, falling back to the platform-conventional name.
    """
    found = shutil.which("curl")
    if found:
        return found
    return "curl.exe" if os.name == "nt" else "curl"


def _curl_post(url: str, body: str, headers: dict[str, str], timeout: float) -> str:
    import subprocess
    cmd = [_curl_bin(), "-s", "-X", "POST", url, "--max-time", str(int(timeout))]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-d", body])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=int(timeout) + 10)
        if result.returncode != 0:
            raise RuntimeError(f"curl exit {result.returncode}: stderr={result.stderr[:200]} stdout={result.stdout[:200]}")
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"curl timed out after {timeout}s")


def _curl_put(url: str, data: bytes, timeout: float = 60) -> bool:
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(data)
        tmp_path = f.name
    try:
        cmd = [_curl_bin(), "-s", "-X", "PUT", url, "--max-time", str(int(timeout)),
               "-H", "Content-Type: application/octet-stream",
               "--data-binary", f"@{tmp_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=int(timeout) + 5)
        return result.returncode == 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ─── QR Login ────────────────────────────────────────────────────────────────

async def qr_login(client: httpx.AsyncClient, timeout: float = 120.0) -> Optional[dict[str, str]]:
    """Perform QR code login. Returns {bot_token, bot_id} or None."""
    data = await _api_post(client, EP_GET_BOT_QR + "?bot_type=3", {})
    if data.get("ret") != 0 or not data.get("qrcode"):
        logger.error(f"QR code error: {data.get('err_msg')}")
        return None

    qrcode = data["qrcode"]
    qr_url = data.get("qrcode_img_content", "")
    print("\n请扫描二维码登录微信:")
    if qr_url:
        print(f"扫码链接: {qr_url}")
    print("等待扫码...\n")

    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        status = await _api_post(client, EP_GET_QR_STATUS + f"?qrcode={qrcode}", {}, timeout=40)
        if status.get("ret") == 0:
            state = status.get("status")
            if state == "scanned":
                print("已扫码，等待确认...")
            elif state == "confirmed":
                print("登录确认！")
                return {
                    "bot_token": status["bot_token"],
                    "bot_id": status["ilink_bot_id"],
                }
            elif state == "expired":
                print("二维码已过期")
                return None
        await asyncio.sleep(2)

    print("登录超时")
    return None


# ─── WeChat Platform ─────────────────────────────────────────────────────────

class WeixinPlatform(Platform):
    """WeChat iLink Bot platform adapter."""

    def __init__(self, bot_id: str = "", token: str = "", poll_timeout: int = 30):
        self._bot_id = bot_id
        self._token = token
        self._poll_timeout = poll_timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._handler: Optional[Callable] = None
        self._offset: int = 0
        self._running = False
        self._context_tokens: dict[str, str] = {}

    def name(self) -> str:
        return "weixin"

    async def start(self, handler: Callable[[Message], Any]) -> None:
        self._handler = handler
        transport = httpx.AsyncHTTPTransport(proxy=None, retries=1)
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(15.0))

        # QR login if no token or token expired
        if not self._token:
            await self._do_login()

        self._running = True
        logger.info(f"WeixinPlatform started: bot_id={self._bot_id}")

        # Poll loop
        try:
            while self._running:
                await self._poll_once()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def _require_client(self) -> httpx.AsyncClient:
        return cast(httpx.AsyncClient, self._client)

    async def _do_login(self) -> None:
        """Perform QR login and save token."""
        result = await qr_login(self._require_client())
        if result:
            self._token = result["bot_token"]
            self._bot_id = result["bot_id"]
            self._save_token(result["bot_token"], result["bot_id"])
            logger.info("QR login successful, token refreshed")
        else:
            raise RuntimeError("QR login failed")

    async def _ensure_valid_token(self) -> bool:
        """Check if token is valid, re-login if expired."""
        try:
            data = await _api_post(
                self._require_client(), EP_GET_UPDATES,
                {"bot_id": self._bot_id, "offset": 0, "limit": 1, "timeout": 3},
                self._token, timeout=10,
            )
            if data.get("ret", 0) == -2:
                logger.warning("Token expired (ret=-2), re-login required")
                await self._do_login()
                return True
            return True
        except Exception as e:
            logger.error(f"Token check failed: {e}")
            return False

    async def _poll_once(self) -> None:
        try:
            data = await _api_post(
                self._require_client(), EP_GET_UPDATES,
                {"bot_id": self._bot_id, "offset": self._offset, "limit": 10, "timeout": self._poll_timeout},
                self._token, timeout=self._poll_timeout + 5,
            )
            logger.debug(f"Poll response: ret={data.get('ret')} msgs={len(data.get('msgs', []))}")

            # Auto re-login on token expiry
            if data.get("ret", 0) == -2:
                logger.warning("Token expired during poll, re-login...")
                await self._do_login()
                return

            msgs = data.get("msgs", [])
            for msg_data in msgs:
                msg = self._parse_message(msg_data)
                if msg and msg.id:
                    self._offset = msg_data.get("seq", 0) + 1
                    if msg.context_token:
                        self._context_tokens[msg.from_user] = msg.context_token
                    if self._handler:
                        await self._handler(msg)

        except Exception as e:
            logger.error(f"Poll error: {e}")

    def _parse_message(self, raw: dict[str, Any]) -> Optional[Message]:
        from_user = raw.get("from_user_id", "")
        if not from_user:
            return None

        # Skip bot's own messages
        if raw.get("msg_type") == MSG_TYPE_BOT:
            return None

        # Parse items
        text = ""
        voice_text = ""
        for item in raw.get("item_list", []):
            t = item.get("type")
            if t == ITEM_TEXT:
                text = (item.get("text_item") or {}).get("text", "")
            elif t == ITEM_VOICE:
                voice_text = (item.get("voice_item") or {}).get("text", "")

        content = text or voice_text
        if not content:
            return None

        return Message(
            id=str(raw.get("message_id", "")),
            content=content,
            msg_type=MessageType.TEXT if text else MessageType.VOICE,
            from_user=from_user,
            to_user=raw.get("to_user_id", ""),
            context_token=raw.get("context_token", ""),
            raw=raw,
        )

    async def send_reply(self, reply: Reply, context_token: str = "") -> bool:
        to_user = reply.metadata.get("from_user", "")
        token = context_token or self._context_tokens.get(to_user, "")

        if reply.voice_path:
            if await self.send_local_file(to_user, reply.voice_path, token):
                # Options reply also needs the text so the user can read the
                # choices; plain voice replies are fine as audio only.
                if reply.metadata.get("options"):
                    await self._send_text(to_user, self._render_options_text(reply), token)
                return True
            logger.warning("Voice file reply failed, falling back to text")

        if reply.content:
            options = reply.metadata.get("options") or []
            if options:
                return await self._send_text(to_user, self._render_options_text(reply), token)
            # WeChat is a plain-text channel (no markdown/segment-tag rendering),
            # so strip the [TEXT]/[MD]/[CODE:lang]/[TABLE] tags before sending.
            cleaned = strip_tags(reply.content) or reply.content
            return await self._send_text(to_user, cleaned, token)

        return False

    @staticmethod
    def _render_options_text(reply: Reply) -> str:
        cleaned = strip_tags(reply.content)
        options = reply.metadata.get("options") or []
        lines = [cleaned, "", "请选择："]
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}. {opt.get('label', opt.get('description', ''))}")
        return "\n".join(lines)

    async def _ensure_context_token(self, to_user: str) -> str:
        return self._context_tokens.get(to_user, "")

    async def _send_text(self, to_user: str, text: str, context_token: str = "") -> bool:
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH - 20] + "\n...(内容过长已截断)"

        message = {
            "from_user_id": "",
            "to_user_id": to_user,
            "client_id": str(uuid.uuid4()),
            "message_type": MSG_TYPE_BOT,
            "message_state": MSG_STATE_FINISH,
            "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
        }
        if not context_token:
            context_token = await self._ensure_context_token(to_user)
        if context_token:
            message["context_token"] = context_token

        try:
            data = await self._api_call(EP_SEND_MESSAGE, {"msg": message})
            if data.get("errcode", 0) == 0:
                if data.get("context_token"):
                    self._context_tokens[to_user] = data["context_token"]
                return True
        except Exception as e:
            logger.error(f"Send text error: {e}")
        return False

    async def _api_call(self, endpoint: str, payload: dict, allow_relogin: bool = True) -> dict:
        """API call with optional auto re-login on token expiry.

        Re-login performs an interactive QR scan; in a background daemon
        stdin is /dev/null so the scan cannot complete and would block ~120s.
        We only attempt re-login when attached to a real TTY (e.g. the
        first-run wizard); otherwise ret=-2 propagates so the caller can fall
        back gracefully.
        """
        data = await _api_post(self._require_client(), endpoint, payload, self._token)
        if data.get("ret", 0) == -2 and allow_relogin and sys.stdin.isatty():
            logger.warning(f"{endpoint} got ret=-2, re-login...")
            await self._do_login()
            data = await _api_post(self._require_client(), endpoint, payload, self._token)
        return data

    async def send_local_file(self, to_user: str, file_path: str, context_token: str = "") -> bool:
        import uuid
        path = Path(file_path)
        if not path.exists():
            return False

        token = context_token or self._context_tokens.get(to_user, "")
        file_data = path.read_bytes()
        file_key = str(uuid.uuid4())

        # Step 1: Get upload URL (Hermes style)
        try:
            upload_payload = {
                "to_user_id": to_user,
                "media_type": UPLOAD_MEDIA_FILE,
                "file_key": file_key,
                "file_name": path.name,
                "file_size": len(file_data),
                "raw_size": len(file_data),
                "raw_file_md5": hashlib.md5(file_data).hexdigest(),
                "aes_key": "",
            }
            if token:

               upload_payload["context_token"] = token
            logger.debug(f"GetUploadUrl request: {upload_payload}")
            data = await self._api_call(EP_GET_UPLOAD_URL, upload_payload)
            logger.debug(f"GetUploadUrl response: {data}")
            err_code = data.get("ret", 0) or data.get("errcode", 0)
            if err_code != 0:
                logger.warning(f"GetUploadUrl failed (err={err_code}); will fallback to text. ret={data.get('ret')} errcode={data.get('errcode')} errmsg={data.get('errmsg', data.get('err_msg', ''))} detail={json.dumps(data, ensure_ascii=False)[:500]}")
                return False
            upload_url = data.get("upload_url") or data.get("upload_full_url")
            if not upload_url:
                logger.error("No upload URL")
                return False
        except Exception as e:
            logger.error(f"Upload URL error: {e}")
            return False

        # Step 2: Upload raw file via curl PUT (Hermes style)
        try:
            ok = await asyncio.wait_for(
                asyncio.to_thread(_curl_put, upload_url, file_data),
                timeout=65,
            )
            if not ok:
                logger.warning("CDN upload failed")
                return False
        except Exception as e:
            logger.error(f"CDN upload error: {e}")
            return False

        # Step 3: Send file message (Hermes style)
        message = {
            "from_user_id": "",
            "to_user_id": to_user,
            "client_id": str(uuid.uuid4()),
            "message_type": MSG_TYPE_BOT,
            "message_state": MSG_STATE_FINISH,
            "item_list": [{
                "type": ITEM_FILE,
                "file_item": {
                    "file_key": file_key,
                    "file_name": path.name,
                    "file_size": len(file_data),
                },
            }],
        }
        if token:
            message["context_token"] = token

        try:
            data = await self._api_call(EP_SEND_MESSAGE, {"msg": message})
            if data.get("errcode", 0) == 0:
                if data.get("context_token"):
                    self._context_tokens[to_user] = data["context_token"]
                logger.info(f"File sent to {to_user}: {path.name}")
                return True
            logger.warning(f"Send file failed: {data}")
        except Exception as e:
            logger.error(f"Send file error: {e}")
        return False

    async def _upload_media(self, to_user: str, file_data: bytes):
        aes_key = os.urandom(16)
        file_key = secrets.token_hex(16)
        encrypted_size = _aes_padded_size(len(file_data))
        upload_payload = {
            "filekey": file_key,
            "media_type": UPLOAD_MEDIA_FILE,
            "to_user_id": to_user,
            "rawsize": len(file_data),
            "rawfilemd5": hashlib.md5(file_data).hexdigest(),
            "filesize": encrypted_size,
            "no_need_thumb": True,
            "aeskey": aes_key.hex(),
        }
        data = await _api_post(self._require_client(), EP_GET_UPLOAD_URL, upload_payload, self._token)
        upload_url = data.get("upload_full_url") or data.get("upload_url")
        if not upload_url and data.get("upload_param"):
            upload_url = f"https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param={data['upload_param']}&filekey={file_key}"
        if not upload_url:
            logger.warning(f"No upload URL in response: {data}")
            return None
        encrypted = _aes_ecb_encrypt(file_data, aes_key)
        resp = await self._require_client().post(upload_url, content=encrypted, headers={"Content-Type": "application/octet-stream"}, timeout=60)
        if resp.status_code != 200:
            logger.warning(f"CDN upload failed: HTTP {resp.status_code} {resp.text[:200]}")
            return None
        encrypted_param = resp.headers.get("x-encrypted-param")
        if not encrypted_param:
            logger.warning("CDN upload response missing x-encrypted-param")
            return None
        return encrypted_param, aes_key, encrypted_size, len(file_data)

    async def _to_amr(self, path) -> bytes:
        if path.suffix.lower() == ".amr":
            return path.read_bytes()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(path),
            "-c:a", "amr_nb",
            "-ar", "8000",
            "-ac", "1",
            "-b:a", "12.2k",
            "-f", "amr",
            "-y", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg AMR convert failed: {stderr.decode(errors='replace')[:300]}")
        return stdout

    async def _send_file(self, to_user: str, file_path: str, context_token: str = "") -> bool:
        path = Path(file_path)
        if not path.exists():
            return False

        ref = await self._upload_media(to_user, await self._to_amr(path))
        if not ref:
            return False
        encrypted_param, aes_key, _, _ = ref

        message = {
            "from_user_id": "",
            "to_user_id": to_user,
            "client_id": "vvm2-" + secrets.token_hex(8),
            "message_type": MSG_TYPE_BOT,
            "message_state": MSG_STATE_FINISH,
            "item_list": [{
                "type": ITEM_VOICE,
                "voice_item": {
                    "media": {
                        "encrypt_query_param": encrypted_param,
                        "aes_key": _format_aes_key_for_api(aes_key),
                        "encrypt_type": 1,
                    },
                },
            }],
        }
        if not context_token:
            context_token = await self._ensure_context_token(to_user)
        if context_token:
            message["context_token"] = context_token

        try:
            data = await _api_post(self._require_client(), EP_SEND_MESSAGE, {"msg": message}, self._token)
            logger.info(f"Send voice response: {data}")
            if data.get("ret", 0) == 0 and data.get("errcode", 0) == 0:
                if data.get("context_token"):
                    self._context_tokens[to_user] = data["context_token"]
                return True
            logger.warning(f"Send voice failed: {data}")
        except Exception as e:
            logger.error(f"Send voice error: {e}")
        return False

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()

    def _save_token(self, token: str, bot_id: str) -> None:
        from pathlib import Path
        env_path = Path(__file__).resolve().parent.parent / ".env"
        lines = []
        found = {"token": False, "bot_id": False}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("WEIXIN_TOKEN="):
                    lines.append(f"WEIXIN_TOKEN={token}")
                    found["token"] = True
                elif line.startswith("WEIXIN_BOT_ID="):
                    lines.append(f"WEIXIN_BOT_ID={bot_id}")
                    found["bot_id"] = True
                else:
                    lines.append(line)
        if not found["token"]:
            lines.append(f"WEIXIN_TOKEN={token}")
        if not found["bot_id"]:
            lines.append(f"WEIXIN_BOT_ID={bot_id}")
        env_path.write_text("\n".join(lines) + "\n")
        logger.info(f"Token saved to {env_path}")


# ─── Register ────────────────────────────────────────────────────────────────

register_platform("weixin", WeixinPlatform)
