from __future__ import annotations

from dataclasses import replace

import pytest

from usac_protocol.capture_data import decode_capture_data, encode_capture_data
from usac_protocol.config_v2 import AcquisitionConfigV2, D10X4_REGISTER_PAIRS
from usac_protocol.frame import (
    CRC_SIZE,
    HEADER_SIZE,
    Flags,
    Frame,
    MessageType,
    decode_frame,
    encode_frame,
)
from usac_protocol.messages import (
    ErrorResponse,
    Io2LoopbackResult,
    decode_io2_loopback_request,
    encode_error,
    encode_io2_loopback_result,
)
from usac_protocol.simulator import SimulatedDevice
from usac_runtime.m3_capture import (
    _read_capture_frame,
    _require_response,
    run_m3_capture,
    run_m3_loopback,
)


def d10x4_config() -> AcquisitionConfigV2:
    return AcquisitionConfigV2.create(
        sample_interval_ticks=120,
        sample_count=2048,
        pretrigger_count=64,
        adc_bits=12,
        aux_flags=0,
        vref_mv=3300,
        burst_period_ticks=50,
        register_pairs=D10X4_REGISTER_PAIRS,
    )


class FakeM3Connection:
    def __init__(self) -> None:
        self.pending = bytearray()
        self.requests: list[Frame] = []
        self.device = SimulatedDevice()
        self.device.config = d10x4_config()

    def write(self, data: bytes) -> int:
        request = decode_frame(data)
        self.requests.append(request)
        if request.message_type is MessageType.RUN_IO2_LOOPBACK_TEST:
            decoded = decode_io2_loopback_request(request.payload)
            result = Io2LoopbackResult(
                request_id=decoded.request_id,
                profile_sha256=self.device.config.profile_sha256,
                device_config_crc32=self.device.config.device_config_crc32,
                burst_period_ticks=50,
                captured_edges=8,
                result_flags=1,
                capture_ticks=(100, 150, 200, 250, 300, 350, 400, 450),
                minimum_interval_ticks=50,
                maximum_interval_ticks=50,
                pre_spi_status=0,
                pre_dev_stat=0,
                pre_tof_config=0x40,
                pre_vdrv_ctrl=0x20,
                post_spi_status=0,
                post_dev_stat=0,
                post_tof_config=0x40,
                post_vdrv_ctrl=0x20,
                final_io2_level=1,
            )
            responses = [
                Frame(
                    MessageType.RUN_IO2_LOOPBACK_TEST,
                    request.sequence,
                    encode_io2_loopback_result(result),
                    Flags.RESPONSE,
                )
            ]
        else:
            responses = self.device.handle(request)
            if request.message_type is MessageType.CAPTURE_ONCE:
                capture = decode_capture_data(responses[1].payload)
                responses[1] = replace(
                    responses[1],
                    payload=encode_capture_data(
                        replace(
                            capture,
                            smclk_calibrated_hz=0,
                            calibration_version=0,
                            quality_flags=0x20,
                        )
                    ),
                )
        for response in responses:
            self.pending.extend(encode_frame(response))
        return len(data)

    def read(self, size: int) -> bytes:
        chunk = bytes(self.pending[:size])
        del self.pending[:size]
        return chunk


class MissingCaptureAckConnection(FakeM3Connection):
    def write(self, data: bytes) -> int:
        request = decode_frame(data)
        if request.message_type is MessageType.CAPTURE_ONCE:
            self.requests.append(request)
            return len(data)
        return super().write(data)


class PartialCaptureDataConnection(FakeM3Connection):
    def write(self, data: bytes) -> int:
        written = super().write(data)
        request = self.requests[-1]
        if request.message_type is MessageType.CAPTURE_ONCE:
            ack_frame_length = HEADER_SIZE + 24 + CRC_SIZE
            partial_capture_length = HEADER_SIZE + 20
            del self.pending[ack_frame_length + partial_capture_length :]
        return written


class PartialCaptureHeaderConnection(FakeM3Connection):
    def write(self, data: bytes) -> int:
        written = super().write(data)
        request = self.requests[-1]
        if request.message_type is MessageType.CAPTURE_ONCE:
            ack_frame_length = HEADER_SIZE + 24 + CRC_SIZE
            del self.pending[ack_frame_length + 5 :]
        return written


class ProgressingCaptureFrameConnection:
    """Deliver a valid frame around one idle poll while virtual time advances."""

    def __init__(self, raw_frame: bytes, clock: list[float]) -> None:
        self._header = raw_frame[:HEADER_SIZE]
        self._remainder = bytearray(raw_frame[HEADER_SIZE:])
        self._clock = clock
        self._read_count = 0
        self.requested_sizes: list[int] = []

    def read(self, size: int) -> bytes:
        self.requested_sizes.append(size)
        self._read_count += 1
        if self._read_count == 1:
            return self._header
        if self._read_count == 2:
            self._clock[0] = 0.75
            chunk = bytes(self._remainder[:64])
            del self._remainder[:64]
            return chunk
        if self._read_count == 3:
            self._clock[0] = 1.25
            return b""
        chunk = bytes(self._remainder[:size])
        del self._remainder[:size]
        return chunk


def test_m3_capture_saves_raw_frame_metadata_and_unmodified_samples(tmp_path) -> None:
    connection = FakeM3Connection()
    events = []

    result = run_m3_capture(
        connection,
        host_nonce=bytes(range(16)),
        set_config_request_id=bytes(range(16, 32)),
        loopback_request_id=bytes(range(32, 48)),
        capture_request_id=bytes(range(48, 64)),
        output_directory=tmp_path,
        progress=events.append,
    )

    assert [frame.message_type for frame in connection.requests] == [
        MessageType.HELLO,
        MessageType.GET_CONFIG,
        MessageType.SET_CONFIG,
        MessageType.RUN_IO2_LOOPBACK_TEST,
        MessageType.CAPTURE_ONCE,
    ]
    assert len(result.capture.samples) == 2048
    assert result.capture.samples[:3] == (211, 248, 285)
    assert result.capture.pretrigger_count == 64
    assert result.capture.quality_flags & 0x20
    assert decode_frame(result.raw_frame_path.read_bytes()).payload == encode_capture_data(
        result.capture
    )
    assert result.samples_path.read_bytes() == result.raw_frame_path.read_bytes()[-4100:-4]
    assert '"interpolated": false' in result.metadata_path.read_text(encoding="utf-8")
    assert [event.stage for event in events[:4]] == [
        "loopback_passed",
        "capture_once_sent",
        "capture_ack_received",
        "capture_data_header_received",
    ]
    receiving = [
        event.received_bytes
        for event in events
        if event.stage == "capture_data_receiving"
    ]
    assert receiving == sorted(receiving)
    assert receiving[-1] == HEADER_SIZE + 4304 + CRC_SIZE
    assert events[-1].stage == "artifacts_saved"


def test_capture_frame_timeout_tracks_idle_time_and_uses_bounded_reads(
    monkeypatch,
) -> None:
    raw_frame = encode_frame(
        Frame(MessageType.CAPTURE_DATA, 5, bytes(600), Flags.RESPONSE)
    )
    clock = [0.0]
    connection = ProgressingCaptureFrameConnection(raw_frame, clock)
    monkeypatch.setattr(
        "usac_runtime.m3_capture.time.monotonic", lambda: clock[0]
    )

    frame, received = _read_capture_frame(
        connection,
        timeout_s=1.0,
        progress=lambda _event: None,
    )

    assert frame.message_type is MessageType.CAPTURE_DATA
    assert received == raw_frame
    assert max(connection.requested_sizes) <= 256


def test_m3_loopback_only_never_sends_capture_once() -> None:
    connection = FakeM3Connection()

    result = run_m3_loopback(
        connection,
        host_nonce=bytes(range(16)),
        set_config_request_id=bytes(range(16, 32)),
        loopback_request_id=bytes(range(32, 48)),
    )

    assert [frame.message_type for frame in connection.requests] == [
        MessageType.HELLO,
        MessageType.GET_CONFIG,
        MessageType.SET_CONFIG,
        MessageType.RUN_IO2_LOOPBACK_TEST,
    ]
    assert result.loopback.result_flags == 1
    assert result.loopback.captured_edges == 8


def test_m3_capture_reports_stage_when_ack_times_out(tmp_path) -> None:
    connection = MissingCaptureAckConnection()
    events = []

    with pytest.raises(TimeoutError) as captured:
        run_m3_capture(
            connection,
            host_nonce=bytes(range(16)),
            set_config_request_id=bytes(range(16, 32)),
            loopback_request_id=bytes(range(32, 48)),
            capture_request_id=bytes(range(48, 64)),
            output_directory=tmp_path,
            timeout_s=0.001,
            progress=events.append,
        )

    assert [event.stage for event in events][-2:] == [
        "loopback_passed",
        "capture_once_sent",
    ]
    notes = "\n".join(captured.value.__notes__)
    assert "last_stage=capture_once_sent" in notes
    assert "received_bytes=0" in notes


def test_m3_capture_reports_partial_capture_data_bytes(tmp_path) -> None:
    connection = PartialCaptureDataConnection()
    events = []

    with pytest.raises(TimeoutError) as captured:
        run_m3_capture(
            connection,
            host_nonce=bytes(range(16)),
            set_config_request_id=bytes(range(16, 32)),
            loopback_request_id=bytes(range(32, 48)),
            capture_request_id=bytes(range(48, 64)),
            output_directory=tmp_path,
            timeout_s=0.001,
            progress=events.append,
        )

    assert [event.stage for event in events][-3:] == [
        "capture_ack_received",
        "capture_data_header_received",
        "capture_data_receiving",
    ]
    assert events[-1].received_bytes == HEADER_SIZE + 20
    assert events[-1].expected_bytes == HEADER_SIZE + 4304 + CRC_SIZE
    notes = "\n".join(captured.value.__notes__)
    assert "last_stage=capture_data_receiving" in notes
    assert "received_bytes=36" in notes


def test_m3_capture_reports_partial_capture_header_bytes(tmp_path) -> None:
    connection = PartialCaptureHeaderConnection()
    events = []

    with pytest.raises(TimeoutError) as captured:
        run_m3_capture(
            connection,
            host_nonce=bytes(range(16)),
            set_config_request_id=bytes(range(16, 32)),
            loopback_request_id=bytes(range(32, 48)),
            capture_request_id=bytes(range(48, 64)),
            output_directory=tmp_path,
            timeout_s=0.001,
            progress=events.append,
        )

    assert events[-1].stage == "capture_data_receiving"
    assert events[-1].received_bytes == 5
    assert events[-1].expected_bytes is None
    assert "received_bytes=5" in "\n".join(captured.value.__notes__)


def test_m3_capture_without_progress_preserves_timeout_exception(tmp_path) -> None:
    connection = MissingCaptureAckConnection()

    with pytest.raises(TimeoutError) as captured:
        run_m3_capture(
            connection,
            host_nonce=bytes(range(16)),
            set_config_request_id=bytes(range(16, 32)),
            loopback_request_id=bytes(range(32, 48)),
            capture_request_id=bytes(range(48, 64)),
            output_directory=tmp_path,
            timeout_s=0.001,
        )

    assert getattr(captured.value, "__notes__", []) == []


def test_m3_capture_ignores_observer_failure(tmp_path) -> None:
    connection = FakeM3Connection()

    def failing_observer(_event) -> None:
        raise OSError("stderr unavailable")

    result = run_m3_capture(
        connection,
        host_nonce=bytes(range(16)),
        set_config_request_id=bytes(range(16, 32)),
        loopback_request_id=bytes(range(32, 48)),
        capture_request_id=bytes(range(48, 64)),
        output_directory=tmp_path,
        progress=failing_observer,
    )

    assert result.capture.sample_count == 2048


def test_m3_device_error_reports_existing_diagnostic_arguments() -> None:
    frame = Frame(
        MessageType.ERROR,
        5,
        encode_error(
            ErrorResponse(
                request_id=bytes(range(16)),
                failed_type=MessageType.CAPTURE_ONCE,
                current_state=6,
                error_code=11,
                detail_arg0=0,
                detail_arg1=2048,
                message="",
            )
        ),
        Flags.RESPONSE,
    )

    with pytest.raises(
        RuntimeError,
        match=r"device ERROR 11 for type 0x05 \(detail0=0, detail1=2048\)",
    ):
        _require_response(frame, sequence=5)
