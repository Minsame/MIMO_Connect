"""Linux/macOS 守护进程管理：后台启动引擎、PID 文件、信号控制。

设计：
- 默认 `mmc`（或 `mmc start`）把引擎 fork 成后台进程，前台只打印几行启动结果即返回，
  不再常驻刷日志；日志写入 mimo_connect.log（RotatingFileHandler，见 main.setup_logging）。
- PID 文件记录后台进程号，供 restart/stop/status 定位与发信号。
- 仅支持 POSIX（os.fork）。Windows 用 GUI 版，不走这里。

注意：本模块不导入 GUI/Qt，保持 CLI 轻量。
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from core import config_io

# 与 config_io 共用同一份用户级数据目录路径，避免落到只读安装目录。
PID_PATH: Path = config_io.PID_PATH
LOG_PATH: Path = config_io.LOG_PATH


def _read_pid() -> int | None:
    """读取 PID 文件；文件缺失或内容非法返回 None。"""
    try:
        text = PID_PATH.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return None
    if not text.isdigit():
        return None
    return int(text)


def _pid_alive(pid: int) -> bool:
    """进程是否存活（POSIX：kill 0 探测）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权限，仍视为存活
    return True


def running_pid() -> int | None:
    """返回正在运行的守护进程 PID；若 PID 文件指向已死进程则清理并返回 None。"""
    pid = _read_pid()
    if pid is None:
        return None
    if _pid_alive(pid):
        return pid
    # 陈旧 PID 文件，清理。
    try:
        PID_PATH.unlink()
    except OSError:
        pass
    return None


def _write_pid(pid: int) -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(pid), encoding="utf-8")


def _run_engine_blocking() -> None:
    """子进程内真正运行引擎（阻塞直到收到停止信号）。"""
    from dotenv import load_dotenv

    load_dotenv(config_io.ENV_PATH, override=True)
    import main as app_main

    app_main.main()


def start(quiet: bool = False) -> int:
    """后台启动引擎。返回 0 成功，非 0 失败。

    若已在运行则提示并返回 0（幂等）。
    """
    if os.name != "posix":
        print("[mmc] 后台守护仅支持 Linux/macOS；Windows 请使用 GUI 版。", file=sys.stderr)
        return 1

    existing = running_pid()
    if existing:
        print(f"[mmc] 引擎已在运行（PID {existing}）。用 'mmc status' 查看，'mmc restart' 重启。")
        return 0

    # 首次 fork：父进程等待子进程写好 PID 后打印结果并返回。
    pid = os.fork()
    if pid > 0:
        # 父进程：等子进程落地（最多 ~5s）。
        for _ in range(50):
            time.sleep(0.1)
            running = running_pid()
            if running:
                _print_started(running, quiet)
                return 0
        print("[mmc] 启动超时：未检测到后台进程，请查看 mimo_connect.log。", file=sys.stderr)
        return 1

    # 子进程：脱离控制终端，成为守护进程。
    os.setsid()
    # 二次 fork，确保不会重新获得控制终端。
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    _write_pid(os.getpid())

    # 重定向标准流：stdin->/dev/null，stdout/stderr 交给日志系统（main.setup_logging
    # 会建文件处理器；这里把裸 fd 也接到 /dev/null，避免 print 干扰终端）。
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

    try:
        _run_engine_blocking()
    finally:
        try:
            PID_PATH.unlink()
        except OSError:
            pass
    os._exit(0)


def _print_started(pid: int, quiet: bool) -> None:
    """前台打印几行启动结果即返回，不常驻。"""
    if quiet:
        print(f"[mmc] 引擎已启动（PID {pid}）。")
        return
    platform = os.getenv("MIMO_CONNECT_PLATFORM", os.getenv("MIMO_CONNECT_MODE", "weixin"))
    model = os.getenv("MIMO_CONNECT_MODEL", "") or "默认"
    work_dir = os.getenv("MIMO_CONNECT_WORK_DIR", str(config_io.PROJECT_ROOT))
    print("─" * 58)
    print("  MIMO_Connect 已在后台启动")
    print("─" * 58)
    print(f"  PID        {pid}")
    print(f"  平台       {platform}")
    print(f"  模型       {model}")
    print(f"  工作目录   {work_dir}")
    print(f"  日志       {LOG_PATH}")
    print("─" * 58)
    print("  mmc status     查看运行状态")
    print("  mmc logs -f    实时跟随日志")
    print("  mmc restart    重启引擎")
    print("  mmc stop       停止引擎")
    print("─" * 58)


def stop(timeout: float = 10.0) -> int:
    """停止后台引擎（SIGTERM，超时后 SIGKILL）。"""
    pid = running_pid()
    if not pid:
        print("[mmc] 引擎未在运行。")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("[mmc] 引擎进程已不存在。")
        return 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            print(f"[mmc] 引擎已停止（PID {pid}）。")
            try:
                PID_PATH.unlink()
            except OSError:
                pass
            return 0
        time.sleep(0.2)
    # 超时强杀。
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        PID_PATH.unlink()
    except OSError:
        pass
    print(f"[mmc] 引擎未在 {timeout:.0f}s 内退出，已强制结束（PID {pid}）。")
    return 0


def restart() -> int:
    """重启引擎：停掉旧进程再后台启动新进程（重新读取 .env / config.yaml）。"""
    pid = running_pid()
    if pid:
        rc = stop()
        if rc != 0:
            return rc
    # 重新加载配置后启动。
    from dotenv import load_dotenv

    load_dotenv(config_io.ENV_PATH, override=True)
    return start()


def status() -> int:
    """打印运行状态。"""
    pid = running_pid()
    if not pid:
        print("[mmc] 引擎未在运行。用 'mmc start' 启动。")
        return 0
    platform = os.getenv("MIMO_CONNECT_PLATFORM", os.getenv("MIMO_CONNECT_MODE", "weixin"))
    model = os.getenv("MIMO_CONNECT_MODEL", "") or "默认"
    work_dir = os.getenv("MIMO_CONNECT_WORK_DIR", str(config_io.PROJECT_ROOT))
    print("─" * 58)
    print("  MIMO_Connect 运行状态：运行中")
    print(f"  PID        {pid}")
    print(f"  平台       {platform}")
    print(f"  模型       {model}")
    print(f"  工作目录   {work_dir}")
    print(f"  日志       {LOG_PATH}")
    print("─" * 58)
    return 0
