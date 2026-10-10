"""Environment-based configuration for the standalone API application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = Path("data/exports/bdfutbol/group2_classification")
DEFAULT_TOP_CAPTURE = Path(
    "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6"
)
DEFAULT_GROUP2_REFEREES_CAPTURE = Path(
    "data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc"
)


@dataclass(frozen=True, slots=True)
class ApiSettings:
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

    @classmethod
    def from_env(cls) -> ApiSettings:
        data_root_value = os.getenv("FDH_DATA_ROOT", str(DEFAULT_DATA_ROOT))
        data_root = _resolve_path(Path(data_root_value), PROJECT_ROOT)
        top_root = _resolve_path(
            Path(os.getenv("FDH_GROUP2_TOP_ROOT", str(DEFAULT_TOP_CAPTURE))),
            PROJECT_ROOT,
        )
        referees_root = _resolve_path(
            Path(
                os.getenv(
                    "FDH_GROUP2_REFEREES_ROOT",
                    str(DEFAULT_GROUP2_REFEREES_CAPTURE),
                )
            ),
            PROJECT_ROOT,
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
            top_players_path=_configured_path("FDH_GROUP2_TOP_PLAYERS", top_root, "normalized/players.json"),
            top_rankings_path=_configured_path("FDH_GROUP2_TOP_RANKINGS", top_root, "normalized/rankings.json"),
            top_progress_path=_configured_path("FDH_GROUP2_TOP_PROGRESS", top_root, "normalized/progress.json"),
            top_foreigners_path=_configured_path("FDH_GROUP2_TOP_FOREIGNERS", top_root, "normalized/foreigners.json"),
            top_capture_metadata_path=_configured_path("FDH_GROUP2_TOP_CAPTURE_METADATA", top_root, "metadata/capture.json"),
            top_validation_path=_configured_path("FDH_GROUP2_TOP_VALIDATION", top_root, "validation/results.json"),
            top_source_html_path=_configured_path("FDH_GROUP2_TOP_SOURCE_HTML", top_root, "raw/source.html"),
            top_team_catalog_path=_configured_optional_path("FDH_GROUP2_TOP_TEAM_CATALOG", PROJECT_ROOT),
            referees_root=referees_root,
            referees_related_matches_path=_configured_optional_path(
                "FDH_GROUP2_REFEREES_MATCHES", PROJECT_ROOT
            ),
            cors_origins=tuple(
                origin.strip()
                for origin in os.getenv("FDH_CORS_ORIGINS", "").split(",")
                if origin.strip()
            ),
        )


def _resolve_path(path: Path, base: Path) -> Path:
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _configured_path(variable: str, root: Path, default_relative: str) -> Path:
    configured = os.getenv(variable)
    path = Path(configured) if configured else Path(default_relative)
    return _resolve_path(path, root)


def _configured_optional_path(variable: str, root: Path) -> Path | None:
    configured = os.getenv(variable)
    return _resolve_path(Path(configured), root) if configured else None
