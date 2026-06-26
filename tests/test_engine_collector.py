"""Tests for engine collector: None events, immediate opening, mode switch, progress query.

Covers:
1. None event (timeout) does not crash collector
2. First TEXT_CHUNK sends opening immediately in hide mode
3. Mode switch hide→show flushes unsent text
4. Mode switch show→hide sends accumulated first_chunks
5. _handle_progress_query intercepts without interrupting running task
6. Normal flow preserved (regression)
7. Negative: empty events, aborted session, dead session
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine, SessionState
from core.interfaces import Event, EventType, Intent, IntentType, Message, Platform, Reply


# ─── Fakes ────────────────────────────────────────────────────────────────────

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
        self._closed = False
        self._aborting = False

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
        return not self._closed

    async def close(self):
        self._closed = True


class FakeAgent:
    def __init__(self, events=None):
        self.session = FakeAgentSession(events)

    def name(self):
        return "fake-agent"

    async def start_session(self, session_id: str, work_dir: str = ""):
        return self.session

    async def stop(self):
        pass


# ─── L1: Unit tests for _check_mode_switch ────────────────────────────────────

async def test_check_mode_switch_no_change():
    """No mode change → returns values unchanged."""
    engine = Engine(FakePlatform(), FakeAgent())
    state = SessionState(user_id="u1")
    state.detail_mode = False
    state.prev_detail_mode = False

    sent, flush = await engine._check_mode_switch(
        state, "response", "sent", [], [], 0.0
    )
    assert sent == "sent"
    assert flush == 0.0
    print("test_check_mode_switch_no_change OK")


async def test_check_mode_switch_hide_to_show_flushes():
    """hide→show: flushes unsent accumulated text."""
    platform = FakePlatform()
    engine = Engine(platform, FakeAgent())
    state = SessionState(user_id="u1")
    state.detail_mode = True
    state.prev_detail_mode = False  # was hide, now show

    sent, flush = await engine._check_mode_switch(
        state, "full response", "", [], [], 0.0
    )
    assert len(platform.replies) == 1
    assert "full response" in platform.replies[0].content
    assert sent == "full response"
    print("test_check_mode_switch_hide_to_show_flushes OK")


async def test_check_mode_switch_hide_to_show_no_unsent():
    """hide→show with everything already sent → no extra reply."""
    platform = FakePlatform()
    engine = Engine(platform, FakeAgent())
    state = SessionState(user_id="u1")
    state.detail_mode = True
    state.prev_detail_mode = False

    sent, flush = await engine._check_mode_switch(
        state, "response", "response", [], [], 0.0  # already sent
    )
    assert len(platform.replies) == 0
    assert sent == "response"
    print("test_check_mode_switch_hide_to_show_no_unsent OK")


async def test_check_mode_switch_show_to_hide_sends_chunks():
    """show→hide: sends accumulated first_chunks as opening."""
    platform = FakePlatform()
    engine = Engine(platform, FakeAgent())
    state = SessionState(user_id="u1")
    state.detail_mode = False
    state.prev_detail_mode = True  # was show, now hide

    sent, flush = await engine._check_mode_switch(
        state, "response", "", ["hello", "world"], [], 0.0
    )
    assert len(platform.replies) == 1
    assert "hello" in platform.replies[0].content
    assert "world" in platform.replies[0].content
    assert sent == "hello\n\nworld"
    print("test_check_mode_switch_show_to_hide_sends_chunks OK")


async def test_check_mode_switch_show_to_hide_no_chunks():
    """show→hide with no first_chunks → no reply."""
    platform = FakePlatform()
    engine = Engine(platform, FakeAgent())
    state = SessionState(user_id="u1")
    state.detail_mode = False
    state.prev_detail_mode = True

    sent, flush = await engine._check_mode_switch(
        state, "response", "", [], [], 0.0
    )
    assert len(platform.replies) == 0
    print("test_check_mode_switch_show_to_hide_no_chunks OK")


async def test_check_mode_switch_hide_to_show_with_chunks():
    """hide→show with first_chunks but no sent_text → flushes full response."""
    platform = FakePlatform()
    engine = Engine(platform, FakeAgent())
    state = SessionState(user_id="u1")
    state.detail_mode = True
    state.prev_detail_mode = False

    sent, flush = await engine._check_mode_switch(
        state, "full text", "", ["chunk1", "chunk2"], [], 0.0
    )
    assert len(platform.replies) == 1
    assert "full text" in platform.replies[0].content
    assert sent == "full text"
    print("test_check_mode_switch_hide_to_show_with_chunks OK")


# ─── L1: Unit tests for _handle_progress_query ───────────────────────────────

async def test_progress_query_returns_status():
    """Progress query while MiMo running → returns current status."""
    engine = Engine(FakePlatform(), FakeAgent())
    state = SessionState(user_id="u1")
    state.last_status = "category=reading_files, tool=read, status=completed"

    # Need a session that reports alive
    state.session = FakeAgentSession()
    state.session._closed = False

    result = engine._handle_progress_query("进度如何", state)
    assert result is not None
    assert "reading_files" in result.content
    print("test_progress_query_returns_status OK")


async def test_progress_query_no_session():
    """No session → returns None (not intercepted)."""
    engine = Engine(FakePlatform(), FakeAgent())
    state = SessionState(user_id="u1")
    state.session = None

    result = engine._handle_progress_query("进度如何", state)
    assert result is None
    print("test_progress_query_no_session OK")


async def test_progress_query_session_dead():
    """Dead session → returns None."""
    engine = Engine(FakePlatform(), FakeAgent())
    state = SessionState(user_id="u1")
    state.session = FakeAgentSession()
    state.session._closed = True

    result = engine._handle_progress_query("进度如何", state)
    assert result is None
    print("test_progress_query_session_dead OK")


async def test_progress_query_no_keywords():
    """No progress keywords → returns None."""
    engine = Engine(FakePlatform(), FakeAgent())
    state = SessionState(user_id="u1")
    state.session = FakeAgentSession()
    state.last_status = "something"

    result = engine._handle_progress_query("帮我写个函数", state)
    assert result is None
    print("test_progress_query_no_keywords OK")


async def test_progress_query_various_keywords():
    """Multiple keyword variants all trigger interception."""
    engine = Engine(FakePlatform(), FakeAgent())
    state = SessionState(user_id="u1")
    state.session = FakeAgentSession()
    state.last_status = "working"

    for keyword in ["进度如何", "现在什么状态", "到哪了", "在干嘛", "什么情况"]:
        result = engine._handle_progress_query(keyword, state)
        assert result is not None, f"'{keyword}' should be intercepted"
    print("test_progress_query_various_keywords OK")


# ─── L2: Integration tests for collector via _handle_message ─────────────────

async def test_none_events_dont_crash():
    """Collector survives None events (timeout) without crashing."""
    events = [
        None,  # timeout
        Event(type=EventType.TEXT_CHUNK, content="hello"),
        None,  # timeout
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    assert len(platform.replies) >= 1
    assert any("hello" in r.content for r in platform.replies)
    print("test_none_events_dont_crash OK")


async def test_only_none_events():
    """Session with only None events → eventually no crash, returns 'no response'."""
    events = [None, None, None, Event(type=EventType.DONE)]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    # Should not crash; may have no replies or a "no response" reply
    print("test_only_none_events OK")


async def test_immediate_opening_on_first_chunk():
    """First TEXT_CHUNK sends opening immediately, not deferred until DONE."""
    events = [
        Event(type=EventType.TEXT_CHUNK, content="第一句。"),
        Event(type=EventType.TEXT_CHUNK, content="第二句。"),
        Event(type=EventType.TEXT_CHUNK, content="最后确认？"),
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="执行任务", from_user="u1"))
    await asyncio.sleep(0.1)

    assert len(platform.replies) == 2
    # Opening: only the first chunk, not first+second
    assert "第一句。" in platform.replies[0].content
    # Tail: remaining unsent text
    assert "第二句。" in platform.replies[1].content
    assert "最后确认？" in platform.replies[1].content
    print("test_immediate_opening_on_first_chunk OK")


async def test_single_text_chunk():
    """Single TEXT_CHUNK → opening + no tail (everything sent)."""
    events = [
        Event(type=EventType.TEXT_CHUNK, content="全部内容"),
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    assert len(platform.replies) == 1
    assert "全部内容" in platform.replies[0].content
    print("test_single_text_chunk OK")


async def test_no_text_chunks():
    """No TEXT_CHUNK events → collector returns 'Agent 无响应' Reply,
    which _run_collector now sends to the platform."""
    events = [
        Event(type=EventType.STATUS, content="working"),
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    # Collector return is now sent via _run_collector wrapper
    assert len(platform.replies) == 1
    assert "无响应" in platform.replies[0].content
    print("test_no_text_chunks OK")


async def test_progress_query_does_not_interrupt():
    """Progress query during running task → returns status, doesn't restart."""
    events = [
        Event(type=EventType.TEXT_CHUNK, content="working on it"),
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    # Start a task
    await engine._handle_message(Message(id="m1", content="执行任务", from_user="u1"))
    await asyncio.sleep(0.05)

    # Simulate progress query by calling _handle_message with progress keywords
    # This should be intercepted and NOT send to agent
    session = engine._sessions["u1"].session
    original_prompts = list(session.prompts)

    await engine._handle_message(Message(id="m2", content="进度如何", from_user="u1"))
    await asyncio.sleep(0.05)

    # No new prompt should have been sent to the agent
    assert session.prompts == original_prompts
    # A status reply should have been sent
    assert len(platform.replies) >= 2  # opening + progress
    print("test_progress_query_does_not_interrupt OK")


async def test_error_event():
    """ERROR event → collector returns error Reply, now sent via _run_collector."""
    events = [
        Event(type=EventType.ERROR, content="something broke"),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    # Error Reply is now sent to the platform by _run_collector
    assert len(platform.replies) == 1
    assert "something broke" in platform.replies[0].content
    print("test_error_event OK")


async def test_text_chunk_then_error():
    """TEXT_CHUNK → opening sent immediately; ERROR return now also sent via _run_collector."""
    events = [
        Event(type=EventType.TEXT_CHUNK, content="started..."),
        Event(type=EventType.ERROR, content="crash"),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    # Opening sent immediately + error reply sent by _run_collector
    assert len(platform.replies) == 2
    assert "started..." in platform.replies[0].content
    assert "crash" in platform.replies[1].content
    print("test_text_chunk_then_error OK")


async def test_hide_mode_detail_mode_text_sends_immediately():
    """In detail_mode (/show), TEXT_CHUNK is sent via detail buffer."""
    events = [
        Event(type=EventType.TEXT_CHUNK, content="detail line 1"),
        Event(type=EventType.TEXT_CHUNK, content="detail line 2"),
        Event(type=EventType.DONE),
    ]
    platform = FakePlatform()
    agent = FakeAgent(events)
    engine = Engine(platform, agent)

    # Set detail mode before sending message
    engine._get_state("u1").detail_mode = True
    engine._get_state("u1").prev_detail_mode = True

    await engine._handle_message(Message(id="m1", content="test", from_user="u1"))
    await asyncio.sleep(0.1)

    # In detail mode, text goes to detail_buffer and is flushed at end
    assert len(platform.replies) >= 1
    combined = " ".join(r.content for r in platform.replies)
    assert "detail line 1" in combined
    assert "detail line 2" in combined
    print("test_hide_mode_detail_mode_text_sends_immediately OK")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    # L1: Unit tests
    await test_check_mode_switch_no_change()
    await test_check_mode_switch_hide_to_show_flushes()
    await test_check_mode_switch_hide_to_show_no_unsent()
    await test_check_mode_switch_show_to_hide_sends_chunks()
    await test_check_mode_switch_show_to_hide_no_chunks()
    await test_check_mode_switch_hide_to_show_with_chunks()

    await test_progress_query_returns_status()
    await test_progress_query_no_session()
    await test_progress_query_session_dead()
    await test_progress_query_no_keywords()
    await test_progress_query_various_keywords()

    # L2: Integration tests
    await test_none_events_dont_crash()
    await test_only_none_events()
    await test_immediate_opening_on_first_chunk()
    await test_single_text_chunk()
    await test_no_text_chunks()
    await test_progress_query_does_not_interrupt()
    await test_error_event()
    await test_text_chunk_then_error()
    await test_hide_mode_detail_mode_text_sends_immediately()

    print(f"\nAll {20} engine collector tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
