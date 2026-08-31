from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from usac_protocol.capture_data import decode_capture_data, encode_capture_data
from usac_protocol.frame import Frame, MessageType, crc32_iso_hdlc, decode_frame, encode_frame
from usac_runtime.spool import (
    ALREADY_COMMITTED,
    DELETED,
    CaptureSpool,
    SpoolConflictError,
)


ROOT = Path(__file__).resolve().parents[3]


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
