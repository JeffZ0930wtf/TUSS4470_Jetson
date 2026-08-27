from __future__ import annotations

import argparse
import json
import secrets
import time
from collections.abc import Sequence

from usac_runtime.m2_smoke import run_m2_smoke


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M2 no-Burst hardware smoke test: HELLO + GET_CONFIG, with an optional "
            "exact reapply of the returned config. This command never sends CAPTURE."
        )
    )
    parser.add_argument("--port", required=True, help="COMx or /dev/ttyACM* device")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument(
        "--hello-only",
        action="store_true",
        help="USB/session identity check only; safe when external VPWR is off",
    )
    parser.add_argument(
        "--apply-same-config",
        action="store_true",
        help="after readback, SET_CONFIG the exact verified bytes once; still no Burst",
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
    if args.hello_only and args.apply_same_config:
        raise SystemExit("--hello-only and --apply-same-config are mutually exclusive")
    if args.expected_device_id is not None:
        expected = args.expected_device_id
        if len(expected) != 32 or expected != expected.lower():
            raise SystemExit("--expected-device-id must be 32 lowercase hexadecimal characters")
        try:
            expected_device_id = bytes.fromhex(expected)
        except ValueError as error:
            raise SystemExit("--expected-device-id is not valid hexadecimal") from error
    else:
        expected_device_id = None

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
        result = run_m2_smoke(
            connection,
            host_nonce=secrets.token_bytes(16),
            apply_same_config=args.apply_same_config,
            hello_only=args.hello_only,
            timeout_s=args.timeout_s,
        )
        if expected_device_id is not None and result.device_id != expected_device_id:
            raise RuntimeError(
                f"device_id mismatch: {result.device_id.hex()} != {expected_device_id.hex()}"
            )
        print(
            json.dumps(
                {
                    "mode": (
                        "hello_only"
                        if args.hello_only
                        else "apply_same_config"
                        if result.applied_same_config
                        else "read_only"
                    ),
                    "burst_command_sent": False,
                    "device_id": result.device_id.hex(),
                    "boot_id": result.boot_id.hex(),
                    "firmware_version": ".".join(map(str, result.firmware_version)),
                    "device_state": result.device_state,
                    "profile_sha256": (
                        result.config.profile_sha256.hex() if result.config else None
                    ),
                    "device_config_crc32": (
                        f"{result.config.device_config_crc32:08x}"
                        if result.config
                        else None
                    ),
                    "sample_interval_ticks": (
                        result.config.sample_interval_ticks if result.config else None
                    ),
                    "burst_period_ticks": (
                        result.config.burst_period_ticks if result.config else None
                    ),
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
