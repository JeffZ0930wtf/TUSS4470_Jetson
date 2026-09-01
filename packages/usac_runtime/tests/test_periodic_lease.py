from __future__ import annotations

from dataclasses import replace

import pytest

from usac_runtime.periodic_lease import (
    LeaseConflictError,
    LeaseRenewal,
    PeriodicLeaseController,
    PeriodicSchedule,
)


class FakePeriodicClient:
    def __init__(self) -> None:
        self.started = []
        self.renewed = []
        self.stopped = []

    def start_periodic(self, schedule: PeriodicSchedule) -> None:
        self.started.append(schedule)

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
        self.renewed.append(renewal)
        return renewal

    def stop_periodic(self, schedule_id: bytes) -> None:
        self.stopped.append(schedule_id)


def schedule() -> PeriodicSchedule:
    return PeriodicSchedule(
        boot_id=bytes(range(16)),
        schedule_id=bytes(range(16, 32)),
        profile_sha256=bytes(range(32)),
        device_config_crc32=0x12345678,
        period_us=1_000_000,
        capture_count=0,
        lease_timeout_ms=3_000,
    )


def test_start_renews_at_timeout_third_with_monotonic_sequences() -> None:
    client = FakePeriodicClient()
    controller = PeriodicLeaseController(client)
    current = schedule()

    controller.start(current, now_ms=10_000)

    assert client.started == [current]
    assert controller.renew_if_due(now_ms=10_999) is False
    assert controller.renew_if_due(now_ms=11_000) is True
    assert controller.renew_if_due(now_ms=11_999) is False
    assert controller.renew_if_due(now_ms=12_000) is True
    assert [renewal.lease_sequence for renewal in client.renewed] == [1, 2]
    assert all(renewal.boot_id == current.boot_id for renewal in client.renewed)


def test_renew_accepts_smaller_positive_remaining_time() -> None:
    class DelayedClient(FakePeriodicClient):
        def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
            self.renewed.append(renewal)
            return replace(renewal, lease_timeout_ms=renewal.lease_timeout_ms - 75)

    controller = PeriodicLeaseController(DelayedClient())
    controller.start(schedule(), now_ms=0)

    assert controller.renew_if_due(now_ms=1_000) is True


@pytest.mark.parametrize(
    "response_change",
    [
        {"boot_id": b"x" * 16},
        {"schedule_id": b"y" * 16},
        {"lease_sequence": 99},
        {"lease_timeout_ms": 0},
        {"lease_timeout_ms": 3_001},
    ],
)
def test_renew_rejects_identity_sequence_or_remaining_time_mismatch(
    response_change,
) -> None:
    class MismatchedClient(FakePeriodicClient):
        def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
            self.renewed.append(renewal)
            return replace(renewal, **response_change)

    controller = PeriodicLeaseController(MismatchedClient())
    controller.start(schedule(), now_ms=0)

    with pytest.raises(LeaseConflictError, match="response"):
        controller.renew_if_due(now_ms=1_000)

    assert controller.active is False


def test_stop_revokes_local_schedule_and_never_renews_again() -> None:
    client = FakePeriodicClient()
    controller = PeriodicLeaseController(client)
    current = schedule()
    controller.start(current, now_ms=0)

    controller.stop()

    assert client.stopped == [current.schedule_id]
    assert controller.active is False
    assert controller.renew_if_due(now_ms=10_000) is False


def test_finish_releases_completed_finite_schedule_without_sending_stop() -> None:
    client = FakePeriodicClient()
    controller = PeriodicLeaseController(client)
    controller.start(schedule(), now_ms=0)

    controller.finish()

    assert controller.active is False
    assert client.stopped == []


def test_second_schedule_cannot_replace_active_lease() -> None:
    client = FakePeriodicClient()
    controller = PeriodicLeaseController(client)
    controller.start(schedule(), now_ms=0)

    with pytest.raises(LeaseConflictError, match="active"):
        controller.start(replace(schedule(), schedule_id=b"z" * 16), now_ms=1)


@pytest.mark.parametrize(
    "change",
    [
        {"period_us": 99_999},
        {"lease_timeout_ms": 999},
        {"lease_timeout_ms": 10_001},
        {"schedule_id": bytes(16)},
    ],
)
def test_schedule_rejects_values_outside_first_version_limits(change) -> None:
    with pytest.raises(ValueError):
        PeriodicLeaseController(FakePeriodicClient()).start(
            replace(schedule(), **change),
            now_ms=0,
        )
