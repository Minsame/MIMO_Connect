"""Tests for the refactored ProgressSummarizer.

Covers per the user's spec:
1) Input is just the latest event + small context bundle (user_task,
   prior_categories) — verify all three flow into the prompt.
2) On exception/timeout the summarizer retries up to 3 times.
3) After exhausting retries it returns ProgressResult(ok=False, error=...)
   carrying the actual error so the engine can surface the cause.
4) On total failure the .text falls back to the raw latest_status.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.progress_summarizer import ProgressResult, ProgressSummarizer


class FakeResp:
    def __init__(self, content):
        self.content = content


class CountingLLM:
    """LLM stub that counts calls and can fail N times before succeeding."""

    def __init__(self, fail_count=0, error_factory=None, success_text="正在读取主文件并准备修改"):
        self.fail_count = fail_count
        self.error_factory = error_factory or (lambda: RuntimeError("boom"))
        self.success_text = success_text
        self.calls = 0
        self.last_messages = None

    async def ainvoke(self, messages):
        self.calls += 1
        self.last_messages = messages
        if self.calls <= self.fail_count:
            raise self.error_factory()
        return FakeResp(self.success_text)


class AlwaysTimeoutLLM:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        await asyncio.sleep(10.0)


async def test_success_first_attempt():
    llm = CountingLLM(fail_count=0)
    s = ProgressSummarizer(llm_client=llm, timeout=2.0, max_retries=3)
    result = await s.summarize(
        latest_status="category=reading_files, tool=read, status=running, call_id=abc, title=read main.py",
        user_task="帮我修改 main.py 的入口函数",
        prior_categories=["reading_files"],
        elapsed_sec=60,
    )
    assert result.ok is True, result
    assert result.text == "正在读取主文件并准备修改", result
    assert llm.calls == 1
    print("test_success_first_attempt OK")


async def test_context_present_in_prompt():
    llm = CountingLLM(fail_count=0)
    s = ProgressSummarizer(llm_client=llm, max_retries=3)
    await s.summarize(
        latest_status="category=modifying_files, tool=edit, status=running",
        user_task="重构 engine.py 的进度心跳",
        prior_categories=["reading_files", "running_command"],
        elapsed_sec=120,
    )
    user_msg = llm.last_messages[-1].content
    assert "重构 engine.py" in user_msg
    assert "reading_files" in user_msg
    assert "running_command" in user_msg
    assert "category=modifying_files" in user_msg
    assert "120" in user_msg
    print("test_context_present_in_prompt OK")


async def test_retry_then_success():
    llm = CountingLLM(fail_count=2, success_text="正在编辑核心文件")
    s = ProgressSummarizer(llm_client=llm, timeout=2.0, max_retries=3)
    result = await s.summarize(
        latest_status="category=modifying_files, tool=edit, status=running",
    )
    assert result.ok is True
    assert result.text == "正在编辑核心文件"
    assert llm.calls == 3, llm.calls  # two failures + one success
    print("test_retry_then_success OK")


async def test_retry_exhausted_returns_error():
    llm = CountingLLM(fail_count=99, error_factory=lambda: ConnectionError("DeepSeek 网络不可达"))
    s = ProgressSummarizer(llm_client=llm, timeout=2.0, max_retries=3)
    raw = "category=running_command, tool=bash, status=running, call_id=z, title=run pytest"
    result = await s.summarize(latest_status=raw, user_task="跑测试")
    assert result.ok is False
    assert result.text == raw, "fallback text should be the raw last_status verbatim"
    assert "ConnectionError" in result.error
    assert "DeepSeek 网络不可达" in result.error
    assert llm.calls == 3, f"expected exactly 3 attempts, got {llm.calls}"
    print("test_retry_exhausted_returns_error OK")


async def test_timeout_counts_as_retry():
    llm = AlwaysTimeoutLLM()
    s = ProgressSummarizer(llm_client=llm, timeout=0.05, max_retries=3)
    raw = "category=using_tool, tool=glob, status=running"
    result = await s.summarize(latest_status=raw)
    assert result.ok is False
    assert result.text == raw
    assert "timeout" in result.error.lower()
    assert llm.calls == 3
    print("test_timeout_counts_as_retry OK")


async def test_no_llm_client():
    s = ProgressSummarizer(llm_client=None, max_retries=3)
    raw = "category=reading_files, tool=read, status=running, call_id=abc"
    result = await s.summarize(latest_status=raw)
    assert result.ok is False
    assert result.text == raw  # raw status passes through
    assert "not configured" in result.error
    print("test_no_llm_client OK")


async def test_empty_status_short_circuit():
    llm = CountingLLM()
    s = ProgressSummarizer(llm_client=llm)
    result = await s.summarize(latest_status="")
    assert result.ok is True
    assert result.text == "正在处理中"
    assert llm.calls == 0
    print("test_empty_status_short_circuit OK")


async def test_empty_response_treated_as_failure():
    """LLM returns empty string each time → counts as failure across all retries."""
    llm = CountingLLM(fail_count=0, success_text="")
    s = ProgressSummarizer(llm_client=llm, max_retries=3)
    result = await s.summarize(latest_status="category=using_tool, tool=read, status=running")
    assert result.ok is False
    assert "empty" in result.error.lower()
    assert llm.calls == 3
    print("test_empty_response_treated_as_failure OK")


async def test_long_response_truncated():
    long_text = "正在" + "处理" * 200
    llm = CountingLLM(success_text=long_text)
    s = ProgressSummarizer(llm_client=llm, max_retries=3)
    result = await s.summarize(latest_status="category=using_tool, tool=read, status=running")
    assert result.ok is True
    assert len(result.text) <= 201
    assert result.text.endswith("…")
    print("test_long_response_truncated OK")


async def main():
    await test_success_first_attempt()
    await test_context_present_in_prompt()
    await test_retry_then_success()
    await test_retry_exhausted_returns_error()
    await test_timeout_counts_as_retry()
    await test_no_llm_client()
    await test_empty_status_short_circuit()
    await test_empty_response_treated_as_failure()
    await test_long_response_truncated()
    print("\nAll progress_summarizer tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
