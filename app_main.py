"""MIMO_Connect 统一入口。

- Windows（默认）：启动 GUI 壳（分步引导 + 托盘 + 设置 + 日志窗口）。
- Linux/macOS：命令行模式，持续打印日志；首次未配置时先跑 CLI 分步向导。
- 可用 --cli 强制命令行模式，--gui 强制 GUI 模式。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _want_gui() -> bool:
    if "--cli" in sys.argv:
        return False
    if "--gui" in sys.argv:
        return True
    return os.name == "nt"


def _run_cli() -> int:
    from dotenv import load_dotenv
    from core import config_io

    force_setup = "--force-setup" in sys.argv
    if force_setup or not config_io.is_configured():
        from scripts import first_run_setup
        # 复用 CLI 分步向导；--force 让它在已存在 .env 时也重新配置。
        if force_setup and "--force" not in sys.argv:
            sys.argv.append("--force")
        rc = first_run_setup.main()
        if rc != 0:
            return rc
    load_dotenv(config_io.ENV_PATH, override=True)

    import main as app_main
    app_main.main()
    return 0


def main() -> int:
    if _want_gui():
        try:
            from gui.app import run_gui
        except Exception as e:
            print(f"[MIMO_Connect] GUI 不可用（{e}），回退到命令行模式。")
            return _run_cli()
        return run_gui()
    return _run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
