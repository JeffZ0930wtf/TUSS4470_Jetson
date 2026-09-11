from __future__ import annotations

import json
from pathlib import Path

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


def test_m4_show_prints_stored_capture_metadata(
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


def test_m4_download_writes_exact_database_blobs(
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
