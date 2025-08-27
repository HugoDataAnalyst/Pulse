import functools
import inspect
from time import perf_counter
from loguru import logger
from typing import Any, Callable, Coroutine, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

def log_timing(name: str | None = None, level: str = "DEBUG") -> Callable[[F], F]:
    """
    Decorator to log execution time of sync/async functions.

    Usage:
        @log_timing("my_task")
        async def foo(...): ...

        @log_timing()
        def bar(...): ...
    """
    def decorator(func: F) -> F:
        func_name = name or func.__qualname__
        is_coro = inspect.iscoroutinefunction(func)

        if is_coro:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                t0 = perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    elapsed = round((perf_counter() - t0) * 1000, 2)
                    logger.opt(depth=1).log(level, f"[Timing] {func_name} executed in {elapsed} ms")
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                t0 = perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    elapsed = round((perf_counter() - t0) * 1000, 2)
                    logger.opt(depth=1).log(level, f"[Timing] {func_name} executed in {elapsed} ms")

        return wrapper

    return decorator
