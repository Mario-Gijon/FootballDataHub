"""Offline sample selection and a non-authorizing future campaign description.

This module deliberately has no browser, access-adapter, HTTP, or acquisition
imports. Building a plan reads the verified MATCH-00 generation and MATCH-01B
store; it never reserves a navigation, writes a checkpoint, or promotes data.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .inventory import (
    MatchDetailInventoryError,
    VerifiedGeneration,
    build_match_detail_inventory,
    load_verified_match_generation,
)
from .store import MatchDetailStore, MatchDetailStoreError

EXCLUDED_SOURCE_MATCH_IDS = frozenset({"272582"})
MAX_SAMPLE_SIZE = 5
MIN_SAMPLE_SIZE = 3
_UNKNOWN_FEATURES = [
    "La estructura HTML de la ficha individual y su compatibilidad con el parser.",
    "Alineaciones, jugadores, sustituciones, tarjetas, eventos y minutos de la ficha.",
    "Expulsiones, autogoles u otras variantes que no se deducen del marcador del catálogo.",
]


class MatchSamplePlanError(ValueError):
    """La generación, inventario o estado no permite preparar un plan fiable."""


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_symlink_path(path: Path) -> None:
    current = path.expanduser().absolute()
    while current != current.parent:
        if current.is_symlink():
            raise MatchSamplePlanError(f"La ruta contiene un symlink: {current}")
        current = current.parent


def _read_persisted_inventory(
    inventory_dir: Path,
    *,
    data_root: Path,
    expected_inventory: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    requested = inventory_dir.expanduser().absolute()
    root = data_root.expanduser().resolve(strict=True)
    _reject_symlink_path(requested)
    if not requested.is_dir():
        raise MatchSamplePlanError("Faltan el directorio y los archivos del inventario persistido")
    try:
        requested.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise MatchSamplePlanError(
            "El inventario persistido debe existir dentro de data_root"
        ) from exc
    if requested.name != expected_inventory.get("inventory_id"):
        raise MatchSamplePlanError("La carpeta no coincide con el inventory_id")

    inventory_path = requested / "inventory.json"
    manifest_path = requested / "manifest.json"
    if any(
        path.is_symlink() or not path.is_file()
        for path in (inventory_path, manifest_path)
    ):
        raise MatchSamplePlanError(
            "Faltan inventory.json/manifest.json regulares en el inventario persistido"
        )
    inventory_raw = inventory_path.read_bytes()
    manifest_raw = manifest_path.read_bytes()
    try:
        persisted = json.loads(inventory_raw)
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchSamplePlanError("El inventario o manifiesto no contiene JSON válido") from exc
    if not isinstance(persisted, dict) or not isinstance(manifest, dict):
        raise MatchSamplePlanError("El inventario y manifiesto deben ser objetos JSON")

    expected_inventory_bytes = _canonical_json(expected_inventory)
    expected_manifest = {
        "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
        "inventory_id": expected_inventory["inventory_id"],
        "inventory_sha256": _sha256(expected_inventory_bytes),
        "record_count": len(expected_inventory["matches"]),
        "source_generation": expected_inventory["source_generation"],
    }
    if (
        persisted != expected_inventory
        or inventory_raw != expected_inventory_bytes
        or manifest != expected_manifest
        or manifest_raw != _canonical_json(expected_manifest)
    ):
        raise MatchSamplePlanError(
            "El inventario persistido está alterado, corrupto o no coincide con MATCH-00"
        )
    return persisted, _sha256(inventory_raw), _sha256(manifest_raw)


def _source_records(
    verified: VerifiedGeneration,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[int, str]]]:
    records: dict[str, dict[str, Any]] = {}
    team_names: dict[str, dict[int, str]] = {}
    groups = verified.matches_payload.get("groups")
    if not isinstance(groups, dict) or set(groups) != {"I", "II"}:
        raise MatchSamplePlanError("La generación no contiene ambos grupos")
    for group in ("I", "II"):
        group_payload = groups[group]
        if not isinstance(group_payload, dict):
            raise MatchSamplePlanError(f"Catálogo inválido para Grupo {group}")
        names: dict[int, str] = {}
        for team in group_payload.get("teams", []):
            team_id = team.get("team_id") if isinstance(team, dict) else None
            name = team.get("name") if isinstance(team, dict) else None
            if (
                not isinstance(team_id, int)
                or isinstance(team_id, bool)
                or not isinstance(name, str)
                or not name.strip()
            ):
                raise MatchSamplePlanError(f"Identidad de equipo inválida en Grupo {group}")
            if team_id in names:
                raise MatchSamplePlanError(f"ID de equipo duplicado en Grupo {group}")
            names[team_id] = name
        team_names[group] = names
        for record in group_payload.get("matches", []):
            if not isinstance(record, dict):
                raise MatchSamplePlanError(f"Registro de partido inválido en Grupo {group}")
            internal_id = record.get("internal_id")
            if not isinstance(internal_id, str) or internal_id in records:
                raise MatchSamplePlanError("ID interno de partido ausente o duplicado")
            records[internal_id] = {**record, "_catalog_group": group}
    return records, team_names


def _candidate_from_inventory_record(
    record: dict[str, Any],
    *,
    source: dict[str, Any],
    team_names: dict[str, dict[int, str]],
) -> dict[str, Any]:
    group = source["_catalog_group"]
    reference = record.get("reference_result")
    expected = {
        "internal_id": record.get("internal_id"),
        "source_match_id": record.get("source_match_id"),
        "status": "played",
        "source_match_url": record.get("source_match_url"),
        "home_team_id": record.get("home_team_id"),
        "away_team_id": record.get("away_team_id"),
        "matchday": record.get("matchday"),
        "source_match_date": record.get("source_match_date"),
        "matchday_date": record.get("matchday_date"),
        "home_goals": reference.get("home_goals") if isinstance(reference, dict) else None,
        "away_goals": reference.get("away_goals") if isinstance(reference, dict) else None,
    }
    if any(source.get(key) != value for key, value in expected.items()):
        raise MatchSamplePlanError(
            f"El catálogo y el inventario discrepan para {record.get('internal_id')}"
        )
    if record.get("group") != group:
        raise MatchSamplePlanError("El grupo del inventario no coincide con MATCH-00")
    names = team_names[group]
    home_id = record.get("home_team_id")
    away_id = record.get("away_team_id")
    if home_id not in names or away_id not in names or home_id == away_id:
        raise MatchSamplePlanError("Los equipos no coinciden con el catálogo de su grupo")
    source_id = record.get("source_match_id")
    url = record.get("source_match_url")
    if (
        not isinstance(source_id, str)
        or not source_id.isdigit()
        or url != f"https://www.bdfutbol.com/es/p/p.php?id={source_id}"
    ):
        raise MatchSamplePlanError("ID y URL individual no son coherentes")
    home_goals = reference["home_goals"]
    away_goals = reference["away_goals"]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (home_goals, away_goals)
    ):
        raise MatchSamplePlanError("El resultado de referencia no es válido")
    return {
        "source_match_id": source_id,
        "internal_id": record["internal_id"],
        "group": group,
        "matchday": record["matchday"],
        "source_match_date": record.get("source_match_date"),
        "matchday_date": source.get("matchday_date"),
        "home_team_id": home_id,
        "home_team_name": names[home_id],
        "away_team_id": away_id,
        "away_team_name": names[away_id],
        "home_goals": home_goals,
        "away_goals": away_goals,
        "source_match_url": url,
        "source_generation_id": record["source_generation_id"],
        "source_generation_manifest_sha256": record[
            "source_generation_manifest_sha256"
        ],
        "source_capture_id": record["source_capture_id"],
        "source_snapshot_sha256": record["source_snapshot_sha256"],
        "source_matches_sha256": record["source_matches_sha256"],
        "unknown_features": list(_UNKNOWN_FEATURES),
    }


def _sample_sort_key(candidate: dict[str, Any]) -> tuple[int, int]:
    return candidate["matchday"], int(candidate["source_match_id"])


def select_sample_candidates(
    verified: VerifiedGeneration,
    inventory: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Select up to five unique matches and report unavailable result categories."""

    expected = build_match_detail_inventory(verified)
    if inventory != expected:
        raise MatchSamplePlanError(
            "El inventario no es la reconstrucción íntegra de la generación validada"
        )
    catalog, team_names = _source_records(verified)
    candidates: list[dict[str, Any]] = []
    for record in inventory["matches"]:
        source_id = record["source_match_id"]
        if source_id in EXCLUDED_SOURCE_MATCH_IDS:
            continue
        source = catalog.get(record["internal_id"])
        if source is None:
            raise MatchSamplePlanError("El inventario referencia un partido ajeno a MATCH-00")
        candidates.append(
            _candidate_from_inventory_record(record, source=source, team_names=team_names)
        )
    candidates.sort(key=lambda item: (0 if item["group"] == "I" else 1, *_sample_sort_key(item)))

    group_ii = [item for item in candidates if item["group"] == "II"]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    category_status: dict[str, dict[str, Any]] = {}

    categories = (
        (
            "scoreless_draw_0_0",
            "Grupo II, marcador 0–0 para revisar una ficha sin goles.",
            lambda item: item["home_goals"] == 0 and item["away_goals"] == 0,
            lambda item: _sample_sort_key(item),
        ),
        (
            "one_goal_margin",
            "Grupo II, victoria por un gol de diferencia.",
            lambda item: abs(item["home_goals"] - item["away_goals"]) == 1,
            lambda item: _sample_sort_key(item),
        ),
        (
            "high_scoring",
            "Grupo II, al menos cinco goles en el resultado del catálogo.",
            lambda item: item["home_goals"] + item["away_goals"] >= 5,
            lambda item: (
                abs(item["home_goals"] - item["away_goals"]),
                -(item["home_goals"] + item["away_goals"]),
                *_sample_sort_key(item),
            ),
        ),
        (
            "asymmetric_score",
            "Grupo II, diferencia de dos o más goles.",
            lambda item: abs(item["home_goals"] - item["away_goals"]) >= 2,
            lambda item: (
                item["home_goals"] + item["away_goals"],
                -abs(item["home_goals"] - item["away_goals"]),
                *_sample_sort_key(item),
            ),
        ),
    )
    for code, reason, predicate, rank in categories:
        pool = sorted((item for item in group_ii if predicate(item)), key=rank)
        chosen = next((item for item in pool if item["internal_id"] not in selected_ids), None)
        if chosen is None:
            category_status[code] = {
                "status": "NO_CANDIDATE",
                "reason": reason,
                "available_in_inventory": bool(pool),
            }
            continue
        candidate = {**chosen, "selection_reason_code": code, "selection_reason": reason}
        selected.append(candidate)
        selected_ids.add(candidate["internal_id"])
        category_status[code] = {
            "status": "SELECTED",
            "reason": reason,
            "internal_id": candidate["internal_id"],
        }

    group_i = [item for item in candidates if item["group"] == "I"]
    group_i.sort(
        key=lambda item: (
            0
            if item["home_goals"] == item["away_goals"]
            and 0 < item["home_goals"] + item["away_goals"] < 5
            else 1,
            *_sample_sort_key(item),
        )
    )
    group_i_choice = next(
        (item for item in group_i if item["internal_id"] not in selected_ids), None
    )
    if group_i_choice is None:
        category_status["group_i"] = {
            "status": "NO_CANDIDATE",
            "reason": "Incluir una ficha del Grupo I para contrastar el primer ejemplo del Grupo II.",
            "available_in_inventory": bool(group_i),
        }
    else:
        reason = "Partido del Grupo I para contrastar el primer ejemplo del Grupo II."
        candidate = {
            **group_i_choice,
            "selection_reason_code": "group_i",
            "selection_reason": reason,
        }
        selected.append(candidate)
        selected_ids.add(candidate["internal_id"])
        category_status["group_i"] = {
            "status": "SELECTED",
            "reason": reason,
            "internal_id": candidate["internal_id"],
        }

    # A small, valid inventory can lack result patterns. Fill to three only from
    # other verified records; the missing category remains explicitly reported.
    for item in candidates:
        if len(selected) >= MIN_SAMPLE_SIZE or len(selected) >= MAX_SAMPLE_SIZE:
            break
        if item["internal_id"] in selected_ids:
            continue
        selected.append(
            {
                **item,
                "selection_reason_code": "baseline_sample",
                "selection_reason": "Muestra adicional verificada para alcanzar una campaña útil.",
            }
        )
        selected_ids.add(item["internal_id"])

    if len(selected) > MAX_SAMPLE_SIZE:
        selected = selected[:MAX_SAMPLE_SIZE]
    return selected, category_status


def _store_read_only_status(
    inventory: dict[str, Any], store_root: Path
) -> dict[str, Any]:
    try:
        with _read_only_existing_store_lock(store_root) as lock_state:
            reconciliation = MatchDetailStore(store_root).reconcile(inventory)
            checkpoint_path = (
                store_root.expanduser().absolute()
                / "states"
                / f"{inventory['inventory_id']}.json"
            )
            checkpoint_sha256 = None
            checkpoint_status = "ABSENT"
            if checkpoint_path.is_symlink():
                checkpoint_status = "INVALID_SYMLINK"
            elif checkpoint_path.is_file():
                checkpoint_raw = checkpoint_path.read_bytes()
                checkpoint_sha256 = _sha256(checkpoint_raw)
                try:
                    checkpoint = json.loads(checkpoint_raw)
                    checkpoint_status = checkpoint.get("status", "INVALID")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    checkpoint_status = "INVALID_JSON"
    except (MatchDetailStoreError, MatchSamplePlanError, OSError) as exc:
        return {
            "integrity_blocked": True,
            "active_stop": False,
            "status": "UNREADABLE",
            "errors": [str(exc)],
            "read_lock": "UNAVAILABLE",
            "verified_capture_count": 0,
            "invalid_snapshots": [],
            "invalid_discovery_artifacts": [],
            "diagnostics": [],
            "pending_navigation_attempt": None,
            "checkpoint_revision": None,
            "checkpoint_sha256": None,
        }
    integrity_blocked = bool(reconciliation["blocked"])
    active_stop = bool(reconciliation["active_stop"])
    return {
        "status": "BLOCKED" if integrity_blocked or active_stop else checkpoint_status,
        "read_lock": lock_state,
        "checkpoint_status": checkpoint_status,
        "checkpoint_revision": reconciliation["revision"],
        "checkpoint_sha256": checkpoint_sha256,
        "integrity_blocked": integrity_blocked,
        "active_stop": active_stop,
        "verified_capture_count": len(reconciliation["verified_by_internal_id"]),
        "invalid_snapshots": reconciliation["invalid_snapshots"],
        "invalid_discovery_artifacts": reconciliation["invalid_discovery_artifacts"],
        "pending_navigation_attempt": reconciliation["interrupted_navigation_attempt"],
        "diagnostics": reconciliation["diagnostics"],
    }


@contextmanager
def _read_only_existing_store_lock(store_root: Path) -> Iterator[str]:
    """Share-lock an existing acquisition lock without creating or editing it."""

    root = store_root.expanduser().absolute()
    _reject_symlink_path(root)
    lock_path = root / "acquisition.lock"
    if lock_path.is_symlink():
        raise MatchSamplePlanError("El lock del almacén es un symlink")
    if not lock_path.exists():
        yield "NO_EXISTING_LOCK_FILE"
        return
    if not lock_path.is_file():
        raise MatchSamplePlanError("El lock del almacén no es un archivo regular")
    with lock_path.open("rb") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MatchSamplePlanError(
                "Hay una operación activa en el almacén; no se toma una lectura concurrente"
            ) from exc
        try:
            yield "SHARED_READ_LOCK"
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def build_sample_plan_from_verified(
    *,
    verified: VerifiedGeneration,
    inventory: dict[str, Any],
    store_root: Path,
    inventory_sha256: str | None = None,
    inventory_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic read-only plan from already verified source data."""

    expected_inventory = build_match_detail_inventory(verified)
    if inventory != expected_inventory:
        raise MatchSamplePlanError(
            "El inventario no es la reconstrucción íntegra de la generación validada"
        )
    candidates, categories = select_sample_candidates(verified, inventory)
    if len({item["internal_id"] for item in candidates}) != len(candidates):
        raise MatchSamplePlanError("La selección contiene partidos duplicados")
    if any(item["source_match_id"] in EXCLUDED_SOURCE_MATCH_IDS for item in candidates):
        raise MatchSamplePlanError("La selección incluye el piloto histórico 272582")

    store = _store_read_only_status(inventory, store_root)
    stop_diagnostics = [
        item
        for item in store["diagnostics"]
        if item.get("stop_acquisition", True)
    ]
    historical_pilot_diagnostic = next(
        (
            item
            for item in store["diagnostics"]
            if item.get("source_match_id") == "272582"
            or item.get("internal_id")
            == "pf-2026-27-group-ii-bdfutbol-272582"
        ),
        None,
    )
    generation_source_hashes = {
        group: {
            "capture_id": item.get("capture_id"),
            "captured_at_utc": item.get("captured_at_utc"),
            "source_snapshot_sha256": item.get("source_snapshot_sha256"),
            "normalized_matches_sha256": item.get("files", {})
            .get("normalized_matches", {})
            .get("sha256"),
        }
        for group, item in sorted(
            (entry["group"], entry) for entry in verified.manifest_payload["source_captures"]
        )
    }
    campaign_basis = {
        "inventory_id": inventory["inventory_id"],
        "inventory_sha256": inventory_sha256,
        "source_generation_id": verified.generation_id,
        "source_generation_manifest_sha256": verified.manifest_sha256,
        "selected_internal_ids": [item["internal_id"] for item in candidates],
    }
    campaign_id = "match-detail-sample-campaign-" + _sha256(
        _canonical_json(campaign_basis)
    )[:16]
    authorization_scope = [
        {
            "campaign_id": campaign_id,
            "inventory_id": inventory["inventory_id"],
            "inventory_sha256": inventory_sha256,
            "inventory_manifest_sha256": inventory_manifest_sha256,
            "source_generation_id": verified.generation_id,
            "source_generation_manifest_sha256": verified.manifest_sha256,
            "internal_id": item["internal_id"],
            "source_match_id": item["source_match_id"],
            "group": item["group"],
            "source_match_url": item["source_match_url"],
            "authorization_status": "NOT_AUTHORIZED",
            "requires_legacy_stop_review": bool(store["active_stop"]),
            "maximum_navigations": 1,
            "automatic_retries": 0,
            "capture_promotion_enabled": False,
        }
        for item in candidates
    ]
    blocked_reasons = []
    if store["integrity_blocked"]:
        blocked_reasons.append("match_store_integrity_blocked")
    if store["active_stop"]:
        blocked_reasons.append("legacy_match_store_active_stop_requires_explicit_review")
    if store["pending_navigation_attempt"] is not None:
        blocked_reasons.append("unresolved_navigation_attempt_requires_manual_review")
    if len(candidates) < MIN_SAMPLE_SIZE:
        blocked_reasons.append("fewer_than_three_verified_sample_candidates")
    if historical_pilot_diagnostic is None and store["active_stop"]:
        blocked_reasons.append("active_stop_cannot_be_attributed_to_a_reviewed_diagnostic")

    plan = {
        "schema_version": "football_data_hub.match_detail_sampling_plan.v1",
        "mode": "offline_read_only_sample_plan",
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
        "promotion_enabled": False,
        "status": "BLOCKED" if blocked_reasons else "PLAN_ONLY_NOT_AUTHORIZED",
        "blocked_reasons": blocked_reasons,
        "source": {
            "competition": inventory["competition"],
            "season": inventory["season"],
            "generation_id": verified.generation_id,
            "generation_manifest_sha256": verified.manifest_sha256,
            "generation_sources": generation_source_hashes,
            "inventory_id": inventory["inventory_id"],
            "inventory_sha256": inventory_sha256,
            "inventory_manifest_sha256": inventory_manifest_sha256,
            "record_count": len(inventory["matches"]),
        },
        "selection_policy": {
            "maximum_candidates": MAX_SAMPLE_SIZE,
            "minimum_target": MIN_SAMPLE_SIZE,
            "excluded_source_match_ids": sorted(EXCLUDED_SOURCE_MATCH_IDS),
            "high_scoring_threshold_goals": 5,
            "asymmetric_threshold_goal_difference": 2,
            "category_status": categories,
        },
        "candidates": candidates,
        "first_candidate": candidates[0] if candidates else None,
        "campaign": {
            "campaign_id": campaign_id,
            "campaign_basis": campaign_basis,
            "is_authorization": False,
            "authorization_status": "NOT_AUTHORIZED",
            "per_match_authorization_scope": authorization_scope,
            "requires_explicit_review_of_legacy_stop": bool(store["active_stop"]),
            "legacy_pilot_stop": {
                "checkpoint_status": store.get("checkpoint_status"),
                "checkpoint_revision": store.get("checkpoint_revision"),
                "checkpoint_sha256": store.get("checkpoint_sha256"),
                "active_stop": store["active_stop"],
                "diagnostic": historical_pilot_diagnostic,
                "checkpoint_modified": False,
            },
        },
        "store": {
            **store,
            "stop_diagnostic_count": len(stop_diagnostics),
            "diagnostic_stop_codes": [
                item.get("error_code") for item in stop_diagnostics
            ],
        },
        "future_guarantees_required": [
            "Autorización independiente, revisada y ligada al campaign_id, inventory_id, hashes de origen, partido, ID BDFutbol y URL exacta.",
            "Registro append-only de la revisión explícita de la parada 272582; mantener intacto su checkpoint y bloquear si falta esa revisión.",
            "Reserva durable started/fsync anterior a la única llamada de navegación; caída brusca requiere revisión manual y nunca reintenta.",
            "Exclusión mutua compartida por procesos para almacén y perfil, mantenida desde la reserva hasta el cierre del navegador.",
            "Diagnósticos y descubrimientos en namespace aislado y no promocionable; promoción futura exige evidencia semántica de DOM ligada al HTML y hash.",
            "Paradas HTTP, desafío, redirección, identidad o estructura siguen siendo bloqueantes; sin desbloqueo automático ni --force.",
        ],
        "campaign_digest": None,
    }
    plan["campaign_digest"] = _sha256(_canonical_json({k: v for k, v in plan.items() if k != "campaign_digest"}))
    return plan


def build_offline_sample_plan(
    *,
    generation_root: Path,
    inventory_dir: Path,
    data_root: Path,
    store_root: Path,
) -> dict[str, Any]:
    """Verify local MATCH-00 and MATCH-01A files, then prepare a read-only plan."""

    try:
        verified = load_verified_match_generation(generation_root, data_root=data_root)
        rebuilt_inventory = build_match_detail_inventory(verified)
        _, inventory_sha256, manifest_sha256 = _read_persisted_inventory(
            inventory_dir,
            data_root=data_root,
            expected_inventory=rebuilt_inventory,
        )
    except (MatchDetailInventoryError, MatchDetailStoreError, OSError) as exc:
        raise MatchSamplePlanError(str(exc)) from exc
    return build_sample_plan_from_verified(
        verified=verified,
        inventory=rebuilt_inventory,
        store_root=store_root,
        inventory_sha256=inventory_sha256,
        inventory_manifest_sha256=manifest_sha256,
    )


def tree_sha256(path: Path) -> str | None:
    """Hash a local tree without following symlinks; useful for offline audits."""

    if not path.exists():
        return None
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*"), key=lambda entry: entry.relative_to(path).as_posix()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        if item.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(item).encode("utf-8"))
        elif item.is_file():
            digest.update(b"F\0" + relative + b"\0")
            digest.update(_sha256(item.read_bytes()).encode("ascii"))
        elif item.is_dir():
            digest.update(b"D\0" + relative + b"\0")
    return digest.hexdigest()
