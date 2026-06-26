"""Segment rewriter: ask the middleware LLM to add proper format tags
to a piece of MiMo output that arrived without them.

Triggered by the platform layer when a segment fails the tag validator.
The rewriter is best-effort: on any failure (no client, timeout, malformed
response) the caller falls back to sending the original text as plain TEXT.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


REWRITE_SYSTEM_PROMPT = """你是格式标注器。给 MiMo Code 输出补上类型标签，每段标签独占一行，不改原文。

标签：[TEXT] 纯文字 | [MD] markdown | [CODE:语言] 代码 | [TABLE] 表格

必须拆分的场景：
- ```` ```语言 ... ``` ```` 代码块 → [CODE:语言]，去掉围栏
- `|` 开头的表格行 → [TABLE]
- 标题/加粗/列表等 markdown → [MD]
- 以上都不是的叙述文字 → [TEXT]

示例（输入 → 输出）：

输入：
任务完成。修复了两个 bug。
| 模块 | 测试 | 状态 |
|------|------|------|
| CLI | 48个 | 通过 |

输出：
[TEXT]
任务完成。修复了两个 bug。
[TABLE]
| 模块 | 测试 | 状态 |
|------|------|------|
| CLI | 48个 | 通过 |

输入：
```python
def hello():
    print('hi')
```
以上是核心代码。

输出：
[CODE:python]
def hello():
    print('hi')
[TEXT]
以上是核心代码。

直接输出标注后的完整文本，不要解释。"""

REWRITE_USER_PROMPT = """待标注原文：

{raw}"""


class SegmentRewriter:
    """Adds format tags to untagged MiMo output via a middleware LLM call."""

    def __init__(self, llm_client=None, timeout: float = 6.0):
        self._client = llm_client
        self._timeout = timeout

    def available(self) -> bool:
        return self._client is not None

    async def rewrite(self, raw: str) -> Optional[str]:
        """Return tagged version of raw, or None on any failure.

        Caller is expected to fall back to sending raw as plain TEXT when
        this returns None.
        """
        if not raw or not raw.strip():
            return None
        if not self._client:
            return None

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=REWRITE_SYSTEM_PROMPT),
                HumanMessage(content=REWRITE_USER_PROMPT.format(raw=raw)),
            ]
            response = await asyncio.wait_for(
                self._client.ainvoke(messages),
                timeout=self._timeout,
            )
            text = (response.content or "").strip()
            if not text:
                logger.warning("SegmentRewriter: empty response, falling back")
                return None
            # Sanity check: did the LLM actually add at least one tag line?
            if not _has_any_tag(text):
                logger.warning("SegmentRewriter: response lacks any tag line, falling back")
                return None
            return text
        except asyncio.TimeoutError:
            logger.warning(f"SegmentRewriter: timed out after {self._timeout}s")
            return None
        except Exception as e:
            logger.warning(f"SegmentRewriter: failed: {e}")
            return None


def _has_any_tag(text: str) -> bool:
    import re
    pattern = re.compile(
        r"^\s*\[\s*(TEXT|MD|CODE|TABLE)\s*(?::\s*[^\]]*?)?\s*\]\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    return bool(pattern.search(text))
