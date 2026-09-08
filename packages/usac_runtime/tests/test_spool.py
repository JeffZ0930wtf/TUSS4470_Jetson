from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from usac_protocol.capture_data import decode_capture_data, encode_capture_data
from usac_protocol.frame import Frame, MessageType, crc32_iso_hdlc, decode_frame, encode_frame
from usac_runtime.spool import (
    ALREADY_COMMITTED,
    DELETED,
    CaptureSpool,
    SpoolConflictError,
)
import usac_runtime.spool as spool_module


ROOT = Path(__file__).resolve().parents[3]


class _TrackedConnection:
    """Expose whether spool transaction scopes explicitly close SQLite."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.closed = False

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        return self._connection.__exit__(*args)

    def close(self) -> None:
        self.closed = True
        self._connection.close()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def test_spool_closes_every_transaction_connection(tmp_path: Path, monkeypatch) -> None:
    real_connect = sqlite3.connect
    observed: list[_TrackedConnection] = []

    def tracked_connect(*args, **kwargs):
        connection = _TrackedConnection(real_connect(*args, **kwargs))
        observed.append(connection)
        return connection

    monkeypatch.setattr(spool_module.sqlite3, "connect", tracked_connect)
    spool = CaptureSpool(tmp_path / "connection-lifetime.sqlite3")
    assert spool.pending_records() == []

    assert len(observed) == 2
    assert all(connection.closed for connection in observed)


def _capture_frame() -> bytes:
    return bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )


def _changed_capture_frame(raw_frame: bytes) -> bytes:
    frame = decode_frame(raw_frame)
    capture = decode_capture_data(frame.payload)
    changed = replace(capture, samples=(capture.samples[0] ^ 1, *capture.samples[1:]))
    return encode_frame(
        Frame(
            MessageType.CAPTURE_DATA,
            frame.sequence,
            encode_capture_data(changed),
            frame.flags,
        )
    )


def _capture_frame_with_id(index: int, *, device_id: bytes | None = None) -> bytes:
    frame = decode_frame(_capture_frame())
    capture = decode_capture_data(frame.payload)
    changed = replace(
        capture,
        device_id=capture.device_id if device_id is None else device_id,
        capture_id=index.to_bytes(16, "little"),
        capture_sequence=index,
    )
    return encode_frame(
        Frame(
            MessageType.CAPTURE_DATA,
            index,
            encode_capture_data(changed),
            frame.flags,
        )
    )


def test_spool_persists_complete_capture_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "bridge-spool.sqlite3"
    raw_frame = _capture_frame()
    spool = CaptureSpool(path)

    stored = spool.store_capture(
        raw_frame,
        source_connection_id=9,
        source_first_stream_offset=100,
        source_last_stream_offset=100 + len(raw_frame) - 1,
        stored_utc_ns=123,
    )

    reopened = CaptureSpool(path).pending_records()
    assert reopened == [stored]
    assert stored.inner_frame == raw_frame
    assert stored.inner_frame_crc32 == crc32_iso_hdlc(raw_frame)
    assert stored.capture_id == bytes(range(16, 32))


def test_spool_returns_same_record_for_identical_capture(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge-spool.sqlite3")
    raw_frame = _capture_frame()
    arguments = {
        "source_connection_id": 9,
        "source_first_stream_offset": 100,
        "source_last_stream_offset": 100 + len(raw_frame) - 1,
        "stored_utc_ns": 123,
    }

    first = spool.store_capture(raw_frame, **arguments)
    second = spool.store_capture(raw_frame, **arguments)

    assert second == first
    assert spool.pending_records() == [first]


def test_spool_rejects_same_capture_identity_with_different_bytes(
    tmp_path: Path,
) -> None:
    spool = CaptureSpool(tmp_path / "bridge-spool.sqlite3")
    raw_frame = _capture_frame()
    arguments = {
        "source_connection_id": 9,
        "source_first_stream_offset": 0,
        "source_last_stream_offset": len(raw_frame) - 1,
        "stored_utc_ns": 123,
    }
    spool.store_capture(raw_frame, **arguments)

    with pytest.raises(SpoolConflictError, match="different frame"):
        spool.store_capture(_changed_capture_frame(raw_frame), **arguments)


def test_spool_commit_is_durable_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "bridge-spool.sqlite3"
    raw_frame = _capture_frame()
    spool = CaptureSpool(path)
    stored = spool.store_capture(
        raw_frame,
        source_connection_id=9,
        source_first_stream_offset=0,
        source_last_stream_offset=len(raw_frame) - 1,
        stored_utc_ns=123,
    )

    first = spool.mark_committed(
        stored.record_id,
        device_id=stored.device_id,
        boot_id=stored.boot_id,
        capture_id=stored.capture_id,
        inner_frame_crc32=stored.inner_frame_crc32,
    )
    second = CaptureSpool(path).mark_committed(
        stored.record_id,
        device_id=stored.device_id,
        boot_id=stored.boot_id,
        capture_id=stored.capture_id,
        inner_frame_crc32=stored.inner_frame_crc32,
    )

    assert first == DELETED
    assert second == ALREADY_COMMITTED
    assert spool.pending_records() == []


def test_spool_rejects_commit_identity_mismatch(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge-spool.sqlite3")
    raw_frame = _capture_frame()
    stored = spool.store_capture(
        raw_frame,
        source_connection_id=9,
        source_first_stream_offset=0,
        source_last_stream_offset=len(raw_frame) - 1,
        stored_utc_ns=123,
    )

    with pytest.raises(SpoolConflictError, match="does not match"):
        spool.mark_committed(
            stored.record_id,
            device_id=bytes(16),
            boot_id=stored.boot_id,
            capture_id=stored.capture_id,
            inner_frame_crc32=stored.inner_frame_crc32,
        )


def test_pending_records_are_read_in_bounded_batches(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge-spool.sqlite3")
    for index in range(1, 4):
        raw_frame = _capture_frame_with_id(index)
        spool.store_capture(
            raw_frame,
            source_connection_id=9,
            source_first_stream_offset=0,
            source_last_stream_offset=len(raw_frame) - 1,
            stored_utc_ns=index,
        )

    first_batch = spool.pending_records(limit=2)

    assert [record.capture_sequence for record in first_batch] == [1, 2]


def test_committed_tombstones_are_pruned_to_configured_limit(tmp_path: Path) -> None:
    path = tmp_path / "bridge-spool.sqlite3"
    spool = CaptureSpool(path, tombstone_limit=2)
    for index in range(1, 4):
        raw_frame = _capture_frame_with_id(index)
        stored = spool.store_capture(
            raw_frame,
            source_connection_id=9,
            source_first_stream_offset=0,
            source_last_stream_offset=len(raw_frame) - 1,
            stored_utc_ns=index,
        )
        spool.mark_committed(
            stored.record_id,
            device_id=stored.device_id,
            boot_id=stored.boot_id,
            capture_id=stored.capture_id,
            inner_frame_crc32=stored.inner_frame_crc32,
        )

    with sqlite3.connect(path) as connection:
        record_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT record_id FROM committed_tombstones ORDER BY record_id"
            )
        ]

    assert record_ids == [2, 3]


def test_committed_tombstone_limit_is_applied_per_device(tmp_path: Path) -> None:
    path = tmp_path / "bridge-spool.sqlite3"
    spool = CaptureSpool(path, tombstone_limit=2)
    devices = (bytes([0x11]) * 16, bytes([0x22]) * 16)
    index = 0
    for device_id, count in ((devices[0], 3), (devices[1], 2)):
        for _ in range(count):
            index += 1
            raw_frame = _capture_frame_with_id(index, device_id=device_id)
            stored = spool.store_capture(
                raw_frame,
                source_connection_id=9,
                source_first_stream_offset=0,
                source_last_stream_offset=len(raw_frame) - 1,
                stored_utc_ns=index,
            )
            spool.mark_committed(
                stored.record_id,
                device_id=stored.device_id,
                boot_id=stored.boot_id,
                capture_id=stored.capture_id,
                inner_frame_crc32=stored.inner_frame_crc32,
            )

    with sqlite3.connect(path) as connection:
        counts = {
            bytes(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT device_id, COUNT(*) FROM committed_tombstones GROUP BY device_id"
            )
        }

    assert counts == {devices[0]: 2, devices[1]: 2}
