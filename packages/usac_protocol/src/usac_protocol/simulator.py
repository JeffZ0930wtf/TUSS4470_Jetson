"""Deterministic software-only USAC device used for protocol verification.

It generates reproducible sample values but never opens USB/SPI, touches a
board, or represents its samples as physical ultrasonic measurements.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable

from .capture_data import CaptureData, CaptureEvent, encode_capture_data
from .config_v2 import AcquisitionConfigV2
from .frame import Flags, Frame, MessageType
from .messages import (
    Ack,
    CapabilitiesResponse,
    HelloResponse,
    RenewPeriodicLease,
    StatusResponse,
    decode_capture_once_request,
    decode_hello_request,
    decode_renew_periodic_lease,
    decode_set_config_request,
    decode_start_periodic_request,
    decode_stop_request,
    encode_ack,
    encode_capabilities_response,
    encode_hello_response,
    encode_renew_periodic_lease,
    encode_status_response,
)
from .safety import validate_boostxl_direct_applied_config


@dataclass(slots=True)
class _PeriodicSchedule:
    """Mutable simulator state corresponding to one firmware-owned schedule."""

    request_id: bytes
    schedule_id: bytes
    period_us: int
    capture_count: int
    lease_deadline_us: int
    next_capture_us: int
    completed_count: int = 0
    lease_sequence: int = 0


class SimulatedDevice:
    """Deterministic protocol device; it never accesses or models real hardware."""

    CONFIGURED_STATE = 2
    PERIODIC_STATE = 6
    LEASE_EXPIRED_ERROR = 18

    def __init__(self, *, clock_us: Callable[[], int] | None = None) -> None:
        self.device_id = hashlib.sha256(b"USAC-SIMULATOR-DEVICE-V1").digest()[:16]
        self.boot_id: bytes | None = None
        self.config: AcquisitionConfigV2 | None = None
        self._clock_us = clock_us or (lambda: time.monotonic_ns() // 1_000)
        self._capture_sequence = 0
        self._missed_capture_count = 0
        self._last_error = 0
        self._schedule: _PeriodicSchedule | None = None
        self._completed: dict[tuple[int, int, bytes], tuple[Frame, ...]] = {}

    def handle(self, frame: Frame) -> list[Frame]:
        cache_key = (int(frame.message_type), frame.sequence, frame.payload)
        if cache_key in self._completed:
            return list(self._completed[cache_key])
        if frame.flags != Flags.NONE:
            raise ValueError("simulator accepts requests with Flags=0 only")

        if frame.message_type is MessageType.HELLO:
            response = self._hello(frame)
        elif frame.message_type is MessageType.GET_CAPABILITIES:
            response = self._get_capabilities(frame)
        elif frame.message_type is MessageType.SET_CONFIG:
            response = self._set_config(frame)
        elif frame.message_type is MessageType.GET_CONFIG:
            response = self._get_config(frame)
        elif frame.message_type is MessageType.CAPTURE_ONCE:
            response = self._capture_once(frame)
        elif frame.message_type is MessageType.START_PERIODIC:
            response = self._start_periodic(frame)
        elif frame.message_type is MessageType.RENEW_PERIODIC_LEASE:
            response = self._renew_periodic(frame)
        elif frame.message_type is MessageType.STOP:
            response = self._stop(frame)
        elif frame.message_type is MessageType.GET_STATUS:
            response = self._get_status(frame)
        else:
            raise ValueError(f"simulator does not support {frame.message_type.name}")
        result = tuple(response)
        self._completed[cache_key] = result
        return list(result)

    def _hello(self, frame: Frame) -> list[Frame]:
        request = decode_hello_request(frame.payload)
        if not request.min_version <= 1 <= request.max_version:
            raise ValueError("simulator and host protocol versions do not overlap")
        self.boot_id = hashlib.sha256(
            b"USAC-BOOT-ID-V1" + self.device_id + request.host_nonce
        ).digest()[:16]
        payload = encode_hello_response(
            HelloResponse(
                host_nonce=request.host_nonce,
                boot_id=self.boot_id,
                device_id=self.device_id,
                negotiated_version=1,
                reset_reason=0,
                fw_major=0,
                fw_minor=1,
                fw_patch=0,
                fw_build=1,
                device_state=0,
            )
        )
        return [Frame(MessageType.HELLO, frame.sequence, payload, Flags.RESPONSE)]

    def _get_capabilities(self, frame: Frame) -> list[Frame]:
        self._require_empty_payload(frame)
        payload = encode_capabilities_response(
            CapabilitiesResponse(
                capability_flags=0x7F,
                mcu_max_command_payload=192,
                max_samples=2048,
                min_sample_interval_ticks=120,
                max_sample_interval_ticks=960,
                min_burst_period_ticks=24,
                max_burst_period_ticks=800,
                max_register_pairs=10,
                max_out3_events=8,
                max_out4_events=8,
                adc_bits=12,
                supported_io_modes=0x0F,
            )
        )
        return [
            Frame(MessageType.GET_CAPABILITIES, frame.sequence, payload, Flags.RESPONSE)
        ]

    def _set_config(self, frame: Frame) -> list[Frame]:
        self._require_hello()
        request = decode_set_config_request(frame.payload)
        if self.config is None:
            if request.expected_profile_sha256 != bytes(32):
                raise ValueError("first configuration must expect an unconfigured device")
        elif request.expected_profile_sha256 != self.config.profile_sha256:
            raise ValueError("expected profile does not match simulator configuration")
        validate_boostxl_direct_applied_config(request.config)
        self.config = request.config
        payload = encode_ack(
            Ack(request.request_id, int(MessageType.SET_CONFIG), 2, 0, self.config.device_config_crc32)
        )
        return [Frame(MessageType.ACK, frame.sequence, payload, Flags.RESPONSE)]

    def _get_config(self, frame: Frame) -> list[Frame]:
        from .config_v2 import encode_config_v2

        self._require_config()
        return [
            Frame(
                MessageType.GET_CONFIG,
                frame.sequence,
                encode_config_v2(self.config),
                Flags.RESPONSE,
            )
        ]

    def _capture_once(self, frame: Frame) -> list[Frame]:
        self._require_hello()
        self._require_config()
        request = decode_capture_once_request(frame.payload)
        assert self.config is not None
        assert self.boot_id is not None
        if request.expected_profile_sha256 != self.config.profile_sha256:
            raise ValueError("capture profile hash does not match")
        if request.expected_device_config_crc32 != self.config.device_config_crc32:
            raise ValueError("capture configuration CRC does not match")
        capture = self._make_capture(request.request_id, bytes(16))
        ack = Frame(
            MessageType.ACK,
            frame.sequence,
            encode_ack(
                Ack(
                    request.request_id,
                    int(MessageType.CAPTURE_ONCE),
                    2,
                    0,
                    self.config.device_config_crc32,
                )
            ),
            Flags.RESPONSE,
        )
        data = Frame(
            MessageType.CAPTURE_DATA,
            frame.sequence,
            encode_capture_data(capture),
            Flags.RESPONSE,
        )
        return [ack, data]

    def _start_periodic(self, frame: Frame) -> list[Frame]:
        self._require_hello()
        self._require_config()
        if self._schedule is not None:
            raise ValueError("a periodic schedule is already active")
        request = decode_start_periodic_request(frame.payload)
        assert self.config is not None
        if request.expected_profile_sha256 != self.config.profile_sha256:
            raise ValueError("periodic profile hash does not match")
        if request.expected_device_config_crc32 != self.config.device_config_crc32:
            raise ValueError("periodic configuration CRC does not match")
        if request.period_us < 100_000:
            raise ValueError("period_us must respect the 10 Hz first-version limit")
        now_us = self._now_us()
        self._schedule = _PeriodicSchedule(
            request_id=request.request_id,
            schedule_id=request.schedule_id,
            period_us=request.period_us,
            capture_count=request.capture_count,
            lease_deadline_us=now_us + request.lease_timeout_ms * 1_000,
            next_capture_us=now_us + request.period_us,
        )
        self._last_error = 0
        return [self._ack(frame, request.request_id, self.PERIODIC_STATE)]

    def _renew_periodic(self, frame: Frame) -> list[Frame]:
        self._require_hello()
        request = decode_renew_periodic_lease(frame.payload)
        schedule = self._schedule
        assert self.boot_id is not None
        if schedule is None:
            raise ValueError("no periodic schedule is active")
        if request.boot_id != self.boot_id or request.schedule_id != schedule.schedule_id:
            raise ValueError("renewal does not match the active boot and schedule")
        now_us = self._now_us()
        if now_us >= schedule.lease_deadline_us:
            self._expire_schedule()
            raise ValueError("periodic lease has expired")
        if request.lease_sequence > schedule.lease_sequence:
            schedule.lease_sequence = request.lease_sequence
            schedule.lease_deadline_us = (
                now_us + request.lease_timeout_or_remaining_ms * 1_000
            )
        response = RenewPeriodicLease(
            self.boot_id,
            schedule.schedule_id,
            schedule.lease_sequence,
            max(0, (schedule.lease_deadline_us - now_us) // 1_000),
        )
        return [
            Frame(
                MessageType.RENEW_PERIODIC_LEASE,
                frame.sequence,
                encode_renew_periodic_lease(response),
                Flags.RESPONSE,
            )
        ]

    def _stop(self, frame: Frame) -> list[Frame]:
        self._require_hello()
        request = decode_stop_request(frame.payload)
        schedule = self._schedule
        if schedule is not None and schedule.schedule_id != request.schedule_id:
            raise ValueError("STOP schedule_id does not match the active schedule")
        self._schedule = None
        self._last_error = 0
        crc = self.config.device_config_crc32 if self.config is not None else 0
        payload = encode_ack(
            Ack(
                request.request_id,
                int(MessageType.STOP),
                self.CONFIGURED_STATE,
                0,
                crc,
            )
        )
        return [Frame(MessageType.ACK, frame.sequence, payload, Flags.RESPONSE)]

    def _get_status(self, frame: Frame) -> list[Frame]:
        self._require_hello()
        self._require_empty_payload(frame)
        now_us = self._now_us()
        if self._schedule is not None and now_us >= self._schedule.lease_deadline_us:
            self._expire_schedule()
        assert self.boot_id is not None
        schedule = self._schedule
        config = self.config
        payload = encode_status_response(
            StatusResponse(
                boot_id=self.boot_id,
                device_state=(
                    self.PERIODIC_STATE if schedule is not None else self.CONFIGURED_STATE
                ),
                last_error=self._last_error,
                profile_sha256=(config.profile_sha256 if config is not None else bytes(32)),
                device_config_crc32=(
                    config.device_config_crc32 if config is not None else 0
                ),
                capture_sequence=self._capture_sequence,
                missed_capture_count=self._missed_capture_count,
                quality_flags=0,
                tuss_dev_stat=0x08,
                vdrv_ready=1,
                out3_enabled=int(config is not None and bool(config.aux_flags & 0x01)),
                out4_enabled=int(config is not None and bool(config.aux_flags & 0x02)),
                clock_fault_flags=0,
                active_schedule_id=(schedule.schedule_id if schedule else bytes(16)),
                lease_sequence=(schedule.lease_sequence if schedule else 0),
                lease_remaining_ms=(
                    max(0, (schedule.lease_deadline_us - now_us) // 1_000)
                    if schedule
                    else 0
                ),
            )
        )
        return [Frame(MessageType.GET_STATUS, frame.sequence, payload, Flags.RESPONSE)]

    def poll(self) -> list[Frame]:
        """Advance the simulated firmware main loop without sleeping or hardware IO."""

        schedule = self._schedule
        if schedule is None:
            return []
        now_us = self._now_us()
        if now_us >= schedule.lease_deadline_us:
            self._expire_schedule()
            return []
        if now_us < schedule.next_capture_us:
            return []
        overdue_periods = (now_us - schedule.next_capture_us) // schedule.period_us
        self._missed_capture_count += overdue_periods
        schedule.next_capture_us += (overdue_periods + 1) * schedule.period_us
        capture = self._make_capture(schedule.request_id, schedule.schedule_id)
        schedule.completed_count += 1
        if schedule.capture_count and schedule.completed_count >= schedule.capture_count:
            self._schedule = None
        return [
            Frame(
                MessageType.CAPTURE_DATA,
                self._capture_sequence,
                encode_capture_data(capture),
                Flags.ASYNC,
            )
        ]

    def _make_capture(self, request_id: bytes, schedule_id: bytes) -> CaptureData:
        assert self.config is not None
        assert self.boot_id is not None
        self._capture_sequence += 1
        samples = tuple(
            (index * 37 + 211) & 0x0FFF for index in range(self.config.sample_count)
        )
        capture_id = hashlib.sha256(
            b"USAC-SIM-CAPTURE-V1"
            + self.boot_id
            + request_id
            + self._capture_sequence.to_bytes(4, "little")
        ).digest()[:16]
        events: list[CaptureEvent] = []
        if self.config.aux_flags & 0x01:
            events.append(self._event(3, 96, 1, 1))
        if self.config.aux_flags & 0x02:
            events.append(self._event(4, 128, 2, 0))
        return CaptureData(
            request_id=request_id,
            schedule_id=schedule_id,
            capture_id=capture_id,
            boot_id=self.boot_id,
            device_id=self.device_id,
            profile_sha256=self.config.profile_sha256,
            device_config_crc32=self.config.device_config_crc32,
            capture_sequence=self._capture_sequence,
            sample_interval_ticks=self.config.sample_interval_ticks,
            burst_period_ticks=self.config.burst_period_ticks,
            sample_count=self.config.sample_count,
            pretrigger_count=self.config.pretrigger_count,
            adc_bits=self.config.adc_bits,
            sample_encoding=1,
            vref_mv=self.config.vref_mv,
            smclk_nominal_hz=24_000_000,
            smclk_calibrated_hz=24_000_000,
            frame_start_tick48=1_000_000 + self._capture_sequence * 10_000,
            t_trigger_offset_ticks=300,
            adc0_hold_offset_ticks=-180,
            adc_aperture_ns=1_000,
            trigger_to_tx_output_ns=125,
            calibration_version=1,
            quality_flags=0,
            tuss_dev_stat=0x08,
            out3_start_level=(0 if self.config.aux_flags & 0x01 else 0xFF),
            out4_start_level=(0 if self.config.aux_flags & 0x02 else 0xFF),
            register_pairs=self.config.register_pairs,
            events=tuple(events),
            samples=samples,
        )

    def _event(
        self, channel: int, sample_index: int, edge: int, level_after: int
    ) -> CaptureEvent:
        assert self.config is not None
        subsample_tick = self.config.sample_interval_ticks // 2
        return CaptureEvent(
            channel=channel,
            edge=edge,
            capture_method=1,
            level_after=level_after,
            sample_index=sample_index,
            subsample_tick=subsample_tick,
            uncertainty_ticks=1,
            frame_offset_ticks=(
                sample_index * self.config.sample_interval_ticks + subsample_tick
            ),
        )

    def _ack(self, frame: Frame, request_id: bytes, state: int) -> Frame:
        assert self.config is not None
        payload = encode_ack(
            Ack(
                request_id,
                int(frame.message_type),
                state,
                0,
                self.config.device_config_crc32,
            )
        )
        return Frame(MessageType.ACK, frame.sequence, payload, Flags.RESPONSE)

    def _expire_schedule(self) -> None:
        self._schedule = None
        self._last_error = self.LEASE_EXPIRED_ERROR

    def _now_us(self) -> int:
        value = self._clock_us()
        if value < 0:
            raise ValueError("simulator clock must not be negative")
        return value

    @staticmethod
    def _require_empty_payload(frame: Frame) -> None:
        if frame.payload:
            raise ValueError(f"{frame.message_type.name} request payload must be empty")

    def _require_hello(self) -> None:
        if self.boot_id is None:
            raise ValueError("HELLO is required before this command")

    def _require_config(self) -> None:
        if self.config is None:
            raise ValueError("SET_CONFIG is required before this command")
