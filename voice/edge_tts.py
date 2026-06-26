"""TTS Voice Provider for MIMO_Connect.

Edge TTS (default) + OpenAI TTS support.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from core.interfaces import VoiceProvider
from core.registry import register_voice_provider

logger = logging.getLogger(__name__)


class MiMoTTSProvider(VoiceProvider):
    def __init__(self, api_key: str = "", api_url: str = "https://api.xiaomimimo.com/v1", model: str = "mimo-v2.5-tts", voice: str = "mimo_default", fallback: Optional[VoiceProvider] = None, timeout: float = 5.0):
        self._api_key = api_key or os.environ.get("MIMO_API_KEY", "")
        self._api_url = api_url
        self._model = model
        self._voice = voice
        self._fallback = fallback
        self._base_timeout = timeout

    def name(self) -> str:
        return "mimo"

    def is_available(self) -> bool:
        return bool(self._api_key) or bool(self._fallback and self._fallback.is_available())

    async def synthesize(self, text: str, output_path: str) -> Optional[str]:
        if self._api_key:
            # Adaptive timeout: ~50ms per character, min 5s, max 120s
            text_len = len(text.strip())
            timeout = min(max(self._base_timeout + text_len / 20, 5.0), 120.0)
            try:
                return await asyncio.wait_for(self._synthesize_mimo(text, output_path), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"MiMo TTS timed out after {timeout:.1f}s (text length={text_len}), falling back")
            except Exception as e:
                logger.warning(f"MiMo TTS failed: {type(e).__name__}: {e}")
        if self._fallback and self._fallback.is_available():
            return await self._fallback.synthesize(text, output_path)
        return None

    async def _synthesize_mimo(self, text: str, output_path: str) -> Optional[str]:
        from openai import OpenAI

        wav_path = output_path.rsplit(".", 1)[0] + ".wav"
        target_ext = Path(output_path).suffix.lower()
        client = OpenAI(api_key=self._api_key, base_url=self._api_url)
        loop = asyncio.get_event_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "user", "content": ""},
                    {"role": "assistant", "content": text},
                ],
                audio={"format": "wav", "voice": self._voice},
            ),
        )
        audio = completion.choices[0].message.audio
        if not audio:
            return None
        Path(wav_path).write_bytes(base64.b64decode(audio.data))

        if target_ext == ".wav":
            return wav_path

        if shutil.which("ffmpeg"):
            if target_ext == ".mp3":
                out_path = output_path
                codec_args = ["-codec:a", "libmp3lame", "-b:a", "128k"]
            elif target_ext == ".ogg":
                out_path = output_path.rsplit(".", 1)[0] + ".ogg"
                codec_args = ["-c:a", "libopus", "-b:a", "64k", "-vbr", "on", "-application", "voip"]
            else:
                out_path = output_path
                codec_args = ["-codec:a", "copy"]

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", wav_path, *codec_args, out_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0:
                Path(wav_path).unlink(missing_ok=True)
                return out_path
        return wav_path


class EdgeTTSProvider(VoiceProvider):
    """Edge TTS provider (free, no API key)."""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%", volume: str = "+0%", fallback: Optional[VoiceProvider] = None):
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._fallback = fallback
        self._available = importlib.util.find_spec("edge_tts") is not None
        if not self._available:
            logger.warning("edge-tts not installed")

    def name(self) -> str:
        return "edge-tts"

    def is_available(self) -> bool:
        return self._available

    async def synthesize(self, text: str, output_path: str) -> Optional[str]:
        if not self._available:
            if self._fallback and self._fallback.is_available():
                return await self._fallback.synthesize(text, output_path)
            return None

        import edge_tts  # type: ignore[import-untyped]

        mp3_path = output_path.rsplit(".", 1)[0] + ".mp3"
        ogg_path = output_path.rsplit(".", 1)[0] + ".ogg"

        try:
            communicate = edge_tts.Communicate(text, self._voice, rate=self._rate, volume=self._volume)
            await communicate.save(mp3_path)
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            if self._fallback and self._fallback.is_available():
                return await self._fallback.synthesize(text, output_path)
            return None

        # Convert to ogg if ffmpeg available
        if shutil.which("ffmpeg"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", mp3_path,
                    "-c:a", "libopus", "-b:a", "64k", "-vbr", "on",
                    "-application", "voip", ogg_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode == 0:
                    Path(mp3_path).unlink(missing_ok=True)
                    return ogg_path
            except Exception as e:
                logger.warning(f"OGG conversion failed: {e}")

        return mp3_path


class WindowsTTSProvider(VoiceProvider):
    """Local Windows TTS provider using SAPI (pywin32)."""

    def __init__(self, voice_gender: str = "female", rate: int = 0, volume: int = 100):
        self._voice_gender = voice_gender
        self._rate = rate
        self._volume = volume
        self._available = importlib.util.find_spec("win32com.client") is not None
        if not self._available:
            logger.warning("pywin32 not installed, Windows TTS unavailable")

    def name(self) -> str:
        return "windows"

    def is_available(self) -> bool:
        return self._available

    async def synthesize(self, text: str, output_path: str) -> Optional[str]:
        if not self._available:
            return None

        wav_path = output_path.rsplit(".", 1)[0] + ".wav"

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sapi_speak, text, wav_path)
        except Exception as e:
            logger.error(f"Windows TTS error: {e}")
            return None

        target_ext = Path(output_path).suffix.lower()
        if target_ext == ".wav":
            return wav_path

        if shutil.which("ffmpeg"):
            if target_ext == ".mp3":
                out_path = output_path
                codec_args = ["-codec:a", "libmp3lame", "-b:a", "128k"]
            elif target_ext == ".ogg":
                out_path = output_path.rsplit(".", 1)[0] + ".ogg"
                codec_args = ["-c:a", "libopus", "-b:a", "64k", "-vbr", "on", "-application", "voip"]
            else:
                out_path = output_path
                codec_args = ["-codec:a", "copy"]

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", wav_path, *codec_args, out_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0:
                Path(wav_path).unlink(missing_ok=True)
                return out_path
        return wav_path

    def _sapi_speak(self, text: str, wav_path: str) -> None:
        import win32com.client  # type: ignore[import-untyped]
        import pythoncom  # type: ignore[import-untyped]
        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(wav_path, 3, False)
            speaker.AudioOutputStream = stream
            speaker.Rate = self._rate
            speaker.Volume = self._volume
            speaker.Speak(text)
            stream.Close()
        finally:
            pythoncom.CoUninitialize()


class OpenAITTSProvider(VoiceProvider):
    """OpenAI TTS provider."""

    def __init__(self, api_key: str, model: str = "tts-1", voice: str = "alloy", base_url: str = "https://api.openai.com/v1"):
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._base_url = base_url

    def name(self) -> str:
        return "openai-tts"

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def synthesize(self, text: str, output_path: str) -> Optional[str]:
        if not self._api_key:
            return None

        import httpx

        mp3_path = output_path.rsplit(".", 1)[0] + ".mp3"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/audio/speech",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={"model": self._model, "input": text, "voice": self._voice, "response_format": "mp3"},
                    timeout=30,
                )
                if resp.status_code == 200:
                    Path(mp3_path).write_bytes(resp.content)
                    return mp3_path
        except Exception as e:
            logger.error(f"OpenAI TTS error: {e}")

        return None


# ─── Register ────────────────────────────────────────────────────────────────

register_voice_provider("mimo", MiMoTTSProvider)
register_voice_provider("edge-tts", EdgeTTSProvider)
register_voice_provider("windows", WindowsTTSProvider)
register_voice_provider("openai-tts", OpenAITTSProvider)
