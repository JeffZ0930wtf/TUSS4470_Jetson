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


class DraftApiClient(FakeApiClient):
    def json(self, method, path, *, body=None, headers=None):
        self.calls.append((method, path, body, headers))
        if path == "/api/v1/config" and method == "GET":
            return {"state": "DRAFT", "actual": None}, {"etag": '"' + "0" * 64 + '"'}
        return {"state": "APPLIED"}, {}


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


def test_draft_saves_semantic_values_without_applying(capsys) -> None:
    client = FakeApiClient()

    result = main(
        ["draft", "--set", "BURST_PULSE=0", "--set", "PRE_DRIVER_MODE=true"],
        client=client,
    )

    assert result == 0
    assert client.calls == [
        (
            "PATCH",
            "/api/v1/config",
            {"changes": {"BURST_PULSE": 0, "PRE_DRIVER_MODE": True}},
            None,
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_first_apply_uses_draft_etag_without_requiring_applied_identity(capsys) -> None:
    client = DraftApiClient()

    assert main(["apply"], client=client) == 0

    assert client.calls == [
        ("GET", "/api/v1/config", None, None),
        (
            "PUT",
            "/api/v1/config",
            {"changes": {}},
            {"If-Match": '"' + "0" * 64 + '"'},
        ),
    ]
    assert json.loads(capsys.readouterr().out) == {"state": "APPLIED"}


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


def test_history_requests_one_bounded_cursor_page(capsys) -> None:
    client = FakeApiClient()

    assert main(["history", "--limit", "25", "--cursor", "100"], client=client) == 0

    assert client.calls == [("GET", "/api/v1/captures?limit=25&cursor=100", None, None)]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_history_can_filter_one_run_session(capsys) -> None:
    client = FakeApiClient()
    session_id = "12" * 16

    assert main(["history", "--session-id", session_id], client=client) == 0

    assert client.calls == [
        ("GET", f"/api/v1/captures?limit=50&session_id={session_id}", None, None)
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}
