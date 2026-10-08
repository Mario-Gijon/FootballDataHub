"""Acquisition and integrity checks for BDFutbol club/team-season snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus
from football_data_hub.providers.bdfutbol.club_team import (
    InvalidClubTeamPage,
    classify_club_team_url,
    parse_club_team_html,
)
from football_data_hub.providers.bdfutbol.discovery import timestamp_utc

_TEAM_SEASON_ID = re.compile(r"^t\d{4}-\d+$")


class InvalidClubTeamSnapshot(ValueError):
    """A raw snapshot is missing, changed, or was not validated as source data."""


class ClubTeamAccessStopped(RuntimeError):
    """Live capture stopped at the first page that was not semantically valid."""

    def __init__(self, url: str, assessment: AccessAssessment, completed: list[dict[str, Any]]) -> None:
        self.url = url
        self.assessment = assessment
        self.completed = completed
        super().__init__(f"Acceso detenido en {url}: {assessment.status.value}")


@dataclass(frozen=True, slots=True)
class ClubTeamSnapshot:
    directory: Path
    url: str
    html: str
    metadata: dict[str, Any]
    sha256: str
    page: dict[str, str]
    capture_disposition: str = "CAPTURED"


def load_club_team_snapshot(directory: Path) -> ClubTeamSnapshot:
    """Load one raw snapshot offline and verify its original rendered HTML hash."""
    directory = directory.expanduser().resolve()
    metadata_path = directory / "metadata.json"
    html_path = directory / "rendered.html"
    if (directory / "INCOMPLETE").exists():
        raise InvalidClubTeamSnapshot(f"Snapshot marcado INCOMPLETE: {directory}")
    if not metadata_path.is_file() or not html_path.is_file():
        raise InvalidClubTeamSnapshot(f"Faltan metadata.json o rendered.html: {directory}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        html_bytes = html_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidClubTeamSnapshot(f"No se pudo leer el snapshot: {directory}") from exc
    if not isinstance(metadata, dict):
        raise InvalidClubTeamSnapshot("metadata.json debe contener un objeto")
    url = metadata.get("requested_url")
    page = classify_club_team_url(url) if isinstance(url, str) else None
    if page is None:
        raise InvalidClubTeamSnapshot(f"URL no reconocida para club/equipo-temporada: {url}")
    if metadata.get("access_status") != AccessStatus.VALID.value:
        raise InvalidClubTeamSnapshot(f"El snapshot no está marcado VALID: {metadata.get('access_status')}")
    if metadata.get("final_url") != url:
        raise InvalidClubTeamSnapshot(f"La URL final no coincide con la solicitada: {url}")
    if not isinstance(metadata.get("http_status"), int) or not 200 <= metadata["http_status"] < 300:
        raise InvalidClubTeamSnapshot(f"HTTP no válido: {metadata.get('http_status')}")
    digest = hashlib.sha256(html_bytes).hexdigest()
    if metadata.get("rendered_html_sha256") != digest:
        raise InvalidClubTeamSnapshot(f"SHA-256 del HTML incorrecto: {directory}")
    if metadata.get("rendered_html_bytes") != len(html_bytes):
        raise InvalidClubTeamSnapshot(f"El tamaño del HTML no coincide con metadata: {directory}")
    try:
        html = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidClubTeamSnapshot(f"El HTML no es UTF-8: {directory}") from exc
    return ClubTeamSnapshot(directory, url, html, metadata, digest, page)


def discover_latest_snapshots(
    raw_root: Path,
    *,
    team_season_ids: set[str] | None = None,
    club_ids: set[str] | None = None,
) -> list[ClubTeamSnapshot]:
    """Find the newest valid snapshot for each requested URL without network access."""
    raw_root = raw_root.expanduser().resolve()
    if not raw_root.is_dir():
        raise FileNotFoundError(f"No existe el directorio raw: {raw_root}")
    candidates: dict[str, list[tuple[Path, str, dict[str, str]]]] = {}
    for metadata_path in raw_root.rglob("metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict) or metadata.get("access_status") != AccessStatus.VALID.value:
            continue
        url = metadata.get("requested_url")
        page = classify_club_team_url(url) if isinstance(url, str) else None
        if page is None:
            continue
        if team_season_ids and page["entity_type"] == "team_season" and page["entity_id"] not in team_season_ids:
            continue
        captured = str(metadata.get("captured_at_utc") or "")
        candidates.setdefault(url, []).append((metadata_path.parent, captured, page))

    validated_by_url: dict[str, ClubTeamSnapshot | None] = {}

    def latest_valid(url: str) -> ClubTeamSnapshot | None:
        if url not in validated_by_url:
            snapshot = None
            for directory, _, _ in sorted(
                candidates[url],
                key=lambda candidate: (candidate[1], str(candidate[0])),
                reverse=True,
            ):
                try:
                    snapshot = load_club_team_snapshot(directory)
                    break
                except InvalidClubTeamSnapshot:
                    continue
            validated_by_url[url] = snapshot
        return validated_by_url[url]

    selected_clubs = set(club_ids or ())
    if team_season_ids and not selected_clubs:
        for url, url_candidates in candidates.items():
            _, _, page = url_candidates[0]
            if page["entity_type"] != "team_season" or page["view"] != "team_alignment":
                continue
            if page["entity_id"] not in team_season_ids:
                continue
            snapshot = latest_valid(url)
            if snapshot is None:
                continue
            parsed = parse_club_team_html(snapshot.html, snapshot.url, source_metadata=snapshot.metadata)
            if parsed.get("club_id"):
                selected_clubs.add(parsed["club_id"])

    selected_urls: set[str] = set()
    for url, url_candidates in candidates.items():
        _, _, page = url_candidates[0]
        if team_season_ids:
            if page["entity_type"] == "team_season" and page["entity_id"] in team_season_ids:
                selected_urls.add(url)
            elif page["entity_type"] == "club" and page["entity_id"] in selected_clubs:
                selected_urls.add(url)
        elif club_ids:
            if page["entity_type"] != "club" or page["entity_id"] in selected_clubs:
                selected_urls.add(url)
        else:
            selected_urls.add(url)

    snapshots: list[ClubTeamSnapshot] = []
    for url in selected_urls:
        snapshot = latest_valid(url)
        if snapshot is not None:
            snapshots.append(snapshot)
    return sorted(snapshots, key=lambda item: (item.page["entity_type"], item.page["entity_id"], item.page["view"]))


def _team_urls(team_season_id: str) -> dict[str, str]:
    if not _TEAM_SEASON_ID.fullmatch(team_season_id):
        raise ValueError(f"ID de equipo-temporada no válido: {team_season_id}")
    base = f"https://www.bdfutbol.com/es/t/{team_season_id}.html"
    return {
        "team_alignment": base,
        "team_roster": f"{base}?t=plantilla",
        "team_statistics": f"{base}?t=lista",
        "team_tracking": f"{base}?t=seg",
        "team_transfers": f"{base}?t=altas",
        "team_matches": f"{base}?tab=partits",
    }


def _club_urls(club_id: str) -> dict[str, str]:
    if not _CLUB_ID.fullmatch(club_id):
        raise ValueError(f"ID permanente de club no válido: {club_id}")
    number = _CLUB_ID.fullmatch(club_id).group("number")  # type: ignore[union-attr]
    base = f"https://www.bdfutbol.com/es/e/{club_id}.html"
    return {
        "club_profile": base,
        "club_statistics": f"{base}?p=stats",
        "club_players": f"https://www.bdfutbol.com/es/e/egols{number}.html",
        "club_coaches": f"https://www.bdfutbol.com/es/e/eentr{number}.html",
        "club_matches": f"https://www.bdfutbol.com/es/p/e{number}.html",
        "club_rivals": f"https://www.bdfutbol.com/es/p/er{number}.html",
    }


def _new_snapshot_run_root(raw_root: Path) -> Path:
    """Reserve a unique raw run directory; never reuse a path that may contain data."""
    raw_root.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp_utc()
    candidate = raw_root / timestamp
    suffix = 1
    while True:
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = raw_root / f"{timestamp}-{suffix:02d}"
            suffix += 1


def _snapshot_for_reuse(
    existing_by_url: dict[str, ClubTeamSnapshot], url: str, *, reuse_existing: bool
) -> ClubTeamSnapshot | None:
    if not reuse_existing:
        return None
    existing = existing_by_url.get(url)
    return replace(existing, capture_disposition="REUSED") if existing else None


_CLUB_ID = re.compile(r"^e(?P<number>\d+)$")


def capture_club_team_snapshots(
    *,
    team_season_ids: list[str],
    raw_root: Path,
    profile_dir: Path,
    browser: str = "brave",
    settle_ms: int = 1200,
    reuse_existing: bool = True,
    match_result_filters: tuple[str, ...] = (),
) -> list[ClubTeamSnapshot]:
    """Capture all discovered team/club views with Brave + Xvfb + CDP.

    The first team page provides the permanent club ID. No form is submitted,
    no preference is saved, and the run stops at the first non-VALID assessment.
    """
    if not team_season_ids:
        raise ValueError("Indica al menos un ID explícito de equipo-temporada")
    if settle_ms < 0:
        raise ValueError("settle_ms debe ser >= 0")
    allowed_result_filters = {"all", "pg", "pe", "pp"}
    invalid_filters = set(match_result_filters) - allowed_result_filters
    if invalid_filters:
        raise ValueError(f"Filtros de resultado no admitidos: {sorted(invalid_filters)}")
    unique_ids = list(dict.fromkeys(team_season_ids))
    for team_id in unique_ids:
        if not _TEAM_SEASON_ID.fullmatch(team_id):
            raise ValueError(f"ID de equipo-temporada no válido: {team_id}")

    from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
    from football_data_hub.core.browser_session import BrowserSessionManager
    from football_data_hub.providers.bdfutbol.access import BDFutbolAccess
    from football_data_hub.providers.bdfutbol.discovery import capture_dom_snapshot

    raw_root = raw_root.expanduser().resolve()
    run_root: Path | None = None
    processed: list[ClubTeamSnapshot] = []
    log: list[dict[str, Any]] = []
    config = BrowserRuntimeConfig(profile_dir=profile_dir, browser=browser)

    existing_by_url = {
        snapshot.url: snapshot
        for snapshot in discover_latest_snapshots(raw_root, team_season_ids=set(unique_ids))
    } if reuse_existing and raw_root.is_dir() else {}

    with BrowserSessionManager(config) as session:
        access = BDFutbolAccess(session)

        def capture(url: str, marker: tuple[str, ...], output_parts: tuple[str, ...]) -> ClubTeamSnapshot:
            nonlocal run_root
            existing = _snapshot_for_reuse(existing_by_url, url, reuse_existing=reuse_existing)
            if existing is not None:
                log.append({"url": url, "status": "REUSED", "snapshot": str(existing.directory)})
                processed.append(existing)
                return existing
            if run_root is None:
                run_root = _new_snapshot_run_root(raw_root)
            output = run_root.joinpath(*output_parts)
            with access.open(url, required_markers=marker, settle_ms=settle_ms) as result:
                assessment = result.assessment
                if assessment.status is not AccessStatus.VALID or result.visit is None:
                    raise ClubTeamAccessStopped(url, assessment, log.copy())
                output.parent.mkdir(parents=True, exist_ok=True)
                capture_dom_snapshot(
                    page=result.visit.page,
                    assessment=assessment,
                    output_dir=output,
                    screenshot=False,
                )
            snapshot = replace(load_club_team_snapshot(output), capture_disposition="CAPTURED")
            processed.append(snapshot)
            existing_by_url[url] = snapshot
            log.append({"url": url, "status": "CAPTURED", "snapshot": str(output)})
            return snapshot

        for team_id in unique_ids:
            team_urls = _team_urls(team_id)
            team_base = capture(
                team_urls["team_alignment"],
                ("Plantilla", "2026-27"),
                (team_id, "team_alignment"),
            )
            team_page = parse_club_team_html(team_base.html, team_base.url, source_metadata=team_base.metadata)
            club_id = team_page.get("club_id")
            if not isinstance(club_id, str):
                raise InvalidClubTeamPage(
                    f"No se pudo resolver el ID permanente del club desde {team_id}; el snapshot del equipo se conservó."
                )
            team_name = next(
                (item.get("name") for item in team_page["relationships"] if item.get("entity_type") == "club"),
                None,
            )
            team_markers = ("2026-27", "1ª RFEF")
            club_markers = (team_name,) if isinstance(team_name, str) and team_name else ("BDFutbol",)
            for view, url in team_urls.items():
                if view == "team_alignment":
                    continue
                capture(url, team_markers, (team_id, view))
            for view, url in _club_urls(club_id).items():
                capture(url, club_markers, (team_id, view))
            for result_filter in dict.fromkeys(match_result_filters):
                parameters = {"cat": "1rf", "temp": "2026-27"}
                if result_filter != "all":
                    parameters["pgep"] = result_filter
                match_url = f"{_club_urls(club_id)['club_matches']}?{urlencode(parameters)}"
                capture(
                    match_url,
                    ("1rf", "2026-27"),
                    (team_id, "club_match_variants", result_filter),
                )
    return processed


def snapshot_view_from_path(directory: Path) -> dict[str, str]:
    """Return safe, non-sensitive URL/view identifiers for logs and manifests."""
    snapshot = load_club_team_snapshot(directory)
    parts = urlsplit(snapshot.url)
    return {**snapshot.page, "url": snapshot.url, "host": parts.hostname or ""}
