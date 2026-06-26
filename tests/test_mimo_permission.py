import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.mimo_code import MiMoSession
from core.interfaces import EventType


class FakeStderr:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, n):
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class FakeProcess:
    def __init__(self, chunks):
        self.stderr = FakeStderr(chunks)
        self.returncode = 1
        self.pid = 0


async def test_stderr_permission_without_newline():
    session = MiMoSession("test")
    process = FakeProcess([
        "错误: \x1b[93m\x1b[1m! \x1b[0mpermission requested: external_directory (E:\\Project_AI\\*); auto-rejecting".encode()
    ])

    await session._read_stderr(process)
    event = session._events.get_nowait()

    assert event.type == EventType.PERMISSION_REQUEST
    assert event.data["permission"] == "external_directory (E:\\Project_AI\\*)"
    assert event.data["allowed_dir"] == "E:\\Project_AI"
    assert event.data["options"][0]["work_dir"] == "E:\\Project_AI"


async def test_stdout_permission_text_becomes_permission_event():
    session = MiMoSession("test")
    await session._process_line("\x1b[93m\x1b[1m! \x1b[0mpermission requested: external_directory (E:\\Project_AI\\*); auto-rejecting")
    event = session._events.get_nowait()

    assert event.type == EventType.PERMISSION_REQUEST
    assert event.data["allowed_dir"] == "E:\\Project_AI"


async def test_multiple_permission_paths_pick_valid_directory():
    session = MiMoSession("test")
    event = session._parse_stderr_permission("permission requested: external_directory (E:\\Project_AI\\*, E:\\Project_AI\\MiMoStatusLight\\*); auto-rejecting")

    assert event is not None
    assert event.data["allowed_dir"] == "E:\\Project_AI"
    assert "," not in event.data["options"][0]["work_dir"]
    assert "*" not in event.data["options"][0]["work_dir"]


async def main():
    await test_stderr_permission_without_newline()
    await test_stdout_permission_text_becomes_permission_event()
    await test_multiple_permission_paths_pick_valid_directory()


if __name__ == "__main__":
    asyncio.run(main())
    print("OK")
