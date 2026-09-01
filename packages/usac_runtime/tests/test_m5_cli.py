from __future__ import annotations

import json
from pathlib import Path

from usac_runtime.m5_cli import main


class FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object, dict[str, str] | None]] = []

    def json(self, method, path, *, body=None, headers=None):
        self.calls.append((method, path, body, headers))
        if path == "/api/v1/config" and method == "GET":
            return {
                "state": "APPLIED",
                "actual": {"profile_sha256": "a" * 64, "device_config_crc32": 7},
            }, {"etag": '"' + "a" * 64 + '"'}
        return {"ok": True}, {}

    def bytes(self, path):
        self.calls.append(("GET", path, None, None))
        return b"\x01\x02\x03\x04"


def test_apply_uses_current_etag_and_semantic_json_values(capsys) -> None:
    client = FakeApiClient()

    result = main(
        ["apply", "--set", "BURST_PULSE=7", "--set", "BPF_BYPASS=false"],
        client=client,
    )

    assert result == 0
    assert client.calls == [
        ("GET", "/api/v1/config", None, None),
        (
            "PUT",
            "/api/v1/config",
            {"changes": {"BURST_PULSE": 7, "BPF_BYPASS": False}},
            {"If-Match": '"' + "a" * 64 + '"'},
        ),
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_capture_binds_request_to_applied_config(capsys) -> None:
    client = FakeApiClient()

    assert main(["capture"], client=client) == 0

    assert client.calls[-1] == (
        "POST",
        "/api/v1/captures",
        {
            "expected_profile_sha256": "a" * 64,
            "expected_device_config_crc32": 7,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
        None,
    )
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_download_writes_raw_sample_bytes(tmp_path: Path, capsys) -> None:
    client = FakeApiClient()
    target = tmp_path / "capture.bin"

    assert main(["download", "01" * 16, str(target)], client=client) == 0

    assert target.read_bytes() == b"\x01\x02\x03\x04"
    assert json.loads(capsys.readouterr().out)["bytes"] == 4


def test_sweep_parses_values_as_one_json_array(capsys) -> None:
    client = FakeApiClient()

    assert main(
        ["sweep", "BURST_PULSE", "[1,2,3]", "--loops", "2"],
        client=client,
    ) == 0

    assert client.calls[-1][1] == "/api/v1/sweeps"
    assert client.calls[-1][2]["values"] == [1, 2, 3]
    assert client.calls[-1][2]["loops"] == 2
    assert json.loads(capsys.readouterr().out) == {"ok": True}
