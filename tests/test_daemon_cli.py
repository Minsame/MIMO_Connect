"""Linux CLI 守护进程与命令层的轻量测试（不真正 fork 引擎）。"""

import os
from pathlib import Path

import pytest

from core import daemon


# 守护进程的 PID/信号探测依赖 POSIX 语义；Windows 上跳过这些用例。
posix_only = pytest.mark.skipif(
    os.name != "posix", reason="daemon PID/signal logic is POSIX-only"
)


@posix_only
def test_running_pid_none_when_no_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "PID_PATH", tmp_path / "x.pid")
    assert daemon.running_pid() is None


@posix_only
def test_running_pid_detects_self(tmp_path: Path, monkeypatch) -> None:
    pidfile = tmp_path / "x.pid"
    pidfile.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(daemon, "PID_PATH", pidfile)
    # 当前进程必然存活，应被识别为运行中。
    assert daemon.running_pid() == os.getpid()


@posix_only
def test_running_pid_cleans_stale(tmp_path: Path, monkeypatch) -> None:
    pidfile = tmp_path / "x.pid"
    # 选一个几乎不可能存在的 PID。
    pidfile.write_text("2147480000", encoding="utf-8")
    monkeypatch.setattr(daemon, "PID_PATH", pidfile)
    assert daemon.running_pid() is None
    # 陈旧 PID 文件应被清理。
    assert not pidfile.exists()


@posix_only
def test_running_pid_ignores_garbage(tmp_path: Path, monkeypatch) -> None:
    pidfile = tmp_path / "x.pid"
    pidfile.write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(daemon, "PID_PATH", pidfile)
    assert daemon.running_pid() is None


@posix_only
def test_status_when_not_running(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(daemon, "PID_PATH", tmp_path / "x.pid")
    rc = daemon.status()
    assert rc == 0
    out = capsys.readouterr().out
    assert "未在运行" in out


@posix_only
def test_stop_when_not_running(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(daemon, "PID_PATH", tmp_path / "x.pid")
    rc = daemon.stop()
    assert rc == 0
    assert "未在运行" in capsys.readouterr().out


def test_cli_help_lists_commands(capsys) -> None:
    import cli_main

    assert "restart" in cli_main.HELP_TEXT
    assert "config" in cli_main.HELP_TEXT
    assert "logs" in cli_main.HELP_TEXT


def test_cli_logs_no_file(tmp_path: Path, monkeypatch, capsys) -> None:
    import cli_main

    monkeypatch.setattr(daemon, "LOG_PATH", tmp_path / "none.log")
    rc = cli_main._cmd_logs([])
    assert rc == 0
    assert "暂无日志" in capsys.readouterr().out


def test_cli_logs_tail(tmp_path: Path, monkeypatch, capsys) -> None:
    import cli_main

    log = tmp_path / "app.log"
    log.write_text("\n".join(f"line{i}" for i in range(50)) + "\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "LOG_PATH", log)
    rc = cli_main._cmd_logs(["-n", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "line49" in out
    assert "line45" in out
    assert "line44" not in out  # 只取末尾 5 行（line45..line49）
