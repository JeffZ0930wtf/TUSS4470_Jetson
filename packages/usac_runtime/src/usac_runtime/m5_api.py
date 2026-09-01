"""Versioned REST adapter for the shared M5 acquisition application service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from .application import (
    AcquisitionApplication,
    CaptureStorageUnavailable,
    ConfigurationEtagConflict,
)
from .device_executor import ConfigConflictError, ConfigValidationError


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

    @api.get("/api/v1/health")
    def health() -> dict[str, str]:
        return application.health()

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
            )
        except ConfigConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
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
            samples = application.capture_samples(capture_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return Response(samples, media_type="application/octet-stream")

    return api
