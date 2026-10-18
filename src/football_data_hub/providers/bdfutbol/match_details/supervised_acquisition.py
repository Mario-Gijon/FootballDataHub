"""Supervised authorization sessions and sequential real match acquisition."""

from __future__ import annotations

import fcntl
import os
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .campaign import MatchCampaignAuthorizationError, MatchCampaignIntegrityError
from .campaign_operations import (
    REPORT_SCHEMA,
    CampaignOperationsError,
    _batch_lock,
    _write_report,
    load_operation_report,
)
from .operational_campaign import (
    AUTHORIZE_CONFIRMATION,
    PLAYER_IDLE_CONFIRMATION,
    OperationalMatchCampaignLedger,
)

SESSION_CONFIRMATION = "EXECUTE_SUPERVISED_MATCH_CAMPAIGN_SESSION"
_REPORT_PREFIX = "acquisition-"
_CAPTURED_STATES = {
    "DISCOVERY_REVIEW_REQUIRED", "VALIDATED", "VALIDATION_FAILED", "REVALIDATED",
    "REVALIDATION_FAILED", "DRAFT_PREPARED", "DOCUMENT_APPROVED", "PUBLISHED",
    "REVIEW_COMPLETED",
}
_VALIDATED_STATES = {
    "VALIDATED", "VALIDATION_FAILED", "REVALIDATED", "REVALIDATION_FAILED",
    "DRAFT_PREPARED", "DOCUMENT_APPROVED", "PUBLISHED", "REVIEW_COMPLETED",
}
_DRAFT_STATES = {"DRAFT_PREPARED", "DOCUMENT_APPROVED", "PUBLISHED", "REVIEW_COMPLETED"}
_BLOCKED_STATES = {"STOPPED", "INTERRUPTED_REQUIRES_REVIEW", "VALIDATION_FAILED", "REVALIDATION_FAILED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_run_id() -> str:
    return _REPORT_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]


@contextmanager
def _player_acquisition_idle_lock(capture_root: Path) -> Iterator[Path]:
    """Hold a shared lock against PLAYER-01C2 for the complete match session."""

    root = capture_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise CampaignOperationsError("La raíz de capturas de jugadores no es un directorio")
    lock_path = root / ".player-mass-acquisition.lock"
    if lock_path.is_symlink():
        raise CampaignOperationsError("El lock de adquisición de jugadores no puede ser symlink")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CampaignOperationsError("El lock de jugadores no es un archivo regular")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise CampaignOperationsError(
                "PLAYER-01C2 está activo; no se inicia la campaña de partidos"
            ) from exc
        yield lock_path
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _session_report(ledger: OperationalMatchCampaignLedger, campaign_id: str) -> list[dict[str, Any]]:
    report_root = ledger.root.parent / "operations" / "reports" / campaign_id
    if not report_root.exists():
        return []
    if report_root.is_symlink() or not report_root.is_dir():
        raise CampaignOperationsError("La ruta de sesiones no es un directorio regular")
    reports = []
    for path in sorted(report_root.glob(f"{_REPORT_PREFIX}*.json")):
        reports.append(load_operation_report(path))
    return reports


def _campaign_metrics(preflight: dict[str, Any]) -> dict[str, int]:
    states = [row["state"] for row in preflight["candidates"]]
    return {
        "candidates_total": len(states),
        "authorized": states.count("AUTHORIZED"),
        "captured": sum(state in _CAPTURED_STATES for state in states),
        "validated": sum(state in _VALIDATED_STATES for state in states),
        "drafts_prepared": sum(state in _DRAFT_STATES for state in states),
        "pending_review": sum(state in {"DISCOVERY_REVIEW_REQUIRED", "DRAFT_PREPARED", "DOCUMENT_APPROVED", "PUBLISHED"} for state in states),
        "published": sum(state in {"PUBLISHED", "REVIEW_COMPLETED"} for state in states),
        "review_completed": states.count("REVIEW_COMPLETED"),
        "blocked": sum(state in _BLOCKED_STATES for state in states),
        "access_failures": states.count("STOPPED"),
        "validation_failures": sum(state in {"VALIDATION_FAILED", "REVALIDATION_FAILED"} for state in states),
    }


def authorize_reviewed_candidates(
    *,
    ledger: OperationalMatchCampaignLedger,
    campaign_id: str,
    data_root: Path,
    status_report: dict[str, Any],
    context: dict[str, Any],
    operator: str,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    refresh_snapshot: Callable[[], tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Prompt for an explicit URL and authorization token for every candidate."""

    if not operator.strip():
        raise MatchCampaignAuthorizationError("Se requiere el nombre del operador")
    run_id = "authorization-" + _new_run_id()[len(_REPORT_PREFIX):]
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "operation_type": "individual_authorization_review",
        "run_id": run_id,
        "campaign_id": campaign_id,
        "operator": operator.strip(),
        "started_at_utc": _now(),
        "finished_at_utc": None,
        "status": "RUNNING",
        "candidates": [],
        "authorization_created": 0,
        "skipped_count": 0,
        "error_count": 0,
        "browser_started": False,
        "http_enabled": False,
        "navigation_enabled": False,
    }
    report_root = ledger.root.parent / "operations" / "reports" / campaign_id
    with _batch_lock(ledger.root.parent):
        preflight = ledger.preflight(campaign_id)
        candidates = sorted(
            (row for row in preflight["candidates"] if row["state"] == "NOT_AUTHORIZED"),
            key=lambda row: (row["group"], row["matchday"], int(row["source_match_id"])),
        )
        report["candidate_count"] = len(preflight["candidates"])
        report["reviewable_count"] = len(candidates)
        report["campaign_progress"] = _campaign_metrics(preflight)
        report_path = _write_report(report_root, report)
        try:
            for index, candidate in enumerate(candidates, start=1):
                latest_preflight = ledger.preflight(campaign_id)
                latest_candidate = next(
                    (item for item in latest_preflight["candidates"] if item["internal_id"] == candidate["internal_id"]),
                    None,
                )
                if latest_candidate is None or latest_candidate["state"] != "NOT_AUTHORIZED":
                    row = {
                        "internal_id": candidate["internal_id"],
                        "source_match_id": candidate["source_match_id"],
                        "status": "SKIPPED_STATE_CHANGED",
                        "state_after": latest_candidate.get("state") if latest_candidate else "MISSING",
                    }
                    report["candidates"].append(row)
                    report["skipped_count"] += 1
                    report["campaign_progress"] = _campaign_metrics(latest_preflight)
                    report_path = _write_report(report_root, report)
                    continue
                current_report, current_context = (
                    refresh_snapshot() if refresh_snapshot else (status_report, context)
                )
                current_by_id = {item["internal_id"]: item for item in current_report.get("matches", [])}
                current = current_by_id.get(candidate["internal_id"])
                row: dict[str, Any] = {
                    "internal_id": candidate["internal_id"],
                    "source_match_id": candidate["source_match_id"],
                    "group": candidate["group"],
                    "matchday": candidate["matchday"],
                    "competition": candidate.get("competition"),
                    "season": candidate.get("season"),
                    "home_team_name": candidate["home_team_name"],
                    "away_team_name": candidate["away_team_name"],
                    "reference_result": candidate.get("reference_result"),
                    "source_match_date": candidate.get("source_match_date"),
                    "matchday_date": candidate.get("matchday_date"),
                    "source_match_url": candidate["source_match_url"],
                    "source_generation_id": candidate["source_generation_id"],
                    "state_before": candidate["state"],
                    "status": "REVIEW_PENDING",
                }
                report["candidates"].append(row)
                reference = candidate.get("reference_result")
                score = (
                    f"{reference['home_goals']}–{reference['away_goals']}"
                    if isinstance(reference, dict)
                    and isinstance(reference.get("home_goals"), int)
                    and isinstance(reference.get("away_goals"), int)
                    else "resultado no disponible"
                )
                date_label = (
                    f"fecha partido {candidate['source_match_date']}"
                    if candidate.get("source_match_date")
                    else f"fecha jornada {candidate.get('matchday_date') or 'no disponible'}"
                )
                output_fn(
                    f"[{index}/{len(candidates)}] {candidate['internal_id']} | "
                    f"{candidate['group']} · J{candidate['matchday']} | "
                    f"{candidate['home_team_name']} {score} {candidate['away_team_name']} | "
                    f"{date_label} | {candidate.get('competition')} {candidate.get('season')}\n"
                    f"URL: {candidate['source_match_url']}\n"
                    f"Generación: {candidate['source_generation_id']}"
                )
                if current is None or current.get("source_match_url") != candidate["source_match_url"]:
                    row.update({"status": "BLOCKED", "reason": "El candidato no coincide con la generación activa"})
                    report["error_count"] += 1
                    report["status"] = "BLOCKED_INTEGRITY"
                    report_path = _write_report(report_root, report)
                    break
                if (
                    candidate["internal_id"] in current_context.get("published_ids", set())
                    or candidate["internal_id"] in current_context.get("captured_ids", set())
                    or candidate["internal_id"] in current_context.get("blocked_ids", set())
                ):
                    row.update({"status": "BLOCKED", "reason": "Publicado, capturado o bloqueado en la reconciliación actual"})
                    report["error_count"] += 1
                    report["status"] = "BLOCKED_INTEGRITY"
                    report_path = _write_report(report_root, report)
                    break
                try:
                    url_confirmation = input_fn("Para revisar este candidato, escriba su URL completa exacta (Enter para omitir): ")
                    if url_confirmation != candidate["source_match_url"]:
                        row["status"] = "SKIPPED_NOT_CONFIRMED"
                        report["skipped_count"] += 1
                    else:
                        token = input_fn(f"Confirme una autorización individual escribiendo {AUTHORIZE_CONFIRMATION}: ")
                        if token != AUTHORIZE_CONFIRMATION:
                            row["status"] = "SKIPPED_NOT_CONFIRMED"
                            report["skipped_count"] += 1
                        else:
                            current_report, current_context = (
                                refresh_snapshot() if refresh_snapshot else (status_report, context)
                            )
                            current_by_id = {item["internal_id"]: item for item in current_report.get("matches", [])}
                            current = current_by_id.get(candidate["internal_id"])
                            latest_candidate = next(
                                (item for item in ledger.preflight(campaign_id)["candidates"] if item["internal_id"] == candidate["internal_id"]),
                                None,
                            )
                            if (
                                current is None
                                or current.get("source_match_url") != candidate["source_match_url"]
                                or latest_candidate is None
                                or latest_candidate["state"] != "NOT_AUTHORIZED"
                            ):
                                row.update({"status": "SKIPPED_STATE_CHANGED", "reason": "El candidato cambió mientras se revisaba"})
                                report["skipped_count"] += 1
                                report_path = _write_report(report_root, report)
                                continue
                            if (
                                candidate["internal_id"] in current_context.get("published_ids", set())
                                or candidate["internal_id"] in current_context.get("captured_ids", set())
                                or candidate["internal_id"] in current_context.get("blocked_ids", set())
                            ):
                                row.update({"status": "BLOCKED", "reason": "Publicado, capturado o bloqueado durante la revisión"})
                                report["error_count"] += 1
                                report["status"] = "BLOCKED_INTEGRITY"
                                report_path = _write_report(report_root, report)
                                break
                            authorization_id = ledger.authorize(
                                campaign_id=campaign_id,
                                internal_id=candidate["internal_id"],
                                confirmed_url=candidate["source_match_url"],
                                operator=operator,
                                confirmation=AUTHORIZE_CONFIRMATION,
                                current_status=current,
                                published=candidate["internal_id"] in current_context.get("published_ids", set()),
                                captured=candidate["internal_id"] in current_context.get("captured_ids", set()),
                                blocked=candidate["internal_id"] in current_context.get("blocked_ids", set()),
                                data_root=data_root,
                            )
                            row.update({"status": "AUTHORIZED", "authorization_id": authorization_id})
                            report["authorization_created"] += 1
                except MatchCampaignIntegrityError as exc:
                    row.update({"status": "BLOCKED_INTEGRITY", "diagnostic": f"{type(exc).__name__}: {exc}"})
                    report["error_count"] += 1
                    report["status"] = "BLOCKED_INTEGRITY"
                    report_path = _write_report(report_root, report)
                    break
                except MatchCampaignAuthorizationError as exc:
                    row.update({"status": "AUTHORIZATION_REJECTED", "diagnostic": str(exc)})
                    report["error_count"] += 1
                report_path = _write_report(report_root, report)
        except (KeyboardInterrupt, EOFError):
            report["status"] = "INTERRUPTED"
        else:
            if report["status"] == "RUNNING":
                report["status"] = "COMPLETED_WITH_ERRORS" if report["error_count"] else "COMPLETED"
        report["finished_at_utc"] = _now()
        report["report_path"] = str(report_path)
        report_path = _write_report(report_root, report)
    report["report_path"] = str(report_path)
    return report


def run_authorized_batch(
    *,
    ledger: OperationalMatchCampaignLedger,
    campaign_id: str,
    data_root: Path,
    player_capture_root: Path,
    operator: str,
    limit: int,
    confirmation: str,
    player_idle_confirmation: str,
    refresh_snapshot: Callable[[], tuple[dict[str, Any], dict[str, Any]]],
    execute_candidate: Callable[[dict[str, Any], str, dict[str, Any], dict[str, Any]], dict[str, Any]],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run only fresh, individually authorized candidates, one URL at a time."""

    if confirmation != SESSION_CONFIRMATION:
        raise MatchCampaignAuthorizationError("La sesión requiere confirmación humana explícita")
    if player_idle_confirmation != PLAYER_IDLE_CONFIRMATION:
        raise MatchCampaignAuthorizationError("Falta confirmar que PLAYER-01C2 está inactivo")
    if not operator.strip() or limit <= 0:
        raise MatchCampaignAuthorizationError("Se requiere operador y un límite positivo")

    run_id = _new_run_id()
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "operation_type": "supervised_match_acquisition",
        "run_id": run_id,
        "campaign_id": campaign_id,
        "operator": operator.strip(),
        "started_at_utc": _now(),
        "finished_at_utc": None,
        "status": "RUNNING",
        "candidates": [],
        "campaign_progress": {},
        "selected_authorized_count": 0,
        "captured_this_session": 0,
        "error_count": 0,
        "access_failure_count": 0,
        "validation_failure_count": 0,
        "stop_acquisition": False,
        "requires_manual_review": False,
        "browser_start_requested": False,
        "http_enabled": False,
        "navigation_enabled": False,
        "navigation_requests": 0,
        "automatic_retries": 0,
        "maximum_navigations_per_authorization": 1,
    }
    report_root = ledger.root.parent / "operations" / "reports" / campaign_id
    with _batch_lock(ledger.root.parent):
        old_reports = _session_report(ledger, campaign_id)
        stopped = next((item for item in old_reports if item.get("stop_acquisition") is True), None)
        if stopped is not None:
            raise CampaignOperationsError(
                f"La campaña tiene una parada previa que requiere revisión humana: {stopped.get('run_id')}"
            )
        # A durable RUNNING report with no process holding the batch lock means
        # a hard interruption. Reconcile it against append-only candidate state.
        for old in old_reports:
            if old.get("status") != "RUNNING":
                continue
            preflight = ledger.preflight(campaign_id)
            states = {row["internal_id"]: row["state"] for row in preflight["candidates"]}
            for item in old.get("candidates", []):
                state = states.get(item.get("internal_id"))
                if item.get("status") == "EXECUTION_PENDING":
                    item["status"] = (
                        "INTERRUPTED_REQUIRES_REVIEW" if state == "INTERRUPTED_REQUIRES_REVIEW"
                        else state if state else "UNKNOWN_AFTER_INTERRUPTION"
                    )
                    if item["status"] == "INTERRUPTED_REQUIRES_REVIEW":
                        old["requires_manual_review"] = True
            old["status"] = "INTERRUPTED"
            old["finished_at_utc"] = _now()
            old["interrupted_recovered_at_utc"] = _now()
            _write_report(report_root, old)

        report_path = _write_report(report_root, report)
        try:
            with _player_acquisition_idle_lock(player_capture_root) as player_lock_path:
                report["player_acquisition_lock"] = str(player_lock_path)
                report_path = _write_report(report_root, report)
                initial = ledger.preflight(campaign_id)
                stopped_candidates = [
                    row for row in initial["candidates"] if row["state"] == "STOPPED"
                ]
                if stopped_candidates:
                    raise CampaignOperationsError(
                        "La campaña contiene una adquisición detenida que requiere revisión humana: "
                        + ", ".join(row["internal_id"] for row in stopped_candidates)
                    )
                authorized = sorted(
                    (row for row in initial["candidates"] if row["state"] == "AUTHORIZED"),
                    key=lambda row: (row["group"], row["matchday"], int(row["source_match_id"])),
                )
                selected = authorized[:limit]
                report["selected_authorized_count"] = len(selected)
                report["campaign_progress"] = _campaign_metrics(initial)
                report_path = _write_report(report_root, report)
                for index, original in enumerate(selected, start=1):
                    report_rows, context = refresh_snapshot()
                    fresh = ledger.preflight(campaign_id)
                    candidate = next(row for row in fresh["candidates"] if row["internal_id"] == original["internal_id"])
                    if candidate["state"] != "AUTHORIZED":
                        row = {
                            "internal_id": candidate["internal_id"],
                            "source_match_id": candidate["source_match_id"],
                            "requested_url": candidate["source_match_url"],
                            "state_before": "AUTHORIZED",
                            "state_after": candidate["state"],
                            "status": "SKIPPED_STATE_CHANGED",
                        }
                        report["candidates"].append(row)
                        report["campaign_progress"] = _campaign_metrics(fresh)
                        report_path = _write_report(report_root, report)
                        if candidate["state"] in {"STOPPED", "INTERRUPTED_REQUIRES_REVIEW"}:
                            report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                            break
                        continue
                    current_by_id = {item["internal_id"]: item for item in report_rows.get("matches", [])}
                    current = current_by_id.get(candidate["internal_id"])
                    if current is None or current.get("source_match_url") != candidate["source_match_url"]:
                        row = {"internal_id": candidate["internal_id"], "source_match_id": candidate["source_match_id"], "status": "BLOCKED_SOURCE_MISMATCH"}
                        report["candidates"].append(row)
                        report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                        report["error_count"] += 1
                        report_path = _write_report(report_root, report)
                        break
                    internal_id = candidate["internal_id"]
                    if (
                        internal_id in context.get("published_ids", set())
                        or internal_id in context.get("captured_ids", set())
                        or internal_id in context.get("blocked_ids", set())
                    ):
                        row = {"internal_id": internal_id, "source_match_id": candidate["source_match_id"], "status": "BLOCKED_NO_LONGER_ELIGIBLE"}
                        report["candidates"].append(row)
                        report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                        report["error_count"] += 1
                        report_path = _write_report(report_root, report)
                        break
                    events = ledger.candidate_events(campaign_id, internal_id)
                    authorizations = [event.get("authorization") for event in events if event["event_type"] == "AUTHORIZED"]
                    if len(events) != 1 or len(authorizations) != 1 or not candidate.get("authorization_id"):
                        row = {"internal_id": internal_id, "source_match_id": candidate["source_match_id"], "status": "BLOCKED_INVALID_AUTHORIZATION"}
                        report["candidates"].append(row)
                        report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                        report["error_count"] += 1
                        report_path = _write_report(report_root, report)
                        break
                    authorization_id = authorizations[0].get("authorization_id")
                    if authorization_id != candidate["authorization_id"] or authorizations[0].get("source_match_url") != candidate["source_match_url"]:
                        row = {"internal_id": internal_id, "source_match_id": candidate["source_match_id"], "status": "BLOCKED_INVALID_AUTHORIZATION"}
                        report["candidates"].append(row)
                        report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                        report["error_count"] += 1
                        report_path = _write_report(report_root, report)
                        break
                    row = {
                        "internal_id": internal_id,
                        "source_match_id": candidate["source_match_id"],
                        "group": candidate["group"],
                        "matchday": candidate["matchday"],
                        "home_team_name": candidate["home_team_name"],
                        "away_team_name": candidate["away_team_name"],
                        "reference_result": candidate.get("reference_result"),
                        "source_match_date": candidate.get("source_match_date"),
                        "matchday_date": candidate.get("matchday_date"),
                        "requested_url": candidate["source_match_url"],
                        "source_generation_id": candidate["source_generation_id"],
                        "authorization_id": authorization_id,
                        "operator": authorizations[0].get("operator"),
                        "state_before": "AUTHORIZED",
                        "status": "EXECUTION_PENDING",
                        "execution_pending_at_utc": _now(),
                    }
                    report["candidates"].append(row)
                    report["campaign_progress"] = _campaign_metrics(fresh)
                    report_path = _write_report(report_root, report)
                    if progress_callback:
                        progress_callback({"event": "candidate_starting", "index": index, "total": len(selected), **row})
                    row["navigation_requested_at_utc"] = _now()
                    report["browser_start_requested"] = True
                    report["http_enabled"] = True
                    report["navigation_enabled"] = True
                    report["navigation_requests"] += 1
                    report_path = _write_report(report_root, report)
                    try:
                        result = execute_candidate(candidate, authorization_id, current, context)
                    except KeyboardInterrupt:
                        row.update({"status": "INTERRUPTED", "diagnostic": "Cancelación solicitada; no se reintentará este intento"})
                        report["status"] = "INTERRUPTED"
                        report["requires_manual_review"] = True
                        report["error_count"] += 1
                        report_path = _write_report(report_root, report)
                        break
                    except Exception as exc:
                        row.update({"status": "CANDIDATE_ERROR", "diagnostic": f"{type(exc).__name__}: {exc}"})
                        report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                        report["error_count"] += 1
                        report_path = _write_report(report_root, report)
                        break
                    row["result"] = result
                    row["status"] = result.get("status", "UNKNOWN_RESULT")
                    row["attempt_id"] = result.get("attempt_id")
                    if row["status"] == "DISCOVERY_REVIEW_REQUIRED":
                        report["captured_this_session"] += 1
                    else:
                        report.update({"status": "BLOCKED_MANUAL_REVIEW", "stop_acquisition": True, "requires_manual_review": True})
                        report["error_count"] += 1
                        if row["status"] == "STOPPED":
                            report["access_failure_count"] += 1
                        if row["status"] in {"VALIDATION_FAILED", "REVALIDATION_FAILED"}:
                            report["validation_failure_count"] += 1
                    after = ledger.preflight(campaign_id)
                    row["state_after"] = next(
                        (item["state"] for item in after["candidates"] if item["internal_id"] == internal_id),
                        "UNKNOWN",
                    )
                    report["campaign_progress"] = _campaign_metrics(after)
                    report_path = _write_report(report_root, report)
                    if progress_callback:
                        progress_callback({"event": "candidate_finished", "index": index, "total": len(selected), **row})
                    if report["stop_acquisition"]:
                        break
                if report["status"] == "RUNNING":
                    report["status"] = "COMPLETED"
        except (KeyboardInterrupt, EOFError):
            report["status"] = "INTERRUPTED"
            report["requires_manual_review"] = any(
                row.get("status") in {"EXECUTION_PENDING", "INTERRUPTED"} for row in report["candidates"]
            )
        except CampaignOperationsError as exc:
            report.update({"status": "BLOCKED_PRECONDITION", "diagnostic": str(exc)})
            report["error_count"] += 1
        report["finished_at_utc"] = _now()
        report["report_path"] = str(report_path)
        report_path = _write_report(report_root, report)
    report["report_path"] = str(report_path)
    return report
