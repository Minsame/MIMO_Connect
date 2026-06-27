"""MIMO_Connect 命令行入口（Linux / macOS，守护进程 + 子命令）。

默认把引擎拉到后台运行，前台只打印启动结果即返回，不再常驻刷日志。
通过子命令控制后台引擎；想看日志用 'mmc logs -f'。

用法：
    mmc                 启动引擎（后台），打印启动结果即返回
    mmc start           同上（显式）
    mmc restart | res   重启引擎（重新读取 .env / config.yaml）
    mmc stop            停止后台引擎
    mmc status          查看运行状态（PID / 平台 / 模型 / 工作目录）
    mmc config          调起配置引导，配置完成后自动重启引擎
    mmc logs [-n N]     显示最近 N 行日志（默认 200）
    mmc logs -f         实时跟随日志（Ctrl-C 退出）
    mmc model           查看当前 MiMo 模型
    mmc help            显示帮助

    mmc --force-setup   等价于 mmc config（向后兼容）
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


HELP_TEXT = """MIMO_Connect 命令行（Linux / macOS）

  mmc                启动引擎（后台运行，打印启动结果即返回）
  mmc start          同上
  mmc restart | res  重启引擎（重新读取 .env / config.yaml）
  mmc stop           停止后台引擎
  mmc status         查看运行状态
  mmc config         调起配置引导，配置完成后自动重启引擎
  mmc logs [-n N]    显示最近 N 行日志（默认 200）
  mmc logs -f        实时跟随日志（Ctrl-C 退出）
  mmc model          查看当前 MiMo 模型
  mmc help           显示本帮助
"""


def _run_setup(force: bool) -> int:
    """运行分步配置引导。force=True 时强制重新配置。"""
    from scripts import first_run_setup

    argv_backup = list(sys.argv)
    sys.argv = ["first_run_setup"]
    if force:
        sys.argv.append("--force")
    try:
        return first_run_setup.main()
    finally:
        sys.argv = argv_backup


def _cmd_config() -> int:
    """配置引导 → 成功后自动重启引擎。"""
    from core import config_io, daemon

    rc = _run_setup(force=True)
    if rc != 0:
        print("[mmc] 配置已取消或未完成；引擎状态未改变。")
        return rc
    print("[mmc] 配置已保存，正在重启引擎以生效 ...")
    from dotenv import load_dotenv

    load_dotenv(config_io.ENV_PATH, override=True)
    return daemon.restart()


def _cmd_logs(args: list[str]) -> int:
    """显示/跟随日志。"""
    from core import daemon

    log_path = daemon.LOG_PATH
    if not log_path.exists():
        print(f"[mmc] 暂无日志文件：{log_path}")
        return 0

    follow = "-f" in args or "--follow" in args
    lines = 200
    for flag in ("-n", "--lines"):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args) and args[i + 1].isdigit():
                lines = int(args[i + 1])

    # 先打印末尾 N 行。
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        tail = f.readlines()[-lines:]
    sys.stdout.write("".join(tail))
    sys.stdout.flush()

    if not follow:
        return 0

    # 跟随模式：轮询新增内容，直到 Ctrl-C。
    import time

    print("\n[mmc] 跟随日志中（Ctrl-C 退出）...", flush=True)
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # 跳到文件末尾
            while True:
                chunk = f.read()
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                else:
                    time.sleep(0.4)
    except KeyboardInterrupt:
        print("\n[mmc] 已退出日志跟随（引擎仍在后台运行）。")
    return 0


def _cmd_model() -> int:
    """查看当前 MiMo 模型。"""
    import os
    from core import config_io
    from dotenv import load_dotenv

    load_dotenv(config_io.ENV_PATH, override=True)
    model = os.getenv("MIMO_CONNECT_MODEL", "") or "默认"
    print(f"[mmc] 当前 MiMo 模型：{model}")
    print("    在飞书/微信对话中用 /model <名称> 可切换（下次新对话生效）。")
    return 0


def main() -> int:
    from core import config_io

    # 首次运行：自动创建 .env / config.yaml（不覆盖已有）。
    config_io.ensure_runtime_files()

    argv = sys.argv[1:]
    cmd = argv[0].lower() if argv else "start"
    rest = argv[1:]

    # 向后兼容：--force-setup 等价于 config。
    if cmd in ("--force-setup", "--config"):
        cmd, rest = "config", []

    if cmd in ("help", "-h", "--help"):
        print(HELP_TEXT)
        return 0
    if cmd == "config":
        return _cmd_config()
    if cmd == "logs":
        return _cmd_logs(rest)
    if cmd == "model":
        return _cmd_model()

    # 以下命令需要守护进程支持（POSIX）。
    from core import daemon

    if cmd in ("restart", "res"):
        # 未配置则先引导。
        if not config_io.is_configured():
            return _cmd_config()
        return daemon.restart()
    if cmd == "stop":
        return daemon.stop()
    if cmd == "status":
        return daemon.status()
    if cmd in ("start",):
        # 首次未配置：先引导，引导内部会在结束时重启/启动。
        if not config_io.is_configured():
            return _cmd_config()
        return daemon.start()

    print(f"[mmc] 未知命令：{cmd}\n", file=sys.stderr)
    print(HELP_TEXT)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
