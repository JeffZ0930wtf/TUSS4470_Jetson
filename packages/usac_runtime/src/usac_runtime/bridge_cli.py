"""Windows M4 bridge CLI: replay pending data or acquire one safe waveform."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from usac_protocol.frame import HEADER_SIZE
from usac_runtime.bridge import (
    CountingConnection,
    deliver_spool,
    new_sqlite_integer_id,
    spool_artifacts,
)
from usac_runtime.config import RuntimeConfig, load_runtime_config
from usac_runtime.m3_capture import M3CaptureProgress, run_m3_capture
from usac_runtime.reconnect import retry_connection
from usac_runtime.spool import CaptureSpool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M4 Windows capture bridge")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("replay", "capture"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--core-host", default="127.0.0.1")
        command.add_argument("--core-port", type=int, default=8765)
        command.add_argument("--timeout-s", type=float, default=3.0)
        command.add_argument("--reconnect-attempts", type=int, default=3)
        command.add_argument("--reconnect-delay-s", type=float, default=0.1)
        if name == "capture":
            command.add_argument("--confirm-external-vpwr-7v", action="store_true")
            command.add_argument(
                "--confirm-loopback-pin40-2k2-pin38", action="store_true"
            )
    return parser


def _spool(config_path: Path) -> tuple[CaptureSpool, RuntimeConfig]:
    config = load_runtime_config(config_path)
    return CaptureSpool(config.storage.spool_dir / "bridge-spool.sqlite3"), config


def _replay(args: argparse.Namespace) -> int:
    spool, _ = _spool(args.config)
    delivered = retry_connection(
        lambda: deliver_spool(
            spool,
            core_host=args.core_host,
            core_port=args.core_port,
            timeout_s=args.timeout_s,
        ),
        attempts=args.reconnect_attempts,
        initial_delay_s=args.reconnect_delay_s,
    )
    print(json.dumps({"mode": "m4_replay", "delivered": delivered}, indent=2))
    return 0


def _capture(args: argparse.Namespace) -> int:
    if not args.confirm_external_vpwr_7v:
        raise SystemExit("refusing M4 capture without confirmed external VPWR 7 V")
    if not args.confirm_loopback_pin40_2k2_pin38:
        raise SystemExit(
            "refusing M4 capture without confirmed pin40-to-2.2k-to-pin38 loopback"
        )
    spool, config = _spool(args.config)
    try:
        import serial
    except ImportError as error:
        raise SystemExit("pyserial is required for M4 capture") from error

    serial_connection = serial.Serial()
    serial_connection.port = config.serial.port
    serial_connection.baudrate = config.serial.baudrate
    serial_connection.timeout = min(args.timeout_s, 0.1)
    serial_connection.write_timeout = args.timeout_s
    serial_connection.dtr = False
    counting = CountingConnection(serial_connection)
    first_stream_offset: int | None = None

    def progress(event: M3CaptureProgress) -> None:
        nonlocal first_stream_offset
        if event.stage == "capture_data_header_received":
            first_stream_offset = counting.received_bytes - HEADER_SIZE
        print(
            f"M4 bridge stage={event.stage} received_bytes={event.received_bytes}",
            file=sys.stderr,
            flush=True,
        )

    try:
        # Only opening the byte stream is retried. Once DTR/HELLO begins, this
        # command never repeats capture or Burst after a transport failure.
        retry_connection(
            serial_connection.open,
            attempts=args.reconnect_attempts,
            initial_delay_s=args.reconnect_delay_s,
        )
        serial_connection.dtr = False
        time.sleep(0.150)
        serial_connection.reset_input_buffer()
        serial_connection.reset_output_buffer()
        serial_connection.dtr = True
        staging = config.storage.data_dir / "bridge" / "staging"
        result = run_m3_capture(
            counting,
            host_nonce=secrets.token_bytes(16),
            set_config_request_id=secrets.token_bytes(16),
            loopback_request_id=secrets.token_bytes(16),
            capture_request_id=secrets.token_bytes(16),
            output_directory=staging,
            timeout_s=args.timeout_s,
            progress=progress,
        )
        if first_stream_offset is None:
            raise RuntimeError("capture stream offset was not observed")
        source_connection_id = new_sqlite_integer_id()
        pending = spool_artifacts(
            spool,
            raw_path=result.raw_frame_path,
            metadata_path=result.metadata_path,
            samples_path=result.samples_path,
            source_connection_id=source_connection_id,
            source_first_stream_offset=first_stream_offset,
            stored_utc_ns=time.time_ns(),
        )
        delivered = deliver_spool(
            spool,
            core_host=args.core_host,
            core_port=args.core_port,
            timeout_s=args.timeout_s,
        )
        print(
            json.dumps(
                {
                    "mode": "m4_single_capture",
                    "capture_id": pending.capture_id.hex(),
                    "sample_count": result.capture.sample_count,
                    "delivered": delivered,
                    "sqlite_committed": True,
                    "interpolated": False,
                },
                indent=2,
            )
        )
        return 0
    finally:
        if serial_connection.is_open:
            serial_connection.dtr = False
            time.sleep(0.100)
            serial_connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    if args.reconnect_attempts < 1 or args.reconnect_delay_s < 0:
        raise SystemExit("reconnect attempts must be positive and delay non-negative")
    if args.command == "replay":
        return _replay(args)
    return _capture(args)
