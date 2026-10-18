"""Offline status and variable-size proposal CLI for MATCH detail campaigns."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .campaign import MatchDetailCampaignLedger
from .inventory import build_match_detail_inventory, load_verified_match_generation
from .scalable_campaigns import (
    ScalableCampaignError,
    build_incremental_match_detail_report,
    build_match_campaign_inventory,
    build_match_campaign_proposal,
    classify_match_campaign_inventory,
    load_match_campaign_proposals,
    write_match_campaign_proposal,
)
from .store import MatchDetailStore


def _parser() -> argparse.ArgumentParser:
    data_root = Path(os.getenv("FDH_LOCAL_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()
    match_store_root = data_root / "matches"
    active_pointer = match_store_root / "active-generation.json"
    default_generation_root = (
        match_store_root
        if active_pointer.exists() or active_pointer.is_symlink()
        else match_store_root / "generations" / "match-00-4ad1d610507e425d"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=data_root)
    parser.add_argument(
        "--generation-root", type=Path,
        default=default_generation_root,
        help="Generación verificada o almacén con active-generation.json; nunca se escoge la más reciente.",
    )
    parser.add_argument(
        "--previous-generation-root", type=Path,
        help="Generación verificada anterior para informar partidos que pasan a disputados.",
    )
    parser.add_argument("--store-root", type=Path, default=data_root / "matches/details")
    parser.add_argument("--published-root", type=Path, default=data_root / "matches/details/published")
    parser.add_argument("--player-inventory-root", type=Path, default=data_root / "players/inventory-2026-27")
    parser.add_argument("--player-compact-root", type=Path, default=data_root / "players/compact-2026-27")
    parser.add_argument("--player-team-captures-root", type=Path, default=data_root / "team-captures")
    parser.add_argument("--player-published-index", type=Path, default=data_root / "published/team_profiles_2026-27.json")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Consulta cobertura y ciclo de vida sin modificar datos")
    status.add_argument("--include-matches", action="store_true", help="Incluye el registro de los 760 encuentros")
    status.add_argument("--group", choices=("I", "II"))
    status.add_argument("--matchday-from", type=int)
    status.add_argument("--matchday-to", type=int)
    status.add_argument("--campaign-id")
    status.add_argument("--state")
    propose = commands.add_parser("propose", help="Crea una propuesta no autorizante y sin navegación")
    propose.add_argument("--groups", choices=("I", "II", "both"), default="both")
    propose.add_argument("--matchday-from", type=int)
    propose.add_argument("--matchday-to", type=int)
    propose.add_argument("--limit", type=int, default=10)
    propose.add_argument("--persist", action="store_true", help="Guarda el plan inmutable bajo matches/details/campaign-proposals")
    propose.add_argument("--newly-played-only", action="store_true", help="Limita a nuevos disputados; requiere --previous-generation-root")
    initialize = commands.add_parser("initialize", help="Inicializa una propuesta verificada como campaña v2; no autoriza")
    initialize.add_argument("--proposal-id", required=True)
    campaign_preflight = commands.add_parser("campaign-preflight", help="Consulta integridad y progreso de una campaña v2")
    campaign_preflight.add_argument("--campaign-id", required=True)
    candidates = commands.add_parser("candidates", help="Lista candidatos de una campaña v2")
    candidates.add_argument("--campaign-id", required=True)
    candidates.add_argument("--group", choices=("I", "II"))
    candidates.add_argument("--matchday", type=int)
    candidates.add_argument("--state")
    authorize = commands.add_parser("authorize", help="Autoriza una sola navegación para un partido")
    authorize.add_argument("--campaign-id", required=True)
    authorize.add_argument("--internal-id", required=True)
    authorize.add_argument("--confirm-url", required=True)
    authorize.add_argument("--operator", required=True)
    authorize.add_argument("--confirm-authorization", required=True)
    execute = commands.add_parser("execute", help="Consume una autorización y realiza una única navegación real")
    execute.add_argument("--campaign-id", required=True)
    execute.add_argument("--internal-id", required=True)
    execute.add_argument("--authorization-id", required=True)
    execute.add_argument("--confirm-url", required=True)
    execute.add_argument("--confirm-execution", required=True)
    execute.add_argument("--player-browser-idle-confirmation", required=True)
    inspect = commands.add_parser("inspect", help="Consulta el estado y artefacto local de un candidato")
    inspect.add_argument("--campaign-id", required=True)
    inspect.add_argument("--internal-id", required=True)
    validate = commands.add_parser("validate", help="Valida offline el artefacto semántico")
    validate.add_argument("--campaign-id", required=True)
    validate.add_argument("--internal-id", required=True)
    revalidate = commands.add_parser(
        "revalidate-failed",
        help="Revalida offline una validación fallida con confirmación de operador; no navega",
    )
    revalidate.add_argument("--campaign-id", required=True)
    revalidate.add_argument("--internal-id", required=True)
    revalidate.add_argument("--operator", required=True)
    revalidate.add_argument("--confirm-revalidation", required=True)
    prepare = commands.add_parser("prepare", help="Prepara el borrador deportivo offline")
    prepare.add_argument("--campaign-id", required=True)
    prepare.add_argument("--internal-id", required=True)
    preview = commands.add_parser("preview", help="Muestra el borrador inmutable para revisión humana")
    preview.add_argument("--campaign-id", required=True)
    preview.add_argument("--internal-id", required=True)
    approve = commands.add_parser("approve", help="Registra aprobación humana específica y ligada a hashes")
    approve.add_argument("--campaign-id", required=True)
    approve.add_argument("--internal-id", required=True)
    approve.add_argument("--draft-path", type=Path, required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--confirm-internal-id", required=True)
    approve.add_argument("--confirm-source-html-sha256", required=True)
    approve.add_argument("--confirm-details-sha256", required=True)
    approve.add_argument("--confirm-action", required=True)
    publish = commands.add_parser("publish", help="Publica un borrador aprobado tras revalidarlo")
    publish.add_argument("--campaign-id", required=True)
    publish.add_argument("--internal-id", required=True)
    verify = commands.add_parser("verify", help="Verifica el paquete público desde sus fuentes")
    verify.add_argument("--campaign-id", required=True)
    verify.add_argument("--internal-id", required=True)
    close = commands.add_parser("complete-review", help="Cierra explícitamente la revisión de una publicación")
    close.add_argument("--campaign-id", required=True)
    close.add_argument("--internal-id", required=True)
    close.add_argument("--reviewer", required=True)
    close.add_argument("--confirm-review", required=True)
    return parser


def _read_campaign_states(campaign_root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Verify persisted legacy campaign ledgers with their existing reader."""

    if not campaign_root.exists():
        return {}, []
    if campaign_root.is_symlink() or not campaign_root.is_dir():
        raise ScalableCampaignError("La raíz de campañas no es un directorio regular")
    lock_path = campaign_root / "campaign-ledger.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ScalableCampaignError("Falta el lock persistido del ledger de campañas")
    states: dict[str, dict[str, Any]] = {}
    summaries: list[dict[str, Any]] = []
    with lock_path.open("rb") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ScalableCampaignError("El ledger cambia mientras se consulta el progreso") from exc
        try:
            for directory in sorted(campaign_root.iterdir()):
                if directory.name == lock_path.name:
                    continue
                if directory.is_symlink() or not directory.is_dir():
                    raise ScalableCampaignError(f"Entrada inesperada en campañas: {directory.name}")
                campaign_path = directory / "campaign.json"
                if campaign_path.is_symlink() or not campaign_path.is_file():
                    raise ScalableCampaignError(f"Falta campaign.json en {directory.name}")
                try:
                    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ScalableCampaignError(f"campaign.json ilegible: {directory.name}") from exc
                candidates = campaign.get("candidates") if isinstance(campaign, dict) else None
                if not isinstance(candidates, list) or not candidates:
                    raise ScalableCampaignError(f"La campaña no tiene candidatos legibles: {directory.name}")
                if campaign.get("schema_version") == "football_data_hub.match_detail_operational_campaign.v2":
                    from .operational_campaign import OperationalMatchCampaignLedger

                    report = OperationalMatchCampaignLedger(campaign_root).preflight(
                        directory.name, acquire_lock=False
                    )
                    state_counts: dict[str, int] = {}
                    for candidate in report["candidates"]:
                        state_counts[candidate["state"]] = state_counts.get(candidate["state"], 0) + 1
                    summaries.append({
                        "campaign_id": directory.name,
                        "proposal_id": report["proposal_id"],
                        "candidate_count": report["candidate_count"],
                        "candidate_states": dict(sorted(state_counts.items())),
                        "blocked_reasons": [],
                        "campaign_version": 2,
                    })
                    for candidate in report["candidates"]:
                        internal_id = candidate["internal_id"]
                        row = {
                            "campaign_id": directory.name,
                            "campaign_version": 2,
                            "state": candidate["state"],
                            "authorization_consumed": candidate["authorization_consumed"],
                            "navigation_count": candidate["navigation_count"],
                            "review_status": "completed" if candidate["state"] == "REVIEW_COMPLETED" else "pending",
                            "blocked_reasons": [],
                            "candidate_identity": {
                                key: candidate.get(key)
                                for key in (
                                    "internal_id", "source_match_id", "group", "home_team_id",
                                    "away_team_id", "reference_result", "source_match_url",
                                    "source_generation_id", "source_generation_manifest_sha256",
                                )
                            },
                        }
                        existing = states.get(internal_id)
                        if existing is not None and existing.get("campaign_id") != directory.name:
                            existing.setdefault("campaigns", [existing["campaign_id"]]).append(directory.name)
                            existing["state"] = "CONFLICTING_CAMPAIGN_MEMBERSHIP"
                        else:
                            row["campaigns"] = [directory.name]
                            states[internal_id] = row
                    continue
                first = candidates[0]
                first_id = first.get("internal_id") if isinstance(first, dict) else None
                if not isinstance(first_id, str):
                    raise ScalableCampaignError(f"Candidato sin identidad en {directory.name}")
                ledger = MatchDetailCampaignLedger(campaign_root)
                _spec, report, _events = ledger.inspect_persisted_campaign_read_only(
                    directory, internal_id=first_id
                )
                state_counts: dict[str, int] = {}
                for candidate in report["candidates"]:
                    state_counts[candidate["state"]] = state_counts.get(candidate["state"], 0) + 1
                summaries.append({
                    "campaign_id": report["campaign_id"],
                    "candidate_count": len(report["candidates"]),
                    "candidate_states": dict(sorted(state_counts.items())),
                    "blocked_reasons": report["blocked_reasons"],
                    "campaign_version": 1,
                })
                for candidate in report["candidates"]:
                    internal_id = candidate["internal_id"]
                    existing = states.get(internal_id)
                    state = candidate["state"]
                    if (
                        report["status"] == "BLOCKED"
                        and state in {"NOT_AUTHORIZED", "AUTHORIZED"}
                    ):
                        state = "CAMPAIGN_BLOCKED"
                    item = {
                        "campaign_id": report["campaign_id"],
                        "state": state,
                        "original_state": candidate["state"],
                        "authorization_consumed": candidate["authorization_consumed"],
                        "navigation_count": candidate["navigation_count"],
                        "review_status": candidate.get("review_status", "pending"),
                        "blocked_reasons": report["blocked_reasons"],
                    }
                    if existing is not None:
                        existing.setdefault("campaigns", [existing["campaign_id"]]).append(item["campaign_id"])
                        existing["state"] = "CONFLICTING_CAMPAIGN_MEMBERSHIP"
                    else:
                        item["campaigns"] = [item["campaign_id"]]
                        states[internal_id] = item
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return states, summaries


def _review_state_ids(
    *,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    bundle: Any,
    player_ids: set[int],
    published_ids: set[str],
) -> tuple[set[str], set[str], dict[str, list[str]]]:
    """Rebuild draft and approval states from their source artifacts offline."""

    from football_data_hub_api.match_details_dataset import (
        MatchDetailsLoadError,
        build_campaign_approval_receipt,
        build_campaign_publication_draft,
        campaign_approval_confirmation,
    )

    review_root = store_root / "review"
    validated: set[str] = set()
    approved: set[str] = set()
    blocked: dict[str, list[str]] = {}
    if not review_root.exists():
        return validated, approved, blocked
    if review_root.is_symlink() or not review_root.is_dir():
        raise ScalableCampaignError("La raíz review no es un directorio regular")
    drafts: dict[str, dict[str, Any]] = {}
    approvals: dict[str, dict[str, Any]] = {}
    for path in sorted(review_root.iterdir()):
        if path.is_symlink() or not path.is_file() or not path.name.endswith(("-draft.json", "-approval.json")):
            raise ScalableCampaignError(f"Entrada inesperada en review: {path.name}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScalableCampaignError(f"Registro review ilegible: {path.name}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("internal_id"), str):
            raise ScalableCampaignError(f"Registro review sin internal_id: {path.name}")
        target = drafts if path.name.endswith("-draft.json") else approvals
        target[value["internal_id"]] = value
    for internal_id, draft_record in drafts.items():
        if internal_id in published_ids:
            continue
        try:
            if draft_record.get("semantic_valid") is not True:
                continue
            source_generation_id = draft_record.get("source_generation_id")
            source_generation_root = generation_root
            source_bundle = bundle
            if source_generation_id != bundle.bootstrap.metadata.generation_id:
                if not isinstance(source_generation_id, str) or not source_generation_id or Path(source_generation_id).name != source_generation_id:
                    raise MatchDetailsLoadError("ID de generación histórica inválido")
                source_generation_root = data_root / "matches" / "generations" / source_generation_id
                from football_data_hub_api.match_results_dataset import load_match_results_dataset
                source_bundle = load_match_results_dataset(source_generation_root, data_root=data_root)
            rebuilt = build_campaign_publication_draft(
                internal_id=internal_id,
                campaign_id=str(draft_record.get("campaign_id", "")),
                artifact_id=str(draft_record.get("artifact_id", "")),
                publication_id=str(draft_record.get("publication_id", "")),
                generation_root=source_generation_root,
                data_root=data_root,
                match_bundle=source_bundle,
                player_ids=player_ids,
            )
            if rebuilt != draft_record:
                raise MatchDetailsLoadError("El borrador guardado difiere de su reconstrucción")
            validated.add(internal_id)
            approval = approvals.get(internal_id)
            if approval is not None:
                approved_at = datetime.fromisoformat(str(approval.get("approved_at_utc", "")).replace("Z", "+00:00"))
                expected = build_campaign_approval_receipt(
                    rebuilt,
                    approved_by=str(approval.get("approved_by", "")),
                    confirm_internal_id=internal_id,
                    confirm_source_html_sha256=str(approval.get("source_html_sha256", "")),
                    confirm_details_sha256=str(approval.get("details_sha256", "")),
                    confirm_action=campaign_approval_confirmation(rebuilt),
                    approved_at_utc=approved_at,
                )
                if expected != approval:
                    raise MatchDetailsLoadError("El recibo de aprobación difiere de su borrador exacto")
                approved.add(internal_id)
        except (MatchDetailsLoadError, OSError, ValueError, KeyError, TypeError) as exc:
            blocked.setdefault(internal_id, []).append(f"REVIEW_ARTIFACT_INVALID:{exc}")
    for internal_id in set(approvals) - set(drafts):
        if internal_id not in published_ids:
            blocked.setdefault(internal_id, []).append("APPROVAL_WITHOUT_DRAFT")
    return validated, approved, blocked


def _load_report(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from football_data_hub.providers.bdfutbol.classification.generation_activation import resolve_match_generation_root
    from football_data_hub_api.match_details_dataset import load_published_match_details
    from football_data_hub_api.match_results_dataset import load_match_results_dataset
    from football_data_hub_api.player_dataset import load_player_directory

    data_root = args.data_root.expanduser().resolve(strict=True)
    generation_root = resolve_match_generation_root(args.generation_root, data_root=data_root)
    verified = load_verified_match_generation(generation_root, data_root=data_root)
    inventory = build_match_campaign_inventory(verified)
    bundle = load_match_results_dataset(generation_root, data_root=data_root)
    player_dir = load_player_directory(
        inventory_root=args.player_inventory_root,
        compact_root=args.player_compact_root,
        team_captures_root=args.player_team_captures_root,
        published_index_path=args.player_published_index,
    )
    published = load_published_match_details(
        args.published_root,
        store_root=args.store_root,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=bundle,
        player_ids=set(player_dir.players_by_id),
    )
    published_ids = set(published)

    acquisition_inventory = build_match_detail_inventory(verified)
    reconciliation = MatchDetailStore(args.store_root).reconcile(acquisition_inventory)
    campaign_states, campaign_summaries = _read_campaign_states(args.store_root / "campaigns")
    proposal_root = args.store_root / "campaign-proposals"
    proposals = load_match_campaign_proposals(proposal_root)
    for proposal in proposals:
        proposal_generation_id = proposal["source"]["generation_id"]
        if proposal_generation_id == verified.generation_id:
            proposal_generation = verified
        else:
            if Path(proposal_generation_id).name != proposal_generation_id:
                raise ScalableCampaignError("La propuesta contiene un ID de generación inseguro")
            historical_root = data_root / "matches" / "generations" / proposal_generation_id
            proposal_generation = load_verified_match_generation(historical_root, data_root=data_root)
        if proposal_generation.manifest_sha256 != proposal["source"]["generation_manifest_sha256"]:
            raise ScalableCampaignError(f"La fuente de la propuesta cambió: {proposal['proposal_id']}")
        source_inventory = build_match_campaign_inventory(proposal_generation)
        source_matches = {item["internal_id"]: item for item in source_inventory["matches"]}
        for candidate in proposal["candidates"]:
            internal_id = candidate["internal_id"]
            observed = source_matches.get(internal_id)
            if observed is None or any(
                candidate.get(key) != observed.get(key)
                for key in (
                    "source_match_id", "group", "matchday", "source_match_date", "matchday_date",
                    "home_team_id", "home_team_name", "away_team_id", "away_team_name",
                    "reference_result", "source_match_url", "source_generation_id",
                    "source_generation_manifest_sha256", "source_capture_id", "source_snapshot_sha256",
                    "source_matches_sha256",
                )
            ) or observed["status"] != "played":
                raise ScalableCampaignError(f"La propuesta no coincide con su MATCH-00 fuente: {internal_id}")
            if internal_id not in campaign_states and internal_id not in published_ids:
                campaign_states[internal_id] = {
                    "campaign_id": proposal["campaign_id"],
                    "state": "PROPOSED_NOT_AUTHORIZED",
                    "authorization_consumed": False,
                    "navigation_count": 0,
                    "review_status": "pending",
                }

    validated_ids, approved_ids, blocked = _review_state_ids(
        store_root=args.store_root,
        generation_root=generation_root,
        data_root=data_root,
        bundle=bundle,
        player_ids=set(player_dir.players_by_id),
        published_ids=published_ids,
    )
    for internal_id, campaign in campaign_states.items():
        if campaign["state"] in {"CAMPAIGN_BLOCKED", "CONFLICTING_CAMPAIGN_MEMBERSHIP"}:
            blocked.setdefault(internal_id, []).extend(
                campaign.get("blocked_reasons") or [campaign["state"]]
            )
        if campaign["state"] == "CONFLICTING_CAMPAIGN_MEMBERSHIP":
            blocked.setdefault(internal_id, []).append("CONFLICTING_CAMPAIGN_MEMBERSHIP")
        source_identity = campaign.get("candidate_identity")
        if source_identity:
            current = next((row for row in inventory["matches"] if row["internal_id"] == internal_id), None)
            if current is None or any(
                source_identity.get(key) != current.get(key)
                for key in (
                    "internal_id", "source_match_id", "group", "home_team_id", "away_team_id",
                    "reference_result", "source_match_url",
                )
            ):
                blocked.setdefault(internal_id, []).append("CAMPAIGN_SOURCE_CONFLICT_WITH_ACTIVE_GENERATION")
    for diag in reconciliation["diagnostics"]:
        if not diag.get("stop_acquisition", True):
            continue
        internal_id = diag.get("internal_id")
        if internal_id in {item["internal_id"] for item in inventory["matches"]}:
            blocked.setdefault(internal_id, []).append(str(diag.get("error_code") or "STOP_DIAGNOSTIC"))
    active_attempt = reconciliation.get("active_navigation_attempt")
    if isinstance(active_attempt, dict):
        internal_id = active_attempt.get("internal_id")
        if internal_id:
            blocked.setdefault(internal_id, []).append("INTERRUPTED_NAVIGATION_REQUIRES_REVIEW")
    if reconciliation["integrity_blocked"]:
        # A damaged shared inventory/checkpoint makes all unpublished candidates
        # unsafe to progress until the source of truth is reconciled.
        for row in inventory["matches"]:
            if row["status"] == "played" and row["internal_id"] not in published_ids:
                blocked.setdefault(row["internal_id"], []).append("STORE_INTEGRITY_BLOCKED")

    status_report = classify_match_campaign_inventory(
        inventory,
        published_ids=published_ids,
        campaign_states=campaign_states,
        captured_ids=reconciliation["verified_by_internal_id"],
        validated_pending_approval_ids=validated_ids,
        approved_pending_publication_ids=approved_ids,
        blocked_reasons=blocked,
    )
    status_report["storage_reconciliation"] = {
        "inventory_id": reconciliation["inventory_id"],
        "verified_snapshots": len(reconciliation["verified_by_internal_id"]),
        "invalid_snapshots": reconciliation["invalid_snapshots"],
        "invalid_discovery_artifacts": reconciliation["invalid_discovery_artifacts"],
        "diagnostic_count": len(reconciliation["diagnostics"]),
        "active_stop": reconciliation["active_stop"],
        "integrity_blocked": reconciliation["integrity_blocked"],
    }
    status_report["campaigns"] = campaign_summaries
    status_report["proposals"] = [
        {"campaign_id": item["campaign_id"], "candidate_count": item["candidate_count"],
         "authorization_status": item["authorization"]["status"], "proposal_id": item["proposal_id"]}
        for item in proposals
    ]
    if args.previous_generation_root is not None:
        previous_root = resolve_match_generation_root(
            args.previous_generation_root, data_root=data_root
        )
        previous_bundle = load_match_results_dataset(previous_root, data_root=data_root)
        status_report["incremental_update"] = build_incremental_match_detail_report(
            previous_bundle,
            bundle,
            status_report,
            published_ids=published_ids,
        )
    status_report["publication_count"] = len(published_ids)
    return status_report, proposals, {
        "generation_root": generation_root,
        "store_root": args.store_root,
        "data_root": data_root,
        "published_root": args.published_root,
        "published_ids": published_ids,
        "captured_ids": set(reconciliation["verified_by_internal_id"]),
        "blocked_ids": set(blocked),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "propose" and args.newly_played_only and args.previous_generation_root is None:
        parser.error("--newly-played-only requiere --previous-generation-root")
    try:
        from .operational_campaign import OperationalMatchCampaignLedger

        ledger = OperationalMatchCampaignLedger(args.store_root / "campaigns")
        data_root = args.data_root.expanduser().resolve()
        if args.command in {"campaign-preflight", "candidates", "inspect", "preview"}:
            preflight = ledger.preflight(args.campaign_id)
            if args.command == "campaign-preflight":
                result = preflight
            elif args.command == "candidates":
                result = dict(preflight)
                result["candidates"] = [
                    row for row in preflight["candidates"]
                    if (args.group is None or row["group"] == args.group)
                    and (args.matchday is None or row["matchday"] == args.matchday)
                    and (args.state is None or row["state"] == args.state)
                ]
            elif args.command == "inspect":
                result = {
                    "candidate": ledger.candidate(args.campaign_id, args.internal_id),
                    "events": ledger.candidate_events(args.campaign_id, args.internal_id),
                }
            else:
                events = ledger.candidate_events(args.campaign_id, args.internal_id)
                prepared = next((item for item in events if item["event_type"] == "DRAFT_PREPARED"), None)
                if prepared is None:
                    raise ScalableCampaignError("Aún no hay borrador preparado")
                result = json.loads((data_root / prepared["draft_path"]).read_text(encoding="utf-8"))
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        report = None
        proposals: list[dict[str, Any]] = []
        context: dict[str, Any] = {
            "data_root": data_root,
            "store_root": args.store_root,
            "published_root": args.published_root,
        }
        if args.command in {"status", "propose", "initialize", "authorize", "execute"}:
            report, proposals, context = _load_report(args)
        if args.command == "status":
            output = dict(report)
            rows = output.get("matches", [])
            filtered = [
                row for row in rows
                if (args.group is None or row["group"] == args.group)
                and (args.matchday_from is None or row["matchday"] >= args.matchday_from)
                and (args.matchday_to is None or row["matchday"] <= args.matchday_to)
                and (args.campaign_id is None or (row.get("campaign") or {}).get("campaign_id") == args.campaign_id)
                and (args.state is None or (row.get("campaign") or {}).get("state") == args.state or row["detail_status"] == args.state)
            ]
            output["filtered_count"] = len(filtered)
            output["filters"] = {
                "group": args.group,
                "matchday_from": args.matchday_from,
                "matchday_to": args.matchday_to,
                "campaign_id": args.campaign_id,
                "state": args.state,
            }
            if args.include_matches:
                output["matches"] = filtered
            else:
                output.pop("matches", None)
            print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "initialize":
            proposal = next((row for row in proposals if row.get("proposal_id") == args.proposal_id), None)
            if proposal is None:
                raise ScalableCampaignError("No se encontró una propuesta persistida con ese proposal_id")
            generation_root = data_root / "matches" / "generations" / proposal["source"]["generation_id"]
            result = ledger.initialize(
                proposal_dir=context["store_root"] / "campaign-proposals" / "plans" / args.proposal_id,
                generation_root=generation_root,
                data_root=data_root,
                published_ids=context["published_ids"],
                captured_ids=context["captured_ids"],
                blocked_ids=context["blocked_ids"],
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command in {"authorize", "execute"}:
            row = next((item for item in report["matches"] if item["internal_id"] == args.internal_id), None)
            if row is None:
                raise ScalableCampaignError("Partido no presente en el inventario de la generación seleccionada")
            shared = {
                "campaign_id": args.campaign_id,
                "internal_id": args.internal_id,
                "confirmed_url": args.confirm_url,
                "current_status": row,
                "published": args.internal_id in context["published_ids"],
                "captured": args.internal_id in context["captured_ids"],
                "blocked": args.internal_id in context["blocked_ids"],
            }
            if args.command == "authorize":
                result = {"status": "AUTHORIZED", "authorization_id": ledger.authorize(
                    **shared, operator=args.operator, confirmation=args.confirm_authorization, data_root=data_root
                )}
            else:
                inventory = ledger.source_inventory(args.campaign_id)
                result = ledger.execute_real(
                    **shared, authorization_id=args.authorization_id, data_root=data_root,
                    profile_dir=data_root / "browser-profiles" / f"match-detail-v2-{row['source_match_id']}",
                    confirmation=args.confirm_execution,
                    player_browser_idle_confirmation=args.player_browser_idle_confirmation,
                    store_root=args.store_root, store_inventory=inventory,
                )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command in {"validate", "revalidate-failed", "prepare", "approve", "publish", "verify", "complete-review"}:
            if args.command == "validate":
                result = ledger.validate_offline_artifact(
                    campaign_id=args.campaign_id, internal_id=args.internal_id, data_root=data_root
                )
            elif args.command == "revalidate-failed":
                result = ledger.revalidate_failed_artifact(
                    campaign_id=args.campaign_id,
                    internal_id=args.internal_id,
                    data_root=data_root,
                    operator=args.operator,
                    confirmation=args.confirm_revalidation,
                )
            elif args.command == "prepare":
                result = ledger.prepare_draft(
                    campaign_id=args.campaign_id, internal_id=args.internal_id, data_root=data_root,
                    generation_root=ledger.generation_root(args.campaign_id, data_root),
                    player_inventory_root=args.player_inventory_root,
                    player_compact_root=args.player_compact_root,
                    player_team_captures_root=args.player_team_captures_root,
                    player_published_index_path=args.player_published_index,
                )
            elif args.command == "approve":
                result = ledger.approve_draft(
                    campaign_id=args.campaign_id, internal_id=args.internal_id, draft_path=args.draft_path,
                    approved_by=args.approved_by, confirm_internal_id=args.confirm_internal_id,
                    confirm_source_html_sha256=args.confirm_source_html_sha256,
                    confirm_details_sha256=args.confirm_details_sha256, confirm_action=args.confirm_action,
                    data_root=data_root,
                )
            else:
                common = {
                    "data_root": data_root,
                    "generation_root": ledger.generation_root(args.campaign_id, data_root),
                    "published_root": args.published_root,
                    "store_root": args.store_root,
                    "player_inventory_root": args.player_inventory_root,
                    "player_compact_root": args.player_compact_root,
                    "player_team_captures_root": args.player_team_captures_root,
                    "player_published_index_path": args.player_published_index,
                }
                if args.command == "publish":
                    result = ledger.publish(campaign_id=args.campaign_id, internal_id=args.internal_id, **common)
                elif args.command == "verify":
                    result = ledger.verify_publication(campaign_id=args.campaign_id, internal_id=args.internal_id, **common)
                else:
                    result = ledger.complete_review(
                        campaign_id=args.campaign_id, internal_id=args.internal_id,
                        reviewer=args.reviewer, confirmation=args.confirm_review, **common,
                    )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        groups = ("I", "II") if args.groups == "both" else (args.groups,)
        if args.newly_played_only:
            incremental_ids = {
                item["internal_id"]
                for item in report["incremental_update"]["newly_played"]
                if item["detail_status"] == "played_pending_acquisition"
            }
            report = {
                **report,
                "matches": [row for row in report["matches"] if row["internal_id"] in incremental_ids],
            }
        plan = build_match_campaign_proposal(
            report,
            groups=groups,
            matchday_from=args.matchday_from,
            matchday_to=args.matchday_to,
            limit=args.limit,
        )
        result: dict[str, Any] = {
            "status": "PROPOSAL_READY_NOT_AUTHORIZED" if plan["candidate_count"] else "NO_ELIGIBLE_CANDIDATES",
            "proposal_id": plan["proposal_id"],
            "campaign_id": plan["campaign_id"],
            "source": plan["source"],
            "selection": plan["selection"],
            "candidate_count": plan["candidate_count"],
            "candidate_group_counts": {
                group: sum(item["group"] == group for item in plan["candidates"])
                for group in ("I", "II")
            },
            "coverage": {"counts": report["counts"], "by_group": report["by_group"]},
            "candidates": plan["candidates"],
            "authorization": plan["authorization"],
            "http_enabled": False,
            "browser_started": False,
            "navigation_enabled": False,
        }
        if args.persist and plan["candidate_count"]:
            target = write_match_campaign_proposal(
                context["store_root"] / "campaign-proposals", plan
            )
            result["persisted_to"] = str(target)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if plan["candidate_count"] else 2
    except (ScalableCampaignError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
