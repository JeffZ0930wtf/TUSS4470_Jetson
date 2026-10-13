"""Versioned REST adapter for the shared acquisition application service."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .application import (
    AcquisitionApplication,
    CaptureStorageUnavailable,
    ConfigurationEtagConflict,
    SessionConflict,
)
from .core_store import SavePolicy
from .device_executor import ConfigConflictError, ConfigValidationError, DeviceUnavailable


_WEB_ROOT = Path(__file__).with_name("web")


class ConfigChanges(BaseModel):
    """Semantic field updates; raw registers and SPI frames have no API field."""

    model_config = ConfigDict(extra="forbid")
    changes: dict[str, Any]


class CaptureRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_profile_sha256: str
    expected_device_config_crc32: int
    trigger_source: str = "SOFTWARE"
    sync_timeout_ms: int = 0
    save_policy: SavePolicy = SavePolicy.SAVE_ALL
    group_id: str | None = None


class PeriodicStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_profile_sha256: str
    expected_device_config_crc32: int
    period_us: int
    capture_count: int
    lease_timeout_ms: int
    save_policy: SavePolicy = SavePolicy.SAVE_ALL
    group_id: str | None = None


class PeriodicStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    schedule_id: str


class SweepStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_profile_sha256: str
    expected_device_config_crc32: int
    field: str
    values: list[Any]
    loops: int = 1
    start_delay_ms: int = 0
    loop_delay_ms: int = 0
    trigger_source: str = "SOFTWARE"
    sync_timeout_ms: int = 0
    save_policy: SavePolicy = SavePolicy.SAVE_ALL
    group_id: str | None = None


class ExperimentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    notes: str = ""


class ExperimentPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    notes: str | None = None


class GroupCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    cell_id: str = ""
    notes: str = ""


class GroupPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    cell_id: str | None = None
    notes: str | None = None


class CaptureAssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_ids: list[str]
    group_id: str | None


class _TemporaryZipResponse(StreamingResponse):
    def __init__(self, file, *, filename: str) -> None:
        self._temporary_file = file
        super().__init__(
            iter(lambda: file.read(64 * 1024), b""),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._temporary_file.close()


def _capture_ids(values: list[str]) -> tuple[bytes, ...]:
    identifiers: list[bytes] = []
    for value in values:
        if len(value) != 32 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("capture_ids must contain 32-character hexadecimal IDs")
        identifiers.append(bytes.fromhex(value))
    distinct = tuple(dict.fromkeys(identifiers))
    if not 1 <= len(distinct) <= 500:
        raise ValueError("capture_ids must contain 1..500 different captures")
    return distinct


def _validation_detail(error: ConfigValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": item.field,
            "code": item.code.value,
            "message": item.message,
        }
        for item in error.errors
    ]


def create_api(application: AcquisitionApplication) -> FastAPI:
    """Create an API whose handlers contain no duplicated device semantics."""

    api = FastAPI(title="TUSS4470 Ultrasonic Acquisition", version="1")
    web_root = _WEB_ROOT
    # Keep each hash URL bound to the bytes this process serves so new HTML
    # cannot mix with stale JS; production asset updates require API restart.
    page = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_bytes()
    styles = (web_root / "styles.css").read_bytes()
    script_hash = hashlib.sha256(script).hexdigest()
    styles_hash = hashlib.sha256(styles).hexdigest()
    page = page.replace(
        'src="/assets/app.js"', f'src="/assets/app.js?v={script_hash}"'
    ).replace(
        'href="/assets/styles.css"', f'href="/assets/styles.css?v={styles_hash}"'
    )
    no_cache_headers = {"Cache-Control": "no-cache"}

    @api.get("/", include_in_schema=False)
    def web_console() -> Response:
        return Response(
            content=page,
            media_type="text/html",
            headers=no_cache_headers,
        )

    @api.get("/assets/app.js", include_in_schema=False)
    def web_script() -> Response:
        return Response(
            content=script,
            media_type="text/javascript",
            headers=no_cache_headers,
        )

    @api.get("/assets/styles.css", include_in_schema=False)
    def web_styles() -> Response:
        return Response(
            content=styles,
            media_type="text/css",
            headers=no_cache_headers,
        )

    @api.get("/api/v1/health")
    def health() -> dict[str, str]:
        return application.health()

    @api.get("/api/v1/storage")
    def storage() -> dict[str, str]:
        try:
            return application.storage()
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.get("/api/v1/experiments")
    def experiments() -> dict[str, object]:
        try:
            return {"items": application.list_experiments()}
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.post("/api/v1/experiments", status_code=201)
    def create_experiment(body: ExperimentCreateBody) -> dict[str, object]:
        try:
            return application.create_experiment(name=body.name, notes=body.notes)
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.patch("/api/v1/experiments/{experiment_id}")
    def update_experiment(
        experiment_id: str, body: ExperimentPatchBody
    ) -> dict[str, object]:
        try:
            return application.update_experiment(
                experiment_id,
                body.model_dump(exclude_unset=True),
            )
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/experiments/{experiment_id}/groups")
    def groups(experiment_id: str) -> dict[str, object]:
        try:
            return {"items": application.list_groups(experiment_id)}
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.post("/api/v1/experiments/{experiment_id}/groups", status_code=201)
    def create_group(
        experiment_id: str, body: GroupCreateBody
    ) -> dict[str, object]:
        try:
            return application.create_group(
                experiment_id,
                name=body.name,
                cell_id=body.cell_id,
                notes=body.notes,
            )
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.patch("/api/v1/groups/{group_id}")
    def update_group(group_id: str, body: GroupPatchBody) -> dict[str, object]:
        try:
            return application.update_group(
                group_id,
                body.model_dump(exclude_unset=True),
            )
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.post("/api/v1/captures/group-assignment")
    def assign_capture_group(body: CaptureAssignmentBody) -> dict[str, int]:
        try:
            assigned_count = application.assign_capture_group(
                _capture_ids(body.capture_ids),
                body.group_id,
            )
            return {"assigned_count": assigned_count}
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/groups/{group_id}/export.zip")
    def export_group(group_id: str) -> Response:
        try:
            application.grouping_metadata(group_id)
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        temporary_file = tempfile.TemporaryFile(mode="w+b")
        try:
            application.write_group_export(group_id, temporary_file)
            temporary_file.seek(0)
        except KeyError as error:
            temporary_file.close()
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            temporary_file.close()
            raise HTTPException(status_code=422, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            temporary_file.close()
            raise HTTPException(status_code=503, detail=str(error)) from error
        except BaseException:
            temporary_file.close()
            raise
        return _TemporaryZipResponse(
            temporary_file,
            filename=f"group-{group_id}.zip",
        )

    @api.get("/api/v1/device")
    def device() -> dict[str, object]:
        return application.device()

    @api.get("/api/v1/config/schema")
    def schema() -> dict[str, object]:
        return application.schema()

    @api.get("/api/v1/config")
    def config() -> JSONResponse:
        return JSONResponse(application.config(), headers={"ETag": application.etag()})

    @api.post("/api/v1/config/validate")
    def validate_config(body: ConfigChanges) -> dict[str, object]:
        try:
            return application.validate_config(body.changes)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.patch("/api/v1/config")
    def save_draft(body: ConfigChanges) -> dict[str, object]:
        try:
            return application.save_draft(body.changes)
        except SessionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.put("/api/v1/config")
    def apply_config(
        body: ConfigChanges,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> JSONResponse:
        if if_match is None:
            raise HTTPException(status_code=428, detail="If-Match is required")
        try:
            payload = application.apply_config(
                body.changes,
                expected_etag=if_match,
            )
        except ConfigurationEtagConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SessionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ConfigValidationError as error:
            raise HTTPException(
                status_code=422,
                detail=_validation_detail(error),
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(payload, headers={"ETag": application.etag()})

    @api.post("/api/v1/captures", status_code=201)
    def capture_once(body: CaptureRequestBody) -> dict[str, object]:
        try:
            return application.capture_once(
                expected_profile_sha256=body.expected_profile_sha256,
                expected_device_config_crc32=body.expected_device_config_crc32,
                trigger_source=body.trigger_source,
                sync_timeout_ms=body.sync_timeout_ms,
                save_policy=body.save_policy,
                group_id=body.group_id,
            )
        except ConfigConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except SessionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/captures")
    def captures(
        limit: int = 50,
        cursor: str | None = None,
        session_id: str | None = None,
        experiment_id: str | None = None,
        group_id: str | None = None,
        ungrouped: bool = False,
    ) -> dict[str, object]:
        try:
            return application.captures(
                limit=limit,
                cursor=cursor,
                session_id=session_id,
                experiment_id=experiment_id,
                group_id=group_id,
                ungrouped=ungrouped,
            )
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/captures/{capture_id}")
    def capture(capture_id: str) -> dict[str, object]:
        try:
            return application.capture(capture_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/captures/{capture_id}/samples")
    def capture_samples(capture_id: str) -> Response:
        try:
            samples, storage = application.capture_samples(capture_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return Response(
            samples,
            media_type="application/octet-stream",
            headers={"X-USAC-Storage": storage},
        )

    @api.post("/api/v1/periodic/start", status_code=202)
    def start_periodic(body: PeriodicStartBody) -> dict[str, object]:
        try:
            return application.start_periodic(
                expected_profile_sha256=body.expected_profile_sha256,
                expected_device_config_crc32=body.expected_device_config_crc32,
                period_us=body.period_us,
                capture_count=body.capture_count,
                lease_timeout_ms=body.lease_timeout_ms,
                save_policy=body.save_policy,
                group_id=body.group_id,
            )
        except (ConfigConflictError, SessionConflict) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.post("/api/v1/periodic/stop")
    def stop_periodic(body: PeriodicStopBody) -> dict[str, object]:
        try:
            return application.stop_periodic(
                session_id=body.session_id,
                schedule_id=body.schedule_id,
            )
        except SessionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/sessions/{session_id}")
    def session(session_id: str) -> dict[str, object]:
        try:
            return application.session(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.post("/api/v1/sweeps", status_code=202)
    def start_sweep(body: SweepStartBody) -> dict[str, object]:
        try:
            return application.start_sweep(
                expected_profile_sha256=body.expected_profile_sha256,
                expected_device_config_crc32=body.expected_device_config_crc32,
                field_name=body.field,
                values=tuple(body.values),
                loops=body.loops,
                start_delay_ms=body.start_delay_ms,
                loop_delay_ms=body.loop_delay_ms,
                trigger_source=body.trigger_source,
                sync_timeout_ms=body.sync_timeout_ms,
                save_policy=body.save_policy,
                group_id=body.group_id,
            )
        except (ConfigConflictError, SessionConflict) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/sweeps/{sweep_id}")
    def sweep(sweep_id: str) -> dict[str, object]:
        try:
            return application.sweep(sweep_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.post("/api/v1/sweeps/{sweep_id}/stop")
    def stop_sweep(sweep_id: str) -> dict[str, object]:
        try:
            return application.stop_sweep(sweep_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return api
