"""Cross-platform terminal helper: arrow keys, numbered menus, step-back support.
No external dependencies (uses msvcrt/termios from stdlib).
"""

import sys

def _getch() -> str:
    """Read one keypress; arrow keys return UP/DOWN. Cross-platform."""
    try:
        import msvcrt
        ch = msvcrt.getch()
        if ch == b"\xe0":
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
        if ch == "\x1b[A": return "UP"
        if ch == "\x1b[B": return "DOWN"
        if ch in ("\r", "\n"): return "ENTER"
        if ch == "\x1b": return "ESC"
        return ch.strip() or ch


def _clear_lines(n: int) -> None:
    """Move cursor up n lines and clear each."""
    for _ in range(n):
        sys.stdout.write("\x1b[1A\x1b[2K")
    sys.stdout.flush()


def menu_select(options: list[str], prompt: str = "",
                default_index: int = 0, allow_back: bool = True) -> int | str:
    """Arrow-key selectable menu. Returns index or BACK/QUIT."""
    n = len(options)
    idx = default_index if 0 <= default_index < n else 0
    extra = 1 + (1 if allow_back else 0)
    first = True

    while True:
        # Clear previous display (skip first pass)
        if not first:
            _clear_lines(n + extra)
        first = False

        # Write menu
        if prompt:
            sys.stdout.write(prompt + "\n")
        for i, opt in enumerate(options):
            prefix = " \u25b6 " if i == idx else "   "
            sys.stdout.write(f"{prefix}{opt}\n")
        if allow_back:
            sys.stdout.write("\n  [\u2191\u2193\u2192  Enter  B \u4e0a\u4e00\u6b65  Q \u9000\u51fa]\n")
        sys.stdout.flush()

        # Read key
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
