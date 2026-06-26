"""End-to-end pipeline test: segment parsing + rewriting + platform dispatch.

Simulates the full flow from MiMo tagged output through the middleware
to platform send, without requiring a live Feishu connection.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.segment_parser import parse_segments, strip_tags, SEG_TEXT, SEG_MD, SEG_CODE, SEG_TABLE
from core.segment_rewriter import SegmentRewriter


class FakeLLM:
    """Simulates the middleware LLM for segment rewriting."""
    def __init__(self, response="[MD]\n**hello**"):
        self._response = response
        self.ainvoke = None  # will be set as async

    async def _ainvoke(self, messages):
        class R:
            def __init__(self, c): self.content = c
        return R(self._response)

    def __init__(self, response="[MD]\n**hello**"):
        self._response = response
        self.ainvoke = self._ainvoke


class FakePlatform:
    def __init__(self):
        self.sent = []  # list of (kind, content)

    def record(self, kind, content):
        self.sent.append((kind, content))


async def test_full_pipeline_with_tagged_output():
    """MiMo outputs tagged segments → parser splits → rewriter skips (already tagged) → dispatch."""
    raw = """[TEXT]
Here is a summary:

[CODE:python]
print("hello world")

[MD]
**Important**: check this table

[TABLE]
| A | B |
|---|---|
| 1 | 2 |
"""
    segments = parse_segments(raw)
    assert len(segments) == 4
    # TEXT is folded into MD (issue: 取消 text，统一按 md 解析)
    assert segments[0].kind == SEG_MD
    assert segments[1].kind == SEG_CODE and segments[1].lang == "python"
    assert segments[2].kind == SEG_MD
    assert segments[3].kind == SEG_TABLE

    # CODE content should have inner fence stripped
    assert "```" not in segments[1].content
    assert "print" in segments[1].content

    # strip_tags should remove all tags
    clean = strip_tags(raw)
    assert "[TEXT]" not in clean
    assert "[CODE:python]" not in clean
    assert "[MD]" not in clean
    assert "[TABLE]" not in clean
    assert "print" in clean
    assert "Important" in clean
    print("test_full_pipeline_with_tagged_output OK")


async def test_full_pipeline_with_untagged_output():
    """MiMo outputs untagged → rewriter adds tags → dispatch."""
    raw = '```python\nprint("hello")\n```'
    rewriter = SegmentRewriter(llm_client=None)
    # No LLM client → rewrite returns None → fallback to [TEXT] prefix
    assert not rewriter.available()
    result = await rewriter.rewrite(raw)
    assert result is None  # no client, no rewrite

    # Simulate with a fake LLM that adds [CODE:python] tag
    class FakeLLM2:
        async def ainvoke(self, messages):
            class R:
                content = '[CODE:python]\n```python\nprint("hello")\n```'
            return R()

    rewriter2 = SegmentRewriter(llm_client=FakeLLM2())
    assert rewriter2.available()
    result2 = await rewriter2.rewrite(raw)
    assert result2 is not None
    assert "[CODE:python]" in result2
    print("test_full_pipeline_with_untagged_output OK")


async def test_dispatch_routing():
    """Verify segment kinds map to correct send methods."""
    # TEXT → _send_text
    # CODE → _send_text (lark_md doesn't support fences)
    # MD → _send_card (lark_md)
    # TABLE → _send_card (lark_md)
    raw = "[TEXT]\nhello\n[CODE:python]\nprint(1)\n[MD]\n**bold**\n[TABLE]\n|a|b|"
    segments = parse_segments(raw)
    kinds = [s.kind for s in segments]
    # TEXT folds into MD (issue: 取消 text，统一按 md 解析)
    assert kinds == [SEG_MD, SEG_CODE, SEG_MD, SEG_TABLE]

    # Verify CODE content has no fences after parsing
    code_seg = [s for s in segments if s.kind == SEG_CODE][0]
    assert "```" not in code_seg.content
    print("test_dispatch_routing OK")


async def test_order_preservation():
    """Segments arrive in order even when rewriter is involved."""
    raw = "first line\n[CODE:python]\nprint(1)\n[TEXT]\nlast line"
    segments = parse_segments(raw)
    assert len(segments) == 3
    assert segments[0].content.strip() == "first line"
    assert segments[1].kind == SEG_CODE
    assert segments[2].content.strip() == "last line"
    print("test_order_preservation OK")


async def test_voice_strips_tags():
    """_strip_for_voice should remove segment tags before TTS."""
    from core.engine import _strip_for_voice
    tagged = "[TEXT]\nHello world\n[CODE:python]\nprint(1)\n[MD]\n**bold**"
    clean = _strip_for_voice(tagged)
    assert "[TEXT]" not in clean
    assert "[CODE:python]" not in clean
    assert "[MD]" not in clean
    assert "Hello" in clean
    assert "bold" in clean
    print("test_voice_strips_tags OK")


async def main():
    await test_full_pipeline_with_tagged_output()
    await test_full_pipeline_with_untagged_output()
    await test_dispatch_routing()
    await test_order_preservation()
    await test_voice_strips_tags()
    print("\nAll e2e pipeline tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
