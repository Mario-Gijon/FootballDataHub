"""Offline, versioned proposals and status views for scalable match campaigns.

This module only consumes verified local generations and ledgers. It cannot
authorize navigation, start a browser, perform HTTP, or publish match details.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .inventory import VerifiedGeneration, _validate_match_url

PLAN_SCHEMA = "football_data_hub.match_detail_campaign_plan.v1"
PLAN_MANIFEST_SCHEMA = "football_data_hub.match_detail_campaign_plan_manifest.v1"
_PLAN_ID = re.compile(r"^match-detail-campaign-plan-[a-f0-9]{16}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_ID = re.compile(r"^[0-9]{5,10}$")


class ScalableCampaignError(ValueError):
    """An inventory, proposal or status source is inconsistent or corrupt."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _teams_by_id(group_payload: dict[str, Any], group: str) -> dict[int, dict[str, Any]]:
    teams = group_payload.get("teams")
    if not isinstance(teams, list) or len(teams) != 20:
        raise ScalableCampaignError(f"El catálogo del Grupo {group} no contiene 20 equipos")
    result: dict[int, dict[str, Any]] = {}
    for team in teams:
        if not isinstance(team, dict):
            raise ScalableCampaignError(f"Equipo mal formado en Grupo {group}")
        team_id = team.get("team_id")
        name = team.get("name")
        if type(team_id) is not int or team_id <= 0 or not isinstance(name, str) or not name.strip():
            raise ScalableCampaignError(f"Identidad de equipo inválida en Grupo {group}")
        if team_id in result:
            raise ScalableCampaignError(f"team_id duplicado en Grupo {group}: {team_id}")
        result[team_id] = team
    return result


def build_match_campaign_inventory(verified: VerifiedGeneration) -> dict[str, Any]:
    """Build a complete fixture inventory, including unplayed and URL-less rows."""

    groups = verified.matches_payload.get("groups")
    if not isinstance(groups, dict) or set(groups) != {"I", "II"}:
        raise ScalableCampaignError("La generación debe contener Grupo I y Grupo II")
    source_captures = verified.manifest_payload.get("source_captures")
    if not isinstance(source_captures, list):
        raise ScalableCampaignError("La generación no contiene capturas de origen")
    captures = {item.get("group"): item for item in source_captures if isinstance(item, dict)}
    if set(captures) != {"I", "II"}:
        raise ScalableCampaignError("La procedencia no cubre ambos grupos")

    records: list[dict[str, Any]] = []
    seen_internal: set[str] = set()
    seen_source: set[str] = set()
    for group in ("I", "II"):
        group_payload = groups[group]
        if not isinstance(group_payload, dict) or group_payload.get("group") != group:
            raise ScalableCampaignError(f"Identidad de Grupo {group} contradictoria")
        teams = _teams_by_id(group_payload, group)
        capture = captures[group]
        source_files = capture.get("files")
        if not isinstance(source_files, dict):
            raise ScalableCampaignError(f"Faltan referencias de origen del Grupo {group}")
        source_html_sha = source_files.get("source_html", {}).get("sha256")
        normalized_sha = source_files.get("normalized_matches", {}).get("sha256")
        if (
            not _SHA.fullmatch(str(source_html_sha))
            or not _SHA.fullmatch(str(normalized_sha))
            or not isinstance(capture.get("capture_id"), str)
            or not capture["capture_id"]
            or not isinstance(capture.get("captured_at_utc"), str)
            or not _SHA.fullmatch(str(capture.get("source_snapshot_sha256", "")))
        ):
            raise ScalableCampaignError(f"Hashes de captura inválidos en Grupo {group}")

        matches = group_payload.get("matches")
        if not isinstance(matches, list):
            raise ScalableCampaignError(f"No hay colección de partidos en Grupo {group}")
        for match in matches:
            if not isinstance(match, dict):
                raise ScalableCampaignError(f"Partido mal formado en Grupo {group}")
            source_id = str(match.get("source_match_id") or "")
            internal_id = match.get("internal_id")
            expected_internal = f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}"
            if (
                not source_id.isdigit()
                or internal_id != expected_internal
                or internal_id in seen_internal
                or source_id in seen_source
            ):
                raise ScalableCampaignError(f"Identidad de partido ausente, duplicada o contradictoria: {internal_id!r}")
            status = match.get("status")
            if status not in {"played", "unplayed", "incomplete"}:
                raise ScalableCampaignError(f"Estado de partido no reconocido para {internal_id}: {status!r}")
            matchday = match.get("matchday")
            if type(matchday) is not int or not 1 <= matchday <= 38:
                raise ScalableCampaignError(f"Jornada inválida para {internal_id}")
            home_id, away_id = match.get("home_team_id"), match.get("away_team_id")
            if (
                type(home_id) is not int
                or type(away_id) is not int
                or home_id == away_id
                or home_id not in teams
                or away_id not in teams
            ):
                raise ScalableCampaignError(f"Identidades de equipos inválidas para {internal_id}")
            goals = (match.get("home_goals"), match.get("away_goals"))
            if status == "played" and any(type(value) is not int or value < 0 for value in goals):
                raise ScalableCampaignError(f"Marcador disputado incompleto para {internal_id}")
            url = match.get("source_match_url")
            if url is not None:
                _validate_match_url(url, source_id)
            source_date = match.get("source_match_date")
            matchday_date = match.get("matchday_date")
            for label, value in (("source_match_date", source_date), ("matchday_date", matchday_date)):
                if value is not None:
                    try:
                        date.fromisoformat(value)
                    except (TypeError, ValueError) as exc:
                        raise ScalableCampaignError(f"{label} inválida para {internal_id}") from exc
            records.append({
                "internal_id": internal_id,
                "source_match_id": source_id,
                "competition": "Primera Federación",
                "season": "2026-27",
                "group": group,
                "matchday": matchday,
                "source_match_date": source_date,
                "matchday_date": matchday_date,
                "home_team_id": home_id,
                "home_team_name": teams[home_id]["name"],
                "away_team_id": away_id,
                "away_team_name": teams[away_id]["name"],
                "status": status,
                "reference_result": (
                    {"home_goals": goals[0], "away_goals": goals[1]}
                    if status == "played" else None
                ),
                "source_match_url": url,
                "source_generation_id": verified.generation_id,
                "source_generation_manifest_sha256": verified.manifest_sha256,
                "source_capture_id": capture.get("capture_id"),
                "source_captured_at_utc": capture.get("captured_at_utc"),
                "source_snapshot_sha256": capture.get("source_snapshot_sha256"),
                "source_matches_sha256": normalized_sha,
            })
            seen_internal.add(internal_id)
            seen_source.add(source_id)
    records.sort(key=lambda item: (item["matchday"], item["matchday_date"] or "9999-12-31", int(item["source_match_id"]), item["group"]))
    source = {
        "source": "BDFutbol",
        "competition": "Primera Federación",
        "season": "2026-27",
        "generation_id": verified.generation_id,
        "generation_manifest_sha256": verified.manifest_sha256,
    }
    base = {
        "schema_version": "football_data_hub.match_detail_campaign_inventory.v1",
        "source": source,
        "counts": {
            "fixtures": len(records),
            "groups": {group: sum(item["group"] == group for item in records) for group in ("I", "II")},
            "played": sum(item["status"] == "played" for item in records),
            "unplayed": sum(item["status"] == "unplayed" for item in records),
            "incomplete": sum(item["status"] == "incomplete" for item in records),
            "played_with_explicit_url": sum(bool(item["status"] == "played" and item["source_match_url"]) for item in records),
            "played_without_explicit_url": sum(bool(item["status"] == "played" and not item["source_match_url"]) for item in records),
        },
        "matches": records,
    }
    return {"inventory_id": "match-detail-campaign-inventory-" + _sha(_canonical(base))[:16], **base}


def classify_match_campaign_inventory(
    inventory: dict[str, Any],
    *,
    published_ids: Iterable[str] = (),
    campaign_states: dict[str, dict[str, Any]] | None = None,
    captured_ids: Iterable[str] = (),
    validated_pending_approval_ids: Iterable[str] = (),
    approved_pending_publication_ids: Iterable[str] = (),
    blocked_reasons: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Join verified read-only state sources without adding a manual state store."""

    published = set(published_ids)
    captured = set(captured_ids)
    validated = set(validated_pending_approval_ids)
    approved = set(approved_pending_publication_ids)
    states = campaign_states or {}
    blocked = blocked_reasons or {}
    rows: list[dict[str, Any]] = []
    for source in inventory["matches"]:
        internal_id = source["internal_id"]
        campaign = states.get(internal_id)
        campaign_state = campaign.get("state") if campaign else None
        is_published = internal_id in published
        if source["status"] != "played":
            status = "unplayed" if source["status"] == "unplayed" else "played_incomplete_or_unresolved"
        elif is_published and campaign_state == "REVIEW_COMPLETED":
            status = "review_completed"
        elif is_published:
            status = "published_approved"
        elif internal_id in blocked:
            status = "blocked_requires_human_review"
        elif campaign_state in {"STOPPED", "INTERRUPTED_REQUIRES_REVIEW", "VALIDATION_FAILED", "REVALIDATION_FAILED", "CAMPAIGN_BLOCKED", "CONFLICTING_CAMPAIGN_MEMBERSHIP"}:
            status = "blocked_requires_human_review"
        elif campaign_state in {"PUBLISHED", "REVIEW_COMPLETED"} and not is_published:
            status = "blocked_requires_human_review"
            blocked.setdefault(internal_id, []).append("V2_LEDGER_PUBLICATION_MISSING_FROM_ACTIVE_INDEX")
        elif campaign_state == "PUBLISHED":
            status = "published_approved"
        elif internal_id in approved:
            status = "approved_pending_publication"
        elif campaign_state in {"DOCUMENT_APPROVED"} or internal_id in approved:
            status = "approved_pending_publication"
        elif campaign_state in {"VALIDATED", "REVALIDATED", "DRAFT_PREPARED"} or internal_id in validated:
            status = "validated_pending_approval"
        elif campaign_state == "DISCOVERY_REVIEW_REQUIRED":
            status = "captured_pending_validation"
        elif campaign_state == "AUTHORIZED":
            status = "authorized_not_executed"
        elif campaign_state == "STARTED":
            status = "blocked_requires_human_review"
        elif internal_id in captured:
            status = "captured_pending_validation"
        elif campaign is not None:
            status = "included_in_existing_campaign"
        elif not source["source_match_url"]:
            status = "played_without_verified_url"
        else:
            status = "played_pending_acquisition"
        next_operation = _next_operation(status)
        if status == "included_in_existing_campaign" and campaign is not None:
            if campaign.get("state") in {"PROPOSED_NOT_AUTHORIZED", "NOT_AUTHORIZED"}:
                next_operation = "review_proposal_then_use_a_separate_individual_authorization_workflow"
        if campaign_state == "AUTHORIZED":
            next_operation = "execute_one_authorized_navigation"
        elif campaign_state == "DISCOVERY_REVIEW_REQUIRED":
            next_operation = "validate_offline_artifact"
        elif campaign_state in {"VALIDATED", "DRAFT_PREPARED"}:
            next_operation = "prepare_or_review_offline_draft"
        elif campaign_state == "DOCUMENT_APPROVED":
            next_operation = "publish_approved_document_offline"
        elif campaign_state == "PUBLISHED":
            next_operation = "verify_publication_and_complete_review"
        elif campaign_state in {"VALIDATED", "REVALIDATED"}:
            next_operation = "prepare_offline_draft"
        elif campaign_state in {"VALIDATION_FAILED", "REVALIDATION_FAILED"}:
            next_operation = "revalidate_failed_artifact_offline_with_operator_confirmation"
        elif campaign_state in {"STOPPED", "STARTED", "INTERRUPTED_REQUIRES_REVIEW"}:
            next_operation = "manual_review_required_no_retry"
        rows.append({
            **source,
            "detail_status": status,
            "published_approved": is_published,
            "review_status": "completed" if campaign_state == "REVIEW_COMPLETED" else "pending",
            "authorization_consumed": bool(campaign and campaign.get("authorization_consumed")),
            "navigation_count": campaign.get("navigation_count", 0) if campaign else 0,
            "campaign": campaign,
            "blocked_reasons": list(blocked.get(internal_id, [])),
            "next_safe_operation": next_operation,
        })
    counts = Counter(row["detail_status"] for row in rows)
    by_group: dict[str, dict[str, int]] = {}
    by_group_matchday: dict[str, dict[str, dict[str, int]]] = {}
    for group in ("I", "II"):
        group_rows = [row for row in rows if row["group"] == group]
        by_group[group] = dict(sorted(Counter(row["detail_status"] for row in group_rows).items()))
        by_group_matchday[group] = {}
        for matchday in sorted({row["matchday"] for row in group_rows}):
            by_group_matchday[group][str(matchday)] = dict(sorted(Counter(
                row["detail_status"] for row in group_rows if row["matchday"] == matchday
            ).items()))
    serialized_counts = {key: counts.get(key, 0) for key in sorted(set(counts) | {
        "unplayed", "played_incomplete_or_unresolved", "played_without_verified_url",
        "played_pending_acquisition", "included_in_existing_campaign", "authorized_not_executed",
        "captured_pending_validation", "validated_pending_approval", "approved_pending_publication",
        "published_approved", "review_completed", "blocked_requires_human_review",
    })}
    # Publication and review completion are independent lifecycle facts. A
    # published candidate whose review was explicitly completed is counted in
    # both; its primary detail_status remains review_completed.
    serialized_counts["published_approved"] = sum(row["published_approved"] for row in rows)
    return {
        "schema_version": "football_data_hub.match_detail_campaign_status.v1",
        "source": inventory["source"],
        "counts": serialized_counts,
        "by_group": by_group,
        "by_group_matchday": by_group_matchday,
        "matches": rows,
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
        "authorization_created": False,
    }


def _next_operation(status: str) -> str:
    return {
        "unplayed": "wait_for_verified_played_result",
        "played_incomplete_or_unresolved": "review_fixture_source",
        "played_without_verified_url": "obtain_authorized_source_evidence",
        "played_pending_acquisition": "human_review_and_individual_authorization_required",
        "included_in_existing_campaign": "continue_existing_campaign_workflow_only",
        "authorized_not_executed": "execute_only_the_existing_one_shot_authorization",
        "captured_pending_validation": "validate_offline_artifact",
        "validated_pending_approval": "explicit_human_document_approval_required",
        "approved_pending_publication": "publish_approved_document_offline",
        "published_approved": "already_published_no_acquisition",
        "review_completed": "no_operation_required",
        "blocked_requires_human_review": "manual_review_required_no_retry",
    }.get(status, "manual_review_required")


def build_match_campaign_proposal(
    status_report: dict[str, Any],
    *,
    groups: Iterable[str] = ("I", "II"),
    matchday_from: int | None = None,
    matchday_to: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic, non-authorizing variable-size candidate plan."""

    selected_groups = tuple(sorted(set(groups)))
    if not selected_groups or set(selected_groups) - {"I", "II"}:
        raise ScalableCampaignError("Selecciona Grupo I, II o ambos")
    for value, label in ((matchday_from, "jornada inicial"), (matchday_to, "jornada final")):
        if value is not None and (type(value) is not int or not 1 <= value <= 38):
            raise ScalableCampaignError(f"{label} inválida")
    if matchday_from is not None and matchday_to is not None and matchday_from > matchday_to:
        raise ScalableCampaignError("El rango de jornadas está invertido")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ScalableCampaignError("El límite de candidatos debe ser positivo")
    candidates = [
        row for row in status_report["matches"]
        if row["group"] in selected_groups
        and row["detail_status"] == "played_pending_acquisition"
        and row["source_match_url"] is not None
        and (matchday_from is None or row["matchday"] >= matchday_from)
        and (matchday_to is None or row["matchday"] <= matchday_to)
    ]
    candidates.sort(key=lambda item: (
        item["matchday"], item["matchday_date"] or "9999-12-31",
        int(item["source_match_id"]), item["group"],
    ))
    available_count = len(candidates)
    if limit is not None:
        candidates = candidates[:limit]
    candidate_fields = (
        "internal_id", "source_match_id", "competition", "season", "group", "matchday",
        "source_match_date", "matchday_date", "home_team_id", "home_team_name", "away_team_id",
        "away_team_name", "reference_result", "source_match_url", "source_generation_id",
        "source_generation_manifest_sha256", "source_capture_id", "source_captured_at_utc",
        "source_snapshot_sha256", "source_matches_sha256", "detail_status",
    )
    candidate_records = [{key: row[key] for key in candidate_fields} for row in candidates]
    source = status_report["source"]
    selection = {
        "groups": list(selected_groups),
        "played_only": True,
        "exclude_published": True,
        "exclude_managed_or_authorized": True,
        "exclude_blocked_or_ambiguous": True,
        "matchday_from": matchday_from,
        "matchday_to": matchday_to,
        "limit": limit,
        "available_candidates_before_limit": available_count,
        "sort": ["matchday", "matchday_date", "source_match_id", "group"],
    }
    campaign_basis = {
        "source": source,
        "selection": selection,
        "selected_internal_ids": [item["internal_id"] for item in candidate_records],
    }
    base = {
        "schema_version": PLAN_SCHEMA,
        "plan_version": 2,
        "campaign_id": "match-detail-campaign-v2-" + _sha(_canonical(campaign_basis))[:16],
        "source": source,
        "selection": selection,
        "candidate_count": len(candidate_records),
        "candidates": candidate_records,
        "authorization": {
            "status": "NOT_AUTHORIZED",
            "is_authorization": False,
            "maximum_navigations_per_candidate": 1,
            "automatic_retries": 0,
            "navigation_enabled": False,
            "browser_started": False,
            "http_enabled": False,
            "capture_promotion_enabled": False,
        },
    }
    plan_sha = _sha(_canonical(base))
    proposal_id = "match-detail-campaign-plan-" + plan_sha[:16]
    return {**base, "proposal_id": proposal_id, "plan_sha256": plan_sha}


def build_incremental_match_detail_report(
    before_bundle: Any,
    after_bundle: Any,
    status_report: dict[str, Any],
    *,
    published_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Report fixtures newly marked played across two verified local bundles."""

    from football_data_hub.providers.bdfutbol.classification.generation_activation import (
        compare_match_generations,
    )

    diff = compare_match_generations(
        before_bundle,
        after_bundle,
        approved_detail_ids=set(published_ids),
    )
    current = {row["internal_id"]: row for row in status_report["matches"]}
    changes = []
    for item in diff["fixtures"]:
        if item.get("change_type") != "newly_played":
            continue
        row = current.get(item["internal_id"])
        if row is None:
            raise ScalableCampaignError("El diff referencia un fixture ausente de la generación nueva")
        changes.append({
            "internal_id": row["internal_id"],
            "source_match_id": row["source_match_id"],
            "group": row["group"],
            "matchday": row["matchday"],
            "detail_status": row["detail_status"],
            "source_match_url": row["source_match_url"],
            "next_safe_operation": row["next_safe_operation"],
            "details_missing": not row["published_approved"],
        })
    return {
        "before_generation_id": diff["before_generation_id"],
        "after_generation_id": diff["after_generation_id"],
        "newly_played_count": len(changes),
        "newly_played_missing_details_count": sum(item["details_missing"] for item in changes),
        "newly_played": changes,
        "source_diff_summary": diff["summary"],
    }


def write_match_campaign_proposal(output_root: Path, plan: dict[str, Any]) -> Path:
    """Persist a complete plan directory atomically and immutably."""

    body = {key: value for key, value in plan.items() if key not in {"proposal_id", "plan_sha256"}}
    actual_sha = _sha(_canonical(body))
    expected_id = "match-detail-campaign-plan-" + actual_sha[:16]
    if (
        plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("plan_sha256") != actual_sha
        or plan.get("proposal_id") != expected_id
        or not _PLAN_ID.fullmatch(expected_id)
        or plan.get("authorization", {}).get("is_authorization") is not False
    ):
        raise ScalableCampaignError("El plan no es canónico, inmutable o no autorizante")
    _validate_plan_payload(plan)
    root = output_root.expanduser().absolute()
    _reject_symlinks(root)
    plans = root / "plans"
    _mkdirs_durable(plans)
    target = plans / expected_id
    plan_raw = _canonical(plan)
    if target.is_symlink():
        raise ScalableCampaignError(f"No se sobrescribe symlink de propuesta: {target}")
    manifest = {
        "schema_version": PLAN_MANIFEST_SCHEMA,
        "proposal_id": expected_id,
        "plan_sha256": _sha(plan_raw),
        "campaign_id": plan["campaign_id"],
        "candidate_count": plan["candidate_count"],
    }
    manifest_raw = _canonical(manifest)
    if target.exists():
        if _load_match_campaign_proposal(target) == plan:
            return target
        raise ScalableCampaignError(f"No se sobrescribe propuesta existente: {target}")
    stage = Path(tempfile.mkdtemp(prefix=f".{expected_id}.", dir=plans))
    try:
        for name, raw in (("plan.json", plan_raw), ("manifest.json", manifest_raw)):
            with (stage / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        _fsync_dir(stage)
        os.rename(stage, target)
        _fsync_dir(plans)
    except FileExistsError as exc:
        raise ScalableCampaignError(f"No se sobrescribe propuesta existente: {target}") from exc
    finally:
        if stage.exists():
            for child in stage.iterdir():
                child.unlink(missing_ok=True)
            stage.rmdir()
    return target


def _load_match_campaign_proposal(plan_dir: Path) -> dict[str, Any]:
    if plan_dir.is_symlink() or not plan_dir.is_dir():
        raise ScalableCampaignError(f"Directorio de propuesta inválido: {plan_dir}")
    if {item.name for item in plan_dir.iterdir()} != {"plan.json", "manifest.json"}:
        raise ScalableCampaignError("La propuesta contiene archivos ausentes o inesperados")
    plan_path, manifest_path = plan_dir / "plan.json", plan_dir / "manifest.json"
    if any(path.is_symlink() or not path.is_file() for path in (plan_path, manifest_path)):
        raise ScalableCampaignError("Faltan los ficheros regulares de una propuesta")
    plan_raw, manifest_raw = plan_path.read_bytes(), manifest_path.read_bytes()
    try:
        plan, manifest = json.loads(plan_raw), json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScalableCampaignError("La propuesta no contiene JSON válido") from exc
    if not isinstance(plan, dict) or plan_raw != _canonical(plan):
        raise ScalableCampaignError("plan.json no es canónico")
    expected_sha = _sha(_canonical({key: value for key, value in plan.items() if key not in {"proposal_id", "plan_sha256"}}))
    expected_id = "match-detail-campaign-plan-" + expected_sha[:16]
    expected_manifest = {
        "schema_version": PLAN_MANIFEST_SCHEMA,
        "proposal_id": expected_id,
        "plan_sha256": _sha(plan_raw),
        "campaign_id": plan.get("campaign_id"),
        "candidate_count": plan.get("candidate_count"),
    }
    if (
        plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("proposal_id") != expected_id
        or plan.get("plan_sha256") != expected_sha
        or plan_dir.name != expected_id
        or manifest != expected_manifest
        or manifest_raw != _canonical(expected_manifest)
        or len(plan.get("candidates", [])) != plan.get("candidate_count")
        or plan.get("authorization", {}).get("is_authorization") is not False
        or plan.get("authorization", {}).get("navigation_enabled") is not False
    ):
        raise ScalableCampaignError("Hashes o contrato de propuesta inválidos")
    _validate_plan_payload(plan)
    return plan


def _validate_plan_payload(plan: dict[str, Any]) -> None:
    source = plan.get("source")
    selection = plan.get("selection")
    candidates = plan.get("candidates")
    authorization = plan.get("authorization")
    if (
        not isinstance(source, dict)
        or source.get("source") != "BDFutbol"
        or source.get("competition") != "Primera Federación"
        or source.get("season") != "2026-27"
        or not isinstance(source.get("generation_id"), str)
        or not source["generation_id"]
        or Path(source["generation_id"]).name != source["generation_id"]
        or not _SHA.fullmatch(str(source.get("generation_manifest_sha256", "")))
        or not isinstance(selection, dict)
        or not isinstance(candidates, list)
        or not isinstance(authorization, dict)
        or authorization.get("status") != "NOT_AUTHORIZED"
        or authorization.get("is_authorization") is not False
        or authorization.get("navigation_enabled") is not False
        or authorization.get("browser_started") is not False
        or authorization.get("http_enabled") is not False
        or authorization.get("capture_promotion_enabled") is not False
        or authorization.get("automatic_retries") != 0
        or authorization.get("maximum_navigations_per_candidate") != 1
        or selection.get("exclude_published") is not True
        or selection.get("exclude_managed_or_authorized") is not True
        or selection.get("exclude_blocked_or_ambiguous") is not True
        or selection.get("played_only") is not True
        or selection.get("groups") not in (["I"], ["II"], ["I", "II"])
        or plan.get("plan_version") != 2
    ):
        raise ScalableCampaignError("La propuesta carece de fuentes, filtros o límites no autorizantes")
    if plan.get("candidate_count") != len(candidates):
        raise ScalableCampaignError("candidate_count no coincide con el contenido")
    if not candidates:
        raise ScalableCampaignError("No se persiste una propuesta sin candidatos elegibles")
    available = selection.get("available_candidates_before_limit")
    limit = selection.get("limit")
    if (
        type(available) is not int
        or available < len(candidates)
        or (limit is not None and (type(limit) is not int or limit < 1 or len(candidates) > limit))
    ):
        raise ScalableCampaignError("Los límites o el recuento de candidatos no son coherentes")
    source_ids: set[str] = set()
    internal_ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ScalableCampaignError("Candidato no es un objeto")
        source_id = item.get("source_match_id")
        group = item.get("group")
        internal_id = item.get("internal_id")
        if (
            not isinstance(source_id, str)
            or not _SOURCE_ID.fullmatch(source_id)
            or group not in selection["groups"]
            or internal_id != f"pf-2026-27-group-{str(group).lower()}-bdfutbol-{source_id}"
            or internal_id in internal_ids
            or source_id in source_ids
            or item.get("detail_status") != "played_pending_acquisition"
            or item.get("source_generation_id") != source["generation_id"]
            or item.get("source_generation_manifest_sha256") != source["generation_manifest_sha256"]
            or item.get("source_match_url") != f"https://www.bdfutbol.com/es/p/p.php?id={source_id}"
            or type(item.get("matchday")) is not int
            or not 1 <= item["matchday"] <= 38
            or type(item.get("home_team_id")) is not int
            or type(item.get("away_team_id")) is not int
            or item["home_team_id"] == item["away_team_id"]
            or not isinstance(item.get("home_team_name"), str)
            or not item["home_team_name"].strip()
            or not isinstance(item.get("away_team_name"), str)
            or not item["away_team_name"].strip()
            or not isinstance(item.get("source_capture_id"), str)
            or not item["source_capture_id"]
            or not isinstance(item.get("source_captured_at_utc"), str)
            or not _SHA.fullmatch(str(item.get("source_snapshot_sha256", "")))
            or not _SHA.fullmatch(str(item.get("source_matches_sha256", "")))
            or not isinstance(item.get("reference_result"), dict)
            or set(item["reference_result"]) != {"home_goals", "away_goals"}
            or any(type(value) is not int or value < 0 for value in item["reference_result"].values())
        ):
            raise ScalableCampaignError(f"Identidad o procedencia inválida en candidato {internal_id!r}")
        _validate_match_url(item["source_match_url"], source_id)
        source_ids.add(source_id)
        internal_ids.add(internal_id)
    expected_campaign = "match-detail-campaign-v2-" + _sha(_canonical({
        "source": source,
        "selection": selection,
        "selected_internal_ids": [item["internal_id"] for item in candidates],
    }))[:16]
    if plan.get("campaign_id") != expected_campaign:
        raise ScalableCampaignError("campaign_id no deriva de la selección y la generación")


def load_match_campaign_proposals(root: Path) -> list[dict[str, Any]]:
    """Read and verify proposals, rejecting malformed or unexpected entries."""

    path = root.expanduser().absolute()
    _reject_symlinks(path)
    plans_root = path / "plans"
    if not plans_root.exists():
        return []
    if plans_root.is_symlink() or not plans_root.is_dir():
        raise ScalableCampaignError("La raíz plans no es un directorio regular")
    result = []
    for child in sorted(plans_root.iterdir()):
        if child.is_symlink() or not child.is_dir() or not _PLAN_ID.fullmatch(child.name):
            raise ScalableCampaignError(f"Entrada no reconocida en plans: {child.name}")
        result.append(_load_match_campaign_proposal(child))
    return result


def _reject_symlinks(path: Path) -> None:
    cursor = path
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise ScalableCampaignError(f"No se permiten symlinks en la ruta: {cursor}")
        cursor = cursor.parent


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdirs_durable(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        if current.is_symlink():
            raise ScalableCampaignError(f"No se permiten symlinks en la ruta: {current}")
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise ScalableCampaignError(f"Directorio padre inválido: {current}")
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            if directory.is_symlink() or not directory.is_dir():
                raise ScalableCampaignError(f"Directorio de salida concurrente inválido: {directory}")
        _fsync_dir(directory.parent)
    _fsync_dir(path)
