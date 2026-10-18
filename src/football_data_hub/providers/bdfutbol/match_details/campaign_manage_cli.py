"""Explicit, fail-closed commands for the MATCH-01C-D1 campaign workflow."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .campaign import (
    MatchCampaignError,
    MatchDetailCampaignLedger,
)
from .real_acquisition import (
    run_authorized_real_candidate,
)
from .review_completion import complete_published_discovery_review
from .sampling_plan import MatchSamplePlanError, build_offline_sample_plan

PLAYER_IDLE_CONFIRMATION = "PLAYER_BROWSER_IDLE_CONFIRMED"


def _parser() -> argparse.ArgumentParser:
    data_root = Path.home() / "FootballDataHub-data"
    generation_id = "match-00-4ad1d610507e425d"
    inventory_id = "match-detail-inventory-8cf339654c80c0ef"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=data_root)
    parser.add_argument(
        "--generation-root", type=Path,
        default=data_root / "matches/generations" / generation_id,
    )
    parser.add_argument(
        "--inventory-dir", type=Path,
        default=data_root / "matches/details/inventories" / inventory_id,
    )
    parser.add_argument("--store-root", type=Path, default=data_root / "matches/details")
    parser.add_argument(
        "--campaign-root", type=Path,
        default=data_root / "matches/details/campaigns",
    )
    parser.add_argument("--published-root", type=Path, default=data_root / "matches/details/published")
    parser.add_argument("--player-inventory-root", type=Path, default=data_root / "players/inventory-2026-27")
    parser.add_argument("--player-compact-root", type=Path, default=data_root / "players/compact-2026-27")
    parser.add_argument("--player-team-captures-root", type=Path, default=data_root / "team-captures")
    parser.add_argument(
        "--player-published-index", type=Path,
        default=data_root / "published/team_profiles_2026-27.json",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("preflight", help="Solo lectura; no crea ledger ni inicia navegador")

    close_review = commands.add_parser(
        "complete-review",
        help="Cierra una revisión solo tras verificar ledger, artefacto y publicación activa aprobada",
    )
    close_review.add_argument("--internal-id", required=True)
    close_review.add_argument("--reviewer", required=True)
    close_review.add_argument("--confirm-review-complete", required=True)

    review = commands.add_parser("review-legacy", help="Registra una decisión humana sobre 272582")
    review.add_argument("--reviewer", required=True)
    review.add_argument(
        "--decision", required=True,
        choices=("scope_to_original_pilot", "block_entire_campaign"),
    )
    review.add_argument("--confirm-historical-review", required=True)

    authorize = commands.add_parser("authorize", help="Autoriza un único candidato y URL")
    authorize.add_argument("--internal-id", required=True)
    authorize.add_argument("--reviewer", required=True)
    authorize.add_argument("--review-id", required=True)
    authorize.add_argument("--confirm-url", required=True)
    authorize.add_argument("--confirm-authorization", required=True)

    run = commands.add_parser("run", help="Ejecuta una navegación real ya autorizada")
    run.add_argument("--internal-id", required=True)
    run.add_argument("--authorization-id", required=True)
    run.add_argument("--confirm-url", required=True)
    run.add_argument("--profile-dir", type=Path, required=True)
    run.add_argument("--confirm-one-navigation", required=True)
    run.add_argument("--confirm-player-browser-idle", required=True)
    return parser


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    return build_offline_sample_plan(
        generation_root=args.generation_root,
        inventory_dir=args.inventory_dir,
        data_root=args.data_root,
        store_root=args.store_root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        plan = _plan(args)
        ledger = MatchDetailCampaignLedger(args.campaign_root)
        if args.command == "preflight":
            report = ledger.preflight(plan)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if report["status"] == "READY_FOR_FUTURE_HUMAN_AUTHORIZATION" else 2
        if args.command == "complete-review":
            result = complete_published_discovery_review(
                plan=plan,
                ledger=ledger,
                internal_id=args.internal_id,
                reviewer=args.reviewer,
                confirmation=args.confirm_review_complete,
                data_root=args.data_root,
                generation_root=args.generation_root,
                published_root=args.published_root,
                player_inventory_root=args.player_inventory_root,
                player_compact_root=args.player_compact_root,
                player_team_captures_root=args.player_team_captures_root,
                player_published_index_path=args.player_published_index,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result["status"] in {"REVIEW_COMPLETED", "REVIEW_ALREADY_COMPLETED"} else 2
        if args.command == "review-legacy":
            review_id = ledger.append_legacy_stop_review(
                plan,
                reviewer=args.reviewer,
                decision=args.decision,
                data_root=args.data_root,
                generation_root=args.generation_root,
                inventory_dir=args.inventory_dir,
                store_root=args.store_root,
                confirmation=args.confirm_historical_review,
            )
            print(json.dumps({"status": "REVIEW_RECORDED", "review_id": review_id}, indent=2))
            return 0
        if args.command == "authorize":
            authorization_id = ledger.authorize_candidate(
                plan,
                internal_id=args.internal_id,
                reviewer=args.reviewer,
                review_id=args.review_id,
                confirmed_url=args.confirm_url,
                data_root=args.data_root,
                generation_root=args.generation_root,
                inventory_dir=args.inventory_dir,
                store_root=args.store_root,
                confirmation=args.confirm_authorization,
            )
            print(json.dumps({"status": "AUTHORIZED", "authorization_id": authorization_id}, indent=2))
            return 0
        result = run_authorized_real_candidate(
            plan=plan,
            ledger=ledger,
            internal_id=args.internal_id,
            authorization_id=args.authorization_id,
            confirmed_url=args.confirm_url,
            data_root=args.data_root,
            generation_root=args.generation_root,
            inventory_dir=args.inventory_dir,
            store_root=args.store_root,
            profile_dir=args.profile_dir,
            confirmation=args.confirm_one_navigation,
            player_browser_idle_confirmation=args.confirm_player_browser_idle,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.status == "DISCOVERY_REVIEW_REQUIRED" else 2
    except (MatchCampaignError, MatchSamplePlanError, OSError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
