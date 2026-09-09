from __future__ import annotations

import socket
import struct
import threading
import time
from pathlib import Path

import pytest

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedResponse,
    decode_capture_committed_request,
    encode_bridge_capture_delivery,
    encode_capture_committed_response,
)
from usac_protocol.config_v2 import AcquisitionConfigV2, D10X4_REGISTER_PAIRS
from usac_protocol.capture_data import decode_capture_data
from usac_protocol.frame import CRC_SIZE, HEADER_SIZE, Flags, Frame, MessageType, decode_frame, encode_frame
from usac_protocol.messages import ErrorResponse, encode_error
from usac_protocol.simulator import SimulatedDevice
from usac_runtime.application import AcquisitionApplication
from usac_runtime.bridge_session import proxy_bridge_session
from usac_runtime.bridge_device_client import BridgeDeviceClient, ReconnectableBridgeDeviceClient
from usac_runtime.device_executor import DeviceUnavailable
from usac_runtime.core_store import CaptureStore
from usac_runtime.device_executor import SingleDeviceExecutor
from usac_runtime.parameter_service import ParameterService
from usac_runtime.periodic_lease import LeaseRenewal, PeriodicSchedule
from usac_runtime.spool import CaptureSpool


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"


def _read_exact(connection: socket.socket, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        chunk = connection.recv(size - len(output))
        if not chunk:
            raise ConnectionError("test peer closed")
        output.extend(chunk)
    return bytes(output)


def _read_frame(connection: socket.socket) -> Frame:
    header = _read_exact(connection, HEADER_SIZE)
    payload_length = struct.unpack_from("<I", header, 12)[0]
    return decode_frame(header + _read_exact(connection, payload_length + CRC_SIZE))


def _serve_device_through_bridge(connection: socket.socket, spool: CaptureSpool) -> None:
    device = SimulatedDevice()
    device.config = _baseline_config()
    stream_offset = 0
    try:
        for _ in range(6):
            request = _read_frame(connection)
            for response in device.handle(request):
                raw = encode_frame(response)
                if response.message_type is not MessageType.CAPTURE_DATA:
                    connection.sendall(raw)
                    continue
                pending = spool.store_capture(
                    raw,
                    source_connection_id=17,
                    source_first_stream_offset=stream_offset,
                    source_last_stream_offset=stream_offset + len(raw) - 1,
                    stored_utc_ns=123,
                )
                stream_offset += len(raw)
                delivery = BridgeCaptureDelivery(
                    connection_id=7,
                    spool_record_id=pending.record_id,
                    source_connection_id=pending.source_connection_id,
                    source_first_stream_offset=pending.source_first_stream_offset,
                    source_last_stream_offset=pending.source_last_stream_offset,
                    stored_utc_ns=pending.stored_utc_ns,
                    inner_frame=pending.inner_frame,
                )
                connection.sendall(
                    encode_frame(
                        Frame(
                            MessageType.BRIDGE_CAPTURE_DELIVERY,
                            response.sequence,
                            encode_bridge_capture_delivery(delivery),
                            Flags.ASYNC,
                        )
                    )
                )
                receipt_frame = _read_frame(connection)
                receipt = decode_capture_committed_request(receipt_frame.payload)
                disposition = spool.mark_committed(
                    receipt.spool_record_id,
                    device_id=receipt.device_id,
                    boot_id=receipt.boot_id,
                    capture_id=receipt.capture_id,
                    inner_frame_crc32=receipt.inner_frame_crc32,
                )
                connection.sendall(
                    encode_frame(
                        Frame(
                            MessageType.CAPTURE_COMMITTED,
                            receipt_frame.sequence,
                            encode_capture_committed_response(
                                CaptureCommittedResponse(7, pending.record_id, disposition)
                            ),
                            Flags.RESPONSE,
                        )
                    )
                )
    finally:
        connection.close()


def _serve_bridge_initialization(connection: socket.socket) -> None:
    """Serve the HELLO and capabilities requests needed to publish a session."""

    device = SimulatedDevice()
    try:
        for _ in range(2):
            request = _read_frame(connection)
            for response in device.handle(request):
                connection.sendall(encode_frame(response))
    finally:
        connection.close()


def _baseline_config() -> AcquisitionConfigV2:
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


def test_device_error_preserves_diagnostic_arguments() -> None:
    frame = Frame(
        MessageType.ERROR,
        7,
        encode_error(
            ErrorResponse(bytes(16), MessageType.CAPTURE_ONCE, 6, 11, 0x1234, 0x5678, "")
        ),
        Flags.RESPONSE,
    )

    try:
        BridgeDeviceClient._raise_device_error(frame)
    except RuntimeError as error:
        assert "detail0=4660" in str(error)
        assert "detail1=22136" in str(error)
    else:
        raise AssertionError("device ERROR did not raise")


def _serve_capture_before_renew_response(
    connection: socket.socket,
    spool: CaptureSpool,
    renewal_fails_after_capture: bool = False,
) -> None:
    """Reproduce a periodic frame arriving while core waits for lease renewal."""

    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    device.config = _baseline_config()
    try:
        for _ in range(7):
            request = _read_frame(connection)
            responses = device.handle(request)
            if request.message_type is MessageType.RENEW_PERIODIC_LEASE:
                now_us[0] = 100_000
                capture_frame = device.poll()[0]
                raw_capture = encode_frame(capture_frame)
                pending = spool.store_capture(
                    raw_capture,
                    source_connection_id=41,
                    source_first_stream_offset=0,
                    source_last_stream_offset=len(raw_capture) - 1,
                    stored_utc_ns=123,
                )
                delivery = BridgeCaptureDelivery(
                    connection_id=43,
                    spool_record_id=pending.record_id,
                    source_connection_id=pending.source_connection_id,
                    source_first_stream_offset=pending.source_first_stream_offset,
                    source_last_stream_offset=pending.source_last_stream_offset,
                    stored_utc_ns=pending.stored_utc_ns,
                    inner_frame=pending.inner_frame,
                )
                connection.sendall(
                    encode_frame(
                        Frame(
                            MessageType.BRIDGE_CAPTURE_DELIVERY,
                            capture_frame.sequence,
                            encode_bridge_capture_delivery(delivery),
                            Flags.ASYNC,
                        )
                    )
                )
                receipt_frame = _read_frame(connection)
                receipt = decode_capture_committed_request(receipt_frame.payload)
                disposition = spool.mark_committed(
                    receipt.spool_record_id,
                    device_id=receipt.device_id,
                    boot_id=receipt.boot_id,
                    capture_id=receipt.capture_id,
                    inner_frame_crc32=receipt.inner_frame_crc32,
                )
                connection.sendall(
                    encode_frame(
                        Frame(
                            MessageType.CAPTURE_COMMITTED,
                            receipt_frame.sequence,
                            encode_capture_committed_response(
                                CaptureCommittedResponse(43, pending.record_id, disposition)
                            ),
                            Flags.RESPONSE,
                        )
                    )
                )
                if renewal_fails_after_capture:
                    # A finite schedule removes itself after its final capture.
                    # Real firmware can therefore reject the already-in-flight
                    # renewal even though the interleaved frame was committed.
                    responses = [
                        Frame(
                            MessageType.ERROR,
                            request.sequence,
                            encode_error(
                                ErrorResponse(
                                    bytes(16),
                                    int(MessageType.RENEW_PERIODIC_LEASE),
                                    6,
                                    5,
                                    0,
                                    0,
                                    "",
                                )
                            ),
                            Flags.RESPONSE,
                        )
                    ]
            for response in responses:
                connection.sendall(encode_frame(response))
        # Keep the transport alive after the injected renewal. The production
        # bridge is persistent; closing here would turn a successful count into
        # an unrelated connection-loss failure before the worker can finish.
        while connection.recv(1024):
            pass
    finally:
        connection.close()


def _serve_capture_before_stop_response(
    connection: socket.socket,
    spool: CaptureSpool,
) -> None:
    """Deliver one already-due frame after STOP begins but before its ACK."""

    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    device.config = _baseline_config()
    try:
        while True:
            request = _read_frame(connection)
            capture_frame = None
            if request.message_type is MessageType.STOP:
                now_us[0] = 100_000
                capture_frame = device.poll()[0]
            responses = device.handle(request)
            if capture_frame is not None:
                # Give the periodic worker time to observe stop_event. The
                # application must retain handler ownership until STOP ACK.
                time.sleep(0.05)
                raw_capture = encode_frame(capture_frame)
                pending = spool.store_capture(
                    raw_capture,
                    source_connection_id=51,
                    source_first_stream_offset=0,
                    source_last_stream_offset=len(raw_capture) - 1,
                    stored_utc_ns=456,
                )
                delivery = BridgeCaptureDelivery(
                    connection_id=53,
                    spool_record_id=pending.record_id,
                    source_connection_id=pending.source_connection_id,
                    source_first_stream_offset=pending.source_first_stream_offset,
                    source_last_stream_offset=pending.source_last_stream_offset,
                    stored_utc_ns=pending.stored_utc_ns,
                    inner_frame=pending.inner_frame,
                )
                connection.sendall(
                    encode_frame(
                        Frame(
                            MessageType.BRIDGE_CAPTURE_DELIVERY,
                            capture_frame.sequence,
                            encode_bridge_capture_delivery(delivery),
                            Flags.ASYNC,
                        )
                    )
                )
                receipt_frame = _read_frame(connection)
                receipt = decode_capture_committed_request(receipt_frame.payload)
                disposition = spool.mark_committed(
                    receipt.spool_record_id,
                    device_id=receipt.device_id,
                    boot_id=receipt.boot_id,
                    capture_id=receipt.capture_id,
                    inner_frame_crc32=receipt.inner_frame_crc32,
                )
                connection.sendall(
                    encode_frame(
                        Frame(
                            MessageType.CAPTURE_COMMITTED,
                            receipt_frame.sequence,
                            encode_capture_committed_response(
                                CaptureCommittedResponse(53, pending.record_id, disposition)
                            ),
                            Flags.RESPONSE,
                        )
                    )
                )
            for response in responses:
                connection.sendall(encode_frame(response))
    except ConnectionError:
        pass
    finally:
        connection.close()


def test_bridge_device_client_commits_before_releasing_spool(tmp_path: Path) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "spool.sqlite3")
    worker = threading.Thread(
        target=_serve_device_through_bridge,
        args=(bridge_socket, spool),
        daemon=True,
    )
    worker.start()
    device = BridgeDeviceClient(core_socket, timeout_s=1.0)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=CaptureStore(tmp_path / "core.sqlite3"),
    )

    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    capture = application.capture_once(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        trigger_source="SOFTWARE",
        sync_timeout_ms=0,
    )

    worker.join(timeout=1.0)
    assert not worker.is_alive()
    assert capture["sample_count"] == 2048
    assert spool.pending_records() == []
    assert application.captures(limit=10, cursor=None)["items"][0]["capture_id"] == capture["capture_id"]


def test_single_capture_keeps_applied_context_until_delivery_is_resolved(
    tmp_path: Path,
) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "single-transaction-spool.sqlite3")
    bridge_worker = threading.Thread(
        target=_serve_device_through_bridge,
        args=(bridge_socket, spool),
        daemon=True,
    )
    bridge_worker.start()
    entered_persistence = threading.Event()
    release_persistence = threading.Event()

    class PausedApplication(AcquisitionApplication):
        def _persist_capture(self, *args, **kwargs):
            entered_persistence.set()
            assert release_persistence.wait(timeout=1)
            return super()._persist_capture(*args, **kwargs)

    device = BridgeDeviceClient(core_socket, timeout_s=1.0)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    store = CaptureStore(tmp_path / "single-transaction-core.sqlite3")
    application = PausedApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    captures = []
    capture_errors = []

    def capture_once() -> None:
        try:
            captures.append(
                application.capture_once(
                    expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
                    expected_device_config_crc32=int(
                        applied["actual"]["device_config_crc32"]
                    ),
                    trigger_source="SOFTWARE",
                    sync_timeout_ms=0,
                )
            )
        except Exception as error:  # pragma: no cover - asserted below
            capture_errors.append(error)

    capture_worker = threading.Thread(target=capture_once)
    capture_worker.start()
    assert entered_persistence.wait(timeout=1)

    drafts = []
    draft_finished = threading.Event()

    def save_later_draft() -> None:
        drafts.append(application.save_draft({"sample_interval_ticks": 240}))
        draft_finished.set()

    draft_worker = threading.Thread(target=save_later_draft)
    draft_worker.start()
    assert draft_finished.wait(timeout=0.05) is False

    release_persistence.set()
    capture_worker.join(timeout=1)
    draft_worker.join(timeout=1)
    device.close()
    bridge_worker.join(timeout=1)

    assert capture_errors == []
    assert len(captures) == 1
    assert drafts[0]["requested"]["sample_interval_ticks"] == 240
    archived = store.get_capture(bytes.fromhex(captures[0]["capture_id"]))
    assert archived.sample_interval_ticks == 120
    assert archived.requested_config["sample_interval_ticks"] == 120
    assert archived.readback_config["sample_interval_ticks"] == 120
    assert archived.actual_config["sample_rate_hz"] == 200_000.0
    assert spool.pending_records() == []


class _SimulatedSerial:
    """Small blocking serial double driven by the real protocol simulator."""

    def __init__(self) -> None:
        self.device = SimulatedDevice()
        self.device.config = _baseline_config()
        self.pending = bytearray()
        self.condition = threading.Condition()
        self.closed = False

    def write(self, data: bytes) -> int:
        request = decode_frame(data)
        responses = b"".join(encode_frame(item) for item in self.device.handle(request))
        with self.condition:
            self.pending.extend(responses)
            self.condition.notify_all()
        return len(data)

    def read(self, size: int) -> bytes:
        deadline = time.monotonic() + 0.1
        with self.condition:
            while not self.pending and not self.closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self.condition.wait(remaining)
            data = bytes(self.pending[:size])
            del self.pending[:size]
            return data

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()


def test_real_bridge_proxy_forwards_commands_and_spools_capture(tmp_path: Path) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "proxy-spool.sqlite3")
    serial = _SimulatedSerial()
    worker = threading.Thread(
        target=proxy_bridge_session,
        kwargs={
            "core_connection": bridge_socket,
            "serial_connection": serial,
            "spool": spool,
            "connection_id": 19,
            "source_connection_id": 23,
            "commit_timeout_s": 1.0,
        },
        daemon=True,
    )
    worker.start()
    device = BridgeDeviceClient(core_socket, timeout_s=1.0)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=CaptureStore(tmp_path / "proxy-core.sqlite3"),
    )

    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    capture = application.capture_once(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        trigger_source="SOFTWARE",
        sync_timeout_ms=0,
    )
    device.close()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert capture["sample_count"] == 2048
    assert spool.pending_records() == []


def test_first_host_apply_uses_the_configuration_already_active_at_boot(
    tmp_path: Path,
) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "boot-config-spool.sqlite3")
    serial = _SimulatedSerial()
    serial.device.config = _baseline_config()
    errors: list[BaseException] = []

    def run_bridge() -> None:
        try:
            proxy_bridge_session(
                core_connection=bridge_socket,
                serial_connection=serial,
                spool=spool,
                connection_id=31,
                source_connection_id=37,
                commit_timeout_s=1.0,
            )
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run_bridge, daemon=True)
    worker.start()
    device = BridgeDeviceClient(core_socket, timeout_s=0.5)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=CaptureStore(tmp_path / "boot-config-core.sqlite3"),
    )

    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    device.close()
    worker.join(timeout=1.0)

    assert errors == []
    assert applied["state"] == "APPLIED"
    assert applied["actual"]["profile_sha256"] == _baseline_config().profile_sha256.hex()


def test_bridge_proxy_does_not_treat_an_idle_core_socket_as_disconnect(
    tmp_path: Path,
) -> None:
    core_socket, bridge_socket = socket.socketpair()
    bridge_socket.settimeout(0.01)
    serial = _SimulatedSerial()
    errors: list[BaseException] = []

    def run_bridge() -> None:
        try:
            proxy_bridge_session(
                core_connection=bridge_socket,
                serial_connection=serial,
                spool=CaptureSpool(tmp_path / "idle-spool.sqlite3"),
                connection_id=41,
                source_connection_id=43,
                commit_timeout_s=1.0,
            )
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run_bridge, daemon=True)
    worker.start()
    time.sleep(0.20)

    assert worker.is_alive()
    assert errors == []

    core_socket.close()
    worker.join(timeout=1.0)
    assert not worker.is_alive()


def test_reconnected_bridge_replays_pending_before_new_command(tmp_path: Path) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "replay-spool.sqlite3")
    raw_capture = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
    spool.store_capture(
        raw_capture,
        source_connection_id=31,
        source_first_stream_offset=100,
        source_last_stream_offset=100 + len(raw_capture) - 1,
        stored_utc_ns=123,
    )
    serial = _SimulatedSerial()
    errors: list[BaseException] = []

    def run_bridge() -> None:
        try:
            proxy_bridge_session(**{
            "core_connection": bridge_socket,
            "serial_connection": serial,
            "spool": spool,
            "connection_id": 29,
            "source_connection_id": 37,
            "commit_timeout_s": 1.0,
            })
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run_bridge, daemon=True)
    worker.start()
    store = CaptureStore(tmp_path / "replay-core.sqlite3")
    capture = decode_capture_data(decode_frame(raw_capture).payload)
    store.register_delivery_policy(
        device_id=capture.device_id,
        boot_id=capture.boot_id,
        session_id="61" * 16,
        save_policy="SAVE_ALL",
    )
    device = BridgeDeviceClient(core_socket, timeout_s=1.0, replay_store=store)

    deadline = time.monotonic() + 0.25
    while spool.pending_records() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert spool.pending_records() == []
    capabilities = device.capabilities()
    device.close()
    worker.join(timeout=1.0)

    assert errors == []
    assert capabilities.max_samples == 2048
    assert store.capture_count() == 1
    assert spool.pending_records() == []


def test_reconnectable_device_switches_sessions_without_retrying_failed_command() -> None:
    class Session:
        def __init__(self, label: str, *, fails: bool = False) -> None:
            self.label = label
            self.fails = fails
            self.status_calls = 0
            self.close_calls = 0
            self.hello = label
            self.boot_id = label.encode().ljust(16, b"0")
            self.device_id = b"device".ljust(16, b"0")

        def status(self) -> str:
            self.status_calls += 1
            if self.fails:
                raise ConnectionError("old session lost")
            return self.label

        def close(self) -> None:
            self.close_calls += 1

    old = Session("old", fails=True)
    new = Session("new")
    device = ReconnectableBridgeDeviceClient(old)
    assert device.published_session.connected is True
    assert device.published_session.hello == "old"
    assert device.published_session.session_generation == 0

    with pytest.raises(DeviceUnavailable, match="bridge session was lost"):
        device.status()
    assert old.status_calls == 1
    assert old.close_calls == 1
    assert device.connected is False
    assert device.session_generation == 1
    assert device.published_session.connected is False
    assert device.published_session.hello is None
    assert device.published_session.session_generation == 1

    device.replace(new)

    assert old.close_calls == 1
    assert device.session_generation == 2
    assert device.hello == "new"
    assert device.published_session.connected is True
    assert device.published_session.hello == "new"
    assert device.published_session.boot_id == new.boot_id
    assert device.published_session.session_generation == 2
    assert device.status() == "new"
    assert new.status_calls == 1


def test_reconnectable_device_can_wait_without_an_initial_bridge() -> None:
    class Session:
        hello = "ready"
        boot_id = b"boot".ljust(16, b"0")
        device_id = b"device".ljust(16, b"0")

        def status(self) -> str:
            return "connected"

        def close(self) -> None:
            pass

    device = ReconnectableBridgeDeviceClient()

    assert device.connected is False
    assert device.backend_kind == "BRIDGE"
    assert device.published_session.connected is False
    assert device.published_session.device_id is None
    assert device.published_session.session_generation == 0
    with pytest.raises(DeviceUnavailable, match="bridge device is not connected"):
        device.status()

    device.replace(Session())

    assert device.connected is True
    assert device.status() == "connected"
    assert device.session_generation == 1


def test_reconnectable_device_publishes_real_bridge_identity_without_locking() -> None:
    core_socket, bridge_socket = socket.socketpair()
    worker = threading.Thread(
        target=_serve_bridge_initialization,
        args=(bridge_socket,),
        daemon=True,
    )
    worker.start()
    client = BridgeDeviceClient(core_socket, timeout_s=1.0)
    device = ReconnectableBridgeDeviceClient(client)

    published = device.published_session
    assert published.connected is True
    assert published.device_id == client.device_id
    assert published.boot_id == client.boot_id

    device.close()
    assert device.published_session.connected is False
    assert device.published_session.device_id is None
    worker.join(timeout=1)


def test_periodic_capture_arriving_before_renew_response_is_not_lost(
    tmp_path: Path,
) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "interleaved-spool.sqlite3")
    worker = threading.Thread(
        target=_serve_capture_before_renew_response,
        args=(bridge_socket, spool),
        daemon=True,
    )
    worker.start()
    store = CaptureStore(tmp_path / "interleaved-core.sqlite3")
    device = BridgeDeviceClient(core_socket, timeout_s=1.0, replay_store=store)
    config = _baseline_config()
    device.apply_config(config)
    schedule = PeriodicSchedule(
        boot_id=device.boot_id,
        schedule_id=bytes.fromhex("44" * 16),
        profile_sha256=config.profile_sha256,
        device_config_crc32=config.device_config_crc32,
        period_us=100_000,
        capture_count=2,
        lease_timeout_ms=3_000,
    )
    device.start_periodic(schedule)
    observed = []

    def persist_interleaved(capture) -> bool:
        if capture.schedule_id != schedule.schedule_id:
            return False
        delivery = device.capture_delivery(capture.capture_id)
        result = store.commit_delivery(delivery)
        device.confirm_capture(result.receipt)
        device.release_capture(capture.capture_id)
        observed.append(capture.capture_id)
        return True

    device.set_async_capture_handler(persist_interleaved)
    renewal = device.renew_periodic(
        LeaseRenewal(device.boot_id, schedule.schedule_id, 1, 3_000)
    )
    device.close()
    worker.join(timeout=1.0)

    assert renewal.lease_sequence == 1
    assert len(observed) == 1
    assert store.capture_count() == 1
    assert spool.pending_records() == []


def test_application_counts_interleaved_periodic_capture(tmp_path: Path) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "application-interleaved-spool.sqlite3")
    worker = threading.Thread(
        target=_serve_capture_before_renew_response,
        args=(bridge_socket, spool),
        daemon=True,
    )
    worker.start()
    store = CaptureStore(tmp_path / "application-interleaved-core.sqlite3")
    device = BridgeDeviceClient(
        core_socket,
        timeout_s=1.0,
        replay_store=store,
    )
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    started = application.start_periodic(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        period_us=100_000,
        capture_count=1,
        lease_timeout_ms=1_000,
    )

    deadline = time.monotonic() + 1.5
    status = application.session(started["session_id"])
    while status["state"] == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.01)
        status = application.session(started["session_id"])
    device.close()
    worker.join(timeout=1.0)

    assert status["state"] == "COMPLETED", status
    assert status["capture_count"] == 1
    assert store.capture_count() == 1
    assert spool.pending_records() == []


def test_application_completes_when_final_capture_precedes_failed_renewal(
    tmp_path: Path,
) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "final-before-failed-renew-spool.sqlite3")
    worker = threading.Thread(
        target=_serve_capture_before_renew_response,
        args=(bridge_socket, spool, True),
        daemon=True,
    )
    worker.start()
    store = CaptureStore(tmp_path / "final-before-failed-renew-core.sqlite3")
    device = BridgeDeviceClient(
        core_socket,
        timeout_s=1.0,
        replay_store=store,
    )
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    started = application.start_periodic(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        period_us=100_000,
        capture_count=1,
        lease_timeout_ms=1_000,
    )

    deadline = time.monotonic() + 1.5
    status = application.session(started["session_id"])
    while status["state"] == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.01)
        status = application.session(started["session_id"])
    device.close()
    worker.join(timeout=1.0)

    assert status["state"] == "COMPLETED", status
    assert status["error"] is None
    assert status["capture_count"] == 1
    assert store.capture_count() == 1
    assert spool.pending_records() == []


def test_application_stop_counts_capture_arriving_before_stop_ack(
    tmp_path: Path,
) -> None:
    core_socket, bridge_socket = socket.socketpair()
    spool = CaptureSpool(tmp_path / "capture-before-stop-spool.sqlite3")
    worker = threading.Thread(
        target=_serve_capture_before_stop_response,
        args=(bridge_socket, spool),
        daemon=True,
    )
    worker.start()
    store = CaptureStore(tmp_path / "capture-before-stop-core.sqlite3")
    device = BridgeDeviceClient(core_socket, timeout_s=1.0, replay_store=store)
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')
    started = application.start_periodic(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        period_us=100_000,
        capture_count=0,
        lease_timeout_ms=1_000,
    )

    stopped = application.stop_periodic(
        session_id=started["session_id"],
        schedule_id=started["schedule_id"],
    )
    device.close()
    worker.join(timeout=1.0)

    assert stopped["state"] == "STOPPED"
    assert stopped["capture_count"] == 1
    assert store.capture_count() == 1
    assert spool.pending_records() == []
