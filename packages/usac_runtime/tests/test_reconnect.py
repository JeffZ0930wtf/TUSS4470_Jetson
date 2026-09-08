from __future__ import annotations

import pytest

from usac_runtime.reconnect import retry_connection, supervise_sessions


def test_connection_retry_uses_bounded_exponential_delays() -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("offline")
        return "connected"

    assert retry_connection(
        operation,
        attempts=3,
        initial_delay_s=0.1,
        sleep=delays.append,
    ) == "connected"
    assert delays == [0.1, 0.2]


def test_connection_retry_stops_after_configured_attempts() -> None:
    with pytest.raises(ConnectionError, match="offline"):
        retry_connection(
            lambda: (_ for _ in ()).throw(ConnectionError("offline")),
            attempts=2,
            initial_delay_s=0,
            sleep=lambda _: None,
        )


def test_connection_retry_does_not_retry_non_transport_errors() -> None:
    calls = 0

    def unsafe_operation() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("protocol rejected")

    with pytest.raises(ValueError, match="protocol rejected"):
        retry_connection(unsafe_operation, attempts=3, sleep=lambda _: None)
    assert calls == 1


def test_session_supervisor_reopens_after_transport_loss_without_replaying_work() -> None:
    sessions = 0
    delays: list[float] = []

    def run_one_session() -> None:
        nonlocal sessions
        sessions += 1
        if sessions == 1:
            raise OSError("USB device reset")

    supervise_sessions(
        run_one_session,
        reconnect_delay_s=0.25,
        should_stop=lambda: sessions >= 2,
        sleep=delays.append,
    )

    assert sessions == 2
    assert delays == [0.25]


def test_session_supervisor_does_not_hide_protocol_errors() -> None:
    with pytest.raises(ValueError, match="invalid frame"):
        supervise_sessions(
            lambda: (_ for _ in ()).throw(ValueError("invalid frame")),
            reconnect_delay_s=0,
            should_stop=lambda: False,
            sleep=lambda _: None,
        )
