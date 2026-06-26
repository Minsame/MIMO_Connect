"""Integration test for segment-tag normalization + ordering preservation in Engine.

Verifies:
1. When a reply lacks any format tag and rewriter succeeds, the rewritten
   text replaces the original.
2. When a reply lacks any tag and rewriter returns None (failure), the
   content is prepended with [TEXT] so the platform routes it as plain text.
3. When two replies are sent in sequence and the first needs rewriting,
   the platform receives them in the original order (rewrite is awaited
   inline so the second reply cannot overtake the first).
4. Replies that already contain tags are passed through untouched.
5. Replies carrying options skip rewriting entirely.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine, SessionState
from core.interfaces import Reply


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """LLM that adds [TEXT] tag, with configurable delay and failure mode."""

    def __init__(self, delay=0.0, fail=False, output_prefix="[TEXT]\n"):
        self.delay = delay
        self.fail = fail
        self.output_prefix = output_prefix
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("simulated LLM failure")
        # The user prompt is the LAST message; extract raw after the marker.
        body = ""
        if messages:
            txt = messages[-1].content
            # Support both old and new prompt formats
            for marker in ("原文：\n\n", "原文:\n\n"):
                s = txt.find(marker)
                if s >= 0:
                    body = txt[s + len(marker):]
                    break
        return FakeLLMResponse(self.output_prefix + body)


class FakePlatform:
    def __init__(self):
        self.received = []

    def name(self):
        return "fake"

    async def start(self, handler):
        return None

    async def send_reply(self, reply, context_token=""):
        self.received.append(reply.content)
        return True


class FakeAgent:
    def name(self):
        return "fake-agent"

    async def start_session(self, session_id, work_dir=""):
        return None

    async def stop(self):
        return None


def make_engine(llm=None):
    return Engine(FakePlatform(), FakeAgent(), voice=None, intent_router=None, llm_client=llm)


def make_state():
    return SessionState(user_id="u1")


async def test_rewrite_success():
    llm = FakeLLM(delay=0.05)
    engine = make_engine(llm=llm)
    state = make_state()
    reply = Reply(content="hello world without tag")
    await engine._send_platform_reply(reply, state)
    assert engine._platform.received[0].startswith("[TEXT]"), engine._platform.received
    assert "hello world without tag" in engine._platform.received[0]
    assert len(llm.calls) == 1
    print("test_rewrite_success OK")


async def test_rewrite_failure_falls_back_to_text():
    llm = FakeLLM(fail=True)
    engine = make_engine(llm=llm)
    state = make_state()
    reply = Reply(content="oops no tag")
    await engine._send_platform_reply(reply, state)
    sent = engine._platform.received[0]
    # Should be prefixed with [MD] by the fallback path (TEXT folded into MD)
    assert sent.startswith("[MD]"), sent
    assert "oops no tag" in sent
    print("test_rewrite_failure_falls_back_to_text OK")


async def test_rewrite_skipped_when_already_tagged():
    llm = FakeLLM()
    engine = make_engine(llm=llm)
    state = make_state()
    reply = Reply(content="[TEXT]\nalready tagged")
    await engine._send_platform_reply(reply, state)
    assert engine._platform.received[0] == "[TEXT]\nalready tagged"
    assert len(llm.calls) == 0  # rewriter not called
    print("test_rewrite_skipped_when_already_tagged OK")


async def test_options_skip_rewrite():
    llm = FakeLLM()
    engine = make_engine(llm=llm)
    state = make_state()
    reply = Reply(content="please choose")
    reply.metadata["has_options"] = True
    await engine._send_platform_reply(reply, state)
    assert engine._platform.received[0] == "please choose"
    assert len(llm.calls) == 0
    print("test_options_skip_rewrite OK")


async def test_no_llm_client_falls_back_to_text():
    engine = make_engine(llm=None)
    state = make_state()
    reply = Reply(content="raw without llm")
    await engine._send_platform_reply(reply, state)
    sent = engine._platform.received[0]
    assert sent.startswith("[MD]"), sent
    assert "raw without llm" in sent
    print("test_no_llm_client_falls_back_to_text OK")


async def test_order_preserved_when_first_needs_rewrite():
    """Critical: send two replies in sequence; first lacks tags (slow rewrite),
    second already has tags. Verify platform sees them in original order
    because _send_platform_reply is awaited."""
    llm = FakeLLM(delay=0.2)  # rewrite takes 200ms
    engine = make_engine(llm=llm)
    state = make_state()

    reply1 = Reply(content="first reply no tag")
    reply2 = Reply(content="[TEXT]\nsecond reply already tagged")

    # Sequential await — same as how engine.py emits them
    await engine._send_platform_reply(reply1, state)
    await engine._send_platform_reply(reply2, state)

    received = engine._platform.received
    assert len(received) == 2, received
    assert "first reply no tag" in received[0], f"expected first first, got {received}"
    assert received[1] == "[TEXT]\nsecond reply already tagged", received
    print("test_order_preserved_when_first_needs_rewrite OK")


async def test_rewriter_response_without_tag_falls_back():
    """If LLM returns text but with no tag at all, treat as failure."""

    class NoTagLLM:
        calls = []

        async def ainvoke(self, messages):
            self.calls.append(messages)
            return FakeLLMResponse("just plain text no tag at all")

    llm = NoTagLLM()
    engine = make_engine(llm=llm)
    state = make_state()
    reply = Reply(content="some content")
    await engine._send_platform_reply(reply, state)
    sent = engine._platform.received[0]
    assert sent.startswith("[MD]"), sent
    assert "some content" in sent
    print("test_rewriter_response_without_tag_falls_back OK")


async def main():
    await test_rewrite_success()
    await test_rewrite_failure_falls_back_to_text()
    await test_rewrite_skipped_when_already_tagged()
    await test_options_skip_rewrite()
    await test_no_llm_client_falls_back_to_text()
    await test_order_preserved_when_first_needs_rewrite()
    await test_rewriter_response_without_tag_falls_back()
    print("\nAll segment-rewrite tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
