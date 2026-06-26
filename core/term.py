"""终端 UI 辅助：启动横幅 + 按 TTY 能力分级着色的日志格式化器。

用于 Linux/macOS 命令行运行态（mmc / app_main.py --cli）。在非 TTY
（重定向到文件、管道、CI）时自动退化为无颜色纯文本，保证日志可读。
"""

from __future__ import annotations

import logging
import os
import sys

# ANSI 颜色
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_COLORS = {
    "DEBUG": "\033[38;5;244m",   # 灰
    "INFO": "\033[38;5;75m",     # 蓝
    "WARNING": "\033[38;5;179m", # 琥珀
    "ERROR": "\033[38;5;203m",   # 红
    "CRITICAL": "\033[48;5;203m\033[97m",  # 红底白字
}
_LEVEL_TAG = {
    "DEBUG": "DBG",
    "INFO": "INF",
    "WARNING": "WRN",
    "ERROR": "ERR",
    "CRITICAL": "CRT",
}


def supports_color(stream=None) -> bool:
    """判断目标流是否适合输出 ANSI 颜色。"""
    stream = stream or sys.stderr
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("MIMO_CONNECT_NO_COLOR"):
        return False
    is_tty = hasattr(stream, "isatty") and stream.isatty()
    if sys.platform == "win32":
        # 现代 Windows 终端（WT / VSCode）支持 ANSI；保守起见仅 TTY 时启用。
        return is_tty and bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))
    return is_tty


class ColorFormatter(logging.Formatter):
    """带颜色的日志格式化器：时间(暗) 级别(色块) name(暗) message。"""

    def __init__(self, use_color: bool = True) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        level = record.levelname
        tag = _LEVEL_TAG.get(level, level[:3])
        name = record.name
        msg = record.getMessage()
        if record.exc_info:
            msg = f"{msg}\n{self.formatException(record.exc_info)}"
        if not self._use_color:
            return f"{ts} [{tag}] {name}: {msg}"
        color = _COLORS.get(level, "")
        return (
            f"{_DIM}{ts}{_RESET} "
            f"{color}{_BOLD} {tag} {_RESET} "
            f"{_DIM}{name}{_RESET}  {msg}"
        )


def banner(platform: str, work_dir: str, model: str, mimo_path: str = "") -> str:
    """组装启动横幅（带运行配置摘要）。非 TTY 时返回纯文本版本。"""
    use_color = supports_color()
    line = "\u2500" * 58
    title = "MIMO_Connect"
    subtitle = "飞书 / 微信 \u2192 本地 MiMo Code 中间层"
    rows = [
        ("平台", platform or "-"),
        ("工作目录", work_dir or "-"),
        ("MiMo 模型", model or "默认"),
        ("mimo CLI", mimo_path or "PATH 自动查找"),
    ]
    if use_color:
        c = "\033[38;5;75m"
        out = [f"{c}{_BOLD}{line}{_RESET}"]
        out.append(f"{c}{_BOLD}  {title}{_RESET}   {_DIM}{subtitle}{_RESET}")
        out.append(f"{c}{line}{_RESET}")
        for k, v in rows:
            out.append(f"  {_DIM}{k:<10}{_RESET} {v}")
        out.append(f"{c}{line}{_RESET}")
        out.append(f"  {_DIM}Ctrl-C 退出 \u00b7 日志见 mimo_connect.log{_RESET}")
        out.append("")
        return "\n".join(out)
    out = [line, f"  {title}   {subtitle}", line]
    for k, v in rows:
        out.append(f"  {k:<10} {v}")
    out.append(line)
    out.append("  Ctrl-C 退出 · 日志见 mimo_connect.log")
    out.append("")
    return "\n".join(out)
