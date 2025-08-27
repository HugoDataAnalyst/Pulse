# services/appscheduler.py
import asyncio
from typing import Awaitable, Callable, Dict
from loguru import logger

JobFn = Callable[[], Awaitable[None]]

class AppScheduler:
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._stopped = asyncio.Event()

    def every(
        self,
        name: str,
        seconds: float,
        job: JobFn,
        *,
        run_immediately: bool = True,
        start_delay: float | None = None,
    ) -> None:
        """
        Schedule `job` to run every `seconds` until `stop()` is called.
        - run_immediately=True: run once right away, then every `seconds`.
          If False, first run occurs after the first interval (or start_delay if provided).
        - start_delay: optional initial delay (overrides run_immediately for the first wait).
        """
        if name in self._tasks and not self._tasks[name].done():
            logger.warning(f"[scheduler] job '{name}' already running")
            return
        self._tasks[name] = asyncio.create_task(
            self._run_loop(name, seconds, job, run_immediately=run_immediately, start_delay=start_delay)
        )

    async def _run_loop(
        self,
        name: str,
        seconds: float,
        job: JobFn,
        *,
        run_immediately: bool,
        start_delay: float | None,
    ):
        logger.info(f"[scheduler] start job '{name}' every {seconds:.1f}s")
        try:
            # Optional initial delay
            if start_delay is not None:
                logger.debug(f"[scheduler:{name}] initial delay {start_delay:.1f}s")
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=max(0.0, start_delay))
                    return  # stopped during initial delay
                except asyncio.TimeoutError:
                    pass
            elif not run_immediately:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=max(0.0, seconds))
                    return  # stopped before first run
                except asyncio.TimeoutError:
                    pass

            while not self._stopped.is_set():
                started = asyncio.get_event_loop().time()
                try:
                    await job()
                    logger.info(f"[scheduler] job '{name}' ran, rescheduled in {seconds:.1f}s")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(f"[scheduler] job '{name}' crashed: {e}")

                # sleep until next tick (or stop)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=max(0.0, seconds))
                except asyncio.TimeoutError:
                    # timeout -> proceed to next run
                    pass
        except asyncio.CancelledError:
            logger.info(f"[scheduler] job '{name}' cancelled")
            raise
        except Exception as e:
            logger.exception(f"[scheduler] loop for '{name}' failed: {e}")

    async def stop(self):
        self._stopped.set()
        for name, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._tasks.clear()
