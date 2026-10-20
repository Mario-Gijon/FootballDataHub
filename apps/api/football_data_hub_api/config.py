"""Environment-based configuration for the prepared competition datasets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from football_data_hub.providers.bdfutbol.context import (
    CompetitionContext,
    get_competition_context,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATA_ROOT = Path("data/exports/bdfutbol/group2_classification")
DEFAULT_TOP_CAPTURE = Path(
    "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6"
)
DEFAULT_GROUP2_REFEREES_CAPTURE = Path(
    "data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc"
)
DEFAULT_GROUP2_STATISTICS_CAPTURE = Path(
    "data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363"
)
DEFAULT_GROUP1_DATA_ROOT = Path("data/exports/bdfutbol/group1_classification")
DEFAULT_GROUP1_CLASSIFICATION_CAPTURE = Path(
    "20261010T202500.293648Z-b770724f"
)
DEFAULT_GROUP1_TOP_CAPTURE = Path(
    "data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb"
)
DEFAULT_GROUP1_STATISTICS_CAPTURE = Path(
    "data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9"
)
DEFAULT_TEAM_PROFILES_INDEX = Path("config/team_profiles_2026-27.json")


@dataclass(frozen=True, slots=True)
class GroupDatasetSettings:
    """Paths and expected identity for one group's independently captured data."""

    context: CompetitionContext
    matches_path: Path
    classification_path: Path
    progress_path: Path
    capture_metadata_path: Path
    top_players_path: Path | None = None
    top_rankings_path: Path | None = None
    top_progress_path: Path | None = None
    top_foreigners_path: Path | None = None
    top_capture_metadata_path: Path | None = None
    top_validation_path: Path | None = None
    top_source_html_path: Path | None = None
    top_team_catalog_path: Path | None = None
    statistics_root: Path | None = None
    referee_match_reference_path: Path | None = None

    @property
    def group(self) -> str:
        return self.context.group_roman


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Legacy Group II fields plus explicit Group I paths and shared REF capture."""

    # Keep the original fields so existing Group II integrations and tests remain valid.
    matches_path: Path
    classification_path: Path
    progress_path: Path
    capture_metadata_path: Path
    cors_origins: tuple[str, ...] = ()
    top_players_path: Path | None = None
    top_rankings_path: Path | None = None
    top_progress_path: Path | None = None
    top_foreigners_path: Path | None = None
    top_capture_metadata_path: Path | None = None
    top_validation_path: Path | None = None
    top_source_html_path: Path | None = None
    top_team_catalog_path: Path | None = None
    referees_root: Path | None = None
    referees_related_matches_path: Path | None = None
    statistics_root: Path | None = None
    group: str = "II"
    group1_settings: GroupDatasetSettings | None = None
    team_profiles_index_path: Path | None = None
    local_data_root: Path | None = None
    match_generation_root: Path | None = None
    player_inventory_root: Path | None = None
    player_compact_root: Path | None = None
    player_team_captures_root: Path | None = None
    player_published_index_path: Path | None = None
    match_details_store_root: Path | None = None
    match_details_published_root: Path | None = None
    match_local_preview_artifact: Path | None = None
    update_admin_token: str | None = None

    def for_group(self, group: str | int) -> GroupDatasetSettings:
        """Return a group-specific view without mutating or copying any dataset."""

        normalized = _normalize_group(group)
        if normalized == "I":
            if self.group1_settings is None:
                raise ValueError("No hay capturas configuradas para Grupo I")
            return self.group1_settings
        return GroupDatasetSettings(
            context=get_competition_context(group=2),
            matches_path=self.matches_path,
            classification_path=self.classification_path,
            progress_path=self.progress_path,
            capture_metadata_path=self.capture_metadata_path,
            top_players_path=self.top_players_path,
            top_rankings_path=self.top_rankings_path,
            top_progress_path=self.top_progress_path,
            top_foreigners_path=self.top_foreigners_path,
            top_capture_metadata_path=self.top_capture_metadata_path,
            top_validation_path=self.top_validation_path,
            top_source_html_path=self.top_source_html_path,
            top_team_catalog_path=self.top_team_catalog_path,
            statistics_root=self.statistics_root,
            referee_match_reference_path=(
                (self.referees_root / "validation/match_reference.json")
                if self.referees_root is not None
                else None
            ),
        )

    @classmethod
    def from_env(cls) -> ApiSettings:
        local_root_value = os.getenv("FDH_LOCAL_DATA_ROOT")
        local_data_root = (
            _resolve_path(Path(local_root_value), PROJECT_ROOT)
            if local_root_value
            else None
        )
        match_store_pointer = (
            local_data_root / "matches" / "active-generation.json"
            if local_data_root is not None
            else None
        )
        match_generation_default = (
            "matches"
            if match_store_pointer is not None
            and (match_store_pointer.exists() or match_store_pointer.is_symlink())
            else "matches/generations/match-00-4ad1d610507e425d"
        )
        data_root = _resolve_path(
            Path(os.getenv("FDH_DATA_ROOT", str(DEFAULT_DATA_ROOT))), PROJECT_ROOT
        )
        group2_top_root = _resolve_path(
            Path(os.getenv("FDH_GROUP2_TOP_ROOT", str(DEFAULT_TOP_CAPTURE))),
            PROJECT_ROOT,
        )
        referees_root = _resolve_path(
            Path(
                os.getenv(
                    "FDH_REFEREES_ROOT",
                    os.getenv(
                        "FDH_GROUP2_REFEREES_ROOT",
                        str(DEFAULT_GROUP2_REFEREES_CAPTURE),
                    ),
                )
            ),
            PROJECT_ROOT,
        )
        group2_statistics_root = _resolve_path(
            Path(
                os.getenv(
                    "FDH_GROUP2_STATISTICS_ROOT",
                    str(DEFAULT_GROUP2_STATISTICS_CAPTURE),
                )
            ),
            PROJECT_ROOT,
        )

        group1_root = _resolve_path(
            Path(os.getenv("FDH_GROUP1_DATA_ROOT", str(DEFAULT_GROUP1_DATA_ROOT))),
            PROJECT_ROOT,
        )
        group1_capture_root = _resolve_path(
            Path(
                os.getenv(
                    "FDH_GROUP1_CAPTURE_ROOT",
                    str(DEFAULT_GROUP1_CLASSIFICATION_CAPTURE),
                )
            ),
            group1_root,
        )
        group1_top_root = _resolve_path(
            Path(os.getenv("FDH_GROUP1_TOP_ROOT", str(DEFAULT_GROUP1_TOP_CAPTURE))),
            PROJECT_ROOT,
        )
        group1_statistics_root = _resolve_path(
            Path(
                os.getenv(
                    "FDH_GROUP1_STATISTICS_ROOT",
                    str(DEFAULT_GROUP1_STATISTICS_CAPTURE),
                )
            ),
            PROJECT_ROOT,
        )

        group1 = GroupDatasetSettings(
            context=get_competition_context(group=1),
            matches_path=_configured_path(
                "FDH_GROUP1_MATCHES", group1_capture_root, "normalized/matches.json"
            ),
            classification_path=_configured_path(
                "FDH_GROUP1_CLASSIFICATION",
                group1_capture_root,
                "normalized/classification.json",
            ),
            progress_path=_configured_path(
                "FDH_GROUP1_PROGRESS", group1_capture_root, "normalized/progress.json"
            ),
            capture_metadata_path=_configured_path(
                "FDH_GROUP1_CAPTURE_METADATA", group1_capture_root, "metadata/capture.json"
            ),
            top_players_path=_configured_path(
                "FDH_GROUP1_TOP_PLAYERS", group1_top_root, "normalized/players.json"
            ),
            top_rankings_path=_configured_path(
                "FDH_GROUP1_TOP_RANKINGS", group1_top_root, "normalized/rankings.json"
            ),
            top_progress_path=_configured_path(
                "FDH_GROUP1_TOP_PROGRESS", group1_top_root, "normalized/progress.json"
            ),
            top_foreigners_path=_configured_path(
                "FDH_GROUP1_TOP_FOREIGNERS", group1_top_root, "normalized/foreigners.json"
            ),
            top_capture_metadata_path=_configured_path(
                "FDH_GROUP1_TOP_CAPTURE_METADATA", group1_top_root, "metadata/capture.json"
            ),
            top_validation_path=_configured_path(
                "FDH_GROUP1_TOP_VALIDATION", group1_top_root, "validation/results.json"
            ),
            top_source_html_path=_configured_path(
                "FDH_GROUP1_TOP_SOURCE_HTML", group1_top_root, "raw/source.html"
            ),
            top_team_catalog_path=_configured_path(
                "FDH_GROUP1_TOP_TEAM_CATALOG",
                group1_capture_root,
                "normalized/matches.json",
            ),
            statistics_root=group1_statistics_root,
            referee_match_reference_path=_configured_path(
                "FDH_GROUP1_REFEREE_MATCH_REFERENCE",
                group1_capture_root,
                "validation/referee_reference.json",
            ),
        )

        return cls(
            matches_path=_configured_path(
                "FDH_GROUP2_MATCHES",
                data_root,
                "derived-res01-20261010T102656Z/normalized/matches.json",
            ),
            classification_path=_configured_path(
                "FDH_GROUP2_CLASSIFICATION",
                data_root,
                "20261010T102656.252222Z-72f200ad/normalized/classification.json",
            ),
            progress_path=_configured_path(
                "FDH_GROUP2_PROGRESS",
                data_root,
                "20261010T102656.252222Z-72f200ad/normalized/progress.json",
            ),
            capture_metadata_path=_configured_path(
                "FDH_GROUP2_CAPTURE_METADATA",
                data_root,
                "20261010T102656.252222Z-72f200ad/metadata/capture.json",
            ),
            top_players_path=_configured_path(
                "FDH_GROUP2_TOP_PLAYERS", group2_top_root, "normalized/players.json"
            ),
            top_rankings_path=_configured_path(
                "FDH_GROUP2_TOP_RANKINGS", group2_top_root, "normalized/rankings.json"
            ),
            top_progress_path=_configured_path(
                "FDH_GROUP2_TOP_PROGRESS", group2_top_root, "normalized/progress.json"
            ),
            top_foreigners_path=_configured_path(
                "FDH_GROUP2_TOP_FOREIGNERS", group2_top_root, "normalized/foreigners.json"
            ),
            top_capture_metadata_path=_configured_path(
                "FDH_GROUP2_TOP_CAPTURE_METADATA", group2_top_root, "metadata/capture.json"
            ),
            top_validation_path=_configured_path(
                "FDH_GROUP2_TOP_VALIDATION", group2_top_root, "validation/results.json"
            ),
            top_source_html_path=_configured_path(
                "FDH_GROUP2_TOP_SOURCE_HTML", group2_top_root, "raw/source.html"
            ),
            top_team_catalog_path=_configured_optional_path(
                "FDH_GROUP2_TOP_TEAM_CATALOG", PROJECT_ROOT
            ),
            referees_root=referees_root,
            referees_related_matches_path=_configured_optional_path(
                "FDH_GROUP2_REFEREES_MATCHES", PROJECT_ROOT
            ),
            statistics_root=group2_statistics_root,
            group="II",
            group1_settings=group1,
            team_profiles_index_path=_resolve_path(
                Path(os.getenv("FDH_TEAM_PROFILES_INDEX", str(DEFAULT_TEAM_PROFILES_INDEX))),
                PROJECT_ROOT,
            ),
            local_data_root=local_data_root,
            match_generation_root=_optional_data_path(
                "FDH_MATCH_GENERATION_ROOT",
                local_data_root,
                match_generation_default,
            ),
            player_inventory_root=_optional_data_path(
                "FDH_PLAYER_INVENTORY_ROOT",
                local_data_root,
                "players/inventory-2026-27",
            ),
            player_compact_root=_optional_data_path(
                "FDH_PLAYER_COMPACT_ROOT",
                local_data_root,
                "players/compact-2026-27",
            ),
            player_team_captures_root=_optional_data_path(
                "FDH_PLAYER_TEAM_CAPTURES_ROOT",
                local_data_root,
                "team-captures",
            ),
            player_published_index_path=_optional_data_path(
                "FDH_PLAYER_PUBLISHED_INDEX",
                local_data_root,
                "published/team_profiles_2026-27.json",
            ),
            match_details_store_root=_optional_data_path(
                "FDH_MATCH_DETAILS_STORE_ROOT",
                local_data_root,
                "matches/details",
            ),
            match_details_published_root=_optional_data_path(
                "FDH_MATCH_DETAILS_PUBLISHED_ROOT",
                local_data_root,
                "matches/details/published",
            ),
            match_local_preview_artifact=(
                _resolve_path(Path(os.environ["FDH_MATCH_LOCAL_PREVIEW_ARTIFACT"]), PROJECT_ROOT)
                if os.getenv("FDH_MATCH_LOCAL_PREVIEW_ARTIFACT")
                else None
            ),
            update_admin_token=os.getenv("FDH_UPDATE_ADMIN_TOKEN"),
            cors_origins=tuple(
                origin.strip()
                for origin in os.getenv("FDH_CORS_ORIGINS", "").split(",")
                if origin.strip()
            ),
        )


def _normalize_group(value: str | int) -> str:
    normalized = str(value).strip().upper()
    aliases = {"1": "I", "I": "I", "2": "II", "II": "II"}
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("El grupo debe ser 1 o 2") from exc


def _resolve_path(path: Path, base: Path) -> Path:
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _configured_path(variable: str, root: Path, default_relative: str) -> Path:
    configured = os.getenv(variable)
    path = Path(configured) if configured else Path(default_relative)
    return _resolve_path(path, root)


def _configured_optional_path(variable: str, root: Path) -> Path | None:
    configured = os.getenv(variable)
    return _resolve_path(Path(configured), root) if configured else None


def _optional_data_path(
    variable: str, data_root: Path | None, default_relative: str
) -> Path | None:
    configured = os.getenv(variable)
    if configured:
        return _resolve_path(Path(configured), PROJECT_ROOT)
    if data_root is not None:
        return (data_root / default_relative).resolve()
    return None
