"""FastAPI entry point for prepared Group I and Group II datasets."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
from dataclasses import replace
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlsplit

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
    MatchPageResponse,
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
    build_match_page,
    load_match_results_dataset,
)
from football_data_hub_api.match_details_dataset import (
    MatchDetailsLoadError,
    load_local_discovery_preview,
    load_published_match_details,
)
from football_data_hub_api.player_dataset import (
    PlayerDatasetLoadError,
    PlayerDirectoryBundle,
    load_player_directory,
)
from football_data_hub_api.manual_updates import (
    ManualUpdateError,
    ManualUpdateManager,
    UpdateAlreadyRunning,
    apply_active_group_data,
    public_manual_update_job,
)

logger = logging.getLogger("football_data_hub_api")
GROUP_CODES = {"1": "I", "2": "II"}


def _reload_after_manual_update(app: FastAPI, configured: ApiSettings, manager: ManualUpdateManager, job: dict[str, object]) -> None:
    """Load the applied two-group state, then swap validated bundles together."""
    datasets = dict(app.state.datasets)
    group_settings = dict(app.state.group_settings)
    match_results = app.state.match_results
    match_details = app.state.match_detail_documents
    if job.get("scope") == "competition":
        candidate = job["candidate"]
        if not isinstance(candidate, dict):
            raise ManualUpdateError("La activación no contiene su candidato validado.")
        for roman, number in (("I", "1"), ("II", "2")):
            base_settings = group_settings.get(number) or configured.for_group(roman)
            capture_root = Path(candidate["source_captures"][roman])
            replacement = replace(
                base_settings,
                matches_path=Path(candidate["normalized_matches"][roman]),
                classification_path=capture_root / "normalized/classification.json",
                progress_path=capture_root / "normalized/progress.json",
                capture_metadata_path=capture_root / "metadata/capture.json",
            )
            group_settings[number] = replacement
            datasets[number] = load_dataset(replacement)
        if configured.match_generation_root is None or configured.local_data_root is None:
            raise ManualUpdateError("No se puede recargar la generación activa de resultados.")
        match_results = load_match_results_dataset(
            configured.match_generation_root,
            data_root=configured.local_data_root,
        )
        _assert_group_catalogs_match_generation(datasets, match_results)
        match_details = {}
        if configured.match_details_published_root and configured.match_details_store_root:
            player_ids = set(app.state.player_directory.players_by_id) if app.state.player_directory else set()
            match_details = load_published_match_details(
                configured.match_details_published_root,
                store_root=configured.match_details_store_root,
                generation_root=configured.match_generation_root,
                data_root=configured.local_data_root,
                match_bundle=match_results,
                player_ids=player_ids,
            )

    matches_paths = {key: value.matches_path for key, value in group_settings.items()}
    unavailable_groups = {
        "I" if key == "1" else "II": str(value)
        for key, value in app.state.dataset_errors.items()
        if key not in datasets
    }
    roster = load_team_roster_registry(
        configured.team_profiles_index_path,
        datasets=datasets,
        matches_paths=matches_paths,
        unavailable_group_errors=unavailable_groups,
    )
    follow = load_team_follow_registry(
        configured.team_profiles_index_path,
        datasets=datasets,
        matches_paths=matches_paths,
        roster_registry=roster,
        unavailable_group_errors=unavailable_groups,
    )
    transfers = load_team_transfers_registry(
        configured.team_profiles_index_path,
        roster_registry=roster,
        unavailable_group_errors=unavailable_groups,
    )

    app.state.datasets = datasets
    app.state.group_settings = group_settings
    app.state.team_roster_registry = roster
    app.state.team_follow_registry = follow
    app.state.team_transfers_registry = transfers
    app.state.match_results = match_results
    app.state.match_results_error = None if match_results is not None else app.state.match_results_error
    app.state.match_detail_documents = match_details
    app.state.match_detail_publication_error = None
    manager.group_match_paths = {"I": group_settings["1"].matches_path, "II": group_settings["2"].matches_path}
    manager.group_classification_paths = {"I": group_settings["1"].classification_path, "II": group_settings["2"].classification_path}
    manager.group_progress_paths = {"I": group_settings["1"].progress_path, "II": group_settings["2"].progress_path}


def _assert_group_catalogs_match_generation(datasets: dict[str, DatasetBundle], match_results: MatchResultsBundle) -> None:
    """Guard the shared fixture truth used by group and team pages after activation."""
    for group_number, group_roman in (("1", "I"), ("2", "II")):
        dataset = datasets.get(group_number)
        generated = match_results.bootstrap.groups.get(group_roman)
        if dataset is None or generated is None:
            raise ManualUpdateError(f"No se pueden sincronizar las vistas del Grupo {group_roman}.")
        api_matches = {str(match.match_id): match for match in dataset.bootstrap.matches}
        generated_matches = {str(match.source_match_id): match for match in generated.matches}
        if len(api_matches) != len(dataset.bootstrap.matches) or len(generated_matches) != len(generated.matches):
            raise ManualUpdateError(f"Hay IDs de partido duplicados en el Grupo {group_roman}.")
        if set(api_matches) != set(generated_matches):
            raise ManualUpdateError(f"Clasificación/Resultados y fichas de partido tienen calendarios distintos en Grupo {group_roman}.")
        shared_fields = (
            "matchday", "matchday_date", "source_match_date", "home_team_id", "away_team_id",
            "home_goals", "away_goals", "status", "unplayed_state", "postponed_by_source_rule",
            "source_match_url", "stadium_id", "stadium_name", "stadium_url",
            "referee_id", "referee_name", "referee_url",
        )
        for source_match_id, api_match in api_matches.items():
            generated_match = generated_matches[source_match_id]
            if any(getattr(api_match, field, None) != getattr(generated_match, field, None) for field in shared_fields):
                raise ManualUpdateError(
                    f"El partido {source_match_id} discrepa entre el catálogo del Grupo {group_roman} y la generación activa."
                )


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
        app.state.match_detail_documents = {}
        app.state.match_detail_publication_error = None
        app.state.player_directory = None
        app.state.player_directory_error = None

        group_settings = {}
        group_match_paths = {}
        group_classification_paths = {}
        group_progress_paths = {}
        for group in ("I", "II"):
            group_key = "1" if group == "I" else "2"
            try:
                group_settings[group_key] = apply_active_group_data(
                    configured.for_group(group), group, configured.local_data_root
                )
            except (ManualUpdateError, ValueError, TypeError) as exc:
                app.state.dataset_errors[group_key] = exc
                app.state.top_dataset_errors[group_key] = exc
                app.state.statistics_dataset_errors[group_key] = exc
                app.state.referee_group_errors[group] = str(exc)
                continue
            group_match_paths[group] = group_settings[group_key].matches_path
            group_classification_paths[group] = group_settings[group_key].classification_path
            group_progress_paths[group] = group_settings[group_key].progress_path
        app.state.group_settings = group_settings
        app.state.manual_update_manager = ManualUpdateManager(
            project_root=PROJECT_ROOT,
            data_root=configured.local_data_root,
            profile_dir=Path(os.getenv(
                "FDH_BDFUTBOL_PROFILE",
                str(Path.home() / ".football-data-hub-chromium-pure-cdp"),
            )),
            browser_executable=(
                Path(os.environ["FDH_BDFUTBOL_BROWSER_EXECUTABLE"])
                if os.getenv("FDH_BDFUTBOL_BROWSER_EXECUTABLE")
                else None
            ),
            group_match_paths=group_match_paths,
            group_classification_paths=group_classification_paths,
            group_progress_paths=group_progress_paths,
            team_profiles_index=configured.team_profiles_index_path,
            match_generation_root=configured.match_generation_root,
            match_details_store_root=configured.match_details_store_root,
            player_inventory_root=configured.player_inventory_root,
            player_compact_root=configured.player_compact_root,
            player_team_captures_root=configured.player_team_captures_root,
            player_published_index_path=configured.player_published_index_path,
        )
        app.state.manual_update_manager.on_competition_applied = (
            lambda job: _reload_after_manual_update(
                app, configured, app.state.manual_update_manager, job
            )
        )

        for group in ("1", "2"):
            if group not in group_settings:
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

        activation_pending = bool(
            configured.local_data_root
            and (configured.local_data_root / "operations" / "manual-updates" / "activation-pending.json").exists()
        )
        if activation_pending:
            app.state.match_results_error = ManualUpdateError(
                "Hay una activación interrumpida; Resultados queda temporalmente indisponible hasta recuperar los punteros."
            )
        elif configured.match_generation_root is not None and configured.local_data_root is not None:
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

        if (
            app.state.match_results is not None
            and configured.match_details_published_root is not None
            and configured.match_details_store_root is not None
            and configured.match_generation_root is not None
            and configured.local_data_root is not None
        ):
            try:
                player_ids = set(app.state.player_directory.players_by_id) if app.state.player_directory else set()
                app.state.match_detail_documents = load_published_match_details(
                    configured.match_details_published_root,
                    store_root=configured.match_details_store_root,
                    generation_root=configured.match_generation_root,
                    data_root=configured.local_data_root,
                    match_bundle=app.state.match_results,
                    player_ids=player_ids,
                )
            except (MatchDetailsLoadError, OSError, ValueError, KeyError, TypeError) as exc:
                app.state.match_detail_publication_error = exc
                app.state.match_detail_documents = {}
                logger.exception("Los detalles publicados no superaron la validación; Resultados sigue disponible")
        try:
            yield
        finally:
            app.state.manual_update_manager.close()

    app = FastAPI(
        title="FootballDataHub API",
        description=(
            "API de consulta para Primera Federación 2026/27, Grupos I y II, "
            "con actualización manual disponible únicamente desde el entorno local. "
            "Los filtros interactivos se calculan en el cliente."
        ),
        version="1.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["If-None-Match", "Content-Type"],
    )

    def require_local_update_access(request: Request) -> ManualUpdateManager:
        """Keep unauthenticated write operations confined to loopback clients."""
        client_host = request.client.host if request.client is not None else None
        try:
            is_loopback = client_host is not None and ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = False
        host = request.headers.get("host", "")
        try:
            host_name = urlsplit(f"//{host}").hostname
            is_local_host = bool(
                host_name == "localhost"
                or (host_name and ipaddress.ip_address(host_name).is_loopback)
            )
        except ValueError:
            is_local_host = False
        origin = request.headers.get("origin")
        if origin:
            try:
                origin_parts = urlsplit(origin)
                origin_host = origin_parts.hostname
                is_local_origin = bool(
                    origin_parts.scheme in {"http", "https"}
                    and origin_host
                    and (origin_host == "localhost" or ipaddress.ip_address(origin_host).is_loopback)
                )
            except ValueError:
                is_local_origin = False
        else:
            is_local_origin = True
        has_forwarded_identity = any(
            request.headers.get(name)
            for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip")
        )
        fetch_site = request.headers.get("sec-fetch-site")
        is_same_site_context = fetch_site is None or fetch_site in {"same-origin", "same-site", "none"}
        if not (is_loopback and is_local_host and is_local_origin and is_same_site_context) or has_forwarded_identity:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "local_updates_only", "message": "Las actualizaciones solo se pueden iniciar desde FootballDataHub en este equipo."},
            )
        manager: ManualUpdateManager = request.app.state.manual_update_manager
        if not manager.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "manual_updates_disabled", "message": "Las actualizaciones no están configuradas en este entorno local."},
            )
        return manager

    @app.get("/api/v1/updates/status", tags=["updates"])
    def manual_update_status(request: Request) -> dict[str, object]:
        manager = require_local_update_access(request)
        return manager.public_status("competition")

    @app.post("/api/v1/updates/competition", status_code=status.HTTP_202_ACCEPTED, tags=["updates"])
    def start_competition_update(request: Request) -> dict[str, object]:
        manager = require_local_update_access(request)
        try:
            return public_manual_update_job(manager.start(scope="competition")) or {}
        except UpdateAlreadyRunning as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "update_in_progress", "message": str(exc)}) from exc
        except ManualUpdateError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "update_unavailable", "message": str(exc)}) from exc

    @app.get("/api/v1/updates/latest", tags=["updates"])
    def latest_update(request: Request) -> dict[str, object] | None:
        manager = require_local_update_access(request)
        return public_manual_update_job(manager.latest("competition"))

    @app.get("/api/v1/updates/jobs/{job_id}", tags=["updates"])
    def update_job(job_id: str, request: Request) -> dict[str, object]:
        manager = require_local_update_access(request)
        job = manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "update_job_not_found", "message": "No encontramos ese trabajo."})
        return public_manual_update_job(job) or {}

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
        "/api/v1/matches/{internal_id}",
        response_model=MatchPageResponse,
        tags=["matches"],
        summary="Consultar un partido de la generación verificada MATCH-00",
    )
    def match_page(
        internal_id: str, request: Request, response: Response
    ) -> MatchPageResponse | Response:
        bundle: MatchResultsBundle | None = request.app.state.match_results
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "match_results_unavailable",
                    "message": "La generación local de Resultados no está disponible o no superó la validación.",
                },
            )
        page = build_match_page(
            bundle,
            internal_id,
            details=getattr(request.app.state, "match_detail_documents", {}).get(internal_id),
        )
        if page is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "match_not_found",
                    "message": "No encontramos ese encuentro en la generación publicada.",
                },
            )
        page_etag = (
            f'"match-page-v1-{hashlib.sha256(page.model_dump_json().encode("utf-8")).hexdigest()[:24]}"'
        )
        response.headers["ETag"] = page_etag
        if _etag_matches(request.headers.get("if-none-match"), page_etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": page_etag})
        return page

    @app.get(
        "/__local-preview/matches/{internal_id}",
        response_model=MatchPageResponse,
        include_in_schema=False,
    )
    def local_match_preview(internal_id: str, request: Request) -> MatchPageResponse:
        """Loopback-only read-only presentation of an explicitly configured discovery artifact."""

        client_host = request.client.host if request.client is not None else None
        try:
            is_loopback = client_host is not None and ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback or configured.match_local_preview_artifact is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "preview_not_enabled"})
        bundle: MatchResultsBundle | None = request.app.state.match_results
        if (
            bundle is None
            or configured.match_generation_root is None
            or configured.local_data_root is None
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "preview_not_available"})
        player_directory = request.app.state.player_directory
        player_ids = set(player_directory.players_by_id) if player_directory is not None else set()
        try:
            return load_local_discovery_preview(
                configured.match_local_preview_artifact,
                internal_id=internal_id,
                generation_root=configured.match_generation_root,
                data_root=configured.local_data_root,
                match_bundle=bundle,
                player_ids=player_ids,
            )
        except (MatchDetailsLoadError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.exception("No se pudo construir la vista previa local del partido")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "preview_not_available"},
            ) from exc

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
