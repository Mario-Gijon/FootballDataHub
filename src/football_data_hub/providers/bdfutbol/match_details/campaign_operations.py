"""Supervised offline queues for MATCH detail campaigns.

This coordinator delegates semantic validation, draft creation, publication and
verification to the existing MATCH-04D ledger and API dataset functions. It has
no browser or HTTP capability.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .campaign import MatchCampaignIntegrityError
from .operational_campaign import OperationalMatchCampaignLedger

OPERATIONS_SCHEMA = "football_data_hub.match_detail_campaign_operations.v1"
REPORT_SCHEMA = "football_data_hub.match_detail_campaign_operations_report.v1"
PUBLISH_CONFIRMATION = "PUBLISH_ONLY_INDIVIDUALLY_APPROVED_MATCH_DETAILS"
_CAMPAIGN_ID = re.compile(r"^match-detail-campaign-v2-[0-9a-f]{16}$")
_batch_lock_state = threading.local()


class CampaignOperationsError(ValueError):
    """An operational queue or its persisted report is invalid."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise CampaignOperationsError(f"{label} no puede ser un enlace simbólico: {path}")


def _resolve_relative_file(root: Path, relative_path: str, label: str) -> Path:
    root = root.expanduser().resolve(strict=True)
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise MatchCampaignIntegrityError(f"La ruta de {label} debe ser relativa y permanecer dentro del almacén")
    path = root
    for part in relative.parts:
        path = path / part
        _reject_symlink(path, label)
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise MatchCampaignIntegrityError(f"El archivo de {label} queda fuera del almacén o no es regular")
    return resolved


def _ensure_report_root(report_root: Path) -> None:
    missing: list[Path] = []
    cursor = report_root
    while not cursor.exists():
        _reject_symlink(cursor, "La ruta de informes")
        missing.append(cursor)
        cursor = cursor.parent
    _reject_symlink(cursor, "La ruta de informes")
    if not cursor.is_dir():
        raise CampaignOperationsError(f"La ruta de informes no es un directorio: {cursor}")
    for path in reversed(missing):
        path.mkdir()
        if not path.is_dir():
            raise CampaignOperationsError(f"No se pudo crear la ruta de informes: {path}")


@contextmanager
def _batch_lock(store_root: Path) -> Iterator[None]:
    operations_root = store_root / "operations"
    _reject_symlink(store_root, "La raíz del almacén")
    if operations_root.exists():
        _reject_symlink(operations_root, "La raíz de operaciones")
        if not operations_root.is_dir():
            raise CampaignOperationsError("La raíz de operaciones no es un directorio")
    else:
        operations_root.mkdir(parents=True)
    lock_path = operations_root / "offline-batch.lock"
    _reject_symlink(lock_path, "El lock de operaciones")
    lock_key = str(lock_path.resolve(strict=False))
    held = getattr(_batch_lock_state, "held", None)
    if held is None:
        held = {}
        _batch_lock_state.held = held
    # Campaign authorization and its executor are one operation in one
    # thread. Reuse that thread's already-held OS lock instead of exposing a
    # caller-controlled "lock already held" flag that could skip locking.
    if lock_key in held:
        descriptor, depth = held[lock_key]
        held[lock_key] = (descriptor, depth + 1)
        try:
            yield
        finally:
            current_descriptor, current_depth = held[lock_key]
            if current_descriptor != descriptor or current_depth <= 1:
                raise CampaignOperationsError("Estado interno de reentrada del lock inconsistente")
            held[lock_key] = (descriptor, current_depth - 1)
        return
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CampaignOperationsError("El lock de operaciones no es un archivo regular")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CampaignOperationsError("Ya hay otro lote operativo en ejecución") from exc
        held[lock_key] = (descriptor, 1)
        yield
    finally:
        held.pop(lock_key, None)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _write_report(report_root: Path, report: dict[str, Any]) -> Path:
    """Atomically replace the current run checkpoint; run IDs are unique."""

    _ensure_report_root(report_root)
    report_path = report_root / f"{report['run_id']}.json"
    _reject_symlink(report_path, "El informe")
    if report_path.exists():
        prior = load_operation_report(report_path)
        if prior.get("run_id") != report.get("run_id"):
            raise CampaignOperationsError("El identificador de informe ya está ocupado por otra ejecución")
    envelope = {
        "schema_version": REPORT_SCHEMA,
        "report_sha256": _sha(_canonical(report)),
        "report": report,
    }
    raw = _canonical(envelope)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{report_path.name}.", dir=report_root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, report_path)
        directory_fd = os.open(report_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return report_path


def load_operation_report(path: Path) -> dict[str, Any]:
    _reject_symlink(path, "El informe")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignOperationsError("No se puede leer el informe operativo") from exc
    if not isinstance(envelope, dict):
        raise CampaignOperationsError("El informe operativo debe ser un objeto JSON")
    report = envelope.get("report")
    if (
        envelope.get("schema_version") != REPORT_SCHEMA
        or not isinstance(report, dict)
        or envelope.get("report_sha256") != _sha(_canonical(report))
    ):
        raise CampaignOperationsError("El hash o contrato del informe operativo no coincide")
    return report


def build_batch_preflight(ledger: OperationalMatchCampaignLedger, campaign_id: str) -> dict[str, Any]:
    """Read-only plan of offline actions; failed states are never retried."""

    campaign = ledger.preflight(campaign_id)
    actions = []
    counts: dict[str, int] = {}
    for candidate in campaign["candidates"]:
        state = candidate["state"]
        if state == "DISCOVERY_REVIEW_REQUIRED":
            action = "validate_saved_artifact_then_prepare_if_valid"
        elif state in {"VALIDATED", "REVALIDATED"}:
            action = "prepare_draft"
        elif state == "DRAFT_PREPARED":
            action = "already_prepared_no_change"
        elif state in {"VALIDATION_FAILED", "REVALIDATION_FAILED", "STOPPED", "INTERRUPTED_REQUIRES_REVIEW"}:
            action = "manual_review_no_automatic_retry"
        elif state == "DOCUMENT_APPROVED":
            action = "explicit_publication_queue_only"
        elif state in {"PUBLISHED", "REVIEW_COMPLETED"}:
            action = "already_published_no_change"
        else:
            action = "not_in_offline_batch_scope"
        counts[action] = counts.get(action, 0) + 1
        actions.append({
            "internal_id": candidate["internal_id"],
            "source_match_id": candidate["source_match_id"],
            "group": candidate["group"],
            "matchday": candidate["matchday"],
            "state": state,
            "action": action,
            "artifact_id": (candidate.get("artifact") or {}).get("artifact_id"),
            "source_html_sha256": (candidate.get("artifact") or {}).get("source_html_sha256"),
        })
    return {
        "schema_version": OPERATIONS_SCHEMA,
        "campaign_id": campaign_id,
        "candidate_count": campaign["candidate_count"],
        "actions": actions,
        "action_counts": dict(sorted(counts.items())),
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
        "approval_enabled": False,
        "publication_enabled": False,
    }


def run_offline_batch(
    *,
    ledger: OperationalMatchCampaignLedger,
    campaign_id: str,
    data_root: Path,
    player_inventory_root: Path,
    player_compact_root: Path,
    player_team_captures_root: Path,
    player_published_index_path: Path,
) -> dict[str, Any]:
    """Validate already-saved HTML and prepare valid drafts, resumably."""

    if not _CAMPAIGN_ID.fullmatch(campaign_id):
        raise CampaignOperationsError("campaign_id v2 inválido")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    report = {
        "schema_version": REPORT_SCHEMA,
        "run_id": run_id,
        "campaign_id": campaign_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_generation_id": None,
        "source_generation_manifest_sha256": None,
        "finished_at_utc": None,
        "status": "RUNNING",
        "candidates": [],
        "processed_count": 0,
        "prepared_count": 0,
        "validation_failed_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
    }
    report_root = ledger.root.parent / "operations" / "reports" / campaign_id
    report_path: Path | None = None
    with _batch_lock(ledger.root.parent):
        # This full preflight validates the campaign plan, append-only event
        # chains, every referenced artifact and any prior review records.
        initial = ledger.preflight(campaign_id)
        if initial["candidates"]:
            report["source_generation_id"] = initial["candidates"][0].get("source_generation_id")
            report["source_generation_manifest_sha256"] = initial["candidates"][0].get("source_generation_manifest_sha256")
        candidates = sorted(initial["candidates"], key=lambda item: (item["group"], item["matchday"], int(item["source_match_id"])))
        report["candidate_count"] = len(candidates)
        report_path = _write_report(report_root, report)
        fatal_integrity_error = False
        for initial_candidate in candidates:
            internal_id = initial_candidate["internal_id"]
            result: dict[str, Any] = {
                "internal_id": internal_id,
                "source_match_id": initial_candidate["source_match_id"],
                "group": initial_candidate["group"],
                "matchday": initial_candidate["matchday"],
                "state_before": initial_candidate["state"],
                "actions": [],
                "status": "SKIPPED",
            }
            try:
                with ledger.lock.exclusive_lock():
                    current_events = ledger.candidate_events(campaign_id, internal_id)
                    state = ledger._state(current_events)
                result["state_before"] = state
                if state == "DISCOVERY_REVIEW_REQUIRED":
                    validation = ledger.validate_offline_artifact(
                        campaign_id=campaign_id, internal_id=internal_id, data_root=data_root
                    )
                    result["actions"].append({
                        "operation": "validate_offline_artifact",
                        "status": validation["status"],
                        "source_html_sha256": validation.get("source_html_sha256"),
                        "evidence_sha256": validation.get("evidence_sha256"),
                        "diagnostic": validation.get("diagnostic"),
                    })
                    if validation["status"] == "VALIDATION_FAILED":
                        result["status"] = "VALIDATION_FAILED"
                        report["validation_failed_count"] += 1
                    elif validation["status"] == "VALIDATED":
                        prepared = ledger.prepare_draft(
                            campaign_id=campaign_id,
                            internal_id=internal_id,
                            data_root=data_root,
                            generation_root=ledger.generation_root(campaign_id, data_root),
                            player_inventory_root=player_inventory_root,
                            player_compact_root=player_compact_root,
                            player_team_captures_root=player_team_captures_root,
                            player_published_index_path=player_published_index_path,
                        )
                        result["actions"].append({"operation": "prepare_draft", **prepared})
                        result["status"] = "DRAFT_PREPARED"
                        report["prepared_count"] += 1
                    else:
                        raise CampaignOperationsError(f"Resultado de validación inesperado: {validation['status']}")
                    report["processed_count"] += 1
                elif state in {"VALIDATED", "REVALIDATED"}:
                    prepared = ledger.prepare_draft(
                        campaign_id=campaign_id,
                        internal_id=internal_id,
                        data_root=data_root,
                        generation_root=ledger.generation_root(campaign_id, data_root),
                        player_inventory_root=player_inventory_root,
                        player_compact_root=player_compact_root,
                        player_team_captures_root=player_team_captures_root,
                        player_published_index_path=player_published_index_path,
                    )
                    result["actions"].append({"operation": "prepare_draft", **prepared})
                    result["status"] = "DRAFT_PREPARED"
                    report["prepared_count"] += 1
                    report["processed_count"] += 1
                elif state == "DRAFT_PREPARED":
                    result["status"] = "ALREADY_PREPARED"
                    report["skipped_count"] += 1
                else:
                    result["status"] = "PROTECTED_STATE_SKIPPED"
                    result["reason"] = "No se revalidan fallos ni se procesan operaciones ajenas al lote offline"
                    report["skipped_count"] += 1
                with ledger.lock.exclusive_lock():
                    final_events = ledger.candidate_events(campaign_id, internal_id)
                    result["state_after"] = ledger._state(final_events)
            except MatchCampaignIntegrityError as exc:
                # A corrupt hash chain, campaign or artifact means the shared
                # source of truth is not safe to continue consuming.
                result["status"] = "INTEGRITY_BLOCKED"
                result["diagnostic"] = f"{type(exc).__name__}: {exc}"
                report["error_count"] += 1
                fatal_integrity_error = True
            except Exception as exc:  # candidate-local operational failure; do not affect independent candidates
                result["status"] = "CANDIDATE_ERROR"
                result["diagnostic"] = f"{type(exc).__name__}: {exc}"
                report["error_count"] += 1
            report["candidates"].append(result)
            report["status"] = "BLOCKED_INTEGRITY" if fatal_integrity_error else "RUNNING"
            report_path = _write_report(report_root, report)
            if fatal_integrity_error:
                break
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        report["status"] = "BLOCKED_INTEGRITY" if fatal_integrity_error else (
            "COMPLETED_WITH_ERRORS" if report["error_count"] or report["validation_failed_count"] else "COMPLETED"
        )
        report["report_path"] = str(report_path)
        report_path = _write_report(report_root, report)
    report["report_path"] = str(report_path)
    return report


def build_review_queue(ledger: OperationalMatchCampaignLedger, campaign_id: str, data_root: Path) -> list[dict[str, Any]]:
    """Build human-readable, hash-checked summaries for individual review."""

    with ledger.lock.shared_lock():
        preflight = ledger.preflight(campaign_id, acquire_lock=False)
        output = []
        campaign_dir = ledger.root / campaign_id
        for candidate in preflight["candidates"]:
            if candidate["state"] != "DRAFT_PREPARED":
                continue
            events = ledger.candidate_events(campaign_id, candidate["internal_id"])
            prepared = next((event for event in events if event["event_type"] == "DRAFT_PREPARED"), None)
            if prepared is None:
                raise MatchCampaignIntegrityError("El estado de revisión carece de DRAFT_PREPARED")
            draft_path = _resolve_relative_file(data_root, prepared["draft_path"], "El borrador")
            raw = draft_path.read_bytes()
            if _sha(raw) != prepared["draft_sha256"]:
                raise MatchCampaignIntegrityError("El borrador de revisión no coincide con el hash del ledger")
            draft = json.loads(raw)
            if draft.get("internal_id") != candidate["internal_id"] or draft.get("semantic_valid") is not True:
                raise MatchCampaignIntegrityError("El borrador de revisión no corresponde a un documento validado")
            details = draft.get("details") if isinstance(draft.get("details"), dict) else {}
            discovery = next(event for event in events if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED")
            artifact = campaign_dir / discovery["artifact"]["artifact_relative_path"]
            validation = next((event for event in reversed(events) if event["event_type"] in {"VALIDATED", "REVALIDATED"}), {})
            validation_payload = validation.get("validation", {})
            if not isinstance(validation_payload, dict) or validation_payload.get("semantic_valid") is not True:
                raise MatchCampaignIntegrityError("El borrador no conserva una validación semántica verificable")
            errors = validation_payload.get("errors", [])
            checks = validation_payload.get("checks", [])
            validation_warnings = validation_payload.get("warnings", [])
            if (
                not isinstance(errors, (list, tuple))
                or not isinstance(checks, (list, tuple))
                or not isinstance(validation_warnings, (list, tuple))
            ):
                raise MatchCampaignIntegrityError("El borrador contiene evidencia de validación mal formada")
            failed_checks = [
                check for check in checks
                if isinstance(check, dict) and check.get("passed") is False
            ]
            warnings = list(errors)
            warnings.extend(validation_warnings)
            warnings.extend(f"{check.get('name', 'validation_check')}: {check.get('message', 'failed')}" for check in failed_checks)
            output.append({
                "internal_id": candidate["internal_id"],
                "source_match_id": candidate["source_match_id"],
                "group": candidate["group"],
                "matchday": candidate["matchday"],
                "source_match_date": candidate.get("source_match_date"),
                "home_team_name": candidate["home_team_name"],
                "away_team_name": candidate["away_team_name"],
                "reference_result": candidate.get("reference_result"),
                "observed_result": {"home_goals": details.get("home_goals"), "away_goals": details.get("away_goals")},
                "kickoff_time_local": details.get("kickoff_time_local"),
                "kickoff_state": details.get("kickoff_state"),
                "kickoff_source_text": details.get("kickoff_source_text"),
                "coaches": {
                    "home": (details.get("home") or {}).get("coach"),
                    "away": (details.get("away") or {}).get("coach"),
                },
                "lineups": {
                    side: {
                        "starters": (details.get(side) or {}).get("starters"),
                        "substitutes": (details.get(side) or {}).get("substitutes"),
                    }
                    for side in ("home", "away")
                },
                "events": details.get("events"),
                "warnings": warnings,
                "validation_errors": errors,
                "validation_warnings": validation_warnings,
                "validation_checks": checks,
                "missing_fields": [field for field in ("match_date", "kickoff_time_local", "events") if details.get(field) is None],
                "source_html_sha256": draft.get("source_html_sha256"),
                "details_sha256": prepared["details_sha256"],
                "draft_sha256": prepared["draft_sha256"],
                "draft_path": str(draft_path),
                "source_html_path": str(artifact / "source.html"),
                "artifact_manifest_path": str(artifact / "manifest.json"),
                "discovery_json_path": str(artifact / "discovery.json"),
                "metadata_json_path": str(artifact / "metadata.json"),
                "campaign_state": candidate["state"],
                "approval_pending": candidate["state"] == "DRAFT_PREPARED",
            })
        return output


def build_publication_queue(ledger: OperationalMatchCampaignLedger, campaign_id: str) -> list[dict[str, Any]]:
    with ledger.lock.shared_lock():
        preflight = ledger.preflight(campaign_id, acquire_lock=False)
        output = []
        for candidate in preflight["candidates"]:
            if candidate["state"] != "DOCUMENT_APPROVED":
                continue
            events = ledger.candidate_events(campaign_id, candidate["internal_id"])
            prepared = next((item for item in events if item["event_type"] == "DRAFT_PREPARED"), None)
            approved = next((item for item in events if item["event_type"] == "DOCUMENT_APPROVED"), None)
            if prepared is None or approved is None:
                raise MatchCampaignIntegrityError("La cola de publicación carece de borrador o aprobación")
            output.append({
                "campaign_id": campaign_id,
                "internal_id": candidate["internal_id"],
                "source_match_id": candidate["source_match_id"],
                "group": candidate["group"],
                "matchday": candidate["matchday"],
                "home_team_name": candidate["home_team_name"],
                "away_team_name": candidate["away_team_name"],
                "reference_result": candidate.get("reference_result"),
                "state": candidate["state"],
                "next_operation": "publish_then_verify",
                "approved_by": approved.get("approved_by"),
                "draft_sha256": prepared.get("draft_sha256"),
                "details_sha256": prepared.get("details_sha256"),
                "approval_sha256": approved.get("approval_sha256"),
            })
        return output


def publish_approved_batch(
    *,
    ledger: OperationalMatchCampaignLedger,
    campaign_id: str,
    confirmation: str,
    data_root: Path,
    generation_root: Path,
    published_root: Path,
    store_root: Path,
    player_inventory_root: Path,
    player_compact_root: Path,
    player_team_captures_root: Path,
    player_published_index_path: Path,
) -> dict[str, Any]:
    """Publish only DOCUMENT_APPROVED candidates after a typed explicit action."""

    if confirmation != PUBLISH_CONFIRMATION:
        raise CampaignOperationsError("La publicación por lote requiere confirmación explícita")
    report = {
        "schema_version": REPORT_SCHEMA,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8],
        "campaign_id": campaign_id,
        "status": "RUNNING",
        "source_generation_id": None,
        "source_generation_manifest_sha256": None,
        "candidates": [],
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
        "human_approval_created": False,
        "review_completion_created": False,
    }
    report_root = ledger.root.parent / "operations" / "reports" / campaign_id
    with _batch_lock(ledger.root.parent):
        candidates = ledger.preflight(campaign_id)["candidates"]
        if candidates:
            report["source_generation_id"] = candidates[0].get("source_generation_id")
            report["source_generation_manifest_sha256"] = candidates[0].get("source_generation_manifest_sha256")
        for candidate in candidates:
            if candidate["state"] != "DOCUMENT_APPROVED":
                continue
            row = {"internal_id": candidate["internal_id"], "state_before": "DOCUMENT_APPROVED"}
            try:
                published = ledger.publish(
                    campaign_id=campaign_id,
                    internal_id=candidate["internal_id"],
                    data_root=data_root,
                    generation_root=generation_root,
                    published_root=published_root,
                    store_root=store_root,
                    player_inventory_root=player_inventory_root,
                    player_compact_root=player_compact_root,
                    player_team_captures_root=player_team_captures_root,
                    player_published_index_path=player_published_index_path,
                )
                verified = ledger.verify_publication(
                    campaign_id=campaign_id,
                    internal_id=candidate["internal_id"],
                    data_root=data_root,
                    generation_root=generation_root,
                    published_root=published_root,
                    store_root=store_root,
                    player_inventory_root=player_inventory_root,
                    player_compact_root=player_compact_root,
                    player_team_captures_root=player_team_captures_root,
                    player_published_index_path=player_published_index_path,
                )
                row.update({"status": "PUBLISHED_VERIFIED", "publish": published, "verify": verified})
            except MatchCampaignIntegrityError as exc:
                row.update({"status": "INTEGRITY_BLOCKED", "diagnostic": f"{type(exc).__name__}: {exc}"})
                report["candidates"].append(row)
                report["status"] = "BLOCKED_INTEGRITY"
                break
            except Exception as exc:
                row.update({"status": "CANDIDATE_ERROR", "diagnostic": f"{type(exc).__name__}: {exc}"})
            report["candidates"].append(row)
            report["status"] = "RUNNING"
            _write_report(report_root, report)
        if report["status"] == "RUNNING":
            report["status"] = "COMPLETED_WITH_ERRORS" if any(item["status"] == "CANDIDATE_ERROR" for item in report["candidates"]) else "COMPLETED"
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        report_path = _write_report(report_root, report)
    report["report_path"] = str(report_path)
    return report


def build_worklist(status_report: dict[str, Any]) -> dict[str, Any]:
    """Expose exact v1/v2 lifecycle states alongside global coverage metrics."""

    state_by_detail = {
        "authorized_not_executed": "AUTHORIZED",
        "captured_pending_validation": "DISCOVERY_REVIEW_REQUIRED",
        "validated_pending_approval": "VALIDATED",
        "approved_pending_publication": "DOCUMENT_APPROVED",
        "published_approved": "PUBLISHED",
        "review_completed": "REVIEW_COMPLETED",
        "blocked_requires_human_review": "STOPPED",
        "played_pending_acquisition": "AVAILABLE_FOR_PROPOSAL",
        "included_in_existing_campaign": "NOT_AUTHORIZED",
        "played_without_verified_url": "STOPPED",
        "played_incomplete_or_unresolved": "STOPPED",
        "unplayed": "NOT_APPLICABLE",
    }
    all_rows = []
    for source in status_report.get("matches", []):
        campaign = source.get("campaign") or {}
        state = campaign.get("state") or state_by_detail.get(source.get("detail_status"), "UNKNOWN")
        if state == "PROPOSED_NOT_AUTHORIZED":
            state = "NOT_AUTHORIZED"
        if source.get("detail_status") == "blocked_requires_human_review":
            reasons = source.get("blocked_reasons") or []
            if any("INTERRUPTED" in str(reason) for reason in reasons) or state == "INTERRUPTED_REQUIRES_REVIEW":
                state = "INTERRUPTED_REQUIRES_REVIEW"
        all_rows.append({
            "internal_id": source.get("internal_id"),
            "source_match_id": source.get("source_match_id"),
            "competition": source.get("competition"),
            "season": source.get("season"),
            "match_status": source.get("status"),
            "home_team_id": source.get("home_team_id"),
            "home_team_name": source.get("home_team_name"),
            "away_team_id": source.get("away_team_id"),
            "away_team_name": source.get("away_team_name"),
            "reference_result": source.get("reference_result"),
            "matchday": source.get("matchday"),
            "source_match_date": source.get("source_match_date"),
            "matchday_date": source.get("matchday_date"),
            "group": source.get("group"),
            "source_match_url": source.get("source_match_url"),
            "source_generation_id": source.get("source_generation_id"),
            "source_generation_manifest_sha256": source.get("source_generation_manifest_sha256"),
            "campaign_id": campaign.get("campaign_id"),
            "campaign_ids": campaign.get("campaigns") or ([campaign["campaign_id"]] if campaign.get("campaign_id") else []),
            "state": state,
            "next_operation": source.get("next_safe_operation"),
            "blocked_reasons": source.get("blocked_reasons", []),
            "detail_status": source.get("detail_status"),
        })
    groups: dict[str, Any] = {}
    for group in ("I", "II"):
        group_rows = [row for row in all_rows if row["group"] == group]
        by_matchday: dict[str, Any] = {}
        for matchday in sorted({row["matchday"] for row in group_rows}):
            rows = [row for row in group_rows if row["matchday"] == matchday]
            by_matchday[str(matchday)] = _coverage_metrics(rows)
        groups[group] = {"metrics": _coverage_metrics(group_rows), "by_matchday": by_matchday}
    campaigns: dict[str, Any] = {}
    for campaign_id in sorted({campaign_id for row in all_rows for campaign_id in row["campaign_ids"]}):
        campaign_rows = [row for row in all_rows if campaign_id in row["campaign_ids"]]
        campaigns[campaign_id] = {
            "metrics": _coverage_metrics(campaign_rows),
            "states": _count(campaign_rows, "state"),
            "internal_ids": [row["internal_id"] for row in campaign_rows],
        }
    return {
        "schema_version": OPERATIONS_SCHEMA,
        "source": status_report.get("source"),
        "matches": all_rows,
        "coverage_by_group": groups,
        "coverage_by_campaign": campaigns,
        "counts_by_exact_state": _count(all_rows, "state"),
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
    }


def _count(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _coverage_metrics(rows: list[dict[str, Any]]) -> dict[str, int]:
    published = sum(row.get("detail_status") in {"published_approved", "review_completed"} for row in rows)
    blocked = sum(row.get("detail_status") in {
        "blocked_requires_human_review", "played_without_verified_url",
        "played_incomplete_or_unresolved",
    } for row in rows)
    return {
        "registered": len(rows),
        "played": sum(row.get("detail_status") != "unplayed" and row.get("reference_result") is not None for row in rows),
        "published": published,
        "reviewed": sum(row.get("state") == "REVIEW_COMPLETED" for row in rows),
        "pending_acquisition": sum(row.get("state") in {"AVAILABLE_FOR_PROPOSAL", "NOT_AUTHORIZED", "AUTHORIZED"} for row in rows),
        "pending_review": sum(row.get("state") in {"DISCOVERY_REVIEW_REQUIRED", "VALIDATED", "REVALIDATED", "DRAFT_PREPARED", "DOCUMENT_APPROVED", "PUBLISHED"} for row in rows),
        "blocked": blocked,
    }
