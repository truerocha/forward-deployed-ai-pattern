"""
Retry utilities for DynamoDB operations that must not be silently swallowed.

Provides a decorator for operations where failure means data loss
(DAG orphans, leaked concurrency slots, stale dashboard state).
"""
import functools
import logging
import time
from typing import TypeVar, Callable, Any

logger = logging.getLogger("fde.retry")

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retriable_exceptions: tuple = (Exception,),
    operation_name: str = "",
):
    """Decorator that retries a function with exponential backoff.

    Used for DynamoDB operations that MUST succeed (complete_task, fail_task)
    because failure means DAG orphans and leaked concurrency slots.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds (doubles each retry).
        max_delay: Maximum delay cap in seconds.
        retriable_exceptions: Exception types that trigger retry.
        operation_name: Human-readable name for logging.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            name = operation_name or func.__name__
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retriable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            name, max_retries + 1, e,
                        )
                        raise

                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        "%s attempt %d/%d failed: %s — retrying in %.1fs",
                        name, attempt + 1, max_retries + 1, e, delay,
                    )
                    time.sleep(delay)

            raise last_exception  # Unreachable but satisfies type checker

        return wrapper
    return decorator
