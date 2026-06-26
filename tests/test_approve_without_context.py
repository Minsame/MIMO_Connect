import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine import Engine
from core.interfaces import Message, Platform, Reply


class FakePlatform(Platform):
    def name(self):
        return "fake"

    async def start(self, handler):
        pass

    async def send_reply(self, reply: Reply, context_token: str = ""):
        return True

    async def stop(self):
        pass


class FakeAgentSession:
    def __init__(self):
        self.prompts = []

    async def send(self, prompt):
        self.prompts.append(prompt)

    def events(self):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    def alive(self):
        return True

    async def close(self):
        pass


class FakeAgent:
    def __init__(self):
        self.session = FakeAgentSession()

    def name(self):
        return "fake-agent"

    async def start_session(self, session_id: str, work_dir: str = ""):
        return self.session

    async def stop(self):
        pass


async def test_start_text_passes_original_text_to_agent():
    agent = FakeAgent()
    engine = Engine(FakePlatform(), agent)

    await engine._handle_message(Message(id="m1", content="开始", from_user="u1"))

    assert agent.session.prompts == ["开始"]


if __name__ == "__main__":
    asyncio.run(test_start_text_passes_original_text_to_agent())
    print("OK")
