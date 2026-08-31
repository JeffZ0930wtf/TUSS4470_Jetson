from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from usac_runtime.bridge_cli import main
from usac_runtime.core_service import open_listener, serve_connections
from usac_runtime.core_store import CaptureStore
from usac_runtime.spool import CaptureSpool


ROOT = Path(__file__).resolve().parents[3]


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "runtime.toml"
    path.write_text(
        "\n".join(
            [
                "[serial]",
                'port = "COM9"',
                "baudrate = 115200",
                "timeout_ms = 2000",
                "",
                "[storage]",
                f'data_dir = "{(tmp_path / "data").as_posix()}"',
                f'spool_dir = "{(tmp_path / "spool").as_posix()}"',
                f'sqlite_path = "{(tmp_path / "core.sqlite3").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_bridge_replay_cli_delivers_existing_pending(
    tmp_path: Path, capsys,
) -> None:
    config = _config(tmp_path)
    spool = CaptureSpool(tmp_path / "spool" / "bridge-spool.sqlite3")
    raw = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
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

    exit_code = main(
        [
            "replay",
            "--config",
            str(config),
            "--core-port",
            str(port),
        ]
    )
    worker.join(timeout=2)
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["delivered"] == 1
    assert spool.pending_records() == []
    assert store.capture_count() == 1


def test_bridge_capture_requires_explicit_hardware_confirmations(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    with pytest.raises(SystemExit, match="external VPWR"):
        main(["capture", "--config", str(config)])
