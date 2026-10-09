from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from usac_protocol.bridge_messages import BridgeCaptureDelivery
from usac_runtime.core_store import CaptureStore
from usac_runtime.export_cli import main


ROOT = Path(__file__).resolve().parents[3]


def _stored_capture(database: Path) -> bytes:
    raw = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
    result = CaptureStore(database).commit_delivery(
        BridgeCaptureDelivery(
            connection_id=1,
            spool_record_id=2,
            source_connection_id=3,
            source_first_stream_offset=0,
            source_last_stream_offset=len(raw) - 1,
            stored_utc_ns=4,
            inner_frame=raw,
        )
    )
    return result.receipt.capture_id


def test_show_prints_stored_capture_metadata(
    tmp_path: Path, capsys,
) -> None:
    database = tmp_path / "acquisition.sqlite3"
    capture_id = _stored_capture(database)

    exit_code = main(
        ["show", "--sqlite", str(database), "--capture-id", capture_id.hex()]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["capture_id"] == capture_id.hex()
    assert output["sample_count"] == 4
    assert output["interpolated"] is False


def test_download_writes_exact_database_blobs(
    tmp_path: Path, capsys,
) -> None:
    database = tmp_path / "acquisition.sqlite3"
    capture_id = _stored_capture(database)
    output_directory = tmp_path / "download"

    exit_code = main(
        [
            "download",
            "--sqlite",
            str(database),
            "--capture-id",
            capture_id.hex(),
            "--output-dir",
            str(output_directory),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    prefix = capture_id.hex()
    record = CaptureStore(database).get_capture(capture_id)

    assert exit_code == 0
    assert (output_directory / f"{prefix}.usac").read_bytes() == record.wire_frame
    assert (output_directory / f"{prefix}.u16le").read_bytes() == record.sample_blob
    assert json.loads((output_directory / f"{prefix}.json").read_text("utf-8"))[
        "capture_id"
    ] == prefix
    assert output["raw_frame"].endswith(f"{prefix}.usac")


@pytest.mark.parametrize("alias_kind", ["same-path", "resolved-path", "hard-link"])
def test_group_export_rejects_sqlite_file_as_output_without_changing_database(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    database = tmp_path / "acquisition.sqlite3"
    store = CaptureStore(database)
    experiment = store.create_experiment(name="preserve database")
    group = store.create_group(experiment["experiment_id"], name="preserve group")
    capture_id = _stored_capture(database)
    store.assign_capture_group([capture_id], group["group_id"])

    if alias_kind == "same-path":
        output = database
    elif alias_kind == "resolved-path":
        alias_directory = tmp_path / "alias-directory"
        alias_directory.mkdir()
        output = alias_directory / ".." / database.name
    else:
        output = tmp_path / "hard-link.sqlite3"
        os.link(database, output)

    database_before = database.read_bytes()
    with pytest.raises(SystemExit, match="output must not be the SQLite database"):
        main(
            [
                "group",
                "--sqlite",
                str(database),
                "--group-id",
                group["group_id"],
                "--output",
                str(output),
            ]
        )

    assert database.read_bytes() == database_before
    assert store.get_capture(capture_id).group_id == group["group_id"]


def test_group_export_checks_group_before_truncating_existing_output(
    tmp_path: Path,
) -> None:
    database = tmp_path / "acquisition.sqlite3"
    store = CaptureStore(database)
    experiment = store.create_experiment(name="preserve export")
    group = store.create_group(experiment["experiment_id"], name="valid group")
    capture_id = _stored_capture(database)
    store.assign_capture_group([capture_id], group["group_id"])
    database_before = database.read_bytes()
    output = tmp_path / "existing-export.zip"
    output.write_bytes(b"preserve this existing file")

    with pytest.raises(KeyError):
        main(
            [
                "group",
                "--sqlite",
                str(database),
                "--group-id",
                "f" * 32,
                "--output",
                str(output),
            ]
        )

    assert database.read_bytes() == database_before
    assert store.get_capture(capture_id).group_id == group["group_id"]
    assert output.read_bytes() == b"preserve this existing file"


def test_show_and_download_export_current_grouping_metadata(
    tmp_path: Path,
    capsys,
) -> None:
    database = tmp_path / "grouping-metadata.sqlite3"
    store = CaptureStore(database)
    experiment = store.create_experiment(name="before rename")
    group = store.create_group(
        experiment["experiment_id"], name="before rename", cell_id="cell-1"
    )
    capture_id = _stored_capture(database)
    store.assign_capture_group([capture_id], group["group_id"])
    store.update_experiment(experiment["experiment_id"], name="current experiment")
    store.update_group(group["group_id"], name="current group", cell_id="cell-2")

    show_result = main(
        ["show", "--sqlite", str(database), "--capture-id", capture_id.hex()]
    )
    shown = json.loads(capsys.readouterr().out)
    output_directory = tmp_path / "download"
    download_result = main(
        [
            "download",
            "--sqlite",
            str(database),
            "--capture-id",
            capture_id.hex(),
            "--output-dir",
            str(output_directory),
        ]
    )
    downloaded = json.loads(capsys.readouterr().out)
    downloaded_metadata = json.loads(
        (output_directory / f"{capture_id.hex()}.json").read_text("utf-8")
    )
    expected_grouping = store.grouping_metadata(group["group_id"])

    assert show_result == 0
    assert download_result == 0
    assert shown["grouping_metadata"] == expected_grouping
    assert downloaded["grouping_metadata"] == expected_grouping
    assert downloaded_metadata["grouping_metadata"] == expected_grouping

    store.assign_capture_group([capture_id], None)
    expected_ungrouped = store.grouping_metadata(None)
    main(["show", "--sqlite", str(database), "--capture-id", capture_id.hex()])
    ungrouped_show = json.loads(capsys.readouterr().out)
    main(
        [
            "download",
            "--sqlite",
            str(database),
            "--capture-id",
            capture_id.hex(),
            "--output-dir",
            str(output_directory),
        ]
    )
    ungrouped_download = json.loads(capsys.readouterr().out)
    ungrouped_metadata = json.loads(
        (output_directory / f"{capture_id.hex()}.json").read_text("utf-8")
    )

    assert ungrouped_show["grouping_metadata"] == expected_ungrouped
    assert ungrouped_download["grouping_metadata"] == expected_ungrouped
    assert ungrouped_metadata["grouping_metadata"] == expected_ungrouped
