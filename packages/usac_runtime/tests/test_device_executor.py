from __future__ import annotations

import threading
from pathlib import Path

import pytest

from usac_runtime.device_executor import (
    ConfigConflictError,
    ConfigValidationError,
    DeviceReadback,
    SingleDeviceExecutor,
)
from usac_runtime.parameter_service import ConfigState, ParameterService
from usac_runtime.run_plan import RunPlanV1, SweepPlan


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"


class FakeDeviceClient:
    def __init__(self) -> None:
        self.session_generation = 0
        self.apply_calls = 0
        self.capture_calls = 0
        self.apply_started = threading.Event()
        self.allow_apply_to_finish = threading.Event()
        self.allow_apply_to_finish.set()
        self.capture_started = threading.Event()
        self.status_started = threading.Event()
        self.applied_configs = []
        self.capture_arguments = []

    def apply_config(self, config):
        self.apply_calls += 1
        self.applied_configs.append(config)
        self.apply_started.set()
        assert self.allow_apply_to_finish.wait(timeout=1)
        return DeviceReadback(config)

    def capture_once(self, *, config, trigger_source: str, sync_timeout_ms: int):
        self.capture_calls += 1
        self.capture_arguments.append((config, trigger_source, sync_timeout_ms))
        self.capture_started.set()
        return {
            "profile_sha256": config.profile_sha256.hex(),
            "device_config_crc32": config.device_config_crc32,
            "trigger_source": trigger_source,
            "sync_timeout_ms": sync_timeout_ms,
        }

    def poll_captures(self):
        return ("periodic-capture",)

    def status(self):
        self.status_started.set()
        return {"state": "safe"}


@pytest.fixture
def executor() -> tuple[SingleDeviceExecutor, FakeDeviceClient]:
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    client = FakeDeviceClient()
    return SingleDeviceExecutor(service, client), client


def test_unsafe_draft_never_reaches_device(executor) -> None:
    worker, client = executor
    worker.update_draft({"PRE_DRIVER_MODE": True})

    with pytest.raises(ConfigValidationError) as caught:
        worker.apply_draft()

    assert caught.value.errors[0].field == "PRE_DRIVER_MODE"
    assert client.apply_calls == 0
    assert worker.snapshot().state is ConfigState.DRAFT


def test_apply_publishes_applied_only_after_exact_device_readback(executor) -> None:
    worker, client = executor

    applied = worker.apply_draft()

    assert client.apply_calls == 1
    assert applied.state is ConfigState.APPLIED
    assert applied.readback["sample_interval_ticks"] == 120
    assert worker.snapshot() == applied


def test_new_transport_session_invalidates_previous_applied_configuration(executor) -> None:
    worker, client = executor
    applied = worker.apply_draft()

    client.session_generation += 1

    assert worker.snapshot().state is ConfigState.DRAFT
    assert worker.snapshot().requested == applied.requested
    assert worker.applied_etag() == f'"{"0" * 64}"'
    with pytest.raises(ConfigConflictError, match="no APPLIED"):
        worker.capture_once(
            expected_profile_sha256=str(applied.actual["profile_sha256"]),
            expected_device_config_crc32=int(applied.actual["device_config_crc32"]),
            trigger_source="SOFTWARE",
            sync_timeout_ms=0,
        )


def test_apply_and_capture_are_serialized_per_device(executor) -> None:
    worker, client = executor
    validated = worker.validated_target()
    client.allow_apply_to_finish.clear()
    applied_result = []
    capture_result = []

    applying = threading.Thread(target=lambda: applied_result.append(worker.apply_draft()))
    applying.start()
    assert client.apply_started.wait(timeout=1)

    capturing = threading.Thread(
        target=lambda: capture_result.append(
            worker.capture_once(
                expected_profile_sha256=validated.profile_sha256.hex(),
                expected_device_config_crc32=validated.device_config_crc32,
                trigger_source="SOFTWARE",
                sync_timeout_ms=0,
            )
        )
    )
    capturing.start()

    assert client.capture_started.wait(timeout=0.05) is False
    client.allow_apply_to_finish.set()
    applying.join(timeout=1)
    capturing.join(timeout=1)

    assert len(applied_result) == 1
    assert len(capture_result) == 1
    assert client.capture_calls == 1


def test_capture_hash_conflict_fails_before_device_call(executor) -> None:
    worker, client = executor
    applied = worker.apply_draft()

    with pytest.raises(ConfigConflictError, match="profile"):
        worker.capture_once(
            expected_profile_sha256="00" * 32,
            expected_device_config_crc32=int(applied.actual["device_config_crc32"]),
            trigger_source="SOFTWARE",
            sync_timeout_ms=0,
        )

    assert client.capture_calls == 0


def test_periodic_delivery_callback_remains_inside_device_serialization(executor) -> None:
    worker, client = executor
    callback_started = threading.Event()
    release_callback = threading.Event()

    def commit_before_release(_capture) -> None:
        callback_started.set()
        assert release_callback.wait(timeout=1)

    polling = threading.Thread(
        target=lambda: worker.poll_captures(on_capture=commit_before_release)
    )
    polling.start()
    assert callback_started.wait(timeout=1)

    reading_status = threading.Thread(target=worker.status)
    reading_status.start()
    assert client.status_started.wait(timeout=0.05) is False

    release_callback.set()
    polling.join(timeout=1)
    reading_status.join(timeout=1)
    assert client.status_started.is_set()


def test_run_plan_executes_sweep_under_one_lock_and_restores_baseline(executor) -> None:
    worker, client = executor
    baseline = worker.apply_draft()
    slept: list[float] = []
    plan = RunPlanV1(
        loops=2,
        start_delay_ms=5,
        loop_delay_ms=7,
        sweep=SweepPlan("BURST_PULSE", (1, 2)),
    )

    captures = worker.execute_run_plan(plan, sleep=slept.append)

    assert len(captures) == 4
    assert [item.sweep_index for item in captures] == [0, 0, 1, 1]
    assert [item.loop_index for item in captures] == [0, 1, 0, 1]
    assert [item.snapshot.requested["BURST_PULSE"] for item in captures] == [1, 1, 2, 2]
    assert all(item.snapshot.state is ConfigState.APPLIED for item in captures)
    assert all(item.snapshot.readback["sample_interval_ticks"] == 120 for item in captures)
    assert [arguments[0].register_pairs[8][1] & 0x3F for arguments in client.capture_arguments] == [
        1,
        1,
        2,
        2,
    ]
    assert slept == [0.005, 0.007, 0.007]
    assert worker.snapshot() == baseline
    assert worker.snapshot().state is ConfigState.APPLIED
    assert client.applied_configs[-1].profile_sha256.hex() == baseline.actual["profile_sha256"]


def test_run_plan_cancellation_restores_baseline_before_next_capture(executor) -> None:
    worker, client = executor
    baseline = worker.apply_draft()
    cancelled = False

    def on_capture(_capture) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(RuntimeError, match="stopped"):
        worker.execute_run_plan(
            RunPlanV1(loops=3, sweep=SweepPlan("BURST_PULSE", (2, 3))),
            sleep=lambda _: None,
            cancelled=lambda: cancelled,
            on_capture=on_capture,
        )

    assert client.capture_calls == 1
    assert worker.snapshot() == baseline


def test_run_plan_streaming_callback_does_not_retain_capture_history(executor) -> None:
    worker, _client = executor
    worker.apply_draft()
    streamed = []

    retained = worker.execute_run_plan(
        RunPlanV1(loops=20),
        sleep=lambda _: None,
        on_capture=streamed.append,
    )

    assert len(streamed) == 20
    assert retained == ()


def test_run_plan_passes_external_slave_sync_contract_to_every_capture(executor) -> None:
    worker, client = executor
    worker.apply_draft()

    worker.execute_run_plan(
        RunPlanV1(
            loops=2,
            trigger_source="EXTERNAL_SYNC_SLAVE",
            sync_timeout_ms=500,
        ),
        sleep=lambda _: None,
    )

    assert [(source, timeout) for _, source, timeout in client.capture_arguments] == [
        ("EXTERNAL_SYNC_SLAVE", 500),
        ("EXTERNAL_SYNC_SLAVE", 500),
    ]
