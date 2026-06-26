"""在后台线程里运行现有的 asyncio Engine，并把日志桥接给 GUI。

设计：
- GUI 跑在 Qt 主线程；引擎跑在独立 QThread 内的私有事件循环里。
- 通过自定义 logging.Handler 把日志行 emit 成 Qt 信号，推送到日志窗口。
- 提供 start()/stop()，stop 时优雅关闭 Engine 并停掉事件循环。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal


class QtLogHandler(logging.Handler, QObject):
    """把日志记录转成 Qt 信号，供日志窗口实时显示。"""

    record_emitted = Signal(str)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.record_emitted.emit(self.format(record))
        except Exception:
            pass


class EngineRunner(QThread):
    """在独立线程内运行 main.run() 的事件循环。"""

    started_ok = Signal()
    stopped = Signal()
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None

    def run(self) -> None:  # noqa: D401 - QThread entrypoint
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._stop_event = asyncio.Event()
            loop.run_until_complete(self._main())
            self.stopped.emit()
        except Exception as e:  # 引擎启动/运行异常上报 GUI
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._loop = None

    async def _main(self) -> None:
        # 延迟导入，避免在未装依赖时拖垮 GUI 启动。
        import main as app_main

        self.started_ok.emit()
        runner_task = asyncio.ensure_future(app_main.run())
        stop_task = asyncio.ensure_future(self._stop_event.wait())
        done, pending = await asyncio.wait(
            {runner_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done and not runner_task.done():
            runner_task.cancel()
            try:
                await runner_task
            except asyncio.CancelledError:
                pass
        for task in pending:
            task.cancel()
        # 若引擎自身抛错，传播出去以便 run() 上报。
        if runner_task in done:
            runner_task.result()

    def stop(self) -> None:
        """从 GUI 线程请求停止引擎。"""
        loop = self._loop
        stop_event = self._stop_event
        if loop and stop_event and loop.is_running():
            loop.call_soon_threadsafe(stop_event.set)
