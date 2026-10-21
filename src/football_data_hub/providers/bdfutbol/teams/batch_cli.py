"""Controlled, offline-plannable and resumable one-team-at-a-time acquisition."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from football_data_hub.core.browser_runtime import BrowserRuntimeError
from football_data_hub.core.browser_session import BrowserSessionError
from football_data_hub.providers.bdfutbol.access import AccessStatus
from football_data_hub.providers.bdfutbol.context import SUPPORTED_SEASON, get_competition_context

from .acquisition import (
    DEFAULT_VIEWS,
    FOLLOW_STATES,
    StaleMatchCatalogError,
    TeamAcquisitionStopped,
    acquire_team_profile,
    create_team_capture_id,
)
from .batch import (
    BatchAccessDenied,
    BatchLocalFailure,
    BatchStop,
    BatchTeamOutcome,
    inspect_team_captures,
    run_team_batch,
    write_batch_manifest,
)
from .capture_store import CaptureInspection, inspect_team_capture
from .catalog import load_team_catalog
from .export import CAPTURE_POLICY_ID, export_team_capture
from .cli import _DEFAULT_MATCH_CATALOGS, _reuse_capture_seed
from .evidence_store import TeamEvidenceCheckpoint, find_pending_evidence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=(SUPPORTED_SEASON,), default=SUPPORTED_SEASON)
    parser.add_argument("--groups", choices=("I", "II", "both"), default="both")
    parser.add_argument("--team-id", type=int, action="append", dest="team_ids")
    parser.add_argument("--limit", type=int, help="Limita el número de equipos seleccionados para un piloto.")
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=5.0,
        help="Pausa entre páginas y equipos adquiridos; los pilotos reales deben respetar al menos 5 s.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Inspecciona el inventario y muestra el plan sin abrir navegador.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="No reutiliza capturas completas, parciales ni checkpoints: adquiere de nuevo el equipo solicitado.",
    )
    parser.add_argument("--view", action="append", choices=tuple(DEFAULT_VIEWS))
    parser.add_argument(
        "--refresh-view",
        action="append",
        choices=tuple(DEFAULT_VIEWS),
        help=(
            "Vuelve a adquirir una vista seleccionada aunque exista en la captura semilla; "
            "las demás vistas verificadas se reutilizan."
        ),
    )
    parser.add_argument("--group1-catalog", type=Path)
    parser.add_argument("--group2-catalog", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("FDH_TEAM_CAPTURE_ROOT", "data/exports/bdfutbol/teams")),
    )
    parser.add_argument(
        "--allow-repository-storage",
        action="store_true",
        help="Permite explícitamente guardar capturas bajo el checkout Git (solo desarrollo controlado).",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get("FDH_BDFUTBOL_PROFILE", str(Path.home() / ".football-data-hub-chromium-pure-cdp"))),
    )
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--startup-timeout-seconds", type=float, default=35.0)
    parser.add_argument("--navigation-timeout-ms", type=int, default=45_000)
    parser.add_argument("--no-xvfb", action="store_false", dest="use_xvfb")
    parser.set_defaults(use_xvfb=True)
    return parser.parse_args(argv)


def _catalog_path(args: argparse.Namespace, group: int) -> Path:
    supplied = args.group1_catalog if group == 1 else args.group2_catalog
    if supplied:
        return supplied
    env = os.environ.get(f"FDH_BDFUTBOL_GROUP{group}_MATCHES") or os.environ.get(f"FDH_GROUP{group}_MATCHES")
    return Path(env).expanduser() if env else _DEFAULT_MATCH_CATALOGS[group]


def _assessment_key(assessment: CaptureInspection | None) -> tuple[Any, ...]:
    if assessment is None:
        return (False, 0, 0, 0, "")
    created = str(
        assessment.metadata.get("created_at_utc")
        or assessment.metadata.get("captured_at_utc")
        or assessment.capture_id
    )
    return (*assessment.coverage_score, created, assessment.capture_id)


def _storage_preflight(root: Path) -> dict[str, Any]:
    """Report space and permissions without creating or changing the root."""
    candidate = root.expanduser()
    probe = candidate
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    permission_target = candidate if candidate.exists() else probe
    return {
        "configured_root": str(candidate),
        "resolved_root": str(candidate.resolve()),
        "root_exists": candidate.exists(),
        "permission_check_path": str(permission_target),
        "readable": os.access(permission_target, os.R_OK),
        "writable": os.access(permission_target, os.W_OK),
        "available_bytes": usage.free,
        "probe_note": "No se creó ni modificó ningún archivo para esta comprobación.",
    }


def _is_inside_repository(path: Path) -> bool:
    repository_root = Path(__file__).resolve().parents[5]
    try:
        path.expanduser().resolve().relative_to(repository_root)
        return True
    except ValueError:
        return False


def _inspect_best(
    output_root: Path,
    *,
    season: str,
    group: int,
    record: dict[str, Any],
    context,
    reference: dict[str, Any],
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    required_views: tuple[str, ...],
) -> CaptureInspection | None:
    candidates = inspect_team_captures(
        output_root,
        season=season,
        team_catalog_record=record,
        competition=context,
        team_catalog_reference=reference,
        group_team_catalog=teams,
        known_matches=matches,
        required_views=required_views,
    )
    usable = [candidate for candidate in candidates if candidate.reusable_as_seed]
    return max(usable, key=_assessment_key) if usable else None


def _team_plan(
    *,
    record: dict[str, Any],
    group: int,
    views: tuple[str, ...],
    assessment: CaptureInspection | None,
    catalog_reference: dict[str, Any],
    pending_evidence=None,
    refresh_views: tuple[str, ...] = (),
) -> dict[str, Any]:
    valid_views = set(assessment.valid_views if assessment else ())
    valid_states = set(assessment.valid_follow_states if assessment else ())
    if pending_evidence is not None:
        valid_views.update(pending_evidence.valid_views)
        valid_states.update(pending_evidence.valid_follow_states)
    missing_views = [view for view in views if view not in valid_views]
    if "alignment" not in valid_views and "alignment" not in missing_views:
        missing_views.insert(0, "alignment")
    required_states = FOLLOW_STATES if "follow" in views else ()
    missing_states = [state for state in required_states if state not in valid_states]
    visit_views = list(missing_views)
    if missing_states and "follow" not in visit_views:
        visit_views.append("follow")
    already_complete = bool(assessment and assessment.complete_for_current_policy)
    views_to_refresh = [view for view in views if view in refresh_views]
    if already_complete:
        visit_views = list(views_to_refresh)
        missing_states = []
        missing_views = []
    elif views_to_refresh:
        visit_views = list(dict.fromkeys((*views_to_refresh, *visit_views)))
    return {
        "group": "I" if group == 1 else "II",
        "team_id": int(record["team_id"]),
        "team_name": str(record.get("name") or record.get("team_name") or ""),
        "action": "refresh_selected_views" if already_complete and views_to_refresh else "skip_complete" if already_complete else (
            "recover_offline" if pending_evidence and not visit_views else
            "resume_pending" if pending_evidence else "acquire_or_rebuild"
        ),
        "capture": assessment.manifest_summary() if assessment else None,
        "pending_evidence": ({
            "capture_id": pending_evidence.capture_id,
            "path": str(pending_evidence.path),
            "valid_views": list(pending_evidence.valid_views),
            "valid_follow_states": list(pending_evidence.valid_follow_states),
            "warnings": list(pending_evidence.warnings),
        } if pending_evidence else None),
        "requested_views": list(views),
        "missing_views": missing_views,
        "missing_follow_states": missing_states,
        "planned_page_visits": visit_views,
        "follow_state_transitions": (
            len(FOLLOW_STATES) if "follow" in views_to_refresh else len(missing_states)
        ),
        "planned_navigation_count": len(visit_views),
        "catalog_reference": catalog_reference,
    }


def select_team_records(
    team_records_by_group: dict[int, list[dict[str, Any]]],
    *,
    groups: tuple[int, ...],
    team_ids: list[int] | None = None,
    limit: int | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Validate requested IDs against the selected catalogs and apply a global limit."""
    if limit is not None and limit < 1:
        raise ValueError("--limit debe ser mayor que cero")
    selected = {group: list(team_records_by_group.get(group, ())) for group in groups}
    if team_ids:
        if len(team_ids) != len(set(team_ids)):
            raise ValueError("--team-id no puede repetirse")
        available_ids = {
            int(record["team_id"])
            for records in selected.values()
            for record in records
        }
        invalid_ids = sorted(set(team_ids) - available_ids)
        if invalid_ids:
            raise ValueError(
                f"IDs no pertenecen a los grupos seleccionados y sus catálogos: {invalid_ids}"
            )
        selected_ids = set(team_ids)
        selected = {
            group: [record for record in records if int(record["team_id"]) in selected_ids]
            for group, records in selected.items()
        }
    if limit is not None:
        remaining = limit
        limited: dict[int, list[dict[str, Any]]] = {}
        for group, records in selected.items():
            limited[group] = records[:remaining]
            remaining -= len(limited[group])
        selected = limited
    return selected


def covers_full_catalog_scope(
    selected_by_group: dict[int, list[dict[str, Any]]],
    catalog_by_group: dict[int, list[dict[str, Any]]],
    *,
    groups: tuple[int, ...],
) -> bool:
    selected = {
        (group, int(record["team_id"]))
        for group in groups
        for record in selected_by_group.get(group, [])
    }
    catalog = {
        (group, int(record["team_id"]))
        for group in groups
        for record in catalog_by_group.get(group, [])
    }
    return bool(catalog) and selected == catalog


def is_complete_batch(
    *,
    full_catalog_scope: bool,
    groups: tuple[int, ...],
    entries: list[dict[str, Any]],
) -> bool:
    return bool(
        full_catalog_scope
        and set(groups) == {1, 2}
        and entries
        and all(entry.get("status") == "complete" for entry in entries)
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not math.isfinite(args.pause_seconds) or args.pause_seconds < 0:
        raise ValueError("--pause-seconds debe ser un número finito no negativo")

    groups = (1, 2) if args.groups == "both" else ((1,) if args.groups == "I" else (2,))
    selected_views = tuple(dict.fromkeys(args.view)) if args.view else DEFAULT_VIEWS
    refresh_views = tuple(dict.fromkeys(args.refresh_view or ()))
    if not set(refresh_views).issubset(selected_views):
        raise ValueError("Cada --refresh-view debe aparecer también entre las vistas seleccionadas con --view.")
    output_root = args.output_root.expanduser()
    if not args.dry_run and _is_inside_repository(output_root) and not args.allow_repository_storage:
        raise ValueError(
            "La adquisición real requiere almacenamiento externo al checkout; "
            "use FDH_TEAM_CAPTURE_ROOT/--output-root o confirme desarrollo con --allow-repository-storage."
        )
    team_records: dict[int, list[dict[str, Any]]] = {}
    matches_by_group: dict[int, list[dict[str, Any]]] = {}
    references: dict[int, dict[str, Any]] = {}
    contexts = {}
    for group in groups:
        contexts[group] = get_competition_context(args.season, group)
        team_records[group], matches_by_group[group], references[group] = load_team_catalog(
            _catalog_path(args, group), competition=contexts[group]
        )
    catalog_teams_by_group = {group: list(records) for group, records in team_records.items()}

    team_records = select_team_records(
        team_records,
        groups=groups,
        team_ids=args.team_ids,
        limit=args.limit,
    )

    inspections: dict[tuple[int, int], CaptureInspection | None] = {}
    pending_by_team = {}
    plans: list[dict[str, Any]] = []
    for group in groups:
        for record in team_records[group]:
            inspection = _inspect_best(
                output_root,
                season=args.season,
                group=group,
                record=record,
                context=contexts[group],
                reference=references[group],
                teams=catalog_teams_by_group[group],
                matches=matches_by_group[group],
                required_views=selected_views,
            )
            if args.force_refresh:
                inspection = None
            inspections[(group, int(record["team_id"]))] = inspection
            pending = None
            if not args.force_refresh and not (inspection and inspection.complete_for_current_policy):
                pending = find_pending_evidence(
                    output_root,
                    season=args.season,
                    group="I" if group == 1 else "II",
                    team_record=record,
                )
            pending_by_team[(group, int(record["team_id"]))] = pending
            plans.append(_team_plan(
                record=record,
                group=group,
                views=selected_views,
                assessment=inspection,
                pending_evidence=pending,
                catalog_reference=references[group],
                refresh_views=refresh_views,
            ))

    if args.dry_run:
        full_catalog_scope = covers_full_catalog_scope(
            team_records,
            catalog_teams_by_group,
            groups=groups,
        )
        print(json.dumps({
            "mode": "dry_run",
            "season": args.season,
            "groups": ["I" if group == 1 else "II" for group in groups],
            "requested_views": list(selected_views),
            "required_follow_states": list(FOLLOW_STATES) if "follow" in selected_views else [],
            "pause_seconds": args.pause_seconds,
            "browser_started": False,
            "teams_selected": len(plans),
            "catalog_team_count": sum(len(catalog_teams_by_group[group]) for group in groups),
            "full_catalog_scope": full_catalog_scope,
            "planned_navigation_count": sum(item["planned_navigation_count"] for item in plans),
            "storage": _storage_preflight(output_root),
            "teams": plans,
        }, ensure_ascii=False, indent=2))
        return 0

    def complete(group: int, team_id: int, _views: tuple[str, ...]) -> CaptureInspection | None:
        if args.force_refresh or refresh_views:
            return None
        item = inspections.get((group, team_id))
        return item if item and item.complete_for_current_policy else None

    def partial(group: int, team_id: int) -> CaptureInspection | None:
        if args.force_refresh:
            return None
        item = inspections.get((group, team_id))
        return item if item and item.reusable_as_seed else None

    def process(group: int, record: dict[str, Any], views: tuple[str, ...]) -> BatchTeamOutcome:
        context = contexts[group]
        team_id = int(record["team_id"])
        inspection = inspections.get((group, team_id))
        seed = None
        if inspection and inspection.reusable_as_seed:
            seed = _reuse_capture_seed(
                inspection.path,
                team_catalog_record=record,
                competition=context,
                team_catalog_reference=references[group],
                group_team_catalog=catalog_teams_by_group[group],
                known_matches=matches_by_group[group],
            )
        pending = pending_by_team.get((group, team_id))
        if pending is not None:
            pending_seed = pending.seed
            if seed is None:
                seed = pending_seed
            else:
                for key in ("raw_views", "access_by_view", "view_urls", "page_titles"):
                    seed.setdefault(key, {})
                    for name, value in pending_seed.get(key, {}).items():
                        seed[key].setdefault(name, value)
                for key in ("follow_state_html", "follow_state_diagnostics"):
                    seed.setdefault(key, {})
                    for name, value in pending_seed.get(key, {}).items():
                        seed[key].setdefault(name, value)
                seed["seed_capture_ids"] = tuple(dict.fromkeys((
                    *seed.get("seed_capture_ids", ()),
                    pending.capture_id,
                )))
                seed["pending_capture_id"] = pending.capture_id
        checkpoint = TeamEvidenceCheckpoint(
            output_root,
            season=args.season,
            group="I" if group == 1 else "II",
            team_record=record,
            catalog_reference=references[group],
            requested_views=views,
            capture_id=(pending.capture_id if pending else create_team_capture_id()),
            resume_path=(pending.path if pending else None),
        )

        def record_failure(kind: str, message: str) -> None:
            try:
                checkpoint.record_failure(kind=kind, message=message)
            except OSError as exc:
                raise BatchStop(
                    f"No se pudo preservar el checkpoint tras {kind}: {type(exc).__name__}: {exc}",
                    kind="storage_error",
                    capture_id=checkpoint.capture_id,
                ) from exc

        acquired_views_needed = tuple(
            view for view in views
            if seed is None or view not in seed["raw_views"] or view in refresh_views
        )
        if seed is None and "alignment" not in acquired_views_needed:
            acquired_views_needed = ("alignment", *acquired_views_needed)

        try:
            bundle = acquire_team_profile(
                team_catalog_record=record,
                team_catalog_reference=references[group],
                group_team_catalog=catalog_teams_by_group[group],
                known_matches=matches_by_group[group],
                competition=context,
                profile_dir=args.profile,
                requested_views=acquired_views_needed,
                browser="chromium",
                browser_executable_path=args.browser_executable,
                startup_timeout_seconds=args.startup_timeout_seconds,
                navigation_timeout_ms=args.navigation_timeout_ms,
                use_xvfb=args.use_xvfb,
                seed_raw_views=(seed or {}).get("raw_views"),
                seed_access_by_view=(seed or {}).get("access_by_view"),
                seed_view_urls=(seed or {}).get("view_urls"),
                seed_page_titles=(seed or {}).get("page_titles"),
                seed_browser=(seed or {}).get("browser"),
                seed_capture_id=(seed or {}).get("capture_id"),
                seed_follow_state_html=(seed or {}).get("follow_state_html"),
                seed_follow_state_diagnostics=(seed or {}).get("follow_state_diagnostics"),
                seed_capture_ids=(seed or {}).get("seed_capture_ids", ()),
                refresh_follow_states="follow" in refresh_views,
                capture_id=checkpoint.capture_id,
                require_follow_states=("follow" in views),
                navigation_pause_seconds=args.pause_seconds,
                evidence_checkpoint=checkpoint,
            )
        except TeamAcquisitionStopped as exc:
            record_failure(kind="access_denied", message=str(exc))
            if exc.assessment.status is AccessStatus.CHALLENGE_REQUIRED:
                raise BatchAccessDenied(str(exc), kind="challenge_required", capture_id=checkpoint.capture_id) from exc
            if exc.assessment.status is AccessStatus.HTTP_ERROR:
                kind = "http_denial" if exc.assessment.http_status in {401, 403, 407, 429} else "http_error"
                raise BatchStop(str(exc), kind=kind, capture_id=checkpoint.capture_id) from exc
            if exc.assessment.status is AccessStatus.NAVIGATION_ERROR:
                raise BatchStop(str(exc), kind="navigation_error", capture_id=checkpoint.capture_id) from exc
            raise
        except (BrowserRuntimeError, BrowserSessionError) as exc:
            record_failure(kind="browser_environment_error", message=f"{type(exc).__name__}: {exc}")
            raise BatchStop(f"{type(exc).__name__}: {exc}", kind="browser_environment_error", capture_id=checkpoint.capture_id) from exc
        except StaleMatchCatalogError as exc:
            record_failure(kind="stale_match_catalog", message=str(exc))
            raise BatchStop(str(exc), kind="stale_match_catalog", capture_id=checkpoint.capture_id) from exc
        except OSError as exc:
            record_failure(kind="storage_error", message=f"{type(exc).__name__}: {exc}")
            raise BatchStop(f"{type(exc).__name__}: {exc}", kind="storage_error", capture_id=checkpoint.capture_id) from exc
        except Exception as exc:
            record_failure(kind="parse_failed", message=f"{type(exc).__name__}: {exc}")
            raise BatchLocalFailure(
                f"{type(exc).__name__}: {exc}",
                capture_id=checkpoint.capture_id,
            ) from exc

        if pending is not None and not bundle.acquired_views:
            bundle = replace(bundle, derivation={
                "mode": "offline_checkpoint_recovery",
                "recovered_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_checkpoint_id": pending.capture_id,
                "source_catalog_reference": pending.manifest.get("related_team_catalog"),
                "active_catalog_reference": references[group],
                "network_navigations": 0,
            })

        try:
            paths = export_team_capture(
                output_root,
                bundle,
                profile_dir=args.profile,
                capture_timestamp_basis=(
                    "per-view browser navigation time; inherited views and Follow states retain their source provenance"
                    if bundle.acquired_views
                    else "offline re-normalization; inherited source timestamps retained"
                ),
            )
        except OSError as exc:
            record_failure(kind="storage_error", message=f"{type(exc).__name__}: {exc}")
            raise BatchStop(f"{type(exc).__name__}: {exc}", kind="storage_error", capture_id=checkpoint.capture_id) from exc

        try:
            published = inspect_team_capture(
                paths["run_directory"],
                team_catalog_record=record,
                competition=context,
                team_catalog_reference=references[group],
                group_team_catalog=catalog_teams_by_group[group],
                known_matches=matches_by_group[group],
            )
            if not published.complete_for_current_policy:
                raise ValueError(
                    "La captura exportada no pasó la inspección posterior a publicación: "
                    + "; ".join(published.reasons)
                )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            record_failure(kind="published_capture_verification_failed", message=message)
            raise BatchLocalFailure(message, capture_id=checkpoint.capture_id) from exc

        checkpoint.mark_complete_and_remove_checkpoint(paths["run_directory"])

        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        acquired_states = tuple(
            state
            for state, diagnostic in bundle.follow_state_diagnostics.items()
            if not diagnostic.get("reused")
        )
        reused_states = tuple(
            state
            for state, diagnostic in bundle.follow_state_diagnostics.items()
            if diagnostic.get("reused")
        )
        return BatchTeamOutcome(
            capture_id=bundle.capture_id,
            views=bundle.requested_views,
            valid=bool(bundle.validation.get("valid")) and paths["run_directory"].is_dir(),
            acquired_views=bundle.acquired_views,
            reused_views=tuple(view for view in bundle.requested_views if view not in bundle.acquired_views),
            follow_states=bundle.parsed.follow_states_captured,
            acquired_follow_states=acquired_states,
            reused_follow_states=reused_states,
            catalog_reference=references[group],
            captured_at_utc=bundle.captured_at_utc,
            acquisition_timestamps={
                "views": {
                    view: item.get("captured_at_utc")
                    for view, item in metadata.get("source_snapshots", {}).items()
                },
                "follow_states": {
                    state: item.get("captured_at_utc")
                    for state, item in metadata.get("follow_states", {}).items()
                },
            },
        )

    manifest = run_team_batch(
        teams_by_group=team_records,
        groups=groups,
        requested_views=selected_views,
        find_complete_capture=complete,
        find_partial_capture=partial,
        process_team=process,
        catalog_references_by_group=references,
        pause_seconds=args.pause_seconds,
    )
    manifest["season"] = args.season
    manifest["source"] = "BDFutbol"
    full_catalog_scope = covers_full_catalog_scope(
        team_records,
        catalog_teams_by_group,
        groups=groups,
    )
    manifest["batch_scope"] = {
        "groups": ["I" if group == 1 else "II" for group in groups],
        "selected_team_count": len(manifest["teams"]),
        "catalog_team_count": sum(len(catalog_teams_by_group[group]) for group in groups),
        "full_catalog_scope": full_catalog_scope,
    }
    manifest["batch_complete"] = is_complete_batch(
        full_catalog_scope=full_catalog_scope and not manifest["stop_reason"],
        groups=groups,
        entries=manifest["teams"],
    )
    manifest["capture_policy"] = {
        "id": CAPTURE_POLICY_ID,
        "required_follow_states": list(FOLLOW_STATES) if "follow" in selected_views else [],
    }
    manifest_path = write_batch_manifest(output_root / args.season, manifest)
    print(json.dumps({
        "manifest": str(manifest_path),
        "summary": manifest["summary"],
        "stopped_on_access_denial": manifest["stopped_on_access_denial"],
    }, ensure_ascii=False, indent=2))
    selected_complete = bool(manifest["teams"]) and all(
        entry.get("status") == "complete" for entry in manifest["teams"]
    )
    return 0 if selected_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
