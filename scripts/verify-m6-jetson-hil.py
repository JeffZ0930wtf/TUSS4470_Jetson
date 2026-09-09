#!/usr/bin/env python3
"""Run bounded M6 Jetson HIL checkpoints against an already running core.

The tool is deliberately opt-in by phase. It never retries a hardware command,
never flashes firmware, and never starts work merely by being imported. Every
phase leaves the device on the D10x4 Pulse=1 baseline when it completes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from usac_runtime.m5_cli import ApiRequestError, HttpApiClient


ZERO_SCHEDULE = "00" * 16
BASELINE = {
    "requested_sample_rate_hz": 200_000,
    "requested_burst_frequency_hz": 480_000,
    "pretrigger_count": 64,
    "IO_MODE": "io_mode_3",
    "BURST_PULSE": 1,
    "HALF_BRG_MODE": False,
    "out3_enabled": False,
    "out4_enabled": False,
    "ZC_CMP_EN": False,
    "ECHO_INT_CMP_EN": False,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def get(client: HttpApiClient, path: str) -> dict[str, object]:
    payload, _ = client.json("GET", path)
    require(isinstance(payload, dict), f"{path} did not return an object")
    return payload


def assert_idle_normal(client: HttpApiClient) -> dict[str, object]:
    device = get(client, "/api/v1/device")
    require(device["connected"] is True, "device is not connected")
    require(device["health"] == "NORMAL", f"device health is {device['health']}")
    require(device["activity"] == "IDLE", f"device activity is {device['activity']}")
    status = device["status"]
    require(status["last_error"] == 0, f"device last_error is {status['last_error']}")
    require(status["tuss_dev_stat"] == 8, "unexpected TUSS_DEV_STAT")
    require(status["vdrv_ready"] == 1, "VDRV_READY is not set")
    require(status["active_schedule_id"] == ZERO_SCHEDULE, "schedule remains active")
    return device


def config(client: HttpApiClient) -> tuple[dict[str, object], str]:
    payload, headers = client.json("GET", "/api/v1/config")
    require(isinstance(payload, dict), "config did not return an object")
    require(headers.get("etag"), "config response has no ETag")
    return payload, headers["etag"]


def apply(client: HttpApiClient, changes: dict[str, object]) -> dict[str, object]:
    _, etag = config(client)
    payload, _ = client.json(
        "PUT",
        "/api/v1/config",
        body={"changes": changes},
        headers={"If-Match": etag},
    )
    require(isinstance(payload, dict) and payload["state"] == "APPLIED", "config was not APPLIED")
    fields = payload["readback"]["fields"]
    for name, value in changes.items():
        require(payload["requested"][name] == value, f"requested mismatch for {name}")
        if name in fields:
            require(fields[name] == value, f"readback mismatch for {name}")
    return payload


def applied_identity(client: HttpApiClient) -> tuple[str, int]:
    payload, _ = config(client)
    require(payload["state"] == "APPLIED", "no APPLIED config")
    actual = payload["actual"]
    return str(actual["profile_sha256"]), int(actual["device_config_crc32"])


def capture(
    client: HttpApiClient,
    *,
    trigger: str = "SOFTWARE",
    sync_timeout_ms: int = 0,
    save_policy: str = "SAVE_NONE",
) -> dict[str, object]:
    profile, crc = applied_identity(client)
    payload, _ = client.json(
        "POST",
        "/api/v1/captures",
        body={
            "expected_profile_sha256": profile,
            "expected_device_config_crc32": crc,
            "trigger_source": trigger,
            "sync_timeout_ms": sync_timeout_ms,
            "save_policy": save_policy,
        },
    )
    require(isinstance(payload, dict), "capture did not return an object")
    require(payload["sample_count"] == 2048, "capture did not contain 2048 samples")
    raw = client.bytes(f"/api/v1/captures/{payload['capture_id']}/samples")
    require(len(raw) == 4096, "capture sample payload was not 4096 bytes")
    return payload


def wait_session(
    client: HttpApiClient,
    session_id: str,
    *,
    terminal: set[str],
    timeout_s: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        session = get(client, f"/api/v1/sessions/{session_id}")
        if session["state"] in terminal:
            return session
        time.sleep(0.05)
    raise RuntimeError(f"session {session_id} did not reach {sorted(terminal)}")


def phase_range(client: HttpApiClient) -> dict[str, object]:
    assert_idle_normal(client)
    cases = [
        {"requested_sample_rate_hz": 25_000, "requested_burst_frequency_hz": 30_000, "IO_MODE": "io_mode_0", "BURST_PULSE": 1},
        {"requested_sample_rate_hz": 200_000, "requested_burst_frequency_hz": 1_000_000, "IO_MODE": "io_mode_1", "BURST_PULSE": 2},
        {"requested_burst_frequency_hz": 480_000, "IO_MODE": "io_mode_2", "BURST_PULSE": 1},
        {"IO_MODE": "io_mode_3", "BURST_PULSE": 63},
    ]
    results = []
    for changes in cases:
        applied = apply(client, changes)
        item = capture(client)
        results.append(
            {
                "capture_id": item["capture_id"],
                "capture_sequence": item["capture_sequence"],
                "sample_interval_ticks": item["sample_interval_ticks"],
                "burst_period_ticks": item["burst_period_ticks"],
                "io_mode": item["requested_config"]["IO_MODE"],
                "burst_pulse": item["requested_config"]["BURST_PULSE"],
                "profile_sha256": applied["actual"]["profile_sha256"],
            }
        )
        assert_idle_normal(client)
    apply(client, BASELINE)
    final = assert_idle_normal(client)
    return {"phase": "range", "captures": results, "final_sequence": final["status"]["capture_sequence"]}


def phase_master_events_sweep(client: HttpApiClient) -> dict[str, object]:
    apply(client, BASELINE)
    master = capture(client, trigger="EXTERNAL_SYNC_MASTER")
    assert_idle_normal(client)

    apply(client, {"out3_enabled": True, "ZC_CMP_EN": True})
    out3 = capture(client, save_policy="SAVE_ALL")
    assert_idle_normal(client)

    apply(client, {"out3_enabled": False, "ZC_CMP_EN": False, "out4_enabled": True, "ECHO_INT_CMP_EN": True})
    out4 = capture(client, save_policy="SAVE_ALL")
    assert_idle_normal(client)
    apply(client, BASELINE)

    profile, crc = applied_identity(client)
    started, _ = client.json(
        "POST",
        "/api/v1/sweeps",
        body={
            "expected_profile_sha256": profile,
            "expected_device_config_crc32": crc,
            "field": "BPF_HPF_FREQ",
            "values": [45, 46],
            "loops": 1,
            "start_delay_ms": 0,
            "loop_delay_ms": 0,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
            "save_policy": "SAVE_LAST",
        },
    )
    require(isinstance(started, dict), "sweep start did not return an object")
    sweep = wait_session(client, str(started["session_id"]), terminal={"COMPLETED"}, timeout_s=15)
    require(sweep["acquired_count"] == 2 and sweep["saved_count"] == 1, "sweep counts did not close")
    current, _ = config(client)
    require(current["requested"]["BPF_HPF_FREQ"] == 46, "sweep did not restore BPF baseline")
    apply(client, BASELINE)
    final = assert_idle_normal(client)
    return {
        "phase": "master-events-sweep",
        "master_capture_id": master["capture_id"],
        "out3": {"capture_id": out3["capture_id"], "events": out3["events"], "quality_flags": out3["quality_flags"]},
        "out4": {"capture_id": out4["capture_id"], "events": out4["events"], "quality_flags": out4["quality_flags"]},
        "sweep": {"session_id": sweep["session_id"], "acquired_count": sweep["acquired_count"], "saved_count": sweep["saved_count"]},
        "final_sequence": final["status"]["capture_sequence"],
    }


def start_periodic(
    client: HttpApiClient,
    *,
    count: int,
    lease_ms: int,
) -> dict[str, object]:
    profile, crc = applied_identity(client)
    payload, _ = client.json(
        "POST",
        "/api/v1/periodic/start",
        body={
            "expected_profile_sha256": profile,
            "expected_device_config_crc32": crc,
            "period_us": 200_000,
            "capture_count": count,
            "lease_timeout_ms": lease_ms,
            "save_policy": "SAVE_NONE",
        },
    )
    require(isinstance(payload, dict), "periodic start did not return an object")
    return payload


def phase_periodic_stop(client: HttpApiClient) -> dict[str, object]:
    apply(client, BASELINE)
    finite_started = start_periodic(client, count=2, lease_ms=1_000)
    finite = wait_session(client, str(finite_started["session_id"]), terminal={"COMPLETED"}, timeout_s=8)
    require(finite["acquired_count"] == 2, "finite periodic did not acquire two frames")

    infinite = start_periodic(client, count=0, lease_ms=3_000)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        running = get(client, f"/api/v1/sessions/{infinite['session_id']}")
        if running["acquired_count"] >= 2:
            break
        time.sleep(0.05)
    require(running["acquired_count"] >= 2, "infinite periodic did not reach two frames")
    stopped, _ = client.json(
        "POST",
        "/api/v1/periodic/stop",
        body={"session_id": infinite["session_id"], "schedule_id": infinite["schedule_id"]},
    )
    require(isinstance(stopped, dict) and stopped["state"] == "STOPPED", "STOP did not reach STOPPED")
    sequence = assert_idle_normal(client)["status"]["capture_sequence"]
    time.sleep(0.4)
    require(assert_idle_normal(client)["status"]["capture_sequence"] == sequence, "capture continued after STOP")
    return {
        "phase": "periodic-stop",
        "finite": {"session_id": finite["session_id"], "acquired_count": finite["acquired_count"]},
        "stopped": {"session_id": stopped["session_id"], "acquired_count": stopped["acquired_count"]},
        "stable_sequence": sequence,
    }


def phase_lease_start(client: HttpApiClient) -> dict[str, object]:
    apply(client, BASELINE)
    started = start_periodic(client, count=0, lease_ms=3_000)
    return {"phase": "lease-start", **started}


def phase_lease_verify(client: HttpApiClient) -> dict[str, object]:
    # The caller pauses core for >3 s between lease-start and this phase. The
    # firmware, not this script, must have expired and cleared the schedule.
    device = get(client, "/api/v1/device")
    status = device["status"]
    require(status["active_schedule_id"] == ZERO_SCHEDULE, "lease-expired schedule is still active")
    require(status["lease_remaining_ms"] == 0, "lease still has remaining time")
    sequence = status["capture_sequence"]
    time.sleep(1.1)
    later = get(client, "/api/v1/device")
    require(later["status"]["capture_sequence"] == sequence, "capture continued after lease expiry")
    require(later["status"]["active_schedule_id"] == ZERO_SCHEDULE, "schedule reactivated after expiry")
    return {"phase": "lease-verify", "stable_sequence": sequence, "last_error": later["status"]["last_error"]}


def phase_slave_timeout(client: HttpApiClient) -> dict[str, object]:
    apply(client, BASELINE)
    before = assert_idle_normal(client)["status"]["capture_sequence"]
    try:
        capture(client, trigger="EXTERNAL_SYNC_SLAVE", sync_timeout_ms=1_000)
    except ApiRequestError as error:
        require("device ERROR 26" in str(error), f"unexpected Slave error: {error}")
    else:
        raise RuntimeError("Slave unexpectedly captured without a rising edge")
    after = get(client, "/api/v1/device")
    require(after["status"]["capture_sequence"] == before, "Slave timeout changed capture sequence")
    return {"phase": "slave-timeout", "capture_sequence": before, "last_error": after["status"]["last_error"]}


def phase_slave_capture(client: HttpApiClient) -> dict[str, object]:
    apply(client, BASELINE)
    print("ARMING_SLAVE: move pin-11 input from GND to 3.3 V now", flush=True)
    item = capture(client, trigger="EXTERNAL_SYNC_SLAVE", sync_timeout_ms=60_000, save_policy="SAVE_ALL")
    assert_idle_normal(client)
    return {"phase": "slave-capture", "capture_id": item["capture_id"], "capture_sequence": item["capture_sequence"]}


PHASES = {
    "range": phase_range,
    "master-events-sweep": phase_master_events_sweep,
    "periodic-stop": phase_periodic_stop,
    "lease-start": phase_lease_start,
    "lease-verify": phase_lease_verify,
    "slave-timeout": phase_slave_timeout,
    "slave-capture": phase_slave_capture,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    result = PHASES[args.phase](HttpApiClient(args.base_url, timeout_s=65.0))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise
