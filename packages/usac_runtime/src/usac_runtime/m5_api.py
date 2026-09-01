"""Versioned REST adapter for the shared M5 acquisition application service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .application import AcquisitionApplication, ConfigurationEtagConflict
from .device_executor import ConfigValidationError


class ConfigChanges(BaseModel):
    """Semantic field updates; raw registers and SPI frames have no API field."""

    model_config = ConfigDict(extra="forbid")
    changes: dict[str, Any]


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

    return api
