"""Offline integrity inspection and selection of versioned team captures."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from football_data_hub.providers.bdfutbol.context import CompetitionContext

from .acquisition import DEFAULT_VIEWS, EXTRACTOR_VERSION, FOLLOW_STATES
from .export import normalized_payloads
from .models import TeamProfileData
from .parser import parse_team_profile_pages, resolve_team_view_urls
from .validation import SEMANTIC_VALIDATION_VERSION, validate_team_profile

REQUIRED_NORMALIZED_FILES = (
    "team_identity.json",
    "team_season.json",
    "players.json",
    "memberships.json",
    "player_statistics.json",
    "player_match_minutes.json",
    "player_match_metrics.json",
    "transfers.json",
    "profile_references.json",
)


@dataclass(frozen=True, slots=True)
class CaptureInspection:
    capture_id: str
    path: Path
    classification: str
    valid_for_original_scope: bool
    active_catalog_compatible: bool
    catalog_compatibility: dict[str, Any]
    complete_for_current_policy: bool
    reusable_as_seed: bool
    valid_views: tuple[str, ...]
    missing_views: tuple[str, ...]
    valid_follow_states: tuple[str, ...]
    missing_follow_states: tuple[str, ...]
    normalized_valid: bool
    current_semantic_validation_version: int | None
    reasons: tuple[str, ...]
    metadata: dict[str, Any]
    parsed: TeamProfileData | None
    validation: dict[str, Any]
    seed: dict[str, Any] | None

    @property
    def coverage_score(self) -> tuple[int, int, int, int]:
        return (
            int(self.complete_for_current_policy),
            len(self.valid_views),
            len(self.valid_follow_states),
            int(self.normalized_valid),
        )

    def manifest_summary(self) -> dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "capture_path": str(self.path),
            "classification": self.classification,
            "valid_for_original_scope": self.valid_for_original_scope,
            "active_catalog_compatible": self.active_catalog_compatible,
            "catalog_compatibility": self.catalog_compatibility,
            "complete_for_current_policy": self.complete_for_current_policy,
            "reusable_as_seed": self.reusable_as_seed,
            "valid_views": list(self.valid_views),
            "missing_views": list(self.missing_views),
            "valid_follow_states": list(self.valid_follow_states),
            "missing_follow_states": list(self.missing_follow_states),
            "normalized_valid": self.normalized_valid,
            "semantic_validation_version": self.current_semantic_validation_version,
            "reasons": list(self.reasons),
            "related_team_catalog": self.metadata.get("related_team_catalog"),
        }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _path_inside(root: Path, relative: str) -> Path:
    base = root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError("La ruta del snapshot sale de la carpeta de captura")
    return target


def _read_hashed_html(root: Path, evidence: dict[str, Any]) -> tuple[bytes, Path]:
    relative = evidence.get("path")
    expected_hash = evidence.get("sha256")
    if not isinstance(relative, str) or not relative or not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("Falta la ruta o el SHA-256 obligatorio del snapshot")
    path = _path_inside(root, relative)
    payload = path.read_bytes()
    if evidence.get("compression") == "gzip" or path.suffix == ".gz":
        payload = gzip.decompress(payload)
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("El SHA-256 del snapshot no coincide")
    return payload, path


def selected_follow_state(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    select = soup.select_one("#vista_jornades")
    if not select:
        return None
    selected = select.select_one("option[selected]")
    return str(selected.get("value")) if selected and selected.get("value") else None


def _catalog_compatible(actual: Any, expected: dict[str, Any] | None, group: str, season: str) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    required = ("group", "season", "sha256")
    if any(not actual.get(key) or not expected.get(key) for key in required):
        return False
    if any(actual.get(key) != expected.get(key) for key in required):
        return False
    expected_capture_id = expected.get("source_capture_id")
    if expected_capture_id and actual.get("source_capture_id") != expected_capture_id:
        return False
    expected_captured_at = expected.get("source_captured_at_utc")
    if expected_captured_at and actual.get("source_captured_at_utc") != expected_captured_at:
        return False
    return actual.get("group") == group and actual.get("season") == season


def compare_catalog_versions(
    *,
    source_reference: dict[str, Any],
    source_teams: list[dict[str, Any]],
    source_matches: list[dict[str, Any]],
    active_reference: dict[str, Any],
    active_teams: list[dict[str, Any]],
    active_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare catalog identity separately from legitimate result updates.

    Existing match IDs must remain attached to the same matchday and home/away
    team IDs. Scores and status may advance as a season is played; missing IDs
    and identity changes are conflicts and are never reconciled by names.
    """
    source_team_ids = {int(item["team_id"]) for item in source_teams}
    active_team_ids = {int(item["team_id"]) for item in active_teams}
    source_by_id: dict[str, dict[str, Any]] = {}
    active_by_id: dict[str, dict[str, Any]] = {}
    duplicate_source_ids: list[str] = []
    duplicate_active_ids: list[str] = []
    for records, index, duplicates in (
        (source_matches, source_by_id, duplicate_source_ids),
        (active_matches, active_by_id, duplicate_active_ids),
    ):
        for item in records:
            match_id = str(item.get("match_id"))
            if match_id in index:
                duplicates.append(match_id)
            else:
                index[match_id] = item

    source_ids = set(source_by_id)
    active_ids = set(active_by_id)
    missing_ids = sorted(source_ids - active_ids)
    added_ids = sorted(active_ids - source_ids)
    identity_conflicts: list[dict[str, Any]] = []
    status_changes: list[dict[str, Any]] = []
    score_changes: list[dict[str, Any]] = []
    schedule_changes: list[dict[str, Any]] = []
    identity_fields = ("matchday", "home_team_id", "away_team_id")
    for match_id in sorted(source_ids & active_ids):
        previous = source_by_id[match_id]
        current = active_by_id[match_id]
        differences = {
            field: {"source": previous.get(field), "active": current.get(field)}
            for field in identity_fields
            if previous.get(field) != current.get(field)
        }
        if differences:
            identity_conflicts.append({"match_id": match_id, "fields": differences})
            continue
        if (
            previous.get("matchday_date") != current.get("matchday_date")
            or previous.get("source_match_date") != current.get("source_match_date")
        ):
            schedule_changes.append({
                "match_id": match_id,
                "source_matchday_date": previous.get("matchday_date"),
                "active_matchday_date": current.get("matchday_date"),
                "source_match_date": previous.get("source_match_date"),
                "active_source_match_date": current.get("source_match_date"),
            })
        if previous.get("status") != current.get("status"):
            status_changes.append({
                "match_id": match_id,
                "source_status": previous.get("status"),
                "active_status": current.get("status"),
            })
        old_score = (previous.get("home_goals"), previous.get("away_goals"))
        new_score = (current.get("home_goals"), current.get("away_goals"))
        if old_score != new_score:
            score_changes.append({
                "match_id": match_id,
                "source_score": list(old_score),
                "active_score": list(new_score),
                "score_added": old_score == (None, None) and new_score != (None, None),
            })

    team_sets_match = source_team_ids == active_team_ids
    identity_compatible = not (
        missing_ids
        or identity_conflicts
        or duplicate_source_ids
        or duplicate_active_ids
        or not team_sets_match
    )
    return {
        "status": "compatible" if identity_compatible else "incompatible",
        "compatible": identity_compatible,
        "source_catalog": {
            "capture_id": source_reference.get("source_capture_id"),
            "captured_at_utc": source_reference.get("source_captured_at_utc"),
            "sha256": source_reference.get("sha256"),
        },
        "active_catalog": {
            "capture_id": active_reference.get("source_capture_id"),
            "captured_at_utc": active_reference.get("source_captured_at_utc"),
            "sha256": active_reference.get("sha256"),
        },
        "source_team_count": len(source_team_ids),
        "active_team_count": len(active_team_ids),
        "team_ids_conserved": team_sets_match,
        "source_match_count": len(source_matches),
        "active_match_count": len(active_matches),
        "match_ids_conserved": not missing_ids,
        "match_ids_added": added_ids,
        "match_ids_missing": missing_ids,
        "duplicate_source_match_ids": sorted(set(duplicate_source_ids)),
        "duplicate_active_match_ids": sorted(set(duplicate_active_ids)),
        "identity_conflicts": identity_conflicts,
        "status_changes": status_changes,
        "score_changes": score_changes,
        "schedule_changes": schedule_changes,
    }


def _load_source_catalog(
    *,
    source_reference: dict[str, Any],
    active_reference: dict[str, Any],
    active_teams: list[dict[str, Any]],
    active_matches: list[dict[str, Any]],
    competition: CompetitionContext,
    history_root: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Load the exact historical catalog referenced by a capture's immutable metadata."""
    if not isinstance(source_reference, dict):
        raise ValueError("La captura no conserva una referencia de catálogo verificable")
    if source_reference.get("sha256") == active_reference.get("sha256"):
        if not _catalog_compatible(source_reference, active_reference, competition.group_roman, competition.season):
            raise ValueError("La referencia del catálogo fuente contradice el catálogo activo con el mismo hash")
        return active_teams, active_matches, active_reference

    path_value = source_reference.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("La captura no conserva la ruta de su catálogo histórico")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        base = history_root or Path(__file__).resolve().parents[5]
        path = base / path
    if not path.is_file():
        raise ValueError(f"No existe el catálogo histórico original: {path}")
    from .catalog import load_team_catalog

    source_teams, source_matches, loaded_reference = load_team_catalog(
        path,
        competition=competition,
    )
    if not _catalog_compatible(
        source_reference,
        loaded_reference,
        competition.group_roman,
        competition.season,
    ):
        raise ValueError("El hash o la procedencia del catálogo histórico no coincide con la captura")
    return source_teams, source_matches, loaded_reference


def _normalized_payloads_match(
    root: Path,
    metadata: dict[str, Any],
    parsed: TeamProfileData,
    *,
    catalog_reference: dict[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    expected_payloads = normalized_payloads(parsed)
    normalized_hashes = metadata.get("normalized_snapshots", {})
    for filename, body in zip(REQUIRED_NORMALIZED_FILES, expected_payloads.values(), strict=True):
        path = root / "normalized" / filename
        if not path.is_file():
            reasons.append(f"Falta JSON normalizado: normalized/{filename}")
            continue
        try:
            raw = path.read_bytes()
            document = json.loads(raw)
            dataset_metadata = document.get("metadata", {})
            if document.get("schema_version") != 1:
                reasons.append(f"Versión inválida en normalized/{filename}")
                continue
            if (
                dataset_metadata.get("capture_id") != metadata.get("capture_id")
                or dataset_metadata.get("team_id") != metadata.get("team_id")
                or dataset_metadata.get("season") != metadata.get("season")
                or dataset_metadata.get("group") != metadata.get("group")
                or (dataset_metadata.get("related_team_catalog") or {}).get("sha256") != catalog_reference.get("sha256")
            ):
                reasons.append(f"Metadatos incompatibles en normalized/{filename}")
                continue
            expected_entry = normalized_hashes.get(filename)
            if expected_entry and hashlib.sha256(raw).hexdigest() != expected_entry.get("sha256"):
                reasons.append(f"Hash normalizado incorrecto: normalized/{filename}")
                continue
            actual_body = {key: value for key, value in document.items() if key not in {"schema_version", "metadata"}}
            if actual_body != _json_safe(body):
                reasons.append(f"JSON no coincide con la normalización offline: normalized/{filename}")
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            reasons.append(f"JSON normalizado ilegible: normalized/{filename}")
    return not reasons, tuple(reasons)


def inspect_team_capture(
    capture_dir: Path,
    *,
    team_catalog_record: dict[str, Any],
    competition: CompetitionContext,
    team_catalog_reference: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    required_views: tuple[str, ...] = DEFAULT_VIEWS,
    required_follow_states: tuple[str, ...] | None = None,
    include_seed_payloads: bool = False,
    catalog_history_root: Path | None = None,
) -> CaptureInspection:
    """Revalidate source and normalized files without opening a browser or network."""
    capture_dir = capture_dir.expanduser()
    reasons: list[str] = []
    metadata: dict[str, Any] = {}
    stored_validation: dict[str, Any] = {}
    parsed: TeamProfileData | None = None
    validation: dict[str, Any] = {}
    raw_views: dict[str, str] = {}
    access_by_view: dict[str, dict[str, Any]] = {}
    view_urls: dict[str, str] = {}
    page_titles: dict[str, str] = {}
    follow_state_html: dict[str, str] = {}
    follow_state_diagnostics: dict[str, dict[str, Any]] = {}
    capture_id = capture_dir.name
    identity_ok = False
    catalog_ok = False
    active_catalog_compatible = False
    catalog_compatibility: dict[str, Any] = {"status": "not_checked", "compatible": False}
    source_catalog_reference: dict[str, Any] = {}
    source_group_team_catalog: list[dict[str, Any]] = []
    source_known_matches: list[dict[str, Any]] = []
    stored_validation_ok = False
    normalized_valid = False
    current_validation_ok = False
    original_validation_ok = False
    valid_views: list[str] = []
    valid_states: list[str] = []

    try:
        metadata = json.loads((capture_dir / "metadata" / "capture.json").read_text(encoding="utf-8"))
        stored_validation = json.loads((capture_dir / "validation" / "results.json").read_text(encoding="utf-8"))
        capture_id = str(metadata.get("capture_id") or "")
        if not capture_id or capture_id != capture_dir.name:
            reasons.append("capture_id no coincide con el directorio versionado")
        expected_identity = {
            "source": "BDFutbol",
            "section": "team_profile",
            "season": competition.season,
            "group": competition.group_roman,
            "group_number": competition.group_number,
            "team_id": int(team_catalog_record["team_id"]),
            "team_name": team_catalog_record.get("name"),
            "team_url": team_catalog_record.get("team_url"),
        }
        identity_ok = all(metadata.get(key) == value for key, value in expected_identity.items())
        if not identity_ok:
            reasons.append("Identidad de fuente/equipo/grupo/temporada incompatible")
        stored_catalog_reference = metadata.get("related_team_catalog")
        try:
            (
                source_group_team_catalog,
                source_known_matches,
                source_catalog_reference,
            ) = _load_source_catalog(
                source_reference=stored_catalog_reference,
                active_reference=team_catalog_reference,
                active_teams=group_team_catalog,
                active_matches=known_matches,
                competition=competition,
                history_root=catalog_history_root,
            )
            catalog_ok = _catalog_compatible(
                stored_catalog_reference,
                source_catalog_reference,
                competition.group_roman,
                competition.season,
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            catalog_ok = False
            reasons.append(f"No se pudo verificar el catálogo histórico original: {exc}")
        if catalog_ok:
            catalog_compatibility = compare_catalog_versions(
                source_reference=source_catalog_reference,
                source_teams=source_group_team_catalog,
                source_matches=source_known_matches,
                active_reference=team_catalog_reference,
                active_teams=group_team_catalog,
                active_matches=known_matches,
            )
            active_catalog_compatible = bool(catalog_compatibility["compatible"])
            if not active_catalog_compatible:
                reasons.append("La captura no es compatible con el catálogo activo: " + json.dumps(
                    {
                        "match_ids_missing": catalog_compatibility["match_ids_missing"],
                        "identity_conflicts": catalog_compatibility["identity_conflicts"],
                        "team_ids_conserved": catalog_compatibility["team_ids_conserved"],
                    },
                    ensure_ascii=False,
                ))
        if not catalog_ok:
            reasons.append("La procedencia íntegra del catálogo de partidos original no pudo verificarse")
        stored_validation_ok = stored_validation.get("valid") is True
        if not stored_validation_ok:
            reasons.append("La validación guardada no está marcada como válida")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        reasons.append(f"Metadatos o validación no se pueden leer: {type(exc).__name__}: {exc}")

    if metadata and identity_ok and catalog_ok:
        requested_in_capture = tuple(metadata.get("requested_views") or ())
        snapshots = metadata.get("source_snapshots") if isinstance(metadata.get("source_snapshots"), dict) else {}
        access_path = capture_dir / "raw" / "access.json"
        try:
            access_payload = json.loads(access_path.read_text(encoding="utf-8"))
            if access_payload.get("capture_id") != capture_id:
                reasons.append("raw/access.json pertenece a otra captura")
            if access_payload.get("views") != metadata.get("access_by_view"):
                reasons.append("raw/access.json no coincide con los metadatos de acceso")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            reasons.append("Falta raw/access.json válido")
        reports = metadata.get("access_by_view") if isinstance(metadata.get("access_by_view"), dict) else {}
        for view in DEFAULT_VIEWS:
            if view not in requested_in_capture or view not in snapshots:
                continue
            evidence = snapshots.get(view, {})
            report = reports.get(view, {})
            try:
                payload, _ = _read_hashed_html(capture_dir, evidence)
                status = evidence.get("access_status")
                http_status = evidence.get("http_status")
                requested_url = report.get("requested_url")
                final_url = report.get("final_url")
                if status != "VALID" or http_status != 200 or report.get("status") != "VALID" or report.get("http_status") != 200:
                    raise ValueError("El snapshot no tiene evidencia HTTP 200/VALID en ambas estructuras")
                if not requested_url or requested_url != final_url or evidence.get("url") != requested_url:
                    raise ValueError("URL solicitada/final/source no coincide")
                if competition.season not in str(evidence.get("title") or report.get("page_title") or ""):
                    raise ValueError("El título no confirma la temporada")
                raw_views[view] = payload.decode("utf-8")
                access_by_view[view] = report
                view_urls[view] = requested_url
                page_titles[view] = str(evidence.get("title") or report.get("page_title") or "")
                valid_views.append(view)
            except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError, gzip.BadGzipFile) as exc:
                reasons.append(f"Vista {view} no reutilizable: {exc}")

        if "alignment" in raw_views:
            try:
                expected_urls = resolve_team_view_urls(
                    raw_views["alignment"], str(team_catalog_record["team_url"])
                )
                for view in tuple(valid_views):
                    if view_urls[view] != expected_urls[view]:
                        raw_views.pop(view, None)
                        access_by_view.pop(view, None)
                        page_titles.pop(view, None)
                        view_urls.pop(view, None)
                        valid_views.remove(view)
                        reasons.append(f"URL de {view} no coincide con el enlace real de Alineación")
            except (KeyError, ValueError) as exc:
                reasons.append(f"No se pueden resolver los enlaces desde Alineación: {exc}")
                raw_views.clear()
                access_by_view.clear()
                page_titles.clear()
                view_urls.clear()
                valid_views.clear()
        else:
            reasons.append("No hay una Alineación íntegra para validar equipo y resolver las vistas")
            raw_views.clear()
            access_by_view.clear()
            page_titles.clear()
            view_urls.clear()
            valid_views.clear()

        if "follow" in raw_views:
            states_evidence = metadata.get("follow_states") if isinstance(metadata.get("follow_states"), dict) else {}
            for state in FOLLOW_STATES:
                evidence = states_evidence.get(state)
                if not isinstance(evidence, dict):
                    continue
                try:
                    payload, _ = _read_hashed_html(capture_dir, evidence)
                    html = payload.decode("utf-8")
                    source_capture_id = evidence.get("source_capture_id") or capture_id
                    referenced_capture_ids = {
                        capture_id,
                        *(str(item) for item in metadata.get("reused_source_capture_ids", [])),
                    }
                    if source_capture_id not in referenced_capture_ids:
                        raise ValueError("La procedencia del estado no está referenciada por la captura")
                    if evidence.get("selected_value") != state:
                        raise ValueError("El valor seleccionado registrado no coincide")
                    state_status = evidence.get("status", "VALID")
                    if state_status == "DERIVED_OFFLINE":
                        if (
                            evidence.get("origin") != "derived_offline"
                            or evidence.get("derivation_method") != "embedded_javascript_matrices_v1"
                            or evidence.get("source_snapshot_sha256") != snapshots.get("follow", {}).get("sha256")
                            or not evidence.get("derived_at_utc")
                        ):
                            raise ValueError("La procedencia de la derivación offline no es válida")
                    elif state_status != "VALID":
                        raise ValueError("El estado del snapshot no es VALID ni DERIVED_OFFLINE")
                    if evidence.get("url") != view_urls["follow"]:
                        raise ValueError("La URL del estado no coincide con Seguimiento")
                    state_soup = BeautifulSoup(html, "html.parser")
                    select = state_soup.select_one("#vista_jornades")
                    option_values = {
                        str(option.get("value"))
                        for option in select.select("option")
                    } if select else set()
                    if state_soup.select_one("#taula-seguiment") is None or state not in option_values:
                        raise ValueError("El DOM no contiene la tabla de Seguimiento")
                    follow_state_html[state] = html
                    follow_state_diagnostics[state] = {
                        key: value
                        for key, value in evidence.items()
                        if key not in {"path", "compression", "stored_bytes", "bytes_utf8"}
                    }
                    follow_state_diagnostics[state].update({
                        "source_capture_id": source_capture_id,
                        "reused": True,
                    })
                    valid_states.append(state)
                except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError, gzip.BadGzipFile) as exc:
                    reasons.append(f"Estado Seguimiento {state} no reutilizable: {exc}")

            # The original follow snapshot itself is evidence for p when it
            # records the selected option, even if old exports lacked a
            # separate follow_states/p file.
            if "p" not in follow_state_html and selected_follow_state(raw_views["follow"]) == "p":
                p_html = raw_views["follow"]
                state_evidence = metadata.get("source_snapshots", {}).get("follow", {})
                follow_state_html["p"] = p_html
                follow_state_diagnostics["p"] = {
                    "selected_value": "p",
                    "url": view_urls["follow"],
                    "source_capture_id": capture_id,
                    "source_view_snapshot": "follow",
                    "captured_at_utc": state_evidence.get("captured_at_utc"),
                    "capture_timestamp_basis": state_evidence.get("capture_timestamp_basis"),
                    "reused": True,
                }
                if "p" not in valid_states:
                    valid_states.append("p")

        requested_valid_views = tuple(view for view in DEFAULT_VIEWS if view in raw_views)
        if "alignment" in raw_views:
            try:
                parsed = parse_team_profile_pages(
                    raw_views,
                    team_catalog_record=team_catalog_record,
                    competition_context=competition,
                    follow_state_html=follow_state_html,
                )
                original_validation = validate_team_profile(
                    parsed,
                    catalog_record=team_catalog_record,
                    group_team_catalog=source_group_team_catalog,
                    known_matches=source_known_matches,
                    requested_views=requested_valid_views,
                )
                original_validation_ok = bool(original_validation.get("valid"))
                if not original_validation_ok:
                    reasons.append("La revalidación semántica offline detectó incoherencias")
                validation = validate_team_profile(
                    parsed,
                    catalog_record=team_catalog_record,
                    group_team_catalog=group_team_catalog,
                    known_matches=known_matches,
                    requested_views=requested_valid_views,
                )
                if not validation.get("valid"):
                    reasons.append("La revalidación contra el catálogo activo detectó incoherencias")
                current_validation_ok = bool(
                    original_validation_ok
                    and validation.get("valid")
                    and active_catalog_compatible
                )
            except (ValueError, TypeError, KeyError) as exc:
                reasons.append(f"La revalidación semántica offline falló: {type(exc).__name__}: {exc}")

        if parsed is not None and original_validation_ok:
            normalized_valid, normalized_reasons = _normalized_payloads_match(
                capture_dir,
                metadata,
                parsed,
                catalog_reference=source_catalog_reference,
            )
            reasons.extend(normalized_reasons)

    required_views_tuple = tuple(dict.fromkeys(required_views))
    required_states_tuple = tuple(dict.fromkeys(
        required_follow_states if required_follow_states is not None else (FOLLOW_STATES if "follow" in required_views_tuple else ())
    ))
    missing_views = tuple(view for view in required_views_tuple if view not in valid_views)
    missing_states = tuple(state for state in required_states_tuple if state not in valid_states)
    seed_ok = bool(identity_ok and catalog_ok and "alignment" in raw_views and parsed is not None and current_validation_ok)
    original_views = tuple(metadata.get("requested_views") or ())
    original_valid = bool(
        stored_validation_ok
        and original_validation_ok
        and original_views
        and all(view in valid_views for view in original_views)
    )
    complete = bool(
        seed_ok
        and stored_validation_ok
        and not missing_views
        and not missing_states
        and normalized_valid
        and metadata.get("extractor_version") == EXTRACTOR_VERSION
        and validation.get("semantic_version") == SEMANTIC_VALIDATION_VERSION
    )
    if complete:
        classification = "complete"
    elif seed_ok:
        classification = "reusable_seed"
    elif identity_ok and catalog_ok and active_catalog_compatible:
        classification = "incomplete"
    else:
        classification = "invalid"

    seed = None
    if seed_ok:
        inherited_ids = list(metadata.get("reused_source_capture_ids") or [])
        inherited_ids.append(capture_id)
        inherited_ids.extend(
            str(item.get("source_capture_id"))
            for item in follow_state_diagnostics.values()
            if item.get("source_capture_id")
        )
        seed = {
            "capture_id": capture_id,
            "seed_capture_ids": tuple(dict.fromkeys(inherited_ids)),
            "path": capture_dir,
        }
        if include_seed_payloads:
            seed.update({
                "raw_views": raw_views,
                "access_by_view": access_by_view,
                "page_titles": page_titles,
                "view_urls": view_urls,
                "browser": metadata.get("browser", {}),
                "follow_state_html": follow_state_html,
                "follow_state_diagnostics": follow_state_diagnostics,
            })

    return CaptureInspection(
        capture_id=capture_id,
        path=capture_dir,
        classification=classification,
        valid_for_original_scope=original_valid,
        active_catalog_compatible=active_catalog_compatible,
        catalog_compatibility=catalog_compatibility,
        complete_for_current_policy=complete,
        reusable_as_seed=seed_ok,
        valid_views=tuple(view for view in DEFAULT_VIEWS if view in valid_views),
        missing_views=missing_views,
        valid_follow_states=tuple(state for state in FOLLOW_STATES if state in valid_states),
        missing_follow_states=missing_states,
        normalized_valid=normalized_valid,
        current_semantic_validation_version=validation.get("semantic_version") if current_validation_ok else None,
        reasons=tuple(dict.fromkeys(reasons)),
        metadata=metadata,
        parsed=None,
        validation=validation,
        seed=seed,
    )
