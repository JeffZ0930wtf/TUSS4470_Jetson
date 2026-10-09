from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from usac_runtime.core_store import CaptureResolution, CaptureStore, SavePolicy
from test_core_store import _capture_frame_with_identity, _delivery
from usac_protocol.capture_data import decode_capture_data
from usac_protocol.frame import decode_frame


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
