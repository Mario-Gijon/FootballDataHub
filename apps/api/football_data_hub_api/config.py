"""Environment-based configuration for the standalone API application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = Path("data/exports/bdfutbol/group2_classification")


@dataclass(frozen=True, slots=True)
class ApiSettings:
    matches_path: Path
    classification_path: Path
    progress_path: Path
    capture_metadata_path: Path
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> ApiSettings:
        data_root_value = os.getenv("FDH_DATA_ROOT", str(DEFAULT_DATA_ROOT))
        data_root = _resolve_path(Path(data_root_value), PROJECT_ROOT)

        return cls(
            matches_path=_configured_path(
                "FDH_GROUP2_MATCHES",
                data_root,
                "derived-clas01b-20261010T102656Z/normalized/matches.json",
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

