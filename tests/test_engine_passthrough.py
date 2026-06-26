import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine import Engine
from core.interfaces import Event, EventType, Intent, IntentType, Message, Platform, Reply


class FakePlatform(Platform):
    def __init__(self):
        self.replies = []

    def name(self):
        return "fake"

    async def start(self, handler):
        pass

    async def send_reply(self, reply: Reply, context_token: str = ""):
        self.replies.append(reply)
        return True

    async def stop(self):
        pass


class FakeAgentSession:
    def __init__(self, events=None):
        self.prompts = []
        self._events = events or []
        self._index = 0

    async def send(self, prompt):
        self.prompts.append(prompt)
        self._index = 0

    def events(self):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    def alive(self):
        return True

    async def close(self):
        pass


class FakeAgent:
    def __init__(self, events=None):
        self.session = FakeAgentSession(events)

    def name(self):
        return "fake-agent"

    async def start_session(self, session_id: str, work_dir: str = ""):
        return self.session

    async def stop(self):
        pass


class RewritingRouter:
    async def classify(self, text, context="", pending_options=None):
        return Intent(type=IntentType.CODE_TASK, payload="被改写的内容")


class VoiceRouter:
    async def classify(self, text, context="", pending_options=None):
        return Intent(type=IntentType.VOICE_ON, payload="被改写的内容")


async def test_normal_message_uses_llm_intent_but_original_prompt():
    agent = FakeAgent()
    engine = Engine(FakePlatform(), agent, intent_router=RewritingRouter())

    await engine._handle_message(Message(id="m1", content="开始实现项目", from_user="u1"))

    assert agent.session.prompts == ["开始实现项目"]


async def test_voice_intent_does_not_forward_rewritten_payload():
    agent = FakeAgent()
    engine = Engine(FakePlatform(), agent, intent_router=VoiceRouter())

    await engine._handle_message(Message(id="m1", content="用语音", from_user="u1"))

    assert engine._sessions["u1"].wants_voice is True
    assert agent.session.prompts == []


async def test_cli_slash_command_bypasses_intent_router():
    agent = FakeAgent()
    engine = Engine(FakePlatform(), agent, intent_router=VoiceRouter())

    await engine._handle_message(Message(id="m1", content="/goal", from_user="u1"))

    assert agent.session.prompts == ["/goal"]


async def test_hide_mode_sends_opening_and_final_tail():
    events = [
        Event(type=EventType.TEXT_CHUNK, content="first sentence."),
        Event(type=EventType.TEXT_CHUNK, content="second sentence."),
        Event(type=EventType.TEXT_CHUNK, content="confirm?"),
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="task", from_user="u1"))
    await asyncio.sleep(0.2)

    # Opening sent immediately on first chunk (not deferred to end)
    # Remaining text is second+third chunks concatenated (no separator)
    # Untagged content now defaults to [MD] (TEXT folded into MD).
    assert [reply.content for reply in platform.replies] == ["[MD]\nfirst sentence.", "[MD]\nsecond sentence.confirm?"]


async def main():
    await test_normal_message_uses_llm_intent_but_original_prompt()
    await test_voice_intent_does_not_forward_rewritten_payload()
    await test_cli_slash_command_bypasses_intent_router()
    await test_hide_mode_sends_opening_and_final_tail()


if __name__ == "__main__":
    asyncio.run(main())
    print("OK")
