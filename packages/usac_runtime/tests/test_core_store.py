from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from usac_protocol.bridge_messages import BridgeCaptureDelivery
from usac_protocol.capture_data import decode_capture_data, encode_capture_data
from usac_protocol.frame import Frame, MessageType, decode_frame, encode_frame
from usac_runtime.core_store import CaptureStore, StorageConflictError


ROOT = Path(__file__).resolve().parents[3]


def _raw_capture() -> bytes:
    return bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )


def _delivery(raw_frame: bytes | None = None) -> BridgeCaptureDelivery:
    inner = _raw_capture() if raw_frame is None else raw_frame
    return BridgeCaptureDelivery(
        connection_id=11,
        spool_record_id=12,
        source_connection_id=13,
        source_first_stream_offset=100,
        source_last_stream_offset=100 + len(inner) - 1,
        stored_utc_ns=14,
        inner_frame=inner,
    )


def _changed_capture_frame() -> bytes:
    frame = decode_frame(_raw_capture())
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


def test_core_store_commits_raw_frame_samples_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "acquisition.sqlite3"
    store = CaptureStore(path)

    result = store.commit_delivery(_delivery())
    record = CaptureStore(path).get_capture(result.receipt.capture_id)

    assert result.inserted is True
    assert result.receipt.connection_id == 11
    assert result.receipt.spool_record_id == 12
    assert record.wire_frame == _raw_capture()
    assert record.sample_blob == bytes.fromhex("00000100ff0f0008")
    assert record.sample_count == 4
    assert record.pretrigger_count == 2
    assert record.sample_interval_ticks == 120
    assert record.burst_period_ticks == 50
    assert record.interpolated is False


def test_core_store_is_idempotent_for_identical_delivery(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "acquisition.sqlite3")

    first = store.commit_delivery(_delivery())
    second = store.commit_delivery(_delivery())

    assert first.inserted is True
    assert second.inserted is False
    assert second.receipt == first.receipt
    assert store.capture_count() == 1


def test_core_store_rejects_same_identity_with_different_frame(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "acquisition.sqlite3")
    store.commit_delivery(_delivery())

    with pytest.raises(StorageConflictError, match="different frame"):
        store.commit_delivery(_delivery(_changed_capture_frame()))

    assert store.capture_count() == 1


def test_core_store_requires_existing_capture(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "acquisition.sqlite3")

    with pytest.raises(KeyError, match="capture_id"):
        store.get_capture(bytes(16))
