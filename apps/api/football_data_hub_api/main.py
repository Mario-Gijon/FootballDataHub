"""FastAPI entry point for prepared Group I and Group II datasets."""

from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from football_data_hub_api.config import (
    ApiSettings,
    DEFAULT_GROUP2_REFEREES_CAPTURE,
    PROJECT_ROOT,
)
from football_data_hub_api.dataset import DatasetBundle, DatasetLoadError, load_dataset
from football_data_hub_api.referee_dataset import (
    RefereeDatasetBundle,
    RefereeDatasetLoadError,
    load_referee_dataset,
)
from football_data_hub_api.schemas import (
    BootstrapResponse,
    DatasetMetadata,
    HealthResponse,
    MatchGenerationBootstrapResponse,
    PlayerDetailResponse,
    PlayerDirectoryResponse,
    ReadinessResponse,
    RefereeBootstrapResponse,
    StatisticsBootstrapResponse,
    TeamRosterResponse,
    TeamTransfersResponse,
    TopBootstrapResponse,
    TeamFollowResponse,
)
from football_data_hub_api.statistics_dataset import (
    StatisticsDatasetBundle,
    StatisticsDatasetLoadError,
    load_statistics_dataset,
)
from football_data_hub_api.top_dataset import (
    TopDatasetBundle,
    TopDatasetLoadError,
    load_top_dataset,
    project_top_player_links,
)
from football_data_hub_api.team_roster_dataset import (
    TeamRosterRegistry,
    load_team_roster_registry,
)
from football_data_hub_api.team_follow_dataset import (
    TeamFollowRegistry,
    load_team_follow_registry,
)
from football_data_hub_api.team_transfers_dataset import (
    TeamTransfersRegistry,
    load_team_transfers_registry,
)
from football_data_hub_api.match_results_dataset import (
    MatchResultsBundle,
    MatchResultsLoadError,
    load_match_results_dataset,
)
from football_data_hub_api.player_dataset import (
    PlayerDatasetLoadError,
    PlayerDirectoryBundle,
    load_player_directory,
)

logger = logging.getLogger("football_data_hub_api")
GROUP_CODES = {"1": "I", "2": "II"}


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    configured = settings or ApiSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.datasets = {}
        app.state.dataset_errors = {}
        app.state.top_datasets = {}
        app.state.top_dataset_errors = {}
        app.state.statistics_datasets = {}
        app.state.statistics_dataset_errors = {}
        app.state.referee_dataset = None
        app.state.referee_dataset_error = None
        app.state.referee_group_errors = {}
        app.state.team_roster_registry = TeamRosterRegistry({}, {}, {}, None, {})
        app.state.team_follow_registry = TeamFollowRegistry({}, {}, {}, None, {})
        app.state.team_transfers_registry = TeamTransfersRegistry({}, {}, {}, None, {})
        app.state.match_results = None
        app.state.match_results_error = None
        app.state.player_directory = None
        app.state.player_directory_error = None

        group_settings = {}
        for group in ("1", "2"):
            try:
                group_settings[group] = configured.for_group(group)
            except (ValueError, TypeError) as exc:
                app.state.dataset_errors[group] = exc
                app.state.top_dataset_errors[group] = exc
                app.state.statistics_dataset_errors[group] = exc
                app.state.referee_group_errors[GROUP_CODES[group]] = str(exc)
                continue

            try:
                app.state.datasets[group] = load_dataset(group_settings[group])
            except (DatasetLoadError, KeyError, TypeError, ValueError) as exc:
                app.state.dataset_errors[group] = exc
                logger.exception("Clasificación y Resultados de Grupo %s no disponibles", group)

            active = app.state.datasets.get(group)
            try:
                app.state.top_datasets[group] = load_top_dataset(
                    group_settings[group],
                    active_teams=active.bootstrap.teams if active is not None else None,
                    active_team_capture_id=(
                        active.bootstrap.metadata.capture_id if active is not None else None
                    ),
                )
            except (TopDatasetLoadError, KeyError, TypeError, ValueError) as exc:
                app.state.top_dataset_errors[group] = exc
                logger.exception("Destacados de Grupo %s no están disponibles", group)

            try:
                app.state.statistics_datasets[group] = load_statistics_dataset(
                    group_settings[group], active
                )
            except (StatisticsDatasetLoadError, KeyError, TypeError, ValueError) as exc:
                app.state.statistics_dataset_errors[group] = exc
                logger.exception("Estadísticas de Grupo %s no están disponibles", group)

        try:
            referee_root = configured.referees_root or (
                PROJECT_ROOT / DEFAULT_GROUP2_REFEREES_CAPTURE
            ).resolve()
            match_sources: dict[str, tuple[Path, Path]] = {}
            if "1" in group_settings and "1" in app.state.datasets:
                match_sources["I"] = (
                    group_settings["1"].matches_path,
                    group_settings["1"].referee_match_reference_path
                    or group_settings["1"].capture_metadata_path.parent
                    / "validation/referee_reference.json",
                )
            if "2" in group_settings and "2" in app.state.datasets:
                match_sources["II"] = (
                    group_settings["2"].matches_path,
                    referee_root / "validation/match_reference.json",
                )
            app.state.referee_dataset = load_referee_dataset(
                configured, group_match_sources=match_sources
            )
            app.state.referee_group_errors.update(
                app.state.referee_dataset.group_reference_errors
            )
            for group in ("1", "2"):
                code = GROUP_CODES[group]
                if group in group_settings and group not in app.state.datasets:
                    app.state.referee_group_errors.setdefault(
                        code, "La captura de Resultados del grupo no está disponible"
                    )
        except (RefereeDatasetLoadError, KeyError, TypeError, ValueError) as exc:
            app.state.referee_dataset_error = exc
            logger.exception("Árbitros no está disponible; el resto de secciones sigue aislado")

        matches_paths = {
            group: settings.matches_path for group, settings in group_settings.items()
        }
        unavailable_groups = {
            "I" if group == "1" else "II": str(error)
            for group, error in app.state.dataset_errors.items()
        }
        app.state.team_roster_registry = load_team_roster_registry(
            configured.team_profiles_index_path,
            datasets=app.state.datasets,
            matches_paths=matches_paths,
            unavailable_group_errors=unavailable_groups,
        )
        app.state.team_follow_registry = load_team_follow_registry(
            configured.team_profiles_index_path,
            datasets=app.state.datasets,
            matches_paths=matches_paths,
            roster_registry=app.state.team_roster_registry,
            unavailable_group_errors=unavailable_groups,
        )
        try:
            app.state.team_transfers_registry = load_team_transfers_registry(
                configured.team_profiles_index_path,
                roster_registry=app.state.team_roster_registry,
                unavailable_group_errors=unavailable_groups,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.exception("Traspasos no están disponibles; el resto de secciones sigue aislado")
            app.state.team_transfers_registry = TeamTransfersRegistry(
                app.state.team_roster_registry.known_teams, {}, {}, str(exc), unavailable_groups
            )

        if configured.match_generation_root is not None and configured.local_data_root is not None:
            try:
                app.state.match_results = load_match_results_dataset(
                    configured.match_generation_root,
                    data_root=configured.local_data_root,
                )
            except (MatchResultsLoadError, OSError, ValueError, KeyError, TypeError) as exc:
                app.state.match_results_error = exc
                logger.exception("La generación de Resultados MATCH-00 no está disponible")
        else:
            app.state.match_results_error = ValueError("No se configuró una generación MATCH-00 local.")

        player_paths = (
            configured.player_inventory_root,
            configured.player_compact_root,
            configured.player_team_captures_root,
            configured.player_published_index_path,
        )
        if all(path is not None for path in player_paths):
            try:
                app.state.player_directory = load_player_directory(
                    inventory_root=configured.player_inventory_root,
                    compact_root=configured.player_compact_root,
                    team_captures_root=configured.player_team_captures_root,
                    published_index_path=configured.player_published_index_path,
                )
            except (PlayerDatasetLoadError, OSError, ValueError, KeyError, TypeError) as exc:
                app.state.player_directory_error = exc
                logger.exception("El inventario de jugadores no está disponible")
        else:
            app.state.player_directory_error = ValueError("No se configuraron las fuentes locales de jugadores.")
        yield

    app = FastAPI(
        title="FootballDataHub API",
        description=(
            "API de solo lectura para Primera Federación 2026/27, Grupos I y II. "
            "Los filtros interactivos se calculan en el cliente."
        ),
        version="1.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["If-None-Match", "Content-Type"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["service"])
    def health(request: Request) -> HealthResponse:
        return HealthResponse(
            status="ok", dataset_ready=request.app.state.datasets.get("2") is not None
        )

    @app.get("/ready", response_model=ReadinessResponse, tags=["service"])
    def readiness(request: Request) -> ReadinessResponse:
        bundle = _require_group_dataset(request, "2")
        return ReadinessResponse(
            status="ready",
            capture_id=bundle.bootstrap.metadata.capture_id,
            dataset_version=bundle.bootstrap.metadata.dataset_version,
        )

    @app.get(
        "/api/v1/matches/bootstrap",
        response_model=MatchGenerationBootstrapResponse,
        tags=["matches"],
        summary="Calendario y resultados de la generación verificada MATCH-00",
    )
    def match_results_bootstrap(
        request: Request, response: Response
    ) -> MatchGenerationBootstrapResponse | Response:
        bundle: MatchResultsBundle | None = request.app.state.match_results
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "match_results_unavailable",
                    "message": "La generación local de Resultados no está disponible o no superó la validación.",
                },
            )
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    @app.get(
        "/api/v1/players",
        response_model=PlayerDirectoryResponse,
        tags=["players"],
        summary="Buscar y paginar jugadores del inventario verificado",
    )
    def players_directory(
        request: Request,
        response: Response,
        q: str = Query(default="", max_length=120),
        group: str | None = Query(default=None, pattern="^(I|II)$"),
        team_id: int | None = Query(default=None, gt=0),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
    ) -> PlayerDirectoryResponse | Response:
        bundle = _require_player_directory(request)
        payload = bundle.list_players(
            query=q, group=group, team_id=team_id, page=page, page_size=page_size
        )
        etag = _payload_etag("players-directory-v1", payload.model_dump_json())
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return payload

    @app.get(
        "/api/v1/players/{player_id}",
        response_model=PlayerDetailResponse,
        tags=["players"],
        summary="Ficha del inventario para un ID de jugador",
    )
    def player_detail(
        player_id: int, request: Request, response: Response
    ) -> PlayerDetailResponse | Response:
        bundle = _require_player_directory(request)
        payload = bundle.detail(player_id)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "player_unknown", "message": "No hay un jugador con ese ID en el inventario."},
            )
        etag = _payload_etag("player-detail-v1", payload.model_dump_json())
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return payload

    @app.get(
        "/api/v1/groups/{group}/bootstrap",
        response_model=BootstrapResponse,
        tags=["groups"],
        summary="Clasificación y resultados preparados para un grupo",
    )
    def group_bootstrap(
        group: str, request: Request, response: Response
    ) -> BootstrapResponse | Response:
        return _conditional_response(
            request,
            response,
            _require_group_dataset(request, group),
            group,
        )

    @app.get(
        "/api/v1/groups/{group}/top/bootstrap",
        response_model=TopBootstrapResponse,
        tags=["groups", "top"],
        summary="Destacados preparados para un grupo",
    )
    def group_top_bootstrap(
        group: str, request: Request, response: Response
    ) -> TopBootstrapResponse | Response:
        bundle = _require_section(request, "top_datasets", "top_dataset_errors", group, "Destacados")
        directory = request.app.state.player_directory
        verified_ids = set(directory.players_by_id) if directory is not None else set()
        payload, etag = project_top_player_links(bundle.bootstrap, verified_ids)
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return payload

    @app.get(
        "/api/v1/groups/{group}/referees/bootstrap",
        response_model=RefereeBootstrapResponse,
        tags=["groups", "referees"],
        summary="Árbitros compartidos con ámbito filtrable por grupo",
    )
    def group_referees_bootstrap(
        group: str, request: Request, response: Response
    ) -> RefereeBootstrapResponse | Response:
        _group_code(group)
        bundle = request.app.state.referee_dataset
        if bundle is None:
            raise _section_unavailable("Árbitros", request.app.state.referee_dataset_error)
        _require_referee_group(request, group)
        return _conditional_response(request, response, bundle, group)

    @app.get(
        "/api/v1/groups/{group}/statistics/bootstrap",
        response_model=StatisticsBootstrapResponse,
        tags=["groups", "statistics"],
        summary="Estadísticas preparadas para un grupo",
    )
    def group_statistics_bootstrap(
        group: str, request: Request, response: Response
    ) -> StatisticsBootstrapResponse | Response:
        return _conditional_response(
            request,
            response,
            _require_section(
                request,
                "statistics_datasets",
                "statistics_dataset_errors",
                group,
                "Estadísticas",
            ),
            group,
        )

    @app.get(
        "/api/v1/teams/{team_id}/seasons/{season}/roster",
        response_model=TeamRosterResponse,
        tags=["teams", "roster"],
        summary="Plantilla normalizada y validada de un equipo",
    )
    def team_roster(
        team_id: int, season: str, request: Request, response: Response
    ) -> TeamRosterResponse | Response:
        if season != "2026-27":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "season_not_available", "message": "Solo está disponible 2026/27."},
            )
        registry: TeamRosterRegistry = request.app.state.team_roster_registry
        if team_id not in registry.known_teams:
            if registry.unavailable_group_errors:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "team_catalog_unavailable", "message": "No se pudieron validar todos los catálogos de equipos."},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "team_unknown", "message": "No existe un equipo con ese identificador."},
            )
        profile = registry.profiles.get(team_id)
        if profile is None:
            if team_id in registry.profile_errors:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "profile_invalid", "message": "La captura seleccionada no superó las validaciones de Plantilla."},
                )
            if registry.index_error:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "profile_index_unavailable", "message": "El índice de capturas de equipos no está disponible."},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "profile_not_captured", "message": "La Plantilla de este equipo aún no tiene una captura publicada."},
            )
        etag = (
            f'"team-roster-v{profile.metadata.contract_version}-'
            f'{team_id}-{season}-{profile.metadata.content_sha256[:24]}"'
        )
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return profile

    @app.get(
        "/api/v1/teams/{team_id}/seasons/{season}/follow",
        response_model=TeamFollowResponse,
        tags=["teams", "follow"],
        summary="Seguimiento por jugador y partido de un equipo",
    )
    def team_follow(
        team_id: int, season: str, request: Request, response: Response
    ) -> TeamFollowResponse | Response:
        if season != "2026-27":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "season_not_available", "message": "Solo está disponible 2026/27."},
            )
        registry: TeamFollowRegistry = request.app.state.team_follow_registry
        if team_id not in registry.known_teams:
            if registry.unavailable_group_errors:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "team_catalog_unavailable", "message": "No se pudieron validar todos los catálogos de equipos."},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "team_unknown", "message": "No existe un equipo con ese identificador."},
            )
        profile = registry.profiles.get(team_id)
        if profile is None:
            if team_id in registry.profile_errors:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "follow_invalid", "message": "La captura seleccionada no superó las validaciones de Seguimiento."},
                )
            if registry.index_error:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "follow_index_unavailable", "message": "El índice de capturas de equipo no está disponible."},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "follow_not_captured", "message": "El Seguimiento de este equipo aún no tiene una captura publicada."},
            )
        representation = profile.model_dump_json().encode("utf-8")
        representation_sha = hashlib.sha256(representation).hexdigest()[:24]
        etag = (
            f'"team-follow-v{profile.metadata.contract_version}-'
            f'{team_id}-{season}-{representation_sha}"'
        )
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return profile

    @app.get(
        "/api/v1/teams/{team_id}/seasons/{season}/transfers",
        response_model=TeamTransfersResponse,
        tags=["teams", "transfers"],
        summary="Altas y bajas normalizadas de un equipo",
    )
    def team_transfers(
        team_id: int, season: str, request: Request, response: Response
    ) -> TeamTransfersResponse | Response:
        if season != "2026-27":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "season_not_available", "message": "Solo está disponible 2026/27."},
            )
        registry: TeamTransfersRegistry = request.app.state.team_transfers_registry
        if team_id not in registry.known_teams:
            if registry.unavailable_group_errors:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "team_catalog_unavailable", "message": "No se pudieron validar todos los catálogos de equipos."},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "team_unknown", "message": "No existe un equipo con ese identificador."},
            )
        profile = registry.profiles.get(team_id)
        if profile is None:
            if team_id in registry.profile_errors:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "transfers_invalid", "message": "La captura seleccionada no superó las validaciones de Traspasos."},
                )
            if registry.index_error:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "transfers_index_unavailable", "message": "El índice de capturas de equipos no está disponible."},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "transfers_not_captured", "message": "Los Traspasos de este equipo aún no tienen una captura publicada."},
            )
        etag = (
            f'"team-transfers-v{profile.metadata.contract_version}-'
            f'{team_id}-{season}-{profile.metadata.content_sha256[:24]}"'
        )
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return profile

    # Compatibility aliases: legacy clients remain on the Group II dataset and ETags.
    @app.get("/api/v1/group2/metadata", response_model=DatasetMetadata, tags=["group2"])
    def group2_metadata(request: Request) -> DatasetMetadata:
        return _require_group_dataset(request, "2").bootstrap.metadata

    @app.get("/api/v1/group2/bootstrap", response_model=BootstrapResponse, tags=["group2"])
    def group2_bootstrap(request: Request, response: Response) -> BootstrapResponse | Response:
        bundle = _require_group_dataset(request, "2")
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    @app.get(
        "/api/v1/group2/top/bootstrap",
        response_model=TopBootstrapResponse,
        tags=["group2", "top"],
    )
    def group2_top_bootstrap(request: Request, response: Response) -> TopBootstrapResponse | Response:
        bundle = _require_section(request, "top_datasets", "top_dataset_errors", "2", "Destacados")
        directory = request.app.state.player_directory
        verified_ids = set(directory.players_by_id) if directory is not None else set()
        payload, etag = project_top_player_links(bundle.bootstrap, verified_ids)
        response.headers["ETag"] = etag
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return payload

    @app.get(
        "/api/v1/group2/referees/bootstrap",
        response_model=RefereeBootstrapResponse,
        tags=["group2", "referees"],
    )
    def group2_referees_bootstrap(request: Request, response: Response) -> RefereeBootstrapResponse | Response:
        bundle = request.app.state.referee_dataset
        if bundle is None:
            raise _section_unavailable("Árbitros", request.app.state.referee_dataset_error)
        _require_referee_group(request, "2")
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    @app.get(
        "/api/v1/group2/statistics/bootstrap",
        response_model=StatisticsBootstrapResponse,
        tags=["group2", "statistics"],
    )
    def group2_statistics_bootstrap(request: Request, response: Response) -> StatisticsBootstrapResponse | Response:
        bundle = _require_section(
            request, "statistics_datasets", "statistics_dataset_errors", "2", "Estadísticas"
        )
        response.headers["ETag"] = bundle.etag
        if _etag_matches(request.headers.get("if-none-match"), bundle.etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": bundle.etag})
        return bundle.bootstrap

    return app


def _group_code(group: str) -> str:
    code = GROUP_CODES.get(group)
    if code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo desconocido")
    return code


def _require_group_dataset(request: Request, group: str) -> DatasetBundle:
    _group_code(group)
    bundle = request.app.state.datasets.get(group)
    if bundle is None:
        error = request.app.state.dataset_errors.get(group)
        detail = "El dataset configurado de Clasificación y Resultados no superó la validación."
        if error:
            detail = f"{detail} Diagnóstico: {error}"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return bundle


def _require_player_directory(request: Request) -> PlayerDirectoryBundle:
    bundle: PlayerDirectoryBundle | None = request.app.state.player_directory
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "player_inventory_unavailable",
                "message": "El inventario local de jugadores no está disponible o no superó la validación.",
            },
        )
    return bundle


def _payload_etag(prefix: str, representation: str) -> str:
    digest = hashlib.sha256(representation.encode("utf-8")).hexdigest()[:24]
    return f'"{prefix}-{digest}"'


def _require_section(
    request: Request, bundle_state: str, error_state: str, group: str, label: str
) -> TopDatasetBundle | StatisticsDatasetBundle:
    _group_code(group)
    bundle = getattr(request.app.state, bundle_state).get(group)
    if bundle is None:
        error = getattr(request.app.state, error_state).get(group)
        raise _section_unavailable(f"{label} de Grupo {GROUP_CODES[group]}", error)
    return bundle


def _require_referee_group(request: Request, group: str) -> None:
    code = _group_code(group)
    error = request.app.state.referee_group_errors.get(code)
    if error:
        raise _section_unavailable(f"Árbitros de Grupo {code}", ValueError(error))


def _section_unavailable(label: str, error: Exception | None) -> HTTPException:
    detail = f"{label} no está disponible: la captura independiente no superó la validación."
    if error:
        detail = f"{detail} Diagnóstico: {error}"
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def _conditional_response(
    request: Request,
    response: Response,
    bundle: DatasetBundle | TopDatasetBundle | RefereeDatasetBundle | StatisticsDatasetBundle,
    group: str,
) -> object:
    versioned_bundle_etag = bundle.api_etag.strip('"')
    etag = f'"group-{group}-{versioned_bundle_etag}"'
    response.headers["ETag"] = etag
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return bundle.bootstrap


def _etag_matches(header: str | None, etag: str) -> bool:
    if header is None:
        return False
    candidates = {candidate.strip() for candidate in header.split(",")}
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


app = create_app()
