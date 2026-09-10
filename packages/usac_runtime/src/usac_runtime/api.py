"""Versioned REST adapter for the shared acquisition application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
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


class PeriodicStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_profile_sha256: str
    expected_device_config_crc32: int
    period_us: int
    capture_count: int
    lease_timeout_ms: int
    save_policy: SavePolicy = SavePolicy.SAVE_ALL


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

    @api.get("/", include_in_schema=False)
    def web_console() -> FileResponse:
        return FileResponse(_WEB_ROOT / "index.html", media_type="text/html")

    @api.get("/assets/app.js", include_in_schema=False)
    def web_script() -> FileResponse:
        return FileResponse(_WEB_ROOT / "app.js", media_type="text/javascript")

    @api.get("/assets/styles.css", include_in_schema=False)
    def web_styles() -> FileResponse:
        return FileResponse(_WEB_ROOT / "styles.css", media_type="text/css")

    @api.get("/api/v1/health")
    def health() -> dict[str, str]:
        return application.health()

    @api.get("/api/v1/storage")
    def storage() -> dict[str, str]:
        try:
            return application.storage()
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

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
            )
        except ConfigConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except SessionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @api.get("/api/v1/captures")
    def captures(
        limit: int = 50,
        cursor: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        try:
            return application.captures(
                limit=limit,
                cursor=cursor,
                session_id=session_id,
            )
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
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
            )
        except (ConfigConflictError, SessionConflict) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
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
            )
        except (ConfigConflictError, SessionConflict) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaptureStorageUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except DeviceUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
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
