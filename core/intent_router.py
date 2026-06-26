"""LLM Intent Router for MIMO_Connect."""

from __future__ import annotations

import json
import logging
from typing import Optional

from core.interfaces import Intent, IntentRouter, IntentType

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 MIMO_Connect 中间层的意图分类器。用户通过飞书/微信与 MiMo Code AI 编程助手交互。

你的职责：只判断意图类型，不改写、不翻译、不补全用户内容。payload 必须逐字返回用户原文。

意图类型：
1. voice_on — 用户要求开启语音回复模式
2. voice_off — 用户要求关闭语音回复模式
3. voice_last — 用户要求把上一条回复转成语音朗读
4. select_option — 用户在选择一个中间层展示的待选选项；明确选择时返回 option_index（从0开始）
5. approve — 用户确认/同意当前操作
6. reject — 用户拒绝/取消当前操作
7. interrupt — 用户**明确命令**中断当前正在执行的操作（如"停"、"停止"、"别做了"、"中断"、"取消任务"）
8. code_task — 用户提出编程相关任务，需要交给 MiMo Code
9. chat — 闲聊、咨询、或者内容不明确

规则：
- payload 必须是用户输入原文，不能改成“好的，确认”等中间层措辞。
- 没有 pending_options 时，approve/reject/code_task/chat 最终都会由 Engine 把用户原文交给 MiMo Code。
- 有 pending_options 时，明确选择编号/方案才返回 select_option；普通文字是用户自定义输入，返回 chat。
- 中间层命令（语音、进度、中断）可以分类，但不要改写用户原文。
- **interrupt 只用于明确的停止命令**。带疑问语气、询问原因或状态的句子（如"为什么停了"、"怎么停下来了"、"是不是卡住了"、"现在到哪了"）不是 interrupt，应分类为 chat，由 MiMo 回答。判断关键：用户是在**下令停止**，还是在**询问/疑惑**。
"""

CLASSIFY_PROMPT = """用户输入：{input}

对话上下文（最近几轮）：
{context}

待选选项（如有）：
{options}

请返回 JSON：{{"type": "voice_on|voice_off|voice_last|select_option|approve|reject|interrupt|code_task|chat", "payload": "用户原文", "option_index": -1}}
只返回 JSON，不要其他内容。"""


class LLMIntentRouter(IntentRouter):
    """LLM-based intent classification using a single model."""

    def __init__(self, llm_client=None, model: str = ""):
        self._client = llm_client
        self._model = model

    async def classify(
        self,
        text: str,
        context: str = "",
        pending_options: Optional[list[dict]] = None,
    ) -> Intent:
        if not self._client:
            return self._fallback_classify(text, pending_options)

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            options_str = ""
            if pending_options:
                options_str = "\n".join(
                    f"{i}. {opt.get('label', opt.get('description', ''))}"
                    for i, opt in enumerate(pending_options)
                )

            prompt = CLASSIFY_PROMPT.format(
                input=text,
                context=context[-2000:] if context else "（无）",
                options=options_str or "（无）",
            )

            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]

            response = await self._client.ainvoke(messages)
            result = json.loads(response.content)

            intent_type = IntentType(result.get("type", "chat"))
            option_index = result.get("option_index", -1)

            return Intent(type=intent_type, payload=text, option_index=option_index)

        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return self._fallback_classify(text, pending_options)

    def _fallback_classify(
        self, text: str, pending_options: Optional[list[dict]] = None
    ) -> Intent:
        lower = text.lower().strip()

        voice_on_kw = ("语音回复", "用语音", "换成语音", "语音模式", "voice on", "voice mode")
        voice_off_kw = ("文字回复", "用文字", "换成文字", "文本回复", "文字模式", "text mode", "text")
        voice_last_kw = ("念给我听", "朗读", "读一下", "语音读", "读给我", "念一下")
        approve_kw = ("好的", "可以", "没问题", "确认", "ok", "行", "嗯", "好", "是的", "对")
        reject_kw = ("不要", "取消", "算了", "不用了", "不行", "拒绝", "否", "不")
        # Interrupt is a COMMAND, not a question. Use whole-text/explicit
        # phrases only, and never fire when the text reads as a question
        # ("为什么停了" must go to chat so MiMo answers it).
        interrupt_phrases = (
            "停", "停止", "停下", "别做了", "别弄了", "中断", "打断",
            "停一下", "先停", "stop", "cancel", "abort",
        )
        question_markers = ("吗", "嘛", "呢", "为什么", "为啥", "怎么", "咋", "是不是",
                            "?", "？", "什么情况", "怎么回事")

        def _is_interrupt_command(s: str) -> bool:
            # A question/inquiry is never an interrupt command.
            if any(q in s for q in question_markers):
                return False
            stripped = s.strip().strip("。.! ！")
            # Exact short command, or starts with an explicit stop verb.
            if stripped in interrupt_phrases:
                return True
            if stripped in ("停止任务", "中断任务", "取消任务", "停止执行", "别做了", "不要做了"):
                return True
            for kw in ("停止", "中断", "打断", "别做了", "别弄了", "stop", "cancel", "abort"):
                if stripped.startswith(kw):
                    return True
            return False

        if pending_options:
            import re
            m = re.match(r"^(\d+)", lower)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(pending_options):
                    return Intent(type=IntentType.SELECT_OPTION, payload=text, option_index=idx)
            if any(k in lower for k in reject_kw):
                return Intent(type=IntentType.REJECT, payload=text)
            if any(k in lower for k in approve_kw):
                return Intent(type=IntentType.APPROVE, payload=text)
            return Intent(type=IntentType.CHAT, payload=text)

        if any(k in text for k in voice_last_kw):
            return Intent(type=IntentType.VOICE_LAST, payload=text)
        if lower in voice_on_kw:
            return Intent(type=IntentType.VOICE_ON, payload=text)
        if lower in voice_off_kw:
            return Intent(type=IntentType.VOICE_OFF, payload=text)
        if _is_interrupt_command(lower):
            return Intent(type=IntentType.INTERRUPT, payload=text)
        if any(k in lower for k in reject_kw):
            return Intent(type=IntentType.REJECT, payload=text)
        if any(k in lower for k in approve_kw):
            return Intent(type=IntentType.APPROVE, payload=text)
        return Intent(type=IntentType.CODE_TASK, payload=text)
