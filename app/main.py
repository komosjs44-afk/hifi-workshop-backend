"""FastAPI application for the Comet web interface (Hi-Fi Workshop, stage 2-A).

Handlers are `async def` without awaits, so requests run one at a time on the event loop and
the in-memory state needs no locking.
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import dev, device, library, player, queue, signal_chain, system
from app.config import VERSION, Settings
from app.errors import DomainError
from app.schemas.common import ErrorResponse
from app.services.container import build_services


def _error(status_code: int, code: str, message: str, details: list[dict] | None = None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def create_app(settings: Settings | None = None, clock: Callable[[], float] = time.monotonic) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Comet API", version=VERSION,
        description="Stage 2-A: in-memory mock engine. No MPD, ALSA device, DSP or DAC is connected.",
        docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
    )
    app.state.services = build_services(settings, clock)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, error: DomainError):
        return _error(error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        details = [{"field": ".".join(str(part) for part in item["loc"] if part != "body"), "message": item["msg"]} for item in error.errors()]
        summary = "; ".join(f"{item['field']}: {item['message']}" if item["field"] else item["message"] for item in details)
        return _error(422, "validation_error", summary or "Invalid request.", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, error: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed"}
        return _error(error.status_code, codes.get(error.status_code, "http_error"), str(error.detail))

    errors = {status: {"model": ErrorResponse} for status in (404, 409, 422, 501)}
    api = APIRouter(prefix="/api", responses=errors)
    for module in (system, library, player, queue, signal_chain, device):
        api.include_router(module.router)
    if settings.dev_api_enabled:
        api.include_router(dev.router)
    app.include_router(api)
    return app


app = create_app()
