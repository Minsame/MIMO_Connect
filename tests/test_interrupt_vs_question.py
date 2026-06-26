"""Issue 5: a question about stopping ("为什么停了") must NOT be treated as an
interrupt command. Only explicit stop commands ("停"、"停止"、"别做了") interrupt.

Covers two layers:
1. The fallback keyword classifier in LLMIntentRouter (no LLM client).
2. The engine's defense-in-depth override: even if an INTERRUPT intent
   arrives for a question-shaped text, the engine forwards it to the agent
   instead of killing the session.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine, SessionState
from core.intent_router import LLMIntentRouter
from core.interfaces import Intent, IntentType, Reply


async def test_fallback_question_is_not_interrupt():
    router = LLMIntentRouter(llm_client=None)
    for q in ("为什么停了", "怎么停下来了", "是不是卡住了", "现在到哪了", "停了吗"):
        intent = await router.classify(q)
        assert intent.type != IntentType.INTERRUPT, f"{q} -> {intent.type}"
    print("test_fallback_question_is_not_interrupt OK")


async def test_fallback_explicit_command_is_interrupt():
    router = LLMIntentRouter(llm_client=None)
    for c in ("停", "停止", "别做了", "中断", "打断", "stop", "cancel", "停止任务"):
        intent = await router.classify(c)
        assert intent.type == IntentType.INTERRUPT, f"{c} -> {intent.type}"
    print("test_fallback_explicit_command_is_interrupt OK")


class _FakeSession:
    def __init__(self):
        self.closed = False

    def alive(self):
        return True

    def running(self):
        return True

    async def send(self, prompt):
        self.sent = prompt

    def events(self):
        async def _gen():
            if False:
                yield None
        return _gen()

    async def close(self):
        self.closed = True


class _FakePlatform:
    def name(self):
        return "fake"

    async def start(self, handler):
        pass

    async def send_reply(self, reply, context_token=""):
        return True

    async def stop(self):
        pass


class _FakeAgent:
    def name(self):
        return "fake"

    async def start_session(self, session_id, work_dir=""):
        return _FakeSession()

    async def stop(self):
        pass


async def test_engine_overrides_interrupt_for_question():
    """An INTERRUPT intent on a question-shaped text must not close the session."""
    engine = Engine(_FakePlatform(), _FakeAgent(), voice=None, intent_router=None, llm_client=None)
    state = SessionState(user_id="u1")
    session = _FakeSession()
    state.session = session

    intent = Intent(type=IntentType.INTERRUPT, payload="为什么停了")
    # dispatch should forward to agent (not close), so session stays open
    await engine._dispatch(intent, state, "为什么停了")
    assert session.closed is False, "question should not close the session"
    assert state.session is not None
    print("test_engine_overrides_interrupt_for_question OK")


async def test_engine_interrupt_command_closes_session():
    engine = Engine(_FakePlatform(), _FakeAgent(), voice=None, intent_router=None, llm_client=None)
    state = SessionState(user_id="u1")
    session = _FakeSession()
    state.session = session

    intent = Intent(type=IntentType.INTERRUPT, payload="停止")
    reply = await engine._dispatch(intent, state, "停止")
    assert session.closed is True
    assert state.session is None
    assert isinstance(reply, Reply) and "中断" in reply.content
    print("test_engine_interrupt_command_closes_session OK")


async def main():
    await test_fallback_question_is_not_interrupt()
    await test_fallback_explicit_command_is_interrupt()
    await test_engine_overrides_interrupt_for_question()
    await test_engine_interrupt_command_closes_session()
    print("\nAll interrupt-vs-question tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
