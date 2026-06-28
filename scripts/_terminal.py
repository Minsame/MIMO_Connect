
"""Cross-platform terminal helper: arrow keys, numbered menus, step-back support.
No external dependencies (uses msvcrt/termios from stdlib).
"""

import sys, os, time

# ── Raw keyboard input ───────────────────────────────────────────

def _getch() -> str:
    """Read one keypress; arrow keys return 'UP'/'DOWN'. Cross-platform."""
    try:
        import msvcrt
        ch = msvcrt.getch()
        if ch == b"\xe0":                      # arrow prefix on Windows
            ch2 = msvcrt.getch()
            return {"H": "UP", "P": "DOWN"}.get(ch2.decode(), "")
        return ch.decode("utf-8", errors="replace")
    except ImportError:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(3)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if ch == "\x1b[A":
            return "UP"
        if ch == "\x1b[B":
            return "DOWN"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == "\x1b":
            return "ESC"
        return ch.strip() or ch


def _clear_lines(n: int) -> None:
    """Move cursor up n lines and clear."""
    for _ in range(n):
        sys.stdout.write("\x1b[1A\x1b[2K")
    sys.stdout.flush()


# ── Interactive select (arrow keys + enter) ─────────────────────

def menu_select(options: list[str], prompt: str = "", default_index: int = 0, allow_back: bool = True) -> int | str:
    """Show a menu with arrow key navigation. Returns index or "BACK"/"QUIT"."""
    n = len(options)
    idx = default_index if 0 <= default_index < n else 0
    extra = 1  # prompt line
    if allow_back:
        extra += 1  # hint line

    while True:
        if prompt:
            sys.stdout.write(prompt + "\n")
        for i, opt in enumerate(options):
            prefix = " \u25b6 " if i == idx else "   "
            sys.stdout.write(f"{prefix}{opt}\n")
        if allow_back:
            sys.stdout.write("\n  [\u2191\u2193\u2192 选择  Enter 确认  B 上一步  Q 退出]\n")
        sys.stdout.flush()

        key = _getch()
        if key == "UP":
            idx = (idx - 1) % n
        elif key == "DOWN":
            idx = (idx + 1) % n
        elif key in ("ENTER", "\r", "\n"):
            _clear_lines(n + extra)
            return idx
        elif key in ("b", "B"):
            _clear_lines(n + extra)
            return "BACK"
        elif key in ("q", "Q", "ESC"):
            _clear_lines(n + extra)
            return "QUIT"
        _clear_lines(n + extra)


# ── Enhanced ask with back support ──────────────────────────────

def ask_with_back(prompt: str, default: str = "", secret: bool = False) -> str:
    """Ask for text input; user can type '\\b' to go back, '\\q' to quit."""
    hint = "  [Enter 确认  |b| 上一步  |q| 退出]"
    full = f"{prompt} {hint}\n  "
    if default:
        full += f"[{default}] "
    while True:
        val = input(full).strip()
        if val.lower() in ("b", "\\b"):
            return "BACK"
        if val.lower() in ("q", "\\q", "quit"):
            return "QUIT"
        if not val and default:
            return default
        if val:
            return val
        sys.stdout.write("\x1b[1A\x1b[2K")  # clear the empty input line

