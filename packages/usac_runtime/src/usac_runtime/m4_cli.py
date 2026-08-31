"""Small M4 operator CLI for reading and downloading committed captures."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from usac_runtime.core_store import CaptureRecord, CaptureStore


def _capture_id(value: str) -> bytes:
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("capture_id must be hexadecimal") from error
    if len(decoded) != 16:
        raise argparse.ArgumentTypeError("capture_id must encode exactly 16 bytes")
    return decoded


def _metadata(record: CaptureRecord) -> dict[str, object]:
    return {
        "capture_id": record.capture_id.hex(),
        "device_id": record.device_id.hex(),
        "boot_id": record.boot_id.hex(),
        "request_id": record.request_id.hex(),
        "profile_sha256": record.profile_sha256.hex(),
        "device_config_crc32": record.device_config_crc32,
        "capture_sequence": record.capture_sequence,
        "sample_interval_ticks": record.sample_interval_ticks,
        "burst_period_ticks": record.burst_period_ticks,
        "sample_count": record.sample_count,
        "pretrigger_count": record.pretrigger_count,
        "quality_flags": record.quality_flags,
        "interpolated": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M4 committed capture access")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "download"):
        command = commands.add_parser(name)
        command.add_argument("--sqlite", type=Path, required=True)
        command.add_argument("--capture-id", type=_capture_id, required=True)
        if name == "download":
            command.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    record = CaptureStore(args.sqlite).get_capture(args.capture_id)
    metadata = _metadata(record)
    if args.command == "show":
        print(json.dumps(metadata, indent=2))
        return 0

    output_directory = args.output_dir.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    prefix = record.capture_id.hex()
    raw_path = output_directory / f"{prefix}.usac"
    sample_path = output_directory / f"{prefix}.u16le"
    metadata_path = output_directory / f"{prefix}.json"
    raw_path.write_bytes(record.wire_frame)
    sample_path.write_bytes(record.sample_blob)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                **metadata,
                "raw_frame": str(raw_path),
                "samples": str(sample_path),
                "metadata": str(metadata_path),
            },
            indent=2,
        )
    )
    return 0
