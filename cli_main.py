"""MIMO_Connect 命令行入口（跨平台，无图形界面）。

职责单一：终端模式运行。未配置时先跑分步引导向导（scripts/first_run_setup.py），
配置完成后启动引擎并把日志持续打印到终端。适用于 Linux / macOS / 无显示器 / 开发调试。

用法：
    python cli_main.py               # 缺配置则引导，否则直接启动
    python cli_main.py --force-setup # 强制重新进入配置向导
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    from dotenv import load_dotenv
    from core import config_io

    force_setup = "--force-setup" in sys.argv
    if force_setup or not config_io.is_configured():
        from scripts import first_run_setup

        if force_setup and "--force" not in sys.argv:
            sys.argv.append("--force")
        rc = first_run_setup.main()
        if rc != 0:
            return rc

    load_dotenv(config_io.ENV_PATH, override=True)

    import main as app_main

    app_main.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
