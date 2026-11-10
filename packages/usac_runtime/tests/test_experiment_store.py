from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from usac_runtime.core_store import (
    CaptureResolution,
    CaptureStore,
    DeletionConflictError,
    SavePolicy,
    StorageConflictError,
)
from test_core_store import _capture_frame_with_identity, _delivery
from usac_protocol.capture_data import decode_capture_data
from usac_protocol.capture_data import encode_capture_data
from usac_protocol.frame import Frame, decode_frame, encode_frame


def _capture_id(frame: bytes) -> bytes:
    return decode_capture_data(decode_frame(frame).payload).capture_id


def _delete_grouping_schema(path: Path) -> None:
    """Turn a current fixture into a pre-grouping database for migration tests."""

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        for index in (
            "captures_group_row",
            "session_latest_group",
            "delivery_policy_group",
        ):
            if index in indexes:
                connection.execute(f'DROP INDEX "{index}"')
        if "experiment_groups" in tables:
            connection.execute("DROP TABLE experiment_groups")
        if "experiments" in tables:
            connection.execute("DROP TABLE experiments")
        for table in (
            "captures",
            "session_latest_captures",
            "delivery_policy_contexts",
        ):
            if table not in tables:
                continue
            columns = {
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if "group_id" in columns:
                connection.execute(f'ALTER TABLE "{table}" DROP COLUMN group_id')


def test_experiment_and_group_crud_exposes_current_names_and_archive_count(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "experiments.sqlite3")

    experiment = store.create_experiment(name="  Bench A  ", notes="ultrasonic")
    group = store.create_group(
        experiment["experiment_id"],
        name="  Cell 01  ",
        cell_id="fixture-7",
        notes="before rename",
    )
    frame = _capture_frame_with_identity(1)
    result = store.commit_delivery(_delivery(frame), group_id=group["group_id"])

    assert experiment["name"] == "Bench A"
    assert group["name"] == "Cell 01"
    assert store.get_experiment(experiment["experiment_id"]) == experiment
    assert store.list_experiments() == [experiment]
    assert store.get_group(group["group_id"])["archived_count"] == 1
    assert store.list_groups(experiment["experiment_id"])[0]["group_id"] == group[
        "group_id"
    ]
    assert store.grouping_metadata(group["group_id"]) == {
        "group_id": group["group_id"],
        "experiment_id": experiment["experiment_id"],
        "group_name": "Cell 01",
        "experiment_name": "Bench A",
        "cell_id": "fixture-7",
    }
    assert store.get_capture(result.receipt.capture_id).group_name == "Cell 01"

    renamed_experiment = store.update_experiment(
        experiment["experiment_id"], name="  Bench B  "
    )
    renamed_group = store.update_group(group["group_id"], name="  Cell 02  ")
    assert renamed_experiment["name"] == "Bench B"
    assert renamed_group["name"] == "Cell 02"
    assert store.grouping_metadata(group["group_id"])["experiment_name"] == "Bench B"
    assert store.grouping_metadata(group["group_id"])["group_name"] == "Cell 02"


def test_entity_validation_and_duplicate_names_are_supported(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "validation.sqlite3")
    first = store.create_experiment(name="same")
    second = store.create_experiment(name="same")
    group = store.create_group(first["experiment_id"], name="same")
    assert first["experiment_id"] != second["experiment_id"]
    assert group["cell_id"] == ""
    assert store.grouping_metadata(group["group_id"])["cell_id"] == ""

    for name in ("", "x" * 121):
        with pytest.raises(ValueError):
            store.create_experiment(name=name)
    with pytest.raises(ValueError):
        store.create_experiment(name="x", notes="n" * 2001)
    with pytest.raises(ValueError):
        store.create_group(first["experiment_id"], name="g", cell_id="c" * 121)
    with pytest.raises(ValueError):
        store.create_group(first["experiment_id"], name="g", notes="n" * 2001)
    with pytest.raises(ValueError):
        store.get_experiment("A" * 32)
    with pytest.raises(ValueError):
        store.get_group("not-an-id")
    with pytest.raises(ValueError):
        store.update_experiment(first["experiment_id"], created_utc_ns=0)
    with pytest.raises(ValueError):
        store.update_group(group["group_id"], unknown="value")
    with pytest.raises(KeyError):
        store.get_experiment("f" * 32)


def test_assign_capture_group_is_atomic_deduplicated_and_reversible(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "assignment.sqlite3")
    experiment = store.create_experiment(name="run")
    group = store.create_group(experiment["experiment_id"], name="group")
    first = _capture_id(_capture_frame_with_identity(1))
    second = _capture_id(_capture_frame_with_identity(2))
    store.commit_delivery(_delivery(_capture_frame_with_identity(1)))
    store.commit_delivery(_delivery(_capture_frame_with_identity(2)))

    assert store.assign_capture_group([first, first], group["group_id"]) == 1
    assert store.assign_capture_group([first], group["group_id"]) == 1
    assert store.get_capture(first).group_id == group["group_id"]
    with pytest.raises(KeyError):
        store.assign_capture_group([second, b"missing-capture!"], group["group_id"])
    assert store.get_capture(second).group_id is None
    with pytest.raises(KeyError):
        store.assign_capture_group([second], "e" * 32)
    assert store.get_capture(second).group_id is None
    assert store.assign_capture_group([first], None) == 1
    assert store.get_capture(first).group_id is None
    assert store.grouping_metadata(None) == {
        "group_id": None,
        "experiment_id": None,
        "group_name": None,
        "experiment_name": None,
        "cell_id": None,
    }
    with pytest.raises(ValueError):
        store.assign_capture_group([], group["group_id"])
    with pytest.raises(ValueError):
        store.assign_capture_group([b"short"], group["group_id"])
    with pytest.raises(ValueError):
        store.assign_capture_group(
            [value.to_bytes(16, "big") for value in range(501)], group["group_id"]
        )


def test_delete_experiment_cascades_group_archives_but_preserves_unrelated_data(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "delete-experiment.sqlite3")
    experiment = store.create_experiment(name="remove me")
    first_group = store.create_group(experiment["experiment_id"], name="first")
    second_group = store.create_group(experiment["experiment_id"], name="second")
    other_experiment = store.create_experiment(name="keep me")
    other_group = store.create_group(other_experiment["experiment_id"], name="keep")
    frames = [_capture_frame_with_identity(i) for i in (1, 2, 3, 4)]
    ids = [_capture_id(frame) for frame in frames]
    store.commit_delivery(_delivery(frames[0]), group_id=first_group["group_id"])
    store.commit_delivery(_delivery(frames[1]), group_id=second_group["group_id"])
    store.commit_delivery(_delivery(frames[2]), group_id=other_group["group_id"])
    store.commit_delivery(_delivery(frames[3]))

    deleted = store.delete_experiment(experiment["experiment_id"])

    assert deleted == {
        "deleted": True,
        "captures_deleted": 2,
        "groups_deleted": 2,
    }
    assert store.capture_count() == 2
    assert store.get_capture(ids[2]).group_id == other_group["group_id"]
    assert store.get_capture(ids[3]).group_id is None
    with pytest.raises(KeyError):
        store.get_experiment(experiment["experiment_id"])
    with pytest.raises(KeyError):
        store.get_group(first_group["group_id"])
    with pytest.raises(KeyError):
        store.get_capture(ids[0])


def test_delete_group_and_capture_remove_events_and_absorb_permanent_replay(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "delete-capture.sqlite3")
    experiment = store.create_experiment(name="remove")
    group = store.create_group(experiment["experiment_id"], name="target")
    frame = _capture_frame_with_identity(1)
    capture_id = _capture_id(frame)
    store.commit_delivery(_delivery(frame), group_id=group["group_id"])
    with sqlite3.connect(store.path) as connection:
        row_id = connection.execute(
            "SELECT row_id FROM captures WHERE capture_id=?", (capture_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO capture_events VALUES (?, 99, 0, 0, 0, 0, 0, 0, 0, 0)",
            (row_id,),
        )

    deleted = store.delete_capture(capture_id)

    assert deleted == {
        "deleted": True,
        "captures_deleted": 1,
        "groups_deleted": 0,
    }
    assert store.get_capture_events(capture_id) == ()
    assert store.get_group(group["group_id"])["archived_count"] == 0
    with sqlite3.connect(store.path) as connection:
        for index in range(4097):
            connection.execute(
                "INSERT INTO capture_resolution_tombstones (device_id, boot_id, capture_id, "
                "inner_frame_crc32, inner_frame_sha256, resolution, session_id, resolved_utc_ns) "
                "VALUES (?, ?, ?, 0, zeroblob(32), 'DISCARDED_BY_POLICY', '', ?)",
                (
                    index.to_bytes(16, "big"),
                    (index + 1).to_bytes(16, "big"),
                    (index + 2).to_bytes(16, "big"),
                    index + 2,
                ),
            )
        connection.commit()
    with store._connect() as connection:
        store._prune_resolutions(connection)

    replay = store.commit_delivery(_delivery(frame))

    assert replay.inserted is False
    assert store.capture_count() == 0
    with pytest.raises(StorageConflictError, match="different frame"):
        store.commit_delivery(_delivery(_changed_capture_frame_for_identity(frame)))


def _changed_capture_frame_for_identity(frame: bytes) -> bytes:
    from dataclasses import replace

    from usac_protocol.capture_data import encode_capture_data
    from usac_protocol.frame import Frame, encode_frame

    decoded = decode_frame(frame)
    capture = decode_capture_data(decoded.payload)
    changed = replace(capture, samples=(capture.samples[0] ^ 1, *capture.samples[1:]))
    return encode_frame(Frame(decoded.message_type, decoded.sequence, encode_capture_data(changed), decoded.flags))


def test_delete_group_invalidates_session_grouping_without_removing_history(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "delete-group-session.sqlite3")
    experiment = store.create_experiment(name="history")
    group = store.create_group(experiment["experiment_id"], name="old group")
    session_id = "ab" * 16
    store.save_session_summary(
        {
            "session_id": session_id,
            "kind": "PERIODIC",
            "state": "COMPLETED",
            "save_policy": "SAVE_ALL",
            "grouping_metadata": {
                "group_id": group["group_id"],
                "experiment_id": experiment["experiment_id"],
                "group_name": group["name"],
                "experiment_name": experiment["name"],
                "cell_id": group["cell_id"],
            },
            "acquired_count": 3,
            "saved_count": 3,
        }
    )

    deleted = store.delete_group(group["group_id"])
    history = store.get_session_summary(session_id)

    assert deleted == {
        "deleted": True,
        "captures_deleted": 0,
        "groups_deleted": 1,
    }
    assert history["grouping_metadata"]["group_id"] is None
    assert history["acquired_count"] == 3
    assert history["saved_count"] == 3


def test_delete_group_suppresses_pending_replay_without_rewriting_history(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "delete-pending-replay.sqlite3")
    experiment = store.create_experiment(name="pending")
    group = store.create_group(experiment["experiment_id"], name="deleted")
    frame = _capture_frame_with_identity(1)
    capture = decode_capture_data(decode_frame(frame).payload)
    session_id = "cd" * 16
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id=session_id,
        save_policy=SavePolicy.SAVE_LAST,
        group_id=group["group_id"],
    )
    store.save_session_summary(
        {
            "session_id": session_id,
            "kind": "PERIODIC",
            "state": "COMPLETED",
            "save_policy": SavePolicy.SAVE_LAST.value,
            "grouping_metadata": store.grouping_metadata(group["group_id"]),
            "acquired_count": 4,
            "saved_count": 1,
            "discarded_by_policy_count": 3,
        }
    )
    store.delete_group(group["group_id"])

    replay = store.commit_replayed_delivery(_delivery(frame))
    history = store.get_session_summary(session_id)
    with store._connect() as connection:
        context = connection.execute(
            "SELECT session_id, save_policy, group_id, suppress_archive "
            "FROM delivery_policy_contexts"
        ).fetchone()

    assert replay.inserted is True
    assert replay.resolution is CaptureResolution.DISCARDED_BY_POLICY
    assert store.capture_count() == 0
    assert store.resolution_count() == 0
    assert history["acquired_count"] == 4
    assert history["saved_count"] == 1
    assert context == (session_id, SavePolicy.SAVE_LAST.value, None, 1)

    # A new task may replace the boot context, but the frame removed by the
    # group deletion remains absorbed by its permanent identity marker.
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id="ef" * 16,
        save_policy=SavePolicy.SAVE_ALL,
    )
    retry = store.commit_replayed_delivery(_delivery(frame))
    assert retry.inserted is False
    with pytest.raises(StorageConflictError, match="different frame"):
        store.commit_replayed_delivery(
            _delivery(_changed_capture_frame_for_identity(frame))
        )


def test_delete_group_rejects_current_assignment_from_an_active_run(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "delete-active-run.sqlite3")
    experiment = store.create_experiment(name="active")
    bound_group = store.create_group(experiment["experiment_id"], name="bound")
    assigned_group = store.create_group(experiment["experiment_id"], name="assigned")
    frame = _capture_frame_with_identity(1)
    session_id = "12" * 16
    store.commit_delivery(
        _delivery(frame),
        save_policy=SavePolicy.SAVE_ALL,
        session_id=session_id,
        group_id=assigned_group["group_id"],
    )
    capture_id = _capture_id(frame)
    store.register_delivery_policy(
        device_id=decode_capture_data(decode_frame(frame).payload).device_id,
        boot_id=decode_capture_data(decode_frame(frame).payload).boot_id,
        session_id=session_id,
        save_policy=SavePolicy.SAVE_ALL,
        group_id=bound_group["group_id"],
    )
    store.save_session_summary(
        {
            "session_id": session_id,
            "kind": "SWEEP",
            "state": "RUNNING",
            "save_policy": SavePolicy.SAVE_ALL.value,
            "grouping_metadata": store.grouping_metadata(bound_group["group_id"]),
        }
    )

    with pytest.raises(DeletionConflictError, match="active run"):
        store.delete_group(assigned_group["group_id"])
    assert store.get_capture(capture_id).group_id == assigned_group["group_id"]


def test_delete_capture_rejects_non_unique_cross_device_identity(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "delete-ambiguous-capture.sqlite3")
    first_frame = _capture_frame_with_identity(1)
    first = decode_frame(first_frame)
    first_capture = decode_capture_data(first.payload)
    second_capture = replace(first_capture, device_id=b"\x22" * 16)
    second_frame = encode_frame(
        Frame(
            first.message_type,
            first.sequence,
            encode_capture_data(second_capture),
            first.flags,
        )
    )
    store.commit_delivery(_delivery(first_frame))
    store.commit_delivery(_delivery(second_frame))

    with pytest.raises(KeyError, match="not found uniquely"):
        store.delete_capture(first_capture.capture_id)
    assert store.capture_count() == 2


def test_group_filters_keep_cursor_order_and_reject_inconsistent_filters(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "filters.sqlite3")
    exp_a = store.create_experiment(name="A")
    exp_b = store.create_experiment(name="B")
    group_a = store.create_group(exp_a["experiment_id"], name="A1")
    group_b = store.create_group(exp_b["experiment_id"], name="B1")
    ids = [_capture_id(_capture_frame_with_identity(i)) for i in (1, 2, 3, 4)]
    store.commit_delivery(_delivery(_capture_frame_with_identity(1)), group_id=group_a["group_id"])
    store.commit_delivery(_delivery(_capture_frame_with_identity(2)), group_id=group_b["group_id"])
    store.commit_delivery(_delivery(_capture_frame_with_identity(3)), group_id=group_a["group_id"])
    store.commit_delivery(_delivery(_capture_frame_with_identity(4)))

    first_page, cursor = store.list_captures(experiment_id=exp_a["experiment_id"], limit=1)
    second_page, next_cursor = store.list_captures(
        experiment_id=exp_a["experiment_id"], after_row_id=cursor, limit=1
    )
    assert [item.capture_id for item in first_page + second_page] == [
        ids[0].hex(),
        ids[2].hex(),
    ]
    assert cursor == first_page[0].row_id
    assert next_cursor is None
    assert store.list_captures(group_id=group_b["group_id"])[0][0].capture_id == ids[1].hex()
    ungrouped, _ = store.list_captures(ungrouped=True)
    assert [item.capture_id for item in ungrouped] == [ids[3].hex()]
    assert first_page[0].group_name == "A1"
    assert first_page[0].experiment_name == "A"
    with pytest.raises(KeyError):
        store.list_captures(experiment_id="f" * 32)
    with pytest.raises(KeyError):
        store.list_captures(group_id="e" * 32)
    with pytest.raises(ValueError):
        store.list_captures(experiment_id=exp_a["experiment_id"], group_id=group_b["group_id"])
    with pytest.raises(ValueError):
        store.list_captures(ungrouped=True, group_id=group_a["group_id"])


def test_group_export_snapshot_yields_grouped_records_and_events(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "snapshot.sqlite3")
    experiment = store.create_experiment(name="export")
    group = store.create_group(experiment["experiment_id"], name="members")
    frame = _capture_frame_with_identity(1)
    capture_id = _capture_id(frame)
    store.commit_delivery(_delivery(frame), group_id=group["group_id"])
    later_frame = _capture_frame_with_identity(2)

    with store.group_export_snapshot(group["group_id"]) as (
        group_metadata,
        experiment_metadata,
        records,
    ):
        # A later rename and assignment must not leak into this pinned export.
        store.update_group(group["group_id"], name="renamed")
        store.commit_delivery(_delivery(later_frame), group_id=group["group_id"])
        exported = list(records)

    assert group_metadata["group_id"] == group["group_id"]
    assert group_metadata["name"] == "members"
    assert experiment_metadata["experiment_id"] == experiment["experiment_id"]
    assert [record.capture_id for record in exported] == [capture_id]
    assert exported[0].events == store.get_capture_events(capture_id)
    assert exported[0].group_id == group["group_id"]
    assert exported[0].group_name == "members"


def test_old_schema_reopen_adds_grouping_columns_without_changing_capture_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    store = CaptureStore(path)
    frame = _capture_frame_with_identity(1)
    capture_id = _capture_id(frame)
    store.commit_delivery(_delivery(frame))
    rolling_frame = _capture_frame_with_identity(2)
    rolling_capture = decode_capture_data(decode_frame(rolling_frame).payload)
    rolling_session = "d4" * 16
    store.register_delivery_policy(
        device_id=rolling_capture.device_id,
        boot_id=rolling_capture.boot_id,
        session_id=rolling_session,
        save_policy=SavePolicy.SAVE_LAST,
    )
    store.commit_delivery(
        _delivery(rolling_frame),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=rolling_session,
    )

    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "SELECT wire_frame_blob, sample_blob FROM captures WHERE capture_id=?",
            (capture_id,),
        ).fetchone()
    _delete_grouping_schema(path)

    migrated = CaptureStore(path)
    reopened = CaptureStore(path)
    record = reopened.get_capture(capture_id)
    with sqlite3.connect(path) as connection:
        after = connection.execute(
            "SELECT wire_frame_blob, sample_blob FROM captures WHERE capture_id=?",
            (capture_id,),
        ).fetchone()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(captures)")
        }
        grouping = connection.execute(
            "SELECT group_id FROM captures WHERE capture_id=?", (capture_id,)
        ).fetchone()
        migrated_columns = {
            table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            for table in (
                "captures",
                "session_latest_captures",
                "delivery_policy_contexts",
            )
        }
        rolling_group = connection.execute(
            "SELECT group_id FROM session_latest_captures WHERE session_id=?",
            (rolling_session,),
        ).fetchone()
        context_group = connection.execute(
            "SELECT group_id FROM delivery_policy_contexts WHERE session_id=?",
            (rolling_session,),
        ).fetchone()

    assert before == after
    assert "group_id" in columns
    assert all("group_id" in table_columns for table_columns in migrated_columns.values())
    assert grouping == (None,)
    assert rolling_group == (None,)
    assert context_group == (None,)
    assert record.wire_frame == frame
    assert migrated.capture_count() == 1


def test_save_last_keeps_frozen_group_after_context_overwrite_and_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rolling.sqlite3"
    store = CaptureStore(path)
    exp_a = store.create_experiment(name="old task")
    exp_b = store.create_experiment(name="new task")
    group_a = store.create_group(exp_a["experiment_id"], name="old group")
    group_b = store.create_group(exp_b["experiment_id"], name="new group")
    frame = _capture_frame_with_identity(1)
    capture = decode_capture_data(decode_frame(frame).payload)
    session_a = "a1" * 16
    session_b = "b2" * 16
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id=session_a,
        save_policy=SavePolicy.SAVE_LAST,
        group_id=group_a["group_id"],
    )
    result = store.commit_delivery(
        _delivery(frame),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_a,
        group_id=group_a["group_id"],
    )
    store.save_session_summary(
        {
            "session_id": session_a,
            "state": "RUNNING",
            "save_policy": SavePolicy.SAVE_LAST.value,
        }
    )
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id=session_b,
        save_policy=SavePolicy.SAVE_LAST,
        group_id=group_b["group_id"],
    )

    reopened = CaptureStore(path)
    assert reopened.reconcile_interrupted_sessions() == 1
    archived = reopened.get_capture(result.receipt.capture_id)
    assert archived.group_id == group_a["group_id"]
    assert archived.experiment_id == exp_a["experiment_id"]


def test_save_last_group_is_preserved_by_explicit_finalize(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "finalize.sqlite3")
    experiment = store.create_experiment(name="task")
    group = store.create_group(experiment["experiment_id"], name="series")
    session_id = "e5" * 16
    frame = _capture_frame_with_identity(1)
    capture_id = _capture_id(frame)
    store.commit_delivery(
        _delivery(frame),
        save_policy=SavePolicy.SAVE_LAST,
        session_id=session_id,
        group_id=group["group_id"],
    )

    assert store.finalize_latest_capture(session_id) == capture_id
    assert store.get_capture(capture_id).group_id == group["group_id"]


def test_terminal_replay_uses_registered_group_and_manual_assignment_survives_replay(
    tmp_path: Path,
) -> None:
    store = CaptureStore(tmp_path / "terminal-replay.sqlite3")
    experiment = store.create_experiment(name="task")
    group_a = store.create_group(experiment["experiment_id"], name="registered")
    group_b = store.create_group(experiment["experiment_id"], name="manual")
    session_id = "c3" * 16
    delivery = _delivery()
    capture = decode_capture_data(decode_frame(delivery.inner_frame).payload)
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id=session_id,
        save_policy=SavePolicy.SAVE_LAST,
        group_id=group_a["group_id"],
    )
    store.save_session_summary(
        {"session_id": session_id, "state": "COMPLETED", "save_policy": "SAVE_LAST"}
    )

    replayed = store.commit_replayed_delivery(delivery)
    assert replayed.resolution is CaptureResolution.RAW_ARCHIVED
    assert store.get_capture(capture.capture_id).group_id == group_a["group_id"]
    assert store.assign_capture_group([capture.capture_id], group_b["group_id"]) == 1

    repeated = store.commit_replayed_delivery(delivery)
    assert repeated.inserted is False
    assert repeated.resolution is CaptureResolution.RAW_ARCHIVED
    assert store.get_capture(capture.capture_id).group_id == group_b["group_id"]
