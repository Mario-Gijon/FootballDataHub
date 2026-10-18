"""Explicit, atomic activation and comparison of immutable MATCH generations.

This module never acquires source data. Generation inputs are verified offline
before a report or active pointer can be written.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.match_details.inventory import (
    MatchDetailInventoryError,
    load_verified_match_generation,
)

ACTIVE_SCHEMA = "football_data_hub.match_generation_active.v1"
ACTIVATION_SCHEMA = "football_data_hub.match_generation_activation.v1"
DIFF_SCHEMA = "football_data_hub.match_generation_diff.v1"


class MatchGenerationActivationError(ValueError):
    """A generation cannot safely be compared, activated, or resolved."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchGenerationActivationError(f"No se puede leer evidencia JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MatchGenerationActivationError(f"Se esperaba un objeto JSON: {path}")
    return value, raw


def _safe_generation_path(generation_id: str, *, data_root: Path) -> Path:
    if (
        not isinstance(generation_id, str)
        or not generation_id
        or "/" in generation_id
        or "\\" in generation_id
        or generation_id in {".", ".."}
    ):
        raise MatchGenerationActivationError("ID de generación no válido.")
    root = data_root.expanduser().resolve(strict=True)
    candidate = root / "matches" / "generations" / generation_id
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise MatchGenerationActivationError("La ruta de generación contiene un symlink.")
        cursor = cursor.parent
    try:
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise MatchGenerationActivationError("La generación no está bajo data_root.") from exc
    return candidate


def resolve_match_generation_root(generation_or_store_root: Path, *, data_root: Path) -> Path:
    """Resolve a concrete generation or a store's explicitly active pointer.

    Concrete paths remain supported for compatibility. A store directory is
    never interpreted by picking the newest child; it must contain a valid
    `active-generation.json` pointer.
    """

    root = generation_or_store_root.expanduser().absolute()
    if (root / "manifest.json").is_file():
        return root
    if root.is_symlink():
        raise MatchGenerationActivationError("La raíz del almacén no puede ser symlink.")
    pointer_path = root / "active-generation.json"
    if pointer_path.is_symlink():
        raise MatchGenerationActivationError("El puntero activo no puede ser symlink.")
    if not pointer_path.is_file():
        raise MatchGenerationActivationError(
            "La ruta no es una generación ni contiene active-generation.json."
        )
    pointer, _ = _read_object(pointer_path)
    expected = {
        "schema_version", "generation_id", "manifest_sha256", "activated_at_utc",
        "activation_id", "activation_record_sha256",
    }
    if set(pointer) != expected or pointer.get("schema_version") != ACTIVE_SCHEMA:
        raise MatchGenerationActivationError("El puntero activo no cumple el esquema conocido.")
    if any(
        not isinstance(pointer.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", pointer[key])
        for key in ("manifest_sha256", "activation_record_sha256")
    ):
        raise MatchGenerationActivationError("El puntero contiene hashes inválidos.")
    activation_id = pointer.get("activation_id")
    if not isinstance(activation_id, str) or not re.fullmatch(r"activation-[0-9a-f]{32}", activation_id):
        raise MatchGenerationActivationError("El puntero no referencia un evento de activación.")
    if not isinstance(pointer.get("generation_id"), str) or not isinstance(pointer.get("activated_at_utc"), str):
        raise MatchGenerationActivationError("El puntero no contiene identidad o fecha válidas.")
    event_path = root / "activations" / "events" / f"{activation_id}.json"
    if (root / "activations").is_symlink() or (root / "activations/events").is_symlink():
        raise MatchGenerationActivationError("La ruta del evento de activación contiene symlinks.")
    if event_path.is_symlink() or not event_path.is_file():
        raise MatchGenerationActivationError("Falta el evento de activación referenciado.")
    event, event_raw = _read_object(event_path)
    event_fields = {
        "schema_version", "activation_id", "generation_id", "manifest_sha256",
        "previous_generation_id", "previous_pointer", "diff_report_sha256",
        "reviewer", "reviewed_report_sha256", "activated_at_utc",
    }
    if (
        set(event) != event_fields
        or _sha(event_raw) != pointer.get("activation_record_sha256")
        or event.get("schema_version") != ACTIVATION_SCHEMA
        or event.get("activation_id") != activation_id
        or event.get("generation_id") != pointer.get("generation_id")
        or event.get("manifest_sha256") != pointer.get("manifest_sha256")
        or event.get("activated_at_utc") != pointer.get("activated_at_utc")
        or not isinstance(event.get("reviewer"), str)
        or not event["reviewer"].strip()
        or event.get("reviewed_report_sha256") != event.get("diff_report_sha256")
    ):
        raise MatchGenerationActivationError("El puntero y el evento de activación no coinciden.")
    report_sha256 = event.get("diff_report_sha256")
    if not isinstance(report_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", report_sha256):
        raise MatchGenerationActivationError("El evento no referencia un hash de informe válido.")
    report_path = root / "diffs" / f"diff-{report_sha256[:24]}.json"
    if (root / "diffs").is_symlink():
        raise MatchGenerationActivationError("La ruta del informe contiene symlink.")
    report, _ = _read_object(report_path)
    report_body = {key: value for key, value in report.items() if key != "report_sha256"}
    if (
        report.get("report_sha256") != report_sha256
        or _sha(_canonical(report_body)) != report_sha256
    ):
        raise MatchGenerationActivationError("El informe de diferencias no coincide con el evento.")
    generation_root = _safe_generation_path(pointer["generation_id"], data_root=data_root)
    try:
        verified = load_verified_match_generation(generation_root, data_root=data_root)
    except (MatchDetailInventoryError, OSError, ValueError, KeyError, TypeError) as exc:
        raise MatchGenerationActivationError(f"La generación activa no supera la validación: {exc}") from exc
    if verified.manifest_sha256 != pointer.get("manifest_sha256"):
        raise MatchGenerationActivationError("El manifiesto de la generación activa no coincide.")
    return generation_root


def _group_records(bundle: Any) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for group_code, group in bundle.bootstrap.groups.items():
        for match in group.matches:
            if match.internal_id in records:
                raise MatchGenerationActivationError(f"Fixture duplicado: {match.internal_id}")
            records[match.internal_id] = {
                "internal_id": match.internal_id,
                "source_match_id": match.source_match_id,
                "group": group_code,
                "matchday": match.matchday,
                "matchday_date": _iso(match.matchday_date),
                "source_match_date": _iso(match.source_match_date),
                "kickoff_time_local": match.kickoff_time_local,
                "home_team_id": match.home_team_id,
                "away_team_id": match.away_team_id,
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "status": match.status,
                "source_match_url": match.source_match_url,
                "stadium_id": match.stadium_id,
                "stadium_name": match.stadium_name,
                "stadium_url": match.stadium_url,
                "referee_id": match.referee_id,
                "referee_name": match.referee_name,
                "referee_url": match.referee_url,
            }
    return records


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def compare_match_generations(
    before: Any,
    after: Any,
    *,
    approved_detail_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Create a deterministic, field-level diff without treating null as deletion."""

    old = _group_records(before)
    new = _group_records(after)
    old_ids, new_ids = set(old), set(new)
    approved = approved_detail_ids or set()
    entries: list[dict[str, Any]] = []
    hard_conflicts: list[str] = []
    review_items: list[str] = []
    tracked_fields = (
        "status", "home_goals", "away_goals", "matchday_date", "source_match_date",
        "kickoff_time_local", "stadium_id", "stadium_name", "stadium_url",
        "referee_id", "referee_name", "referee_url", "source_match_url",
    )
    for internal_id in sorted(old_ids | new_ids):
        if internal_id not in old:
            entries.append({"internal_id": internal_id, "change_type": "fixture_added", "changes": []})
            hard_conflicts.append(internal_id)
            continue
        if internal_id not in new:
            entries.append({"internal_id": internal_id, "change_type": "fixture_missing", "changes": []})
            hard_conflicts.append(internal_id)
            continue
        left, right = old[internal_id], new[internal_id]
        identity_fields = ("source_match_id", "group", "home_team_id", "away_team_id", "matchday")
        identity_changes = [
            {"field": field, "before": left[field], "after": right[field]}
            for field in identity_fields if left[field] != right[field]
        ]
        if identity_changes:
            entries.append({"internal_id": internal_id, "change_type": "identity_conflict", "changes": identity_changes})
            hard_conflicts.append(internal_id)
            continue
        changes: list[dict[str, Any]] = []
        review_required = False
        for field in tracked_fields:
            old_value, new_value = left.get(field), right.get(field)
            if old_value == new_value:
                continue
            if new_value is None:
                changes.append({"field": field, "before": old_value, "after": None, "interpretation": "not_observed_in_new_capture"})
                continue
            changes.append({"field": field, "before": old_value, "after": new_value})
            if field in {"status", "home_goals", "away_goals", "source_match_date", "kickoff_time_local"}:
                review_required = True
        if left["status"] == "played" and right["status"] == "unplayed":
            review_required = True
        if changes:
            kinds = {change["field"] for change in changes}
            if left["status"] == "played" and right["status"] == "unplayed":
                change_type = "played_to_unplayed_conflict"
                review_required = True
            elif left["status"] != "played" and right["status"] == "played":
                change_type = "newly_played"
            elif {"home_goals", "away_goals"} & kinds:
                change_type = "result_corrected"
                review_required = True
            elif {"source_match_date", "matchday_date", "kickoff_time_local"} & kinds:
                change_type = "fixture_updated"
            else:
                change_type = "fixture_updated"
        else:
            change_type = "unchanged"
        entry = {"internal_id": internal_id, "change_type": change_type, "changes": changes}
        if right["status"] == "played":
            entry["detail_status"] = "approved" if internal_id in approved else "details_pending"
        if review_required:
            entry["review_required"] = True
            review_items.append(internal_id)
        entries.append(entry)
    before_generation = before.bootstrap.metadata.generation_id
    after_generation = after.bootstrap.metadata.generation_id
    report: dict[str, Any] = {
        "schema_version": DIFF_SCHEMA,
        "before_generation_id": before_generation,
        "before_generation_sha256": before.bootstrap.metadata.generation_sha256,
        "after_generation_id": after_generation,
        "after_generation_sha256": after.bootstrap.metadata.generation_sha256,
        "fixtures": entries,
        "summary": {
            "unchanged": sum(item["change_type"] == "unchanged" for item in entries),
            "newly_played": sum(item["change_type"] == "newly_played" for item in entries),
            "fixture_updated": sum(item["change_type"] == "fixture_updated" for item in entries),
            "result_corrected": sum(item["change_type"] == "result_corrected" for item in entries),
            "played_to_unplayed_conflicts": sum(item["change_type"] == "played_to_unplayed_conflict" for item in entries),
            "identity_conflicts": sum(item["change_type"] == "identity_conflict" for item in entries),
            "fixtures_added": sum(item["change_type"] == "fixture_added" for item in entries),
            "fixtures_missing": sum(item["change_type"] == "fixture_missing" for item in entries),
            "played_without_approved_details": sum(item.get("detail_status") == "details_pending" for item in entries),
            "played_with_approved_details": sum(item.get("detail_status") == "approved" for item in entries),
            "review_required": len(set(review_items)),
            "hard_conflicts": len(set(hard_conflicts)),
        },
    }
    report["report_sha256"] = _sha(_canonical(report))
    return report


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _write_immutable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except FileExistsError as exc:
        raise MatchGenerationActivationError(f"No se sobrescribe evidencia previa: {path}") from exc
    finally:
        temp.unlink(missing_ok=True)


def activate_match_generation(
    candidate_generation_root: Path,
    *,
    store_root: Path,
    data_root: Path,
    reviewer: str,
    expected_generation_id: str | None,
    confirm_report_sha256: str,
    approved_detail_ids: set[str],
    player_ids: set[int],
) -> dict[str, Any]:
    """Validate and atomically point the store at a candidate generation.

    A legacy explicit generation may be named as the expected predecessor on
    first activation. Published packages are re-read against their historical
    generations and checked against the candidate before the pointer changes.
    """

    if not isinstance(reviewer, str) or not reviewer.strip():
        raise MatchGenerationActivationError("La activación requiere identificar al revisor.")
    store = store_root.expanduser().absolute()
    data = data_root.expanduser().resolve(strict=True)
    pointer_path = store / "active-generation.json"
    lock_path = store / ".generation-activation.lock"
    store.mkdir(parents=True, exist_ok=True)
    if store.is_symlink() or lock_path.is_symlink() or pointer_path.is_symlink():
        raise MatchGenerationActivationError("El almacén o sus bloqueos no pueden contener symlinks.")
    try:
        candidate = load_verified_match_generation(candidate_generation_root, data_root=data)
    except (MatchDetailInventoryError, OSError, ValueError, KeyError, TypeError) as exc:
        raise MatchGenerationActivationError(f"La generación candidata no supera la validación: {exc}") from exc
    from football_data_hub_api.match_results_dataset import load_match_results_dataset

    candidate_bundle = load_match_results_dataset(candidate_generation_root, data_root=data)
    if (
        candidate_bundle.bootstrap.metadata.generation_id != candidate.generation_id
        or candidate_bundle.bootstrap.metadata.generation_sha256 != candidate.manifest_sha256
    ):
        raise MatchGenerationActivationError("La generación candidata cambió durante la validación.")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous_pointer: dict[str, Any] | None = None
        if pointer_path.exists():
            previous_pointer, _ = _read_object(pointer_path)
            previous_root = resolve_match_generation_root(store, data_root=data)
            previous_id = previous_pointer["generation_id"]
        else:
            if not expected_generation_id:
                raise MatchGenerationActivationError(
                    "La primera activación requiere --expected-current-generation explícito."
                )
            previous_root = _safe_generation_path(expected_generation_id, data_root=data)
            previous_id = expected_generation_id
        if previous_id == candidate.generation_id:
            if previous_pointer is not None:
                return {"status": "already_active", "generation_id": candidate.generation_id}
            raise MatchGenerationActivationError("La generación candidata ya es el predecesor explícito.")
        previous_bundle = load_match_results_dataset(previous_root, data_root=data)
        active_ids = set(approved_detail_ids)
        report = compare_match_generations(previous_bundle, candidate_bundle, approved_detail_ids=active_ids)
        if report["summary"]["hard_conflicts"]:
            raise MatchGenerationActivationError("La identidad o el inventario de fixtures cambió; activación bloqueada.")
        if confirm_report_sha256 != report["report_sha256"]:
            raise MatchGenerationActivationError(
                f"La activación exige confirmar el hash exacto del informe: {report['report_sha256']}."
            )
        report_root = store / "diffs"
        report_path = report_root / f"diff-{report['report_sha256'][:24]}.json"
        report_bytes = _canonical(report)
        if report_path.exists():
            try:
                existing_report = report_path.read_bytes()
            except OSError as exc:
                raise MatchGenerationActivationError("No se puede verificar el informe existente.") from exc
            if existing_report != report_bytes:
                raise MatchGenerationActivationError("El informe previo con ese hash fue alterado.")
        else:
            _write_immutable(report_path, report_bytes)

        # Revalidate every published package against its immutable source and
        # candidate fixture before making the new generation visible.
        from football_data_hub_api.match_details_dataset import (
            MatchDetailsLoadError,
            load_published_match_details,
        )

        published_root = store / "details" / "published"
        details_store_root = store / "details"
        try:
            details = load_published_match_details(
                published_root,
                store_root=details_store_root,
                generation_root=candidate_generation_root,
                data_root=data,
                match_bundle=candidate_bundle,
                player_ids=player_ids,
            )
        except (MatchDetailsLoadError, OSError, ValueError, KeyError, TypeError) as exc:
            raise MatchGenerationActivationError(
                f"Una publicación aprobada contradice o no puede verificarse contra la candidata: {exc}"
            ) from exc
        actual_detail_ids = set(details)
        if actual_detail_ids != active_ids:
            raise MatchGenerationActivationError(
                "El conjunto de publicaciones aprobado cambió durante la validación; no se activa."
            )

        activation_id = f"activation-{uuid.uuid4().hex}"
        activation = {
            "schema_version": ACTIVATION_SCHEMA,
            "activation_id": activation_id,
            "generation_id": candidate.generation_id,
            "manifest_sha256": candidate.manifest_sha256,
            "previous_generation_id": previous_id,
            "previous_pointer": previous_pointer,
            "diff_report_sha256": report["report_sha256"],
            "reviewer": reviewer.strip(),
            "reviewed_report_sha256": confirm_report_sha256,
            "activated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        activation_raw = _canonical(activation)
        activation_path = store / "activations" / "events" / f"{activation_id}.json"
        _write_immutable(activation_path, activation_raw)
        pointer = {
            "schema_version": ACTIVE_SCHEMA,
            "generation_id": candidate.generation_id,
            "manifest_sha256": candidate.manifest_sha256,
            "activated_at_utc": activation["activated_at_utc"],
            "activation_id": activation_id,
            "activation_record_sha256": _sha(activation_raw),
        }
        _atomic_write(pointer_path, _canonical(pointer))
        return {"status": "activated", "generation_id": candidate.generation_id,
                "activation_id": activation_id, "report_sha256": report["report_sha256"]}


def write_diff_report(report: dict[str, Any], path: Path) -> Path:
    """Write a report once; existing generations/reports are never replaced."""

    raw = _canonical(report)
    if report.get("report_sha256") != _sha(_canonical({k: v for k, v in report.items() if k != "report_sha256"})):
        raise MatchGenerationActivationError("El hash del informe no coincide con su contenido.")
    _write_immutable(path.expanduser().absolute(), raw)
    return path
