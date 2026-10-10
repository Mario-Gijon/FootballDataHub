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
    RefereeBootstrapResponse,
    ReadinessResponse,
    StatisticsBootstrapResponse,
    TopBootstrapResponse,
)
from football_data_hub_api.top_dataset import (
    TopDatasetBundle,
    TopDatasetLoadError,
    load_top_dataset,
)
from football_data_hub_api.referee_dataset import (
    RefereeDatasetBundle,
    RefereeDatasetLoadError,
    load_referee_dataset,
)
from football_data_hub_api.statistics_dataset import (
    StatisticsDatasetBundle,
    StatisticsDatasetLoadError,
    load_statistics_dataset,
)

logger = logging.getLogger("football_data_hub_api")


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    configured = settings or ApiSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.dataset = None
        app.state.dataset_error = None
        app.state.top_dataset = None
        app.state.top_dataset_error = None
        app.state.referee_dataset = None
        app.state.referee_dataset_error = None
        app.state.statistics_dataset = None
        app.state.statistics_dataset_error = None
        try:
            app.state.dataset = load_dataset(configured)
        except (DatasetLoadError, KeyError, TypeError, ValueError) as exc:
            app.state.dataset_error = exc
            logger.exception("API arrancada sin dataset preparado")
        try:
            active = app.state.dataset
            app.state.top_dataset = load_top_dataset(
                configured,
                active_teams=active.bootstrap.teams if active is not None else None,
                active_team_capture_id=active.bootstrap.metadata.capture_id if active is not None else None,
            )
        except (TopDatasetLoadError, KeyError, TypeError, ValueError) as exc:
            app.state.top_dataset_error = exc
            logger.exception("Destacados no está disponible; clasificación y resultados siguen aislados")
        try:
            app.state.referee_dataset = load_referee_dataset(configured)
        except (RefereeDatasetLoadError, KeyError, TypeError, ValueError) as exc:
            app.state.referee_dataset_error = exc
            logger.exception("Árbitros no está disponible; el resto de secciones sigue aislado")
        try:
            app.state.statistics_dataset = load_statistics_dataset(
                configured, app.state.dataset
            )
        except (StatisticsDatasetLoadError, KeyError, TypeError, ValueError) as exc:
            app.state.statistics_dataset_error = exc
            logger.exception("Estadísticas no está disponible; el resto de secciones sigue aislado")
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

    @app.get(
        "/api/v1/group2/top/bootstrap",
        response_model=TopBootstrapResponse,
        tags=["group2", "top"],
        summary="Datos preparados de rankings y jugadores destacados",
    )
    def group2_top_bootstrap(request: Request, response: Response) -> TopBootstrapResponse | Response:
        bundle = _require_top_dataset(request)
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    @app.get(
        "/api/v1/group2/referees/bootstrap",
        response_model=RefereeBootstrapResponse,
        tags=["group2", "referees"],
        summary="Datos preparados de árbitros de la temporada 2026/27",
    )
    def group2_referees_bootstrap(
        request: Request, response: Response
    ) -> RefereeBootstrapResponse | Response:
        bundle = _require_referee_dataset(request)
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    @app.get(
        "/api/v1/group2/statistics/bootstrap",
        response_model=StatisticsBootstrapResponse,
        tags=["group2", "statistics"],
        summary="Estadísticas, récords, rachas y series de la competición",
    )
    def group2_statistics_bootstrap(
        request: Request, response: Response
    ) -> StatisticsBootstrapResponse | Response:
        bundle = _require_statistics_dataset(request)
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


def _require_top_dataset(request: Request) -> TopDatasetBundle:
    bundle = request.app.state.top_dataset
    if bundle is None:
        detail = "Destacados no está disponible: la captura independiente no superó la validación."
        error = request.app.state.top_dataset_error
        if error:
            detail = f"{detail} Diagnóstico: {error}"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return bundle


def _require_referee_dataset(request: Request) -> RefereeDatasetBundle:
    bundle = request.app.state.referee_dataset
    if bundle is None:
        detail = "Árbitros no está disponible: su captura independiente no superó la validación."
        error = request.app.state.referee_dataset_error
        if error:
            detail = f"{detail} Diagnóstico: {error}"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return bundle


def _require_statistics_dataset(request: Request) -> StatisticsDatasetBundle:
    bundle = request.app.state.statistics_dataset
    if bundle is None:
        detail = "Estadísticas no está disponible: la captura independiente no coincide con Resultados o no superó la validación."
        error = request.app.state.statistics_dataset_error
        if error:
            detail = f"{detail} Diagnóstico: {error}"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return bundle


def _etag_matches(header: str | None, etag: str) -> bool:
    if header is None:
        return False
    candidates = {candidate.strip() for candidate in header.split(",")}
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


app = create_app()
