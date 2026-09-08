"""Thin command-line client for the versioned M5 REST interface.

The CLI intentionally contains no TUSS4470 field table or validation rules.
Those remain in the shared core application so CLI, browser, and future BMS
callers always observe the same semantic configuration state.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiRequestError(RuntimeError):
    """The core API could not satisfy a CLI request."""


class HttpApiClient:
    def __init__(self, base_url: str, *, timeout_s: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def json(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[object, dict[str, str]]:
        request_headers = {"Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            self._base_url + path,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload, {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ApiRequestError(f"HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise ApiRequestError(f"core API unavailable: {error.reason}") from error

    def bytes(self, path: str) -> bytes:
        try:
            with urlopen(self._base_url + path, timeout=self._timeout_s) as response:
                return response.read()
        except (HTTPError, URLError) as error:
            raise ApiRequestError(f"raw download failed: {error}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TUSS4470 acquisition core client")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("USAC_API_URL", "http://127.0.0.1:8000"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("health", "device", "schema", "config"):
        sub.add_parser(name)

    for name in ("draft", "validate", "apply"):
        command = sub.add_parser(name)
        command.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")

    capture = sub.add_parser("capture")
    capture.add_argument("--trigger", default="SOFTWARE")
    capture.add_argument("--sync-timeout-ms", type=int, default=0)
    capture.add_argument(
        "--save-policy",
        choices=("SAVE_NONE", "SAVE_ALL", "SAVE_LAST"),
        default="SAVE_ALL",
    )

    periodic = sub.add_parser("periodic-start")
    periodic.add_argument("--period-us", type=int, required=True)
    periodic.add_argument("--count", type=int, default=0)
    periodic.add_argument("--lease-timeout-ms", type=int, default=3_000)
    periodic.add_argument(
        "--save-policy",
        choices=("SAVE_NONE", "SAVE_ALL", "SAVE_LAST"),
        default="SAVE_ALL",
    )

    periodic_stop = sub.add_parser("periodic-stop")
    periodic_stop.add_argument("session_id")
    periodic_stop.add_argument("schedule_id")

    sweep = sub.add_parser("sweep")
    sweep.add_argument("field")
    sweep.add_argument("values", help="JSON array of discrete semantic values")
    sweep.add_argument("--loops", type=int, default=1)
    sweep.add_argument("--start-delay-ms", type=int, default=0)
    sweep.add_argument("--loop-delay-ms", type=int, default=0)
    sweep.add_argument("--trigger", default="SOFTWARE")
    sweep.add_argument("--sync-timeout-ms", type=int, default=0)
    sweep.add_argument(
        "--save-policy",
        choices=("SAVE_NONE", "SAVE_ALL", "SAVE_LAST"),
        default="SAVE_ALL",
    )

    sweep_stop = sub.add_parser("sweep-stop")
    sweep_stop.add_argument("session_id")
    session = sub.add_parser("session")
    session.add_argument("session_id")
    history = sub.add_parser("history")
    history.add_argument("--limit", type=int, default=50)
    history.add_argument("--cursor", type=int)
    history.add_argument("--session-id")
    show = sub.add_parser("show")
    show.add_argument("capture_id")
    download = sub.add_parser("download")
    download.add_argument("capture_id")
    download.add_argument("output")
    return parser


def _changes(assignments: list[str]) -> dict[str, object]:
    changes: dict[str, object] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"expected FIELD=VALUE, got {assignment!r}")
        name, value_text = assignment.split("=", 1)
        if not name:
            raise ValueError("field name must not be empty")
        try:
            value = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text
        changes[name] = value
    return changes


def _applied_identity(client) -> tuple[str, int, str]:
    config, headers = client.json("GET", "/api/v1/config")
    if config.get("state") != "APPLIED":
        raise ApiRequestError("no APPLIED configuration is available")
    actual = config["actual"]
    return actual["profile_sha256"], actual["device_config_crc32"], headers.get("etag", "")


def _config_etag(client) -> str:
    """Return the current config revision even before its first application."""

    _, headers = client.json("GET", "/api/v1/config")
    etag = headers.get("etag", "")
    if not etag:
        raise ApiRequestError("configuration response did not include an ETag")
    return etag


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(
    argv: Sequence[str] | None = None,
    *,
    client=None,
) -> int:
    args = _parser().parse_args(argv)
    client = client or HttpApiClient(args.base_url)
    try:
        if args.command in {"health", "device", "schema", "config"}:
            paths = {
                "health": "/api/v1/health",
                "device": "/api/v1/device",
                "schema": "/api/v1/config/schema",
                "config": "/api/v1/config",
            }
            payload, _ = client.json("GET", paths[args.command])
        elif args.command == "draft":
            payload, _ = client.json(
                "PATCH", "/api/v1/config", body={"changes": _changes(args.set)}
            )
        elif args.command == "validate":
            payload, _ = client.json(
                "POST", "/api/v1/config/validate", body={"changes": _changes(args.set)}
            )
        elif args.command == "apply":
            etag = _config_etag(client)
            payload, _ = client.json(
                "PUT",
                "/api/v1/config",
                body={"changes": _changes(args.set)},
                headers={"If-Match": etag},
            )
        elif args.command == "capture":
            profile, crc, _ = _applied_identity(client)
            payload, _ = client.json(
                "POST",
                "/api/v1/captures",
                body={
                    "expected_profile_sha256": profile,
                    "expected_device_config_crc32": crc,
                    "trigger_source": args.trigger,
                    "sync_timeout_ms": args.sync_timeout_ms,
                    "save_policy": args.save_policy,
                },
            )
        elif args.command == "periodic-start":
            profile, crc, _ = _applied_identity(client)
            payload, _ = client.json(
                "POST",
                "/api/v1/periodic/start",
                body={
                    "expected_profile_sha256": profile,
                    "expected_device_config_crc32": crc,
                    "period_us": args.period_us,
                    "capture_count": args.count,
                    "lease_timeout_ms": args.lease_timeout_ms,
                    "save_policy": args.save_policy,
                },
            )
        elif args.command == "periodic-stop":
            payload, _ = client.json(
                "POST",
                "/api/v1/periodic/stop",
                body={"session_id": args.session_id, "schedule_id": args.schedule_id},
            )
        elif args.command == "sweep":
            values = json.loads(args.values)
            if not isinstance(values, list):
                raise ValueError("sweep values must be a JSON array")
            profile, crc, _ = _applied_identity(client)
            payload, _ = client.json(
                "POST",
                "/api/v1/sweeps",
                body={
                    "expected_profile_sha256": profile,
                    "expected_device_config_crc32": crc,
                    "field": args.field,
                    "values": values,
                    "loops": args.loops,
                    "start_delay_ms": args.start_delay_ms,
                    "loop_delay_ms": args.loop_delay_ms,
                    "trigger_source": args.trigger,
                    "sync_timeout_ms": args.sync_timeout_ms,
                    "save_policy": args.save_policy,
                },
            )
        elif args.command == "sweep-stop":
            payload, _ = client.json("POST", f"/api/v1/sweeps/{args.session_id}/stop")
        elif args.command == "session":
            payload, _ = client.json("GET", f"/api/v1/sessions/{args.session_id}")
        elif args.command == "history":
            path = f"/api/v1/captures?limit={args.limit}"
            if args.cursor is not None:
                path += f"&cursor={args.cursor}"
            if args.session_id is not None:
                path += f"&session_id={args.session_id}"
            payload, _ = client.json("GET", path)
        elif args.command == "show":
            payload, _ = client.json("GET", f"/api/v1/captures/{args.capture_id}")
        else:
            raw = client.bytes(f"/api/v1/captures/{args.capture_id}/samples")
            target = Path(args.output)
            target.write_bytes(raw)
            payload = {"output": str(target), "bytes": len(raw)}
        _emit(payload)
        return 0
    except (ApiRequestError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
