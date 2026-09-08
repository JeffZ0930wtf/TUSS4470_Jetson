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


def supervise_sessions(
    run_one_session: Callable[[], None],
    *,
    reconnect_delay_s: float,
    should_stop: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Reopen transport sessions, never the command that failed inside one.

    A USB reset or TCP disconnect invalidates the whole HELLO session.  The
    bridge therefore closes both transports and starts a fresh session after
    a short delay.  Protocol/validation failures deliberately escape instead
    of being hidden by an endless reconnect loop.
    """

    if reconnect_delay_s < 0:
        raise ValueError("reconnect_delay_s must be non-negative")
    while not should_stop():
        try:
            run_one_session()
        except (ConnectionError, TimeoutError, OSError):
            pass
        if not should_stop():
            sleep(reconnect_delay_s)
