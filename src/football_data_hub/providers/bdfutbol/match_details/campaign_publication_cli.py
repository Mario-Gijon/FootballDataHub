"""Explicit inspect, validate, prepare, approve and publish commands for MATCH-03."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from football_data_hub_api.match_details_dataset import (
    CAMPAIGN_DRAFT_SCHEMA,
    MatchDetailsLoadError,
    build_campaign_approval_receipt,
    build_campaign_publication_draft,
    campaign_approval_confirmation,
    load_published_match_details,
    publish_campaign_match_detail_draft,
    write_immutable_publication_json,
)
from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import load_player_directory

DEFAULT_GENERATION = "match-00-4ad1d610507e425d"


def _default_data_root() -> Path:
    return Path(os.getenv("FDH_LOCAL_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()


def _path_from_env(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser()


def _parser() -> argparse.ArgumentParser:
    data_root = _default_data_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=data_root)
    parser.add_argument(
        "--generation-root", type=Path,
        default=data_root / "matches/generations" / DEFAULT_GENERATION,
    )
    parser.add_argument("--store-root", type=Path, default=data_root / "matches/details")
    parser.add_argument(
        "--published-root", type=Path,
        default=data_root / "matches/details/published",
    )
    parser.add_argument(
        "--player-inventory-root", type=Path,
        default=_path_from_env("FDH_PLAYER_INVENTORY_ROOT", data_root / "players/inventory-2026-27"),
    )
    parser.add_argument(
        "--player-compact-root", type=Path,
        default=_path_from_env("FDH_PLAYER_COMPACT_ROOT", data_root / "players/compact-2026-27"),
    )
    parser.add_argument(
        "--player-team-captures-root", type=Path,
        default=_path_from_env("FDH_PLAYER_TEAM_CAPTURES_ROOT", data_root / "team-captures"),
    )
    parser.add_argument(
        "--team-profiles-index", type=Path,
        default=_path_from_env("FDH_PLAYER_PUBLISHED_INDEX", data_root / "published/team_profiles_2026-27.json"),
    )

    commands = parser.add_subparsers(dest="command")
    for command in ("inspect", "validate", "prepare"):
        item = commands.add_parser(command, help=f"{command.capitalize()} un candidato; no publica")
        item.add_argument("--internal-id", required=True)
        item.add_argument("--campaign-id", required=True)
        item.add_argument("--artifact-id", required=True)
        item.add_argument("--publication-id")
        if command == "prepare":
            item.add_argument("--output", type=Path, required=True)

    preview = commands.add_parser("preview", help="Imprime un borrador tras revalidar su fuente")
    preview.add_argument("--draft", type=Path, required=True)

    approve = commands.add_parser("approve", help="Registra aprobación humana de un documento exacto")
    approve.add_argument("--draft", type=Path, required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--confirm-internal-id", required=True)
    approve.add_argument("--confirm-source-html-sha256", required=True)
    approve.add_argument("--confirm-details-sha256", required=True)
    approve.add_argument("--confirm-action", required=True)
    approve.add_argument("--output", type=Path, required=True)

    publish = commands.add_parser("publish", help="Publica solo un borrador y recibo aprobados")
    publish.add_argument("--draft", type=Path, required=True)
    publish.add_argument("--approval", type=Path, required=True)

    verify = commands.add_parser("verify", help="Verifica la publicación activa de un partido")
    verify.add_argument("--internal-id", required=True)
    return parser


def _load_json_object(path: Path) -> dict[str, Any]:
    candidate = path.expanduser().absolute()
    cursor = candidate
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MatchDetailsLoadError(f"El registro de entrada contiene un symlink: {cursor}")
        cursor = cursor.parent
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchDetailsLoadError(f"No se puede leer el registro JSON: {candidate}") from exc
    if not isinstance(value, dict):
        raise MatchDetailsLoadError("El registro de entrada debe ser un objeto JSON.")
    return value


def _runtime(args: argparse.Namespace):
    data_root = args.data_root.expanduser().resolve(strict=True)
    generation_root = args.generation_root.expanduser().resolve(strict=True)
    bundle = load_match_results_dataset(generation_root, data_root=data_root)
    player_directory = load_player_directory(
        inventory_root=args.player_inventory_root,
        compact_root=args.player_compact_root,
        team_captures_root=args.player_team_captures_root,
        published_index_path=args.team_profiles_index,
    )
    return data_root, generation_root, bundle, set(player_directory.players_by_id)


def _draft(args: argparse.Namespace) -> tuple[dict[str, Any], tuple[Path, Path, Any, set[int]]]:
    context = _runtime(args)
    data_root, generation_root, bundle, player_ids = context
    draft = build_campaign_publication_draft(
        internal_id=args.internal_id,
        campaign_id=args.campaign_id,
        artifact_id=args.artifact_id,
        publication_id=getattr(args, "publication_id", None),
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=bundle,
        player_ids=player_ids,
    )
    return draft, context


def _revalidate_draft(path: Path, args: argparse.Namespace):
    draft = _load_json_object(path)
    if draft.get("schema_version") != CAMPAIGN_DRAFT_SCHEMA:
        raise MatchDetailsLoadError("El archivo no es un borrador MATCH-03.")
    context = _runtime(args)
    data_root, generation_root, bundle, player_ids = context
    expected = build_campaign_publication_draft(
        internal_id=str(draft.get("internal_id", "")),
        campaign_id=str(draft.get("campaign_id", "")),
        artifact_id=str(draft.get("artifact_id", "")),
        publication_id=str(draft.get("publication_id", "")),
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=bundle,
        player_ids=player_ids,
    )
    if draft != expected:
        raise MatchDetailsLoadError("El borrador no coincide con la evidencia fuente actual.")
    return draft, context


def _summary(draft: dict[str, Any]) -> dict[str, Any]:
    details = draft["details"]
    return {
        "status": "VALIDATED_NOT_PUBLISHED",
        "internal_id": draft["internal_id"],
        "source_match_id": draft["source_match_id"],
        "season": draft["season"],
        "competition": draft["competition"],
        "group": draft["group"],
        "matchday": draft["matchday"],
        "campaign_id": draft["campaign_id"],
        "artifact_id": draft["artifact_id"],
        "navigation_attempt_id": draft["navigation_attempt_id"],
        "access_status": draft["access_status"],
        "semantic_valid": draft["semantic_valid"],
        "promotion_eligible": draft["promotion_eligible"],
        "capture_promotion_enabled": draft["capture_promotion_enabled"],
        "source_html_sha256": draft["source_html_sha256"],
        "details_sha256": draft["details_sha256"],
        "teams": [details["home_team_id"], details["away_team_id"]],
        "team_names": [draft["home_team_name"], draft["away_team_name"]],
        "score": [details["home_goals"], details["away_goals"]],
        "match_date": details["match_date"],
        "starters": [len(details["home"]["starters"] or []), len(details["away"]["starters"] or [])],
        "substitutes": [len(details["home"]["substitutes"] or []), len(details["away"]["substitutes"] or [])],
        "events": len(details["events"] or []),
        "approval_confirmation": campaign_approval_confirmation(draft),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command in {"inspect", "validate", "prepare"}:
            draft, _ = _draft(args)
            if args.command == "prepare":
                output = write_immutable_publication_json(args.output, draft)
                result = {**_summary(draft), "draft_path": str(output)}
            else:
                result = _summary(draft)
                if args.command == "inspect":
                    result["read_only"] = True
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command == "preview":
            draft, _ = _revalidate_draft(args.draft, args)
            print(json.dumps(draft["details"], ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command == "approve":
            draft, _ = _revalidate_draft(args.draft, args)
            receipt = build_campaign_approval_receipt(
                draft,
                approved_by=args.approved_by,
                confirm_internal_id=args.confirm_internal_id,
                confirm_source_html_sha256=args.confirm_source_html_sha256,
                confirm_details_sha256=args.confirm_details_sha256,
                confirm_action=args.confirm_action,
            )
            path = write_immutable_publication_json(args.output, receipt)
            print(json.dumps({"status": "APPROVAL_RECORDED", "approval_path": str(path)}, indent=2))
            return 0

        if args.command == "publish":
            draft, context = _revalidate_draft(args.draft, args)
            approval = _load_json_object(args.approval)
            data_root, generation_root, bundle, player_ids = context
            result = publish_campaign_match_detail_draft(
                draft,
                approval_receipt=approval,
                published_root=args.published_root,
                store_root=args.store_root,
                generation_root=generation_root,
                data_root=data_root,
                match_bundle=bundle,
                player_ids=player_ids,
            )
            print(json.dumps({"status": "PUBLISHED", **result}, indent=2))
            return 0

        if args.command == "verify":
            data_root, generation_root, bundle, player_ids = _runtime(args)
            loaded = load_published_match_details(
                args.published_root,
                store_root=args.store_root,
                generation_root=generation_root,
                data_root=data_root,
                match_bundle=bundle,
                player_ids=player_ids,
            )
            document = loaded.get(args.internal_id)
            if document is None:
                print(json.dumps({"status": "NOT_PUBLISHED", "internal_id": args.internal_id}, indent=2))
                return 2
            print(json.dumps({
                "status": "VERIFIED",
                "internal_id": args.internal_id,
                "publication_status": document.publication_status,
                "source_html_sha256": document.source_html_sha256,
            }, indent=2))
            return 0
    except (MatchDetailsLoadError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
