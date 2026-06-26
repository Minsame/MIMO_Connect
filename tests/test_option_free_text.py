import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine import Engine, SessionState
from core.interfaces import Intent, IntentType


class FakeEngine(Engine):
    def __init__(self):
        pass

    async def _send_to_agent(self, prompt, state):
        state.sent_prompt = prompt
        return None


async def test_free_text_for_pending_options_goes_to_agent():
    engine = FakeEngine()
    state = SessionState("user")
    state.pending_options = [
        {"label": "方案 A", "description": "方案 A"},
        {"label": "其他", "description": "其他"},
    ]

    await engine._dispatch(Intent(type=IntentType.CHAT, payload="被改写的内容", option_index=-1), state, "我想用FastAPI 实现")

    assert state.pending_options == []
    assert state.sent_prompt == "我想用FastAPI 实现"


async def main():
    await test_free_text_for_pending_options_goes_to_agent()


if __name__ == "__main__":
    asyncio.run(main())
    print("OK")
