"""Operator CLI for the single authorized M3 waveform capture."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from usac_runtime.m3_capture import M3CaptureProgress, run_m3_capture


def _print_progress(event: M3CaptureProgress) -> None:
    """Keep human diagnostics separate from the successful stdout JSON."""

    fields = [f"stage={event.stage}", f"received_bytes={event.received_bytes}"]
    if event.expected_bytes is not None:
        fields.append(f"expected_bytes={event.expected_bytes}")
    print("M3 progress: " + " ".join(fields), file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M3 fixed d10x4_v1 capture: verified IO2 loopback followed by one "
            "Pulse=1 acquisition and lossless artifact save."
        )
    )
    parser.add_argument("--port", required=True, help="COMx or /dev/ttyACM* device")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument(
        "--confirm-external-vpwr-7v",
        action="store_true",
        help="confirm measured external VPWR is present; USB-only must never use this command",
    )
    parser.add_argument(
        "--confirm-loopback-pin40-2k2-pin38",
        action="store_true",
        help="confirm pin40 is connected through 2.2 kOhm to pin38",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    if not args.confirm_external_vpwr_7v:
        raise SystemExit("refusing M3 capture without --confirm-external-vpwr-7v")
    if not args.confirm_loopback_pin40_2k2_pin38:
        raise SystemExit(
            "refusing M3 capture without --confirm-loopback-pin40-2k2-pin38"
        )

    try:
        import serial
    except ImportError as error:
        raise SystemExit("pyserial is required; install the project dependencies") from error

    connection = serial.Serial()
    connection.port = args.port
    connection.baudrate = args.baudrate
    connection.timeout = min(args.timeout_s, 0.1)
    connection.write_timeout = args.timeout_s
    connection.dtr = False
    try:
        connection.open()
        connection.dtr = False
        time.sleep(0.150)
        connection.reset_input_buffer()
        connection.reset_output_buffer()
        connection.dtr = True
        result = run_m3_capture(
            connection,
            host_nonce=secrets.token_bytes(16),
            set_config_request_id=secrets.token_bytes(16),
            loopback_request_id=secrets.token_bytes(16),
            capture_request_id=secrets.token_bytes(16),
            output_directory=args.output_dir,
            timeout_s=args.timeout_s,
            progress=_print_progress,
        )
        print(
            json.dumps(
                {
                    "mode": "m3_fixed_single_capture",
                    "burst_command_sent": True,
                    "device_id": result.capture.device_id.hex(),
                    "capture_id": result.capture.capture_id.hex(),
                    "sample_count": result.capture.sample_count,
                    "pretrigger_count": result.capture.pretrigger_count,
                    "sample_interval_ticks": result.capture.sample_interval_ticks,
                    "burst_period_ticks": result.capture.burst_period_ticks,
                    "quality_flags": result.capture.quality_flags,
                    "raw_frame": str(result.raw_frame_path),
                    "metadata": str(result.metadata_path),
                    "samples": str(result.samples_path),
                },
                indent=2,
            )
        )
        return 0
    finally:
        if connection.is_open:
            connection.dtr = False
            time.sleep(0.100)
            connection.close()
