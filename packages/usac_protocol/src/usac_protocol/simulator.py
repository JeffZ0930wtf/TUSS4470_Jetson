from __future__ import annotations

import hashlib

from .capture_data import CaptureData, encode_capture_data
from .config_v2 import AcquisitionConfigV2
from .frame import Flags, Frame, MessageType
from .messages import (
    Ack,
    HelloResponse,
    decode_capture_once_request,
    decode_hello_request,
    decode_set_config_request,
    encode_ack,
    encode_hello_response,
)
from .safety import validate_boostxl_direct_applied_config


class SimulatedDevice:
    """Deterministic protocol device; it never accesses or models real hardware."""

    def __init__(self) -> None:
        self.device_id = hashlib.sha256(b"USAC-SIMULATOR-DEVICE-V1").digest()[:16]
        self.boot_id: bytes | None = None
        self.config: AcquisitionConfigV2 | None = None
        self._capture_sequence = 0
        self._completed: dict[tuple[int, int, bytes], tuple[Frame, ...]] = {}

    def handle(self, frame: Frame) -> list[Frame]:
        cache_key = (int(frame.message_type), frame.sequence, frame.payload)
        if cache_key in self._completed:
            return list(self._completed[cache_key])
        if frame.flags != Flags.NONE:
            raise ValueError("simulator accepts requests with Flags=0 only")

        if frame.message_type is MessageType.HELLO:
            response = self._hello(frame)
        elif frame.message_type is MessageType.SET_CONFIG:
            response = self._set_config(frame)
        elif frame.message_type is MessageType.GET_CONFIG:
            response = self._get_config(frame)
        elif frame.message_type is MessageType.CAPTURE_ONCE:
            response = self._capture_once(frame)
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
        self._capture_sequence += 1
        samples = tuple((index * 37 + 211) & 0x0FFF for index in range(self.config.sample_count))
        capture_id = hashlib.sha256(
            b"USAC-SIM-CAPTURE-V1" + self.boot_id + request.request_id
        ).digest()[:16]
        capture = CaptureData(
            request_id=request.request_id,
            schedule_id=bytes(16),
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
            out3_start_level=0xFF,
            out4_start_level=0xFF,
            register_pairs=self.config.register_pairs,
            events=(),
            samples=samples,
        )
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

    def _require_hello(self) -> None:
        if self.boot_id is None:
            raise ValueError("HELLO is required before this command")

    def _require_config(self) -> None:
        if self.config is None:
            raise ValueError("SET_CONFIG is required before this command")
