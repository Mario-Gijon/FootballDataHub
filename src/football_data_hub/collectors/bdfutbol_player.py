"""Plan and acquire explicit BDFutbol player views without bypassing access checks."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_data_hub.parsers.player_pages import PLAYER_VIEWS, classify_player_view
from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus
from football_data_hub.providers.bdfutbol.discovery import (
    capture_dom_snapshot,
    timestamp_utc,
    write_json,
)
from football_data_hub.parsers.player_pages import discover_player_snapshots

_PLAYER_ID = re.compile(r"^j\d+$")
_VIEW_MARKERS = {
    "profile": ("Futbolista",),
    "statistics": ("Estadísticas",),
    "matches": ("Partidos",),
    "rivals": ("Rivales",),
}
_BASE_URL = "https://www.bdfutbol.com/es"


class PlayerAcquisitionStopped(RuntimeError):
    """A player run stopped at the first access or raw integrity problem."""

    def __init__(
        self,
        *,
        player_id: str,
        view: str,
        url: str,
        status: str,
        records: list[dict[str, Any]],
        reason: str | None = None,
    ) -> None:
        self.player_id = player_id
        self.view = view
        self.url = url
        self.status = status
        self.records = records
        self.reason = reason
        super().__init__(f"Adquisición detenida en {player_id}/{view}: {status} ({url})")


def player_view_url(player_id: str, view: str) -> str:
    """Return the observed canonical route for one of the four player views."""
    if not _PLAYER_ID.fullmatch(player_id):
        raise ValueError(f"ID de jugador no válido: {player_id}")
    digits = player_id[1:]
    routes = {
        "profile": f"{_BASE_URL}/j/{player_id}.html",
        "statistics": f"{_BASE_URL}/j/{player_id}.html?p=stats",
        "matches": f"{_BASE_URL}/p/{player_id}.html",
        "rivals": f"{_BASE_URL}/p/jr{digits}.html",
    }
    try:
        return routes[view]
    except KeyError as exc:
        raise ValueError(f"Vista de jugador no admitida: {view}") from exc


def _player_sort_key(player_id: str) -> tuple[int, str]:
    return int(player_id[1:]), player_id


def _snapshot_matches(candidate: dict[str, Any], url: str) -> bool:
    return (
        candidate.get("usable") is True
        and candidate.get("hash_status") == "VALID"
        and candidate.get("is_base_view_snapshot") is True
        and candidate.get("url") == url
        and candidate.get("requested_url") == url
        and candidate.get("final_url") == url
    )


def build_player_acquisition_plan(
    pilot_candidates: list[dict[str, Any]],
    raw_snapshots: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    batch_size: int = 3,
    refresh: bool = False,
) -> dict[str, Any]:
    """Build a deterministic, read-only plan for a deliberately small pilot."""
    if batch_size < 1:
        raise ValueError("batch_size debe ser al menos 1")
    unique: dict[str, dict[str, Any]] = {}
    for candidate in pilot_candidates:
        player_id = str(candidate.get("player_id") or "")
        if not _PLAYER_ID.fullmatch(player_id):
            raise ValueError(f"ID de jugador no válido en candidatos: {player_id}")
        unique.setdefault(player_id, candidate)

    players = sorted(unique, key=_player_sort_key)
    entries: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    order = 0
    for player_index, player_id in enumerate(players):
        candidate = unique[player_id]
        batch_index = player_index // batch_size + 1
        if len(batches) < batch_index:
            batches.append({"batch": batch_index, "player_ids": []})
        batches[batch_index - 1]["player_ids"].append(player_id)
        team_ids = sorted({str(item) for item in candidate.get("team_season_ids", [])})
        supplied_profile_url = candidate.get("profile_url")
        for view in PLAYER_VIEWS:
            order += 1
            canonical_url = player_view_url(player_id, view)
            url = str(supplied_profile_url) if view == "profile" and supplied_profile_url else canonical_url
            if classify_player_view(url) != (player_id, view):
                raise ValueError(f"URL inconsistente para {player_id}/{view}: {url}")
            candidates = raw_snapshots.get((player_id, view), [])
            valid = sorted(
                (item for item in candidates if _snapshot_matches(item, url)),
                key=lambda item: (str(item.get("captured_at_utc") or ""), str(item.get("snapshot_directory") or "")),
            )
            latest = valid[-1] if valid else None
            filtered = [
                item for item in candidates
                if item.get("usable") is True and item.get("is_base_view_snapshot") is False
            ]
            invalid = [item for item in candidates if item.get("usable") is not True]
            if latest and not refresh:
                acquisition_status = "REUSE_VALID_SNAPSHOT"
            elif latest and refresh:
                acquisition_status = "REFRESH_PENDING"
            elif invalid:
                acquisition_status = "REVALIDATION_REQUIRED"
            elif filtered:
                acquisition_status = "BASE_VIEW_PENDING_FILTERED_VARIANT_EXISTS"
            else:
                acquisition_status = "PENDING_CAPTURE"
            url_status = (
                "VERIFIED_FROM_ROSTER" if view == "profile" and supplied_profile_url
                else "VERIFIED_FROM_RAW_SNAPSHOT" if latest
                else "INFERRED_FROM_OBSERVED_ROUTE_PATTERN"
            )
            entries.append({
                "player_id": player_id,
                "team_season_ids": team_ids,
                "view": view,
                "url": url,
                "url_status": url_status,
                "acquisition_order": order,
                "batch": batch_index,
                "snapshot_status": "CAPTURED_VALID" if latest else (
                    "CAPTURED_NON_VALID" if invalid else (
                        "CAPTURED_FILTERED_VARIANT" if filtered else "PENDING_CAPTURE"
                    )
                ),
                "acquisition_status": acquisition_status,
                "snapshot_available": latest is not None,
                "selected_snapshot_directory": latest.get("snapshot_directory") if latest else None,
                "selected_snapshot_sha256": latest.get("snapshot_sha256") if latest else None,
                "snapshot_count": len(candidates),
                "filtered_variant_count": len(filtered),
                "invalid_snapshot_count": len(invalid),
                "pending": acquisition_status != "REUSE_VALID_SNAPSHOT",
                "parse_status": "PENDING_PARSE" if latest else "NOT_AVAILABLE",
                "interpretation_status": "NOT_ASSESSED",
                "career_completeness": "NOT_ASSESSED",
            })

    return {
        "schema_version": "football_data_hub.player_acquisition_plan.v1",
        "scope": "EXPLICIT_PILOT_CANDIDATES_ONLY",
        "generated_offline": True,
        "browser_started": False,
        "network_requested": False,
        "refresh_requested": refresh,
        "batch_size_players": batch_size,
        "player_count": len(players),
        "view_count": len(entries),
        "valid_snapshots_available": sum(item["snapshot_available"] for item in entries),
        "views_pending": sum(item["pending"] for item in entries),
        "batches": batches,
        "players": [
            {
                "player_id": player_id,
                "selection_reasons": sorted(unique[player_id].get("selection_reasons", [])),
                "team_season_ids": sorted({str(item) for item in unique[player_id].get("team_season_ids", [])}),
                "membership_count": int(unique[player_id].get("membership_count") or 0),
            }
            for player_id in players
        ],
        "views": entries,
    }


def _new_run_root(raw_root: Path) -> Path:
    raw_root.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_utc()
    target = raw_root / stamp
    suffix = 1
    while target.exists():
        target = raw_root / f"{stamp}-{suffix:02d}"
        suffix += 1
    target.mkdir()
    return target


def _validate_written_snapshot(directory: Path, url: str) -> tuple[str, int]:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    raw = (directory / "rendered.html").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if metadata.get("access_status") != AccessStatus.VALID.value:
        raise ValueError("metadata no marca el acceso como VALID")
    if metadata.get("http_status") is None or not 200 <= int(metadata["http_status"]) < 300:
        raise ValueError("HTTP del snapshot no es válido")
    if metadata.get("requested_url") != url or metadata.get("final_url") != url:
        raise ValueError("la URL del snapshot no coincide con la solicitada")
    if metadata.get("rendered_html_sha256") != digest:
        raise ValueError("el SHA-256 del HTML no coincide con metadata")
    if metadata.get("rendered_html_bytes") != len(raw):
        raise ValueError("el tamaño del HTML no coincide con metadata")
    return digest, len(raw)


def capture_player_snapshots(
    *,
    player_ids: list[str],
    raw_root: Path,
    profile_dir: Path,
    browser: str = "brave",
    settle_ms: int = 1200,
    reuse_existing: bool = True,
    refresh: bool = False,
    screenshot: bool = False,
) -> list[dict[str, Any]]:
    """Capture up to three explicitly named players; stop on the first non-VALID page."""
    if not player_ids:
        raise ValueError("Indica al menos un ID explícito de jugador")
    if len(player_ids) > 3:
        raise ValueError("Cada piloto live se limita a tres jugadores como máximo")
    if settle_ms < 0:
        raise ValueError("settle_ms debe ser >= 0")
    ids = sorted(set(player_ids), key=_player_sort_key)
    for player_id in ids:
        if not _PLAYER_ID.fullmatch(player_id):
            raise ValueError(f"ID de jugador no válido: {player_id}")

    raw_root = raw_root.expanduser().resolve()
    discovered = discover_player_snapshots(raw_root) if raw_root.is_dir() else {}
    existing: dict[str, dict[str, Any]] = {}
    for player_id in ids:
        for view in PLAYER_VIEWS:
            url = player_view_url(player_id, view)
            valid = sorted(
                (item for item in discovered.get((player_id, view), []) if _snapshot_matches(item, url)),
                key=lambda item: (str(item.get("captured_at_utc") or ""), str(item.get("snapshot_directory") or "")),
            )
            if valid:
                existing[url] = valid[-1]

    records: list[dict[str, Any]] = []
    to_capture = [
        (player_id, view, player_view_url(player_id, view))
        for player_id in ids for view in PLAYER_VIEWS
        if refresh or not (reuse_existing and player_view_url(player_id, view) in existing)
    ]
    if not to_capture:
        return [
            {
                "player_id": player_id,
                "view": view,
                "url": player_view_url(player_id, view),
                "status": "REUSED_VALID",
                "snapshot_directory": existing[player_view_url(player_id, view)]["snapshot_directory"],
                "snapshot_sha256": existing[player_view_url(player_id, view)]["snapshot_sha256"],
            }
            for player_id in ids for view in PLAYER_VIEWS
        ]

    from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
    from football_data_hub.core.browser_session import BrowserSessionManager
    from football_data_hub.providers.bdfutbol.access import BDFutbolAccess

    run_root = _new_run_root(raw_root)
    state_path = run_root / "acquisition_state.json"
    write_json(state_path, _state_payload(records, run_root))
    session_config = BrowserRuntimeConfig(profile_dir=profile_dir, browser=browser)
    try:
        with BrowserSessionManager(session_config) as session:
            access = BDFutbolAccess(session)
            for player_id in ids:
                for view in PLAYER_VIEWS:
                    url = player_view_url(player_id, view)
                    if reuse_existing and not refresh and url in existing:
                        item = existing[url]
                        records.append({
                            "player_id": player_id,
                            "view": view,
                            "url": url,
                            "status": "REUSED_VALID",
                            "snapshot_directory": item["snapshot_directory"],
                            "snapshot_sha256": item["snapshot_sha256"],
                        })
                        write_json(state_path, _state_payload(records, run_root))
                        continue

                    output = run_root / player_id / view
                    with access.open(
                        url,
                        required_markers=_VIEW_MARKERS[view],
                        settle_ms=settle_ms,
                    ) as result:
                        assessment = result.assessment
                        if assessment.status is not AccessStatus.VALID or result.visit is None:
                            failed = _failed_record(player_id, view, url, assessment)
                            records.append(failed)
                            write_json(state_path, _state_payload(records, run_root))
                            raise PlayerAcquisitionStopped(
                                player_id=player_id,
                                view=view,
                                url=url,
                                status=assessment.status.value,
                                records=records.copy(),
                                reason=assessment.reason,
                            )
                        try:
                            if classify_player_view(assessment.final_url or "") != (player_id, view):
                                raise ValueError("la URL final no identifica el jugador y vista solicitados")
                            capture_dom_snapshot(
                                page=result.visit.page,
                                assessment=assessment,
                                output_dir=output,
                                screenshot=screenshot,
                            )
                            digest, byte_count = _validate_written_snapshot(output, url)
                        except Exception as exc:
                            record = {
                                "player_id": player_id,
                                "view": view,
                                "url": url,
                                "status": "RAW_INTEGRITY_ERROR",
                                "reason": f"{type(exc).__name__}: {exc}",
                                "snapshot_directory": output.relative_to(raw_root).as_posix(),
                            }
                            records.append(record)
                            write_json(state_path, _state_payload(records, run_root))
                            raise PlayerAcquisitionStopped(
                                player_id=player_id,
                                view=view,
                                url=url,
                                status="RAW_INTEGRITY_ERROR",
                                records=records.copy(),
                                reason=record["reason"],
                            ) from exc
                    records.append({
                        "player_id": player_id,
                        "view": view,
                        "url": url,
                        "status": "CAPTURED_VALID",
                        "snapshot_directory": output.relative_to(raw_root).as_posix(),
                        "snapshot_sha256": digest,
                        "snapshot_bytes": byte_count,
                    })
                    write_json(state_path, _state_payload(records, run_root))
    except PlayerAcquisitionStopped:
        raise
    return records


def _failed_record(
    player_id: str,
    view: str,
    url: str,
    assessment: AccessAssessment,
) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "view": view,
        "url": url,
        "status": assessment.status.value,
        "http_status": assessment.http_status,
        "final_url": assessment.final_url,
        "reason": assessment.reason,
    }


def _state_payload(records: list[dict[str, Any]], run_root: Path) -> dict[str, Any]:
    return {
        "schema_version": "football_data_hub.player_acquisition_state.v1",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_directory": run_root.name,
        "records": records,
        "resumable": True,
        "note": "Reanudar con los mismos IDs: las capturas VALID se reutilizan; --refresh crea snapshots nuevos.",
    }
