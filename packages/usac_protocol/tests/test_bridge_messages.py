from __future__ import annotations

from pathlib import Path

import pytest

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedRequest,
    CaptureCommittedResponse,
    decode_bridge_capture_delivery,
    decode_capture_committed_request,
    decode_capture_committed_response,
    encode_bridge_capture_delivery,
    encode_capture_committed_request,
    encode_capture_committed_response,
)
from usac_protocol.frame import Frame, MessageType, encode_frame


ROOT = Path(__file__).resolve().parents[3]


def test_bridge_delivery_preserves_complete_inner_frame() -> None:
    inner = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
    delivery = BridgeCaptureDelivery(
        connection_id=1,
        spool_record_id=2,
        source_connection_id=3,
        source_first_stream_offset=100,
        source_last_stream_offset=100 + len(inner) - 1,
        stored_utc_ns=4,
        inner_frame=inner,
    )

    encoded = encode_bridge_capture_delivery(delivery)

    assert len(encoded) == 56 + len(inner)
    assert decode_bridge_capture_delivery(encoded) == delivery
    assert encoded[-len(inner) :] == inner


def test_capture_committed_request_and_response_have_fixed_layouts() -> None:
    request = CaptureCommittedRequest(
        connection_id=1,
        spool_record_id=2,
        device_id=bytes(range(16)),
        boot_id=bytes(range(16, 32)),
        capture_id=bytes(range(32, 48)),
        inner_frame_crc32=0x12345678,
    )
    response = CaptureCommittedResponse(
        connection_id=1,
        spool_record_id=2,
        disposition=1,
    )

    assert len(encode_capture_committed_request(request)) == 68
    assert decode_capture_committed_request(encode_capture_committed_request(request)) == request
    assert len(encode_capture_committed_response(response)) == 24
    assert decode_capture_committed_response(encode_capture_committed_response(response)) == response


def test_bridge_delivery_rejects_non_capture_inner_frame() -> None:
    inner = encode_frame(Frame(MessageType.ERROR, 1, bytes(188)))
    delivery = BridgeCaptureDelivery(1, 2, 3, 0, len(inner) - 1, 4, inner)

    with pytest.raises(ValueError, match="CAPTURE_DATA"):
        encode_bridge_capture_delivery(delivery)
