"""Captura y carga validada de snapshots de las páginas de competición."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.competition import COMPETITION_URLS


class InvalidCompetitionSnapshot(ValueError):
    """El directorio no contiene un snapshot íntegro y validado."""


@dataclass(frozen=True, slots=True)
class CompetitionSnapshot:
    group: str
    directory: Path
    html: str
    metadata: dict[str, Any]
    sha256: str


class CompetitionAccessStopped(RuntimeError):
    """La navegación de competición terminó sin acceso semántico válido."""

    def __init__(self, group: str, assessment: Any) -> None:
        self.group = group
        self.assessment = assessment
        super().__init__(f"Grupo {group}: acceso detenido con estado {assessment.status.value}")


def load_competition_snapshot(directory: Path, expected_group: str) -> CompetitionSnapshot:
    """Lee offline un snapshot válido, comprobando URL, status, tamaño y hash."""
    if expected_group not in COMPETITION_URLS:
        raise ValueError(f"Grupo fuera del alcance: {expected_group}")
    directory = directory.expanduser().resolve()
    metadata_path = directory / "metadata.json"
    html_path = directory / "rendered.html"
    if (directory / "INCOMPLETE").exists():
        raise InvalidCompetitionSnapshot(f"Snapshot marcado INCOMPLETE: {directory}")
    if not metadata_path.is_file() or not html_path.is_file():
        raise InvalidCompetitionSnapshot(f"Faltan metadata.json o rendered.html en {directory}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        html_bytes = html_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidCompetitionSnapshot(f"No se pudo leer el snapshot: {directory}") from exc
    if not isinstance(metadata, dict):
        raise InvalidCompetitionSnapshot(f"metadata.json debe contener un objeto: {directory}")

    requested_url = metadata.get("requested_url")
    final_url = metadata.get("final_url")
    if metadata.get("access_status") != "VALID":
        raise InvalidCompetitionSnapshot(
            f"El snapshot no está validado como VALID: {metadata.get('access_status')}"
        )
    if requested_url != COMPETITION_URLS[expected_group] or final_url != requested_url:
        raise InvalidCompetitionSnapshot(
            f"URL del snapshot no corresponde al Grupo {expected_group}: {requested_url} -> {final_url}"
        )
    if not isinstance(metadata.get("http_status"), int) or not 200 <= metadata["http_status"] < 300:
        raise InvalidCompetitionSnapshot(f"HTTP no válido en metadata: {metadata.get('http_status')}")

    digest = hashlib.sha256(html_bytes).hexdigest()
    if metadata.get("rendered_html_sha256") != digest:
        raise InvalidCompetitionSnapshot(f"El SHA-256 del HTML no coincide: {directory}")
    if metadata.get("rendered_html_bytes") != len(html_bytes):
        raise InvalidCompetitionSnapshot(f"El tamaño del HTML no coincide con metadata: {directory}")
    try:
        html = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCompetitionSnapshot(f"El HTML no es UTF-8: {directory}") from exc
    return CompetitionSnapshot(expected_group, directory, html, metadata, digest)


def capture_competition_snapshots(
    *,
    raw_root: Path,
    profile_dir: Path,
    browser: str = "brave",
    settle_ms: int = 1000,
) -> dict[str, Path]:
    """Captura Grupo I y II en orden, deteniéndose ante cualquier acceso no válido.

    La sesión usa únicamente BrowserSessionManager + BDFutbolAccess. No conserva
    cookies/credenciales y no intenta resolver Cloudflare ni otros desafíos.
    """
    from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
    from football_data_hub.core.browser_session import BrowserSessionManager
    from football_data_hub.providers.bdfutbol.access import BDFutbolAccess
    from football_data_hub.providers.bdfutbol.discovery import capture_dom_snapshot, timestamp_utc

    run_dir = raw_root.expanduser().resolve() / timestamp_utc()
    config = BrowserRuntimeConfig(profile_dir=profile_dir, browser=browser)
    captured: dict[str, Path] = {}
    markers = {"I": ("Clasificación", "Grupo I", "2026-27"),
               "II": ("Clasificación", "Grupo II", "2026-27")}
    with BrowserSessionManager(config) as session:
        access = BDFutbolAccess(session)
        for group in ("I", "II"):
            with access.open(
                COMPETITION_URLS[group],
                required_markers=markers[group],
                settle_ms=settle_ms,
            ) as result:
                assessment = result.assessment
                if assessment.status.value != "VALID" or result.visit is None:
                    raise CompetitionAccessStopped(group, assessment)
                output_dir = run_dir / f"group_{group.lower()}"
                capture_dom_snapshot(
                    page=result.visit.page,
                    assessment=assessment,
                    output_dir=output_dir,
                    screenshot=False,
                )
                captured[group] = output_dir
    return captured
