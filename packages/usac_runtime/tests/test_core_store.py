from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from usac_protocol.bridge_messages import BridgeCaptureDelivery
from usac_protocol.capture_data import decode_capture_data, encode_capture_data
from usac_protocol.frame import (
    Frame,
    MessageType,
    crc32_iso_hdlc,
    decode_frame,
    encode_frame,
)
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


def _wrong_type_capture_frame() -> bytes:
    frame = decode_frame(_raw_capture())
    return encode_frame(
        Frame(MessageType.HELLO, frame.sequence, frame.payload, frame.flags)
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


def test_core_store_rejects_non_capture_inner_frame(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "acquisition.sqlite3")

    with pytest.raises(ValueError, match="CAPTURE_DATA"):
        store.commit_delivery(_delivery(_wrong_type_capture_frame()))

    assert store.capture_count() == 0


def test_m5_context_events_and_quality_are_committed_with_capture(tmp_path: Path) -> None:
    path = tmp_path / "acquisition.sqlite3"
    store = CaptureStore(path)
    capture = decode_capture_data(decode_frame(_raw_capture()).payload)
    store.save_configuration_context(
        profile_sha256=capture.profile_sha256,
        device_config_crc32=capture.device_config_crc32,
        request_id=capture.request_id,
        requested={"requested_sample_rate_hz": 200_000},
        encoded={"sample_interval_ticks": 120, "register_pairs": [[16, 46]]},
        readback={"sample_interval_ticks": 120, "register_pairs": [[16, 46]]},
        actual={"sample_rate_hz": 200_000.0},
        run_plan={"loops": 1, "trigger_source": "SOFTWARE"},
    )

    result = store.commit_delivery(_delivery())
    record = CaptureStore(path).get_capture(result.receipt.capture_id)
    events = CaptureStore(path).get_capture_events(result.receipt.capture_id)

    assert record.requested_config == {"requested_sample_rate_hz": 200_000}
    assert record.encoded_config["sample_interval_ticks"] == 120
    assert record.readback_config["sample_interval_ticks"] == 120
    assert record.actual_config == {"sample_rate_hz": 200_000.0}
    assert record.run_plan == {"loops": 1, "trigger_source": "SOFTWARE"}
    assert record.adc_clipping is True
    assert record.tuss_dev_stat == capture.tuss_dev_stat
    assert record.transport_crc32 == crc32_iso_hdlc(_raw_capture())
    assert len(events) == 1
    assert events[0].channel == capture.events[0].channel
    assert events[0].sample_index == capture.events[0].sample_index
    assert events[0].subsample_tick == capture.events[0].subsample_tick


def test_existing_m4_database_is_migrated_without_losing_capture(tmp_path: Path) -> None:
    path = tmp_path / "acquisition.sqlite3"
    store = CaptureStore(path)
    result = store.commit_delivery(_delivery())

    reopened = CaptureStore(path)
    record = reopened.get_capture(result.receipt.capture_id)

    assert reopened.capture_count() == 1
    assert record.requested_config == {}
    assert record.run_plan == {}
