"""Operator CLI for the M3 IO2 timing gate without ultrasonic capture."""

from __future__ import annotations

import argparse
import json
import secrets
import time
from collections.abc import Sequence

from usac_runtime.m3_capture import run_m3_loopback


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M3 fixed d10x4_v1 IO2 loopback only: reapplies the exact profile "
            "and returns timer-capture evidence without CAPTURE_ONCE."
        )
    )
    parser.add_argument("--port", required=True, help="COMx or /dev/ttyACM* device")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument(
        "--confirm-external-vpwr-7v",
        action="store_true",
        help="confirm stable external VPWR is present",
    )
    parser.add_argument(
        "--confirm-loopback-pin40-2k2-pin38",
        action="store_true",
        help="confirm pin40 is connected through 2.2 kOhm to pin38",
    )
    parser.add_argument(
        "--expected-device-id",
        help="optional strict 32-character lowercase hexadecimal device_id",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    if not args.confirm_external_vpwr_7v:
        raise SystemExit("refusing M3 loopback without --confirm-external-vpwr-7v")
    if not args.confirm_loopback_pin40_2k2_pin38:
        raise SystemExit(
            "refusing M3 loopback without --confirm-loopback-pin40-2k2-pin38"
        )
    expected_device_id: bytes | None = None
    if args.expected_device_id is not None:
        expected = args.expected_device_id
        if len(expected) != 32 or expected != expected.lower():
            raise SystemExit(
                "--expected-device-id must be 32 lowercase hexadecimal characters"
            )
        try:
            expected_device_id = bytes.fromhex(expected)
        except ValueError as error:
            raise SystemExit("--expected-device-id is not valid hexadecimal") from error

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
        result = run_m3_loopback(
            connection,
            host_nonce=secrets.token_bytes(16),
            set_config_request_id=secrets.token_bytes(16),
            loopback_request_id=secrets.token_bytes(16),
            timeout_s=args.timeout_s,
        )
        if expected_device_id is not None and result.smoke.device_id != expected_device_id:
            raise RuntimeError(
                "device_id mismatch: "
                f"{result.smoke.device_id.hex()} != {expected_device_id.hex()}"
            )
        loopback = result.loopback
        print(
            json.dumps(
                {
                    "mode": "m3_io2_loopback_only",
                    "burst_command_sent": False,
                    "capture_command_sent": False,
                    "io2_loopback_generated": True,
                    "device_id": result.smoke.device_id.hex(),
                    "boot_id": result.smoke.boot_id.hex(),
                    "result_flags": loopback.result_flags,
                    "captured_edges": loopback.captured_edges,
                    "capture_ticks": list(loopback.capture_ticks),
                    "minimum_interval_ticks": loopback.minimum_interval_ticks,
                    "maximum_interval_ticks": loopback.maximum_interval_ticks,
                    "final_io2_level": loopback.final_io2_level,
                    "pre_dev_stat": loopback.pre_dev_stat,
                    "post_dev_stat": loopback.post_dev_stat,
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
