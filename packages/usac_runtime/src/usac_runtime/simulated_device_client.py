"""In-process device client for M5 protocol and interface verification.

This adapter exercises the real USAC payload codecs and the deterministic
simulator without opening a serial port. It is a test/development backend, not
evidence that a configuration has been accepted by physical TUSS4470 hardware.
"""

from __future__ import annotations

import hashlib

from usac_protocol.capture_data import CaptureData, decode_capture_data
from usac_protocol.config_v2 import AcquisitionConfigV2, decode_config_v2
from usac_protocol.frame import Flags, Frame, MessageType
from usac_protocol.messages import (
    CaptureOnceRequest,
    CapabilitiesResponse,
    HelloRequest,
    RenewPeriodicLease,
    SetConfigRequest,
    StartPeriodicRequest,
    StopRequest,
    StatusResponse,
    decode_ack,
    decode_capabilities_response,
    decode_hello_response,
    decode_renew_periodic_lease,
    decode_status_response,
    encode_capture_once_request,
    encode_hello_request,
    encode_renew_periodic_lease,
    encode_set_config_request,
    encode_start_periodic_request,
    encode_stop_request,
)
from usac_protocol.simulator import SimulatedDevice

from .device_executor import DeviceReadback
from .periodic_lease import LeaseRenewal, PeriodicSchedule


class SimulatedDeviceClient:
    """Translate host operations into complete protocol exchanges in memory."""

    _TRIGGER_CODES = {
        "SOFTWARE": 0,
        "EXTERNAL_SYNC_SLAVE": 1,
        "EXTERNAL_SYNC_MASTER": 2,
    }

    def __init__(self, device: SimulatedDevice) -> None:
        self._device = device
        self._sequence = 0
        self._identifier_counter = 0
        self.boot_id: bytes | None = None
        self.device_id: bytes | None = None
        self.last_acked_type: MessageType | None = None
        self._hello()

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _new_identifier(self, purpose: bytes) -> bytes:
        self._identifier_counter += 1
        return hashlib.sha256(
            b"USAC-SIM-CLIENT-V1"
            + purpose
            + self._identifier_counter.to_bytes(4, "little")
        ).digest()[:16]

    def _hello(self) -> None:
        nonce = self._new_identifier(b"hello")
        response = self._device.handle(
            Frame(
                MessageType.HELLO,
                self._next_sequence(),
                encode_hello_request(HelloRequest(nonce, 1, 1)),
            )
        )
        self._require_count(response, 1)
        hello = decode_hello_response(response[0].payload)
        if response[0].flags != Flags.RESPONSE or hello.host_nonce != nonce:
            raise RuntimeError("simulated HELLO response does not match the request")
        self.boot_id = hello.boot_id
        self.device_id = hello.device_id

    def _require_ack(
        self, frame: Frame, request_id: bytes, expected_type: MessageType
    ) -> None:
        if frame.message_type is not MessageType.ACK or frame.flags != Flags.RESPONSE:
            raise RuntimeError(f"simulated device did not ACK {expected_type.name}")
        ack = decode_ack(frame.payload)
        if ack.request_id != request_id or ack.acked_type != expected_type:
            raise RuntimeError(f"simulated {expected_type.name} ACK does not match")
        self.last_acked_type = expected_type

    @staticmethod
    def _require_count(frames: list[Frame], expected: int) -> None:
        if len(frames) != expected:
            raise RuntimeError(
                f"simulated exchange returned {len(frames)} frames; expected {expected}"
            )

    def apply_config(self, config: AcquisitionConfigV2) -> DeviceReadback:
        """Apply one canonical config and expose only the exact device readback."""

        request_id = self._new_identifier(b"set-config")
        expected = (
            self._device.config.profile_sha256
            if self._device.config is not None
            else bytes(32)
        )
        response = self._device.handle(
            Frame(
                MessageType.SET_CONFIG,
                self._next_sequence(),
                encode_set_config_request(SetConfigRequest(request_id, expected, config)),
            )
        )
        self._require_count(response, 1)
        self._require_ack(response[0], request_id, MessageType.SET_CONFIG)
        readback_frames = self._device.handle(
            Frame(MessageType.GET_CONFIG, self._next_sequence(), b"")
        )
        self._require_count(readback_frames, 1)
        readback = decode_config_v2(readback_frames[0].payload)
        return DeviceReadback(
            register_pairs=readback.register_pairs,
            sample_interval_ticks=readback.sample_interval_ticks,
            burst_period_ticks=readback.burst_period_ticks,
        )

    def capture_once(
        self,
        *,
        config: AcquisitionConfigV2,
        trigger_source: str,
        sync_timeout_ms: int,
    ) -> CaptureData:
        """Issue one hash/CRC-bound capture and decode its unmodified payload."""

        request_id = self._new_identifier(b"capture-once")
        response = self._device.handle(
            Frame(
                MessageType.CAPTURE_ONCE,
                self._next_sequence(),
                encode_capture_once_request(
                    CaptureOnceRequest(
                        request_id,
                        config.profile_sha256,
                        config.device_config_crc32,
                        self._TRIGGER_CODES[trigger_source],
                        sync_timeout_ms,
                    )
                ),
            )
        )
        self._require_count(response, 2)
        self._require_ack(response[0], request_id, MessageType.CAPTURE_ONCE)
        if response[1].message_type is not MessageType.CAPTURE_DATA:
            raise RuntimeError("simulated device did not return CAPTURE_DATA")
        return decode_capture_data(response[1].payload)

    def status(self) -> StatusResponse:
        response = self._device.handle(
            Frame(MessageType.GET_STATUS, self._next_sequence(), b"")
        )
        self._require_count(response, 1)
        return decode_status_response(response[0].payload)

    def capabilities(self) -> CapabilitiesResponse:
        """Return the typed GET_CAPABILITIES response used by later interfaces."""

        response = self._device.handle(
            Frame(MessageType.GET_CAPABILITIES, self._next_sequence(), b"")
        )
        self._require_count(response, 1)
        return decode_capabilities_response(response[0].payload)

    def start_periodic(self, schedule: PeriodicSchedule) -> None:
        """Create one firmware-owned schedule; lease renewal remains core-owned."""

        request_id = self._new_identifier(b"start-periodic")
        response = self._device.handle(
            Frame(
                MessageType.START_PERIODIC,
                self._next_sequence(),
                encode_start_periodic_request(
                    StartPeriodicRequest(
                        request_id,
                        schedule.schedule_id,
                        schedule.profile_sha256,
                        schedule.device_config_crc32,
                        schedule.period_us,
                        schedule.capture_count,
                        schedule.lease_timeout_ms,
                    )
                ),
            )
        )
        self._require_count(response, 1)
        self._require_ack(response[0], request_id, MessageType.START_PERIODIC)

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
        response = self._device.handle(
            Frame(
                MessageType.RENEW_PERIODIC_LEASE,
                self._next_sequence(),
                encode_renew_periodic_lease(
                    RenewPeriodicLease(
                        renewal.boot_id,
                        renewal.schedule_id,
                        renewal.lease_sequence,
                        renewal.lease_timeout_ms,
                    )
                ),
            )
        )
        self._require_count(response, 1)
        decoded = decode_renew_periodic_lease(response[0].payload)
        return LeaseRenewal(
            decoded.boot_id,
            decoded.schedule_id,
            decoded.lease_sequence,
            decoded.lease_timeout_or_remaining_ms,
        )

    def stop_periodic(self, schedule_id: bytes) -> None:
        request_id = self._new_identifier(b"stop-periodic")
        response = self._device.handle(
            Frame(
                MessageType.STOP,
                self._next_sequence(),
                encode_stop_request(StopRequest(request_id, schedule_id)),
            )
        )
        self._require_count(response, 1)
        self._require_ack(response[0], request_id, MessageType.STOP)

    def poll_captures(self) -> tuple[CaptureData, ...]:
        """Decode currently available async frames without sleeping or interpolation."""

        captures: list[CaptureData] = []
        for frame in self._device.poll():
            if frame.message_type is not MessageType.CAPTURE_DATA or frame.flags != Flags.ASYNC:
                raise RuntimeError("simulated periodic poll returned a non-capture frame")
            captures.append(decode_capture_data(frame.payload))
        return tuple(captures)
