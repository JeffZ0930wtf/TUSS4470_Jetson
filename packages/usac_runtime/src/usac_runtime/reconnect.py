"""Bounded retries for transport establishment only.

Callers must not wrap CAPTURE, SET_CONFIG, or any other side-effecting protocol
transaction with this helper. It is limited to opening a connection or replaying
an already durable, idempotently identified spool record.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def retry_connection(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    initial_delay_s: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Retry ConnectionError/OSError with a small bounded exponential delay."""

    if attempts < 1:
        raise ValueError("attempts must be positive")
    if initial_delay_s < 0:
        raise ValueError("initial_delay_s must be non-negative")
    delay = initial_delay_s
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (ConnectionError, OSError):
            if attempt == attempts:
                raise
            sleep(delay)
            delay = min(delay * 2, 2.0)
    raise AssertionError("retry loop must return or raise")
