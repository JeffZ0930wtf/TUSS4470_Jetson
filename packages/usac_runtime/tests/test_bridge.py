from __future__ import annotations

import socket
import threading
from pathlib import Path

from usac_runtime.bridge import (
    CountingConnection,
    deliver_spool,
    new_sqlite_integer_id,
    spool_artifacts,
)
from usac_runtime.core_service import open_listener, serve_connections
from usac_runtime.core_store import CaptureStore
from usac_runtime.spool import CaptureSpool


ROOT = Path(__file__).resolve().parents[3]


class ReadOnlyConnection:
    def __init__(self, data: bytes) -> None:
        self.data = bytearray(data)

    def read(self, size: int) -> bytes:
        chunk = bytes(self.data[:size])
        del self.data[:size]
        return chunk

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        pass


def _raw_capture() -> bytes:
    return bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )


def test_counting_connection_tracks_only_received_bytes() -> None:
    connection = CountingConnection(ReadOnlyConnection(b"abcdef"))

    assert connection.read(2) == b"ab"
    assert connection.write(b"request") == 7
    assert connection.read(10) == b"cdef"
    assert connection.received_bytes == 6


def test_sqlite_connection_id_stays_in_positive_signed_range(monkeypatch) -> None:
    requested_widths: list[int] = []

    def fake_randbits(width: int) -> int:
        requested_widths.append(width)
        return 0

    monkeypatch.setattr("usac_runtime.bridge.secrets.randbits", fake_randbits)

    assert new_sqlite_integer_id() == 1
    assert requested_widths == [63]


def test_spool_artifacts_removes_staging_only_after_durable_store(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "capture.usac"
    metadata_path = tmp_path / "capture.json"
    samples_path = tmp_path / "capture.u16le"
    raw_path.write_bytes(_raw_capture())
    metadata_path.write_text("{}\n", encoding="utf-8")
    samples_path.write_bytes(b"samples")
    spool = CaptureSpool(tmp_path / "bridge.sqlite3")

    pending = spool_artifacts(
        spool,
        raw_path=raw_path,
        metadata_path=metadata_path,
        samples_path=samples_path,
        source_connection_id=7,
        source_first_stream_offset=100,
        stored_utc_ns=8,
    )

    assert pending.inner_frame == _raw_capture()
    assert pending.source_last_stream_offset == 100 + len(_raw_capture()) - 1
    assert spool.pending_records() == [pending]
    assert raw_path.exists() is False
    assert metadata_path.exists() is False
    assert samples_path.exists() is False


def test_deliver_spool_replays_all_pending_records(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge.sqlite3")
    raw = _raw_capture()
    spool.store_capture(
        raw,
        source_connection_id=1,
        source_first_stream_offset=0,
        source_last_stream_offset=len(raw) - 1,
        stored_utc_ns=2,
    )
    store = CaptureStore(tmp_path / "core.sqlite3")
    listener = open_listener("127.0.0.1", 0)
    port = int(listener.getsockname()[1])
    worker = threading.Thread(
        target=serve_connections,
        args=(listener, store),
        kwargs={"connection_limit": 1},
    )
    worker.start()

    delivered = deliver_spool(spool, core_host="127.0.0.1", core_port=port)
    worker.join(timeout=2)

    assert delivered == 1
    assert spool.pending_records() == []
    assert store.capture_count() == 1
