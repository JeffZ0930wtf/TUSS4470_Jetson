from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import threading
import time

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
from usac_runtime.core_store import (
    CaptureResolution,
    CaptureStore,
    SavePolicy,
    StorageConflictError,
)
import usac_runtime.core_store as core_store_module


ROOT = Path(__file__).resolve().parents[3]


class _TrackedConnection:
    """Expose whether store transaction scopes explicitly close SQLite."""

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


def test_core_store_closes_every_transaction_connection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_connect = sqlite3.connect
    observed: list[_TrackedConnection] = []

    def tracked_connect(*args, **kwargs):
        connection = _TrackedConnection(real_connect(*args, **kwargs))
        observed.append(connection)
        return connection

    monkeypatch.setattr(core_store_module.sqlite3, "connect", tracked_connect)
    store = CaptureStore(tmp_path / "connection-lifetime.sqlite3")
    assert store.capture_count() == 0

    assert len(observed) == 2
    assert all(connection.closed for connection in observed)


def _raw_capture() -> bytes:
    return bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )


def _delivery(
    raw_frame: bytes | None = None,
    *,
    spool_record_id: int = 12,
) -> BridgeCaptureDelivery:
    inner = _raw_capture() if raw_frame is None else raw_frame
    return BridgeCaptureDelivery(
        connection_id=11,
        spool_record_id=spool_record_id,
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


def _capture_frame_with_identity(marker: int) -> bytes:
    frame = decode_frame(_raw_capture())
    capture = decode_capture_data(frame.payload)
    changed = replace(
        capture,
        capture_id=bytes([marker]) * 16,
        request_id=bytes([marker + 16]) * 16,
        capture_sequence=marker,
    )
    return encode_frame(
        Frame(
            MessageType.CAPTURE_DATA,
            frame.sequence + marker,
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


def test_save_none_commits_a_replayable_resolution_without_raw_blob(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "acquisition.sqlite3")
    session_id = "21" * 16

    first = store.commit_delivery(
        _delivery(),
        save_policy=SavePolicy.SAVE_NONE,
        session_id=session_id,
    )
    replay = store.commit_delivery(
        _delivery(),
        save_policy=SavePolicy.SAVE_NONE,
        session_id=session_id,
    )

    assert first.inserted is True
    assert first.resolution is CaptureResolution.DISCARDED_BY_POLICY
    assert replay.inserted is False
    assert replay.resolution is CaptureResolution.DISCARDED_BY_POLICY
    assert store.capture_count() == 0
    assert store.latest_capture_count(session_id) == 0
    assert store.resolution_count() == 1


def test_bridge_replay_uses_registered_policy_and_refuses_an_unknown_context(
    tmp_path: Path,
) -> None:
    delivery = _delivery()
    capture = decode_capture_data(decode_frame(delivery.inner_frame).payload)
    store = CaptureStore(tmp_path / "replay-policy.sqlite3")
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id="25" * 16,
        save_policy=SavePolicy.SAVE_NONE,
    )

    resolved = store.commit_replayed_delivery(delivery)

    assert resolved.resolution is CaptureResolution.DISCARDED_BY_POLICY
    assert store.capture_count() == 0
    unknown = CaptureStore(tmp_path / "unknown-replay-policy.sqlite3")
    with pytest.raises(RuntimeError, match="no registered save-policy context"):
        unknown.commit_replayed_delivery(delivery)


def test_save_last_replaces_one_rolling_row_then_atomically_archives_latest(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "acquisition.sqlite3")
    session_id = "31" * 16
    first_frame = _capture_frame_with_identity(1)
    last_frame = _capture_frame_with_identity(2)

    first = store.commit_delivery(
        _delivery(first_frame, spool_record_id=101),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_id,
    )
    last = store.commit_delivery(
        _delivery(last_frame, spool_record_id=102),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_id,
    )

    assert first.resolution is CaptureResolution.ROLLING_LATEST
    assert last.resolution is CaptureResolution.ROLLING_LATEST
    assert store.capture_count() == 0
    assert store.latest_capture_count(session_id) == 1

    archived_id = store.finalize_latest_capture(session_id)

    assert archived_id == decode_capture_data(decode_frame(last_frame).payload).capture_id
    assert store.latest_capture_count(session_id) == 0
    assert store.capture_count() == 1
    assert store.get_capture(archived_id).wire_frame == last_frame
    with pytest.raises(KeyError):
        store.get_capture(decode_capture_data(decode_frame(first_frame).payload).capture_id)


def test_restart_marks_open_session_interrupted_and_freezes_save_last(tmp_path: Path) -> None:
    path = tmp_path / "acquisition.sqlite3"
    store = CaptureStore(path)
    session_id = "41" * 16
    last_frame = _capture_frame_with_identity(2)
    store.commit_delivery(
        _delivery(_capture_frame_with_identity(1), spool_record_id=201),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_id,
    )
    store.commit_delivery(
        _delivery(last_frame, spool_record_id=202),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_id,
    )
    store.save_session_summary(
        {
            "session_id": session_id,
            "kind": "PERIODIC",
            "state": "RUNNING",
            "save_policy": "SAVE_LAST",
            "requested_count": 10,
            # Simulate a crash after the second frame decision committed but
            # before the in-memory worker updated its session summary.
            "acquired_count": 1,
            "saved_count": 0,
            "discarded_by_policy_count": 1,
            "last_capture_id": decode_capture_data(decode_frame(last_frame).payload).capture_id.hex(),
            "last_saved_capture_id": None,
            "terminal_reason": None,
        }
    )

    reopened = CaptureStore(path)
    interrupted = reopened.reconcile_interrupted_sessions()
    summary = reopened.get_session_summary(session_id)

    assert interrupted == 1
    assert summary["state"] == "INTERRUPTED"
    assert summary["terminal_reason"] == "CORE_RESTART"
    assert summary["acquired_count"] == 2
    assert summary["saved_count"] == 1
    assert summary["discarded_by_policy_count"] == 1
    assert summary["last_saved_capture_id"] == summary["last_capture_id"]
    assert reopened.capture_count() == 1
    assert reopened.latest_capture_count(session_id) == 0


def test_late_replay_updates_interrupted_save_last_without_orphan_rolling_blob(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "late-replay.sqlite3")
    session_id = "45" * 16
    first_frame = _capture_frame_with_identity(1)
    last_frame = _capture_frame_with_identity(2)
    first_capture = decode_capture_data(decode_frame(first_frame).payload)
    last_capture = decode_capture_data(decode_frame(last_frame).payload)
    store.register_delivery_policy(
        device_id=first_capture.device_id,
        boot_id=first_capture.boot_id,
        session_id=session_id,
        save_policy=SavePolicy.SAVE_LAST,
    )
    store.commit_delivery(
        _delivery(first_frame, spool_record_id=301),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_id,
    )
    store.save_session_summary(
        {
            "session_id": session_id,
            "kind": "PERIODIC",
            "state": "RUNNING",
            "save_policy": "SAVE_LAST",
            "requested_count": 10,
            "capture_count": 1,
            "acquired_count": 1,
            "saved_count": 0,
            "discarded_by_policy_count": 0,
            "last_capture_id": first_capture.capture_id.hex(),
            "last_saved_capture_id": None,
            "terminal_reason": None,
        }
    )
    assert store.reconcile_interrupted_sessions() == 1

    replayed = store.commit_replayed_delivery(
        _delivery(last_frame, spool_record_id=302)
    )
    summary = store.get_session_summary(session_id)

    assert replayed.resolution is CaptureResolution.RAW_ARCHIVED
    assert summary["state"] == "INTERRUPTED"
    assert summary["acquired_count"] == 2
    assert summary["saved_count"] == 1
    assert summary["discarded_by_policy_count"] == 1
    assert summary["last_capture_id"] == last_capture.capture_id.hex()
    assert summary["last_saved_capture_id"] == last_capture.capture_id.hex()
    assert store.capture_count() == 1
    assert store.latest_capture_count(session_id) == 0
    with pytest.raises(KeyError):
        store.get_capture(first_capture.capture_id)
    assert store.get_capture(last_capture.capture_id).wire_frame == last_frame


@pytest.mark.parametrize(
    ("policy", "resolution", "saved_count"),
    [
        (SavePolicy.SAVE_NONE, CaptureResolution.DISCARDED_BY_POLICY, 0),
        (SavePolicy.SAVE_ALL, CaptureResolution.RAW_ARCHIVED, 1),
    ],
)
def test_late_replay_updates_other_terminal_save_policies(
    tmp_path: Path,
    policy: SavePolicy,
    resolution: CaptureResolution,
    saved_count: int,
) -> None:
    store = CaptureStore(tmp_path / f"late-{policy.value}.sqlite3")
    session_id = ("46" if policy is SavePolicy.SAVE_NONE else "47") * 16
    delivery = _delivery()
    capture = decode_capture_data(decode_frame(delivery.inner_frame).payload)
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id=session_id,
        save_policy=policy,
    )
    store.save_session_summary(
        {
            "session_id": session_id,
            "kind": "PERIODIC",
            "state": "RUNNING",
            "save_policy": policy.value,
            "requested_count": 1,
            "capture_count": 0,
            "acquired_count": 0,
            "saved_count": 0,
            "discarded_by_policy_count": 0,
            "last_capture_id": None,
            "last_saved_capture_id": None,
            "terminal_reason": None,
        }
    )
    assert store.reconcile_interrupted_sessions() == 1

    replayed = store.commit_replayed_delivery(delivery)
    summary = store.get_session_summary(session_id)

    assert replayed.resolution is resolution
    assert summary["state"] == "INTERRUPTED"
    assert summary["acquired_count"] == 1
    assert summary["saved_count"] == saved_count
    assert summary["discarded_by_policy_count"] == 1 - saved_count
    assert store.latest_capture_count(session_id) == 0


def test_replay_state_selection_cannot_race_session_finalization(tmp_path: Path) -> None:
    entered_commit = threading.Event()
    release_commit = threading.Event()

    class PausingReplayStore(CaptureStore):
        def commit_delivery(self, delivery, **kwargs):
            if kwargs.get("_connection") is not None:
                entered_commit.set()
                assert release_commit.wait(1.0)
            return super().commit_delivery(delivery, **kwargs)

    path = tmp_path / "replay-finalize-race.sqlite3"
    store = PausingReplayStore(path)
    finalizer = CaptureStore(path)
    session_id = "48" * 16
    delivery = _delivery()
    capture = decode_capture_data(decode_frame(delivery.inner_frame).payload)
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id=session_id,
        save_policy=SavePolicy.SAVE_LAST,
    )
    running = {
        "session_id": session_id,
        "kind": "PERIODIC",
        "state": "RUNNING",
        "save_policy": "SAVE_LAST",
        "capture_count": 0,
        "acquired_count": 0,
        "saved_count": 0,
        "discarded_by_policy_count": 0,
        "last_capture_id": None,
        "last_saved_capture_id": None,
        "terminal_reason": None,
    }
    store.save_session_summary(running)
    replay_errors: list[BaseException] = []

    def replay() -> None:
        try:
            store.commit_replayed_delivery(delivery)
        except BaseException as error:
            replay_errors.append(error)

    def finalize() -> None:
        summary = dict(running)
        summary.update(state="INTERRUPTED", terminal_reason="CORE_RESTART")
        finalizer.finalize_session_summary(summary)

    replay_thread = threading.Thread(target=replay)
    replay_thread.start()
    assert entered_commit.wait(1.0)
    finalize_thread = threading.Thread(target=finalize)
    finalize_thread.start()
    time.sleep(0.05)
    assert finalize_thread.is_alive()
    release_commit.set()
    replay_thread.join(1.0)
    finalize_thread.join(1.0)

    assert replay_errors == []
    assert not replay_thread.is_alive()
    assert not finalize_thread.is_alive()
    summary = finalizer.get_session_summary(session_id)
    assert summary["state"] == "INTERRUPTED"
    assert summary["acquired_count"] == 1
    assert summary["saved_count"] == 1
    assert finalizer.latest_capture_count(session_id) == 0
