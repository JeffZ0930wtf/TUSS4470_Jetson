from __future__ import annotations

from pathlib import Path

from usac_protocol.capture_data import decode_capture_data, encode_capture_data
from usac_protocol.frame import MessageType, decode_frame, encode_frame


ROOT = Path(__file__).resolve().parents[3]
VECTOR_PATH = ROOT / "protocol/vectors/capture-data-v1.hex"


def test_complete_capture_data_vector_decodes_and_reencodes_byte_for_byte() -> None:
    vector = bytes.fromhex(VECTOR_PATH.read_text(encoding="ascii"))
    frame = decode_frame(vector)

    assert frame.message_type is MessageType.CAPTURE_DATA
    assert frame.sequence == 7
    capture = decode_capture_data(frame.payload)
    assert capture.request_id == bytes(range(16))
    assert capture.schedule_id == bytes(16)
    assert capture.capture_id == bytes(range(0x10, 0x20))
    assert capture.boot_id == bytes(range(0x20, 0x30))
    assert capture.device_id == bytes(range(0x30, 0x40))
    assert capture.sample_interval_ticks == 120
    assert capture.burst_period_ticks == 50
    assert capture.samples == (0, 1, 4095, 2048)
    assert len(capture.register_pairs) == 10
    assert len(capture.events) == 1
    assert capture.events[0].channel == 4
    assert capture.events[0].sample_index == 2
    assert encode_capture_data(capture) == frame.payload
    assert encode_frame(frame) == vector
