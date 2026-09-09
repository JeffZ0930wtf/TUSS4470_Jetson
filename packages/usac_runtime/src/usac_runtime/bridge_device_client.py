"""Core-side device adapter for the persistent bridge byte stream.

M5 keeps policy, serialization, and SQLite ownership in core. This adapter
sends ordinary USAC commands through the bridge, while accepting CAPTURE_DATA
only inside a durable BRIDGE_CAPTURE_DELIVERY.
"""

from __future__ import annotations

from collections.abc import Callable
import secrets
import select
import socket
import struct
import threading

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedRequest,
    decode_bridge_capture_delivery,
    decode_capture_committed_response,
    encode_capture_committed_request,
)
from usac_protocol.capture_data import CaptureData, decode_capture_data
from usac_protocol.config_v2 import AcquisitionConfigV2, decode_config_v2
from usac_protocol.frame import (
    CRC_SIZE,
    HEADER_SIZE,
    Flags,
    Frame,
    HOST_MAX_PAYLOAD_LENGTH,
    MessageType,
    decode_frame,
    encode_frame,
)
from usac_protocol.messages import (
    CaptureOnceRequest,
    HelloRequest,
    RenewPeriodicLease,
    SetConfigRequest,
    StartPeriodicRequest,
    StopRequest,
    decode_ack,
    decode_capabilities_response,
    decode_error,
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

from .device_executor import DeviceReadback, DeviceUnavailable, PublishedDeviceSession
from .core_store import CaptureStore
from .periodic_lease import LeaseRenewal, PeriodicSchedule


class BridgeDeviceClient:
    """Translate high-level device operations to one core/bridge TCP stream."""

    _TRIGGER_CODES = {
        "SOFTWARE": 0,
        "EXTERNAL_SYNC_SLAVE": 1,
        "EXTERNAL_SYNC_MASTER": 2,
    }

    def __init__(
        self,
        connection: socket.socket,
        *,
        timeout_s: float = 3.0,
        replay_store: CaptureStore | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._connection = connection
        self._connection.settimeout(timeout_s)
        self._sequence = 0
        # The firmware enters IDLE_SAFE with a complete boot profile already
        # active.  The host must read that profile before its first SET_CONFIG
        # so the optimistic-concurrency hash refers to the device's real state.
        self._device_config: AcquisitionConfigV2 | None = None
        self._pending: tuple[int, BridgeCaptureDelivery, CaptureData] | None = None
        self._replay_store = replay_store
        self._async_capture_handler: Callable[[CaptureData], bool] | None = None
        self.hello = self._hello()
        self.boot_id = self.hello.boot_id
        self.device_id = self.hello.device_id
        # A bridge replays durable pending captures immediately after HELLO.
        # Issue one real device request now so _response() drains and confirms
        # every replay before the connection is published to the application.
        self._capabilities = self._query_capabilities()
        self._published_session = PublishedDeviceSession(
            True,
            "BRIDGE",
            0,
            self.hello,
            self.device_id,
            self.boot_id,
        )

    @property
    def published_session(self) -> PublishedDeviceSession:
        """Return the immutable identity without touching the protocol stream."""

        return self._published_session

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        return self._sequence

    @staticmethod
    def _request_id() -> bytes:
        return secrets.token_bytes(16)

    def _send(self, frame: Frame) -> None:
        if self._pending is not None and frame.message_type is not MessageType.CAPTURE_COMMITTED:
            raise RuntimeError("capture delivery must be committed before another command")
        self._connection.sendall(encode_frame(frame))

    def _read_exact(self, size: int) -> bytes:
        output = bytearray()
        while len(output) < size:
            chunk = self._connection.recv(size - len(output))
            if not chunk:
                raise ConnectionError("bridge disconnected during a protocol frame")
            output.extend(chunk)
        return bytes(output)

    def _receive(self) -> tuple[Frame, bytes]:
        header = self._read_exact(HEADER_SIZE)
        payload_length = struct.unpack_from("<I", header, 12)[0]
        if payload_length > HOST_MAX_PAYLOAD_LENGTH:
            raise ValueError("bridge frame exceeds host payload limit")
        raw = header + self._read_exact(payload_length + CRC_SIZE)
        return decode_frame(raw), raw

    @staticmethod
    def _raise_device_error(frame: Frame) -> None:
        if frame.message_type is MessageType.ERROR:
            error = decode_error(frame.payload)
            raise RuntimeError(
                f"device ERROR {error.error_code} for type 0x{error.failed_type:02X}: "
                f"detail0={error.detail_arg0}, detail1={error.detail_arg1}"
                + (f", message={error.message}" if error.message else "")
            )

    def _response(self, sequence: int, message_type: MessageType) -> Frame:
        while True:
            frame, _ = self._receive()
            if frame.message_type is MessageType.BRIDGE_CAPTURE_DELIVERY:
                capture = self._accept_delivery(frame)
                if (
                    self._async_capture_handler is not None
                    and self._async_capture_handler(capture)
                ):
                    if self._pending is not None:
                        raise RuntimeError("async capture handler did not finish the delivery")
                    continue
                if self._replay_store is None:
                    raise RuntimeError("bridge replay arrived without configured core storage")
                delivery = self.capture_delivery(capture.capture_id)
                result = self._replay_store.commit_replayed_delivery(delivery)
                self.confirm_capture(result.receipt)
                self.release_capture(capture.capture_id)
                continue
            self._raise_device_error(frame)
            if (
                frame.sequence != sequence
                or frame.message_type is not message_type
                or not frame.flags & Flags.RESPONSE
            ):
                raise RuntimeError(f"bridge returned an unexpected {message_type.name} response")
            return frame

    def _ack(self, sequence: int, request_id: bytes, message_type: MessageType) -> None:
        frame = self._response(sequence, MessageType.ACK)
        ack = decode_ack(frame.payload)
        if ack.request_id != request_id or ack.acked_type != message_type:
            raise RuntimeError(f"device ACK does not match {message_type.name}")

    def _hello(self):
        sequence = self._next_sequence()
        nonce = self._request_id()
        self._send(
            Frame(
                MessageType.HELLO,
                sequence,
                encode_hello_request(HelloRequest(nonce, 1, 1)),
            )
        )
        hello = decode_hello_response(self._response(sequence, MessageType.HELLO).payload)
        if hello.host_nonce != nonce:
            raise RuntimeError("device HELLO nonce does not match")
        return hello

    def _query_capabilities(self):
        sequence = self._next_sequence()
        self._send(Frame(MessageType.GET_CAPABILITIES, sequence, b""))
        return decode_capabilities_response(
            self._response(sequence, MessageType.GET_CAPABILITIES).payload
        )

    def capabilities(self):
        """Return capabilities fixed for the current HELLO/boot session."""

        return self._capabilities

    def status(self):
        sequence = self._next_sequence()
        self._send(Frame(MessageType.GET_STATUS, sequence, b""))
        return decode_status_response(self._response(sequence, MessageType.GET_STATUS).payload)

    def _read_config(self) -> AcquisitionConfigV2:
        """Read the configuration currently active in firmware."""

        sequence = self._next_sequence()
        self._send(Frame(MessageType.GET_CONFIG, sequence, b""))
        return decode_config_v2(self._response(sequence, MessageType.GET_CONFIG).payload)

    def apply_config(self, config: AcquisitionConfigV2) -> DeviceReadback:
        if self._device_config is None:
            self._device_config = self._read_config()
        sequence = self._next_sequence()
        request_id = self._request_id()
        expected = self._device_config.profile_sha256
        self._send(
            Frame(
                MessageType.SET_CONFIG,
                sequence,
                encode_set_config_request(SetConfigRequest(request_id, expected, config)),
            )
        )
        self._ack(sequence, request_id, MessageType.SET_CONFIG)
        readback = self._read_config()
        self._device_config = readback
        return DeviceReadback(readback)

    def _accept_delivery(self, frame: Frame) -> CaptureData:
        if self._pending is not None:
            raise RuntimeError("a second capture arrived before the first was committed")
        if frame.message_type is not MessageType.BRIDGE_CAPTURE_DELIVERY or frame.flags != Flags.ASYNC:
            self._raise_device_error(frame)
            raise RuntimeError("bridge did not return a durable capture delivery")
        delivery = decode_bridge_capture_delivery(frame.payload)
        inner = decode_frame(delivery.inner_frame)
        capture = decode_capture_data(inner.payload)
        self._pending = (frame.sequence, delivery, capture)
        return capture

    def set_async_capture_handler(
        self,
        handler: Callable[[CaptureData], bool] | None,
    ) -> None:
        """Install the core callback used when a periodic frame precedes a reply.

        A capture can legitimately reach TCP while the core is waiting for a
        lease response. Handling it inline is required to acknowledge the
        bridge spool and release its one-frame backpressure before that reply
        can be forwarded. The callback returns false for startup replay frames.
        """

        self._async_capture_handler = handler

    def clear_async_capture_handler(
        self,
        handler: Callable[[CaptureData], bool],
    ) -> None:
        """Clear only the callback owned by the finishing run session."""

        if self._async_capture_handler is handler:
            self._async_capture_handler = None

    def capture_once(
        self,
        *,
        config: AcquisitionConfigV2,
        trigger_source: str,
        sync_timeout_ms: int,
    ) -> CaptureData:
        sequence = self._next_sequence()
        request_id = self._request_id()
        self._send(
            Frame(
                MessageType.CAPTURE_ONCE,
                sequence,
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
        self._ack(sequence, request_id, MessageType.CAPTURE_ONCE)
        delivery, _ = self._receive()
        capture = self._accept_delivery(delivery)
        if capture.request_id != request_id:
            raise RuntimeError("capture delivery request_id does not match CAPTURE_ONCE")
        return capture

    def capture_delivery(self, capture_id: bytes) -> BridgeCaptureDelivery | None:
        if self._pending is None or self._pending[2].capture_id != capture_id:
            raise KeyError(f"capture {capture_id.hex()} has no pending bridge delivery")
        return self._pending[1]

    def capture_wire_frame(self, capture_id: bytes) -> bytes:
        delivery = self.capture_delivery(capture_id)
        if delivery is None:
            raise RuntimeError("bridge delivery unexpectedly missing")
        return delivery.inner_frame

    def confirm_capture(self, receipt: CaptureCommittedRequest) -> None:
        if self._pending is None:
            raise RuntimeError("no bridge capture delivery is pending")
        sequence, delivery, capture = self._pending
        if receipt.capture_id != capture.capture_id:
            raise RuntimeError("commit receipt does not match pending capture")
        self._confirm_delivery(sequence, delivery, receipt)
        self._pending = None

    def _confirm_delivery(
        self,
        sequence: int,
        delivery: BridgeCaptureDelivery,
        receipt: CaptureCommittedRequest,
    ) -> None:
        self._connection.sendall(
            encode_frame(
            Frame(
                MessageType.CAPTURE_COMMITTED,
                sequence,
                encode_capture_committed_request(receipt),
            )
            )
        )
        response_frame, _ = self._receive()
        if (
            response_frame.message_type is not MessageType.CAPTURE_COMMITTED
            or response_frame.flags != Flags.RESPONSE
            or response_frame.sequence != sequence
        ):
            raise RuntimeError("bridge returned an invalid commit response")
        response = decode_capture_committed_response(response_frame.payload)
        if (
            response.connection_id != delivery.connection_id
            or response.spool_record_id != delivery.spool_record_id
        ):
            raise RuntimeError("bridge commit response does not match pending delivery")

    def release_capture(self, capture_id: bytes) -> None:
        if self._pending is not None and self._pending[2].capture_id == capture_id:
            raise RuntimeError("pending bridge delivery cannot be released before confirmation")

    def start_periodic(self, schedule: PeriodicSchedule) -> None:
        sequence = self._next_sequence()
        request_id = self._request_id()
        self._send(
            Frame(
                MessageType.START_PERIODIC,
                sequence,
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
        self._ack(sequence, request_id, MessageType.START_PERIODIC)

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
        sequence = self._next_sequence()
        self._send(
            Frame(
                MessageType.RENEW_PERIODIC_LEASE,
                sequence,
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
        result = decode_renew_periodic_lease(
            self._response(sequence, MessageType.RENEW_PERIODIC_LEASE).payload
        )
        return LeaseRenewal(
            result.boot_id,
            result.schedule_id,
            result.lease_sequence,
            result.lease_timeout_or_remaining_ms,
        )

    def stop_periodic(self, schedule_id: bytes) -> None:
        sequence = self._next_sequence()
        request_id = self._request_id()
        self._send(
            Frame(
                MessageType.STOP,
                sequence,
                encode_stop_request(StopRequest(request_id, schedule_id)),
            )
        )
        self._ack(sequence, request_id, MessageType.STOP)

    def poll_captures(self) -> tuple[CaptureData, ...]:
        if self._pending is not None:
            return ()
        readable, _, _ = select.select([self._connection], [], [], 0)
        if not readable:
            return ()
        frame, _ = self._receive()
        return (self._accept_delivery(frame),)

    def close(self) -> None:
        """Close the bridge stream; the bridge then closes serial and clears DTR."""

        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._connection.close()
        self._published_session = PublishedDeviceSession(
            False, "BRIDGE", 1, None, None, None
        )


class ReconnectableBridgeDeviceClient:
    """Publish one current bridge session behind a stable application object.

    Calls are serialized with replacement so a command is handled by exactly
    one session.  A failed command is propagated to its caller; replacement
    only affects later calls and therefore cannot repeat CAPTURE or SET_CONFIG.
    """

    def __init__(self, initial: BridgeDeviceClient | None = None) -> None:
        self._lock = threading.RLock()
        self._client = initial
        self._session_generation = 0
        self._published_session = self._session_view(initial, 0)

    @staticmethod
    def _session_view(client: object | None, generation: int) -> PublishedDeviceSession:
        if client is None:
            return PublishedDeviceSession(False, "BRIDGE", generation, None, None, None)
        return PublishedDeviceSession(
            True,
            "BRIDGE",
            generation,
            getattr(client, "hello", None),
            getattr(client, "device_id", None),
            getattr(client, "boot_id", None),
        )

    @property
    def published_session(self) -> PublishedDeviceSession:
        """Return one atomic reference without acquiring the command lock."""

        return self._published_session

    @property
    def connected(self) -> bool:
        """Report whether an initialized bridge session is currently published."""

        with self._lock:
            return self._client is not None

    @property
    def backend_kind(self) -> str:
        return "BRIDGE"

    @property
    def session_generation(self) -> int:
        with self._lock:
            return self._session_generation

    def replace(self, replacement: BridgeDeviceClient) -> None:
        """Atomically publish a completed HELLO session and retire the old one."""

        with self._lock:
            previous = self._client
            self._client = replacement
            self._session_generation += 1
            self._published_session = self._session_view(
                replacement, self._session_generation
            )
        if previous is not None:
            previous.close()

    def close(self) -> None:
        """Retire the current session without requiring one to exist."""

        with self._lock:
            previous = self._client
            self._client = None
            if previous is not None:
                self._session_generation += 1
            self._published_session = self._session_view(
                None, self._session_generation
            )
        if previous is not None:
            previous.close()

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        with self._lock:
            if self._client is None:
                raise DeviceUnavailable("bridge device is not connected")
            attribute = getattr(self._client, name)
            if not callable(attribute):
                return attribute

        def invoke(*args, **kwargs):
            failed_client = None
            failure = None
            with self._lock:
                if self._client is None:
                    raise DeviceUnavailable("bridge device is not connected")
                client = self._client
                try:
                    return getattr(client, name)(*args, **kwargs)
                except (ConnectionError, TimeoutError, OSError) as error:
                    # Publish the disconnect before returning to HTTP callers.
                    # A later replacement is a new generation and never retries
                    # the failed side effect on the retired stream.
                    if self._client is client:
                        self._client = None
                        self._session_generation += 1
                        self._published_session = self._session_view(
                            None, self._session_generation
                        )
                        failed_client = client
                    failure = error
            if failed_client is not None:
                failed_client.close()
            raise DeviceUnavailable("bridge session was lost") from failure

        return invoke
