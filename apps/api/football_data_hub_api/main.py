"""FastAPI entry point for the prepared Group II datasets."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.dataset import DatasetBundle, DatasetLoadError, load_dataset
from football_data_hub_api.schemas import (
    BootstrapResponse,
    DatasetMetadata,
    HealthResponse,
    ReadinessResponse,
)

logger = logging.getLogger("football_data_hub_api")


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    configured = settings or ApiSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.dataset = None
        app.state.dataset_error = None
        try:
            app.state.dataset = load_dataset(configured)
        except (DatasetLoadError, KeyError, TypeError, ValueError) as exc:
            app.state.dataset_error = exc
            logger.exception("API arrancada sin dataset preparado")
        yield

    app = FastAPI(
        title="FootballDataHub Group II API",
        description=(
            "API de solo lectura para los datos preparados de Primera Federación "
            "2026/27 Grupo II. Los filtros interactivos se calculan en el cliente."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["If-None-Match", "Content-Type"],
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["service"],
        summary="Liveness del proceso",
    )
    def health(request: Request) -> HealthResponse:
        return HealthResponse(
            status="ok", dataset_ready=request.app.state.dataset is not None
        )

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["service"],
        summary="Preparación del dataset",
    )
    def readiness(request: Request) -> ReadinessResponse:
        bundle = _require_dataset(request)
        return ReadinessResponse(
            status="ready",
            capture_id=bundle.bootstrap.metadata.capture_id,
            dataset_version=bundle.bootstrap.metadata.dataset_version,
        )

    @app.get(
        "/api/v1/group2/metadata",
        response_model=DatasetMetadata,
        tags=["group2"],
        summary="Metadatos y cobertura del dataset de Grupo II",
    )
    def group2_metadata(request: Request) -> DatasetMetadata:
        bundle = _require_dataset(request)
        return bundle.bootstrap.metadata

    @app.get(
        "/api/v1/group2/bootstrap",
        response_model=BootstrapResponse,
        tags=["group2"],
        summary="Dataset completo para iniciar el dashboard",
    )
    def group2_bootstrap(request: Request, response: Response) -> BootstrapResponse | Response:
        bundle = _require_dataset(request)
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    return app


def _require_dataset(request: Request) -> DatasetBundle:
    bundle = request.app.state.dataset
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El dataset configurado no está disponible o no superó la validación.",
        )
    return bundle


def _etag_matches(header: str | None, etag: str) -> bool:
    if header is None:
        return False
    candidates = {candidate.strip() for candidate in header.split(",")}
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


app = create_app()
