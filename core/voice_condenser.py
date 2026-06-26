"""Voice condenser: shorten a user-facing reply into 1-2 spoken
sentences before TTS, via the **middleware LLM** (the same separately
configured client used by intent_router / progress_summarizer — not
MiMo Code's internal model).

Why: reading a full rich reply aloud is long and unnatural. For voice
mode we want a concise spoken summary. On any failure (no client,
timeout, empty) the caller falls back to the plain-stripped text.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


CONDENSE_SYSTEM_PROMPT = """你是 MIMO_Connect 中间层的语音播报员。用户开启了语音模式，你要把一段给用户看的回复改写成「适合朗读」的简短口语。

要求：
1) 用自然口语中文，1-3 句，抓住核心结论或要点，不逐句复述
2) 去掉代码、表格、文件路径、命令、URL 等不适合朗读的内容；如果回复主体就是代码/表格，只用一句话说明"已生成代码/表格，请查看文字消息"
3) 遇到必须提及的英文单词或专有名词，直接保留英文原词（不要用反引号或符号包裹）
4) 不要 markdown、不要符号标记、不要"语音播报："之类前缀
5) 不超过 80 个汉字
6) 直接输出朗读文本本身"""

CONDENSE_USER_PROMPT = """待朗读的回复原文：

{raw}

请改写成适合朗读的简短口语。"""


class VoiceCondenser:
    """Condenses a reply into a short spoken form via a middleware LLM call."""

    def __init__(self, llm_client=None, timeout: float = 8.0, max_retries: int = 2):
        self._client = llm_client
        self._timeout = timeout
        self._max_retries = max(1, max_retries)

    def available(self) -> bool:
        return self._client is not None

    async def condense(self, raw: str) -> Optional[str]:
        """Return a short spoken version of raw, or None on any failure.

        Caller falls back to the plain-stripped text when this returns None.
        """
        if not raw or not raw.strip():
            return None
        if not self._client:
            return None

        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            try:
                from langchain_core.messages import HumanMessage, SystemMessage

                messages = [
                    SystemMessage(content=CONDENSE_SYSTEM_PROMPT),
                    HumanMessage(content=CONDENSE_USER_PROMPT.format(raw=raw)),
                ]
                response = await asyncio.wait_for(
                    self._client.ainvoke(messages),
                    timeout=self._timeout,
                )
                text = (response.content or "").strip()
                if text:
                    return text
                last_error = "empty response from LLM"
                logger.warning(f"VoiceCondenser attempt {attempt}/{self._max_retries}: {last_error}")
            except asyncio.TimeoutError:
                last_error = f"timeout after {self._timeout}s"
                logger.warning(f"VoiceCondenser attempt {attempt}/{self._max_retries}: {last_error}")
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"VoiceCondenser attempt {attempt}/{self._max_retries}: {last_error}")

            if attempt < self._max_retries:
                await asyncio.sleep(0.3 * attempt)

        logger.info(f"VoiceCondenser unavailable/failed ({last_error}); caller will use stripped text")
        return None
