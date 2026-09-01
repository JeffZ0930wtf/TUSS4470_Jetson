from __future__ import annotations

from pathlib import Path

from usac_protocol.frame import MessageType
from usac_protocol.simulator import SimulatedDevice
from usac_runtime.device_executor import SingleDeviceExecutor
from usac_runtime.parameter_service import ConfigState, ParameterService
from usac_runtime.periodic_lease import (
    PeriodicLeaseController,
    PeriodicSchedule,
)
from usac_runtime.simulated_device_client import SimulatedDeviceClient


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"


def configured_executor() -> tuple[SingleDeviceExecutor, SimulatedDeviceClient]:
    device = SimulatedDevice()
    client = SimulatedDeviceClient(device)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    return SingleDeviceExecutor(service, client), client


def test_semantic_configuration_round_trips_through_protocol_before_capture() -> None:
    executor, client = configured_executor()
    executor.update_draft(
        {
            "IO_MODE": "io_mode_2",
            "BURST_PULSE": 7,
            "sample_interval_ticks": 731,
            "burst_period_ticks": 347,
            "out3_enabled": True,
            "out4_enabled": True,
        }
    )

    applied = executor.apply_draft()
    capture = executor.capture_once(
        expected_profile_sha256=str(applied.actual["profile_sha256"]),
        expected_device_config_crc32=int(applied.actual["device_config_crc32"]),
        trigger_source="SOFTWARE",
        sync_timeout_ms=0,
    )

    assert applied.state is ConfigState.APPLIED
    assert applied.readback["sample_interval_ticks"] == 731
    assert applied.readback["burst_period_ticks"] == 347
    assert capture.sample_interval_ticks == 731
    assert capture.burst_period_ticks == 347
    assert len(capture.samples) == 2048
    assert [event.channel for event in capture.events] == [3, 4]
    assert client.last_acked_type is MessageType.CAPTURE_ONCE


def test_periodic_lease_controller_operates_the_same_protocol_session() -> None:
    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    client = SimulatedDeviceClient(device)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    executor = SingleDeviceExecutor(service, client)
    applied = executor.apply_draft()
    assert client.boot_id is not None
    schedule = PeriodicSchedule(
        boot_id=client.boot_id,
        schedule_id=bytes(range(16, 32)),
        profile_sha256=bytes.fromhex(str(applied.actual["profile_sha256"])),
        device_config_crc32=int(applied.actual["device_config_crc32"]),
        period_us=100_001,
        capture_count=1,
        lease_timeout_ms=1_000,
    )
    controller = PeriodicLeaseController(client)

    controller.start(schedule, now_ms=0)
    now_us[0] = 100_001
    captures = client.poll_captures()

    assert len(captures) == 1
    assert captures[0].schedule_id == schedule.schedule_id
    assert len(captures[0].samples) == 2048
    assert client.status().active_schedule_id == bytes(16)
