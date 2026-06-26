"""Issue 4: MiMo interstitial narration (text emitted on steps that end with
reason="tool-calls") must NOT leak into the final reply. Only text from the
step ending with reason="stop" is the user-facing answer; interstitial text is
demoted to a STATUS event.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.mimo_code import MiMoSession
from core.interfaces import EventType


def _drain(session):
    events = []
    while not session._events.empty():
        events.append(session._events.get_nowait())
    return events


async def test_interstitial_text_demoted_to_status():
    session = MiMoSession("t")
    # A step that ends with tool-calls: its text is "what I'll do next" narration.
    await session._process_line('{"type":"text","part":{"type":"text","text":"目录结构を確認します"}}')
    await session._process_line('{"type":"step_finish","part":{"type":"step-finish","reason":"tool-calls"}}')
    events = _drain(session)
    kinds = [e.type for e in events]
    assert EventType.TEXT_CHUNK not in kinds, kinds
    assert EventType.STATUS in kinds, kinds
    print("test_interstitial_text_demoted_to_status OK")


async def test_final_text_becomes_text_chunk():
    session = MiMoSession("t")
    await session._process_line('{"type":"text","part":{"type":"text","text":"这是最终答案。"}}')
    await session._process_line('{"type":"step_finish","part":{"type":"step-finish","reason":"stop"}}')
    events = _drain(session)
    text_chunks = [e for e in events if e.type == EventType.TEXT_CHUNK]
    assert len(text_chunks) == 1, events
    assert "最终答案" in text_chunks[0].content
    print("test_final_text_becomes_text_chunk OK")


async def test_narration_then_final_only_final_surfaces():
    session = MiMoSession("t")
    # Step 1: narration + tool-calls
    await session._process_line('{"type":"text","part":{"type":"text","text":"先看一下文件"}}')
    await session._process_line('{"type":"step_finish","part":{"type":"step-finish","reason":"tool-calls"}}')
    # Step 2: final answer + stop
    await session._process_line('{"type":"text","part":{"type":"text","text":"分析完成，结论是X。"}}')
    await session._process_line('{"type":"step_finish","part":{"type":"step-finish","reason":"stop"}}')
    events = _drain(session)
    text_chunks = [e for e in events if e.type == EventType.TEXT_CHUNK]
    assert len(text_chunks) == 1, [e.content for e in events]
    assert "先看一下文件" not in text_chunks[0].content
    assert "结论是X" in text_chunks[0].content
    print("test_narration_then_final_only_final_surfaces OK")


async def main():
    await test_interstitial_text_demoted_to_status()
    await test_final_text_becomes_text_chunk()
    await test_narration_then_final_only_final_surfaces()
    print("\nAll step-text classification tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
