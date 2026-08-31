from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from usac_runtime.core_service import main, open_listener, serve_connections
from usac_runtime.core_store import CaptureStore
from usac_runtime.delivery import deliver_pending
from usac_runtime.spool import CaptureSpool


ROOT = Path(__file__).resolve().parents[3]


def test_core_service_accepts_localhost_delivery(tmp_path: Path) -> None:
    raw = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
    spool = CaptureSpool(tmp_path / "bridge.sqlite3")
    pending = spool.store_capture(
        raw,
        source_connection_id=1,
        source_first_stream_offset=0,
        source_last_stream_offset=len(raw) - 1,
        stored_utc_ns=2,
    )
    store = CaptureStore(tmp_path / "core.sqlite3")
    listener = open_listener("127.0.0.1", 0)
    address = listener.getsockname()
    worker = threading.Thread(
        target=serve_connections,
        args=(listener, store),
        kwargs={"connection_limit": 1},
    )
    worker.start()

    with socket.create_connection(address, timeout=1) as connection:
        connection.settimeout(1)
        disposition = deliver_pending(
            connection,
            spool,
            pending,
            connection_id=5,
            sequence=6,
        )
    worker.join(timeout=2)

    assert disposition == 1
    assert worker.is_alive() is False
    assert spool.pending_records() == []
    assert store.capture_count() == 1


def test_core_service_cli_serves_configured_database(tmp_path: Path) -> None:
    probe = open_listener("127.0.0.1", 0)
    port = int(probe.getsockname()[1])
    probe.close()
    database = tmp_path / "core.sqlite3"
    result: list[int] = []
    worker = threading.Thread(
        target=lambda: result.append(
            main(
                [
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--sqlite",
                    str(database),
                    "--connection-limit",
                    "1",
                ]
            )
        )
    )
    worker.start()

    deadline = time.monotonic() + 2
    while True:
        try:
            connection = socket.create_connection(("127.0.0.1", port), timeout=0.2)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)

    raw = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
    spool = CaptureSpool(tmp_path / "bridge-cli.sqlite3")
    pending = spool.store_capture(
        raw,
        source_connection_id=7,
        source_first_stream_offset=0,
        source_last_stream_offset=len(raw) - 1,
        stored_utc_ns=8,
    )
    with connection:
        deliver_pending(
            connection,
            spool,
            pending,
            connection_id=9,
            sequence=10,
        )
    worker.join(timeout=2)

    assert result == [0]
    assert CaptureStore(database).capture_count() == 1
