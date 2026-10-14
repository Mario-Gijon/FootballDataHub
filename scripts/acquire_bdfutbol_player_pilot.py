"""Acquire the explicitly selected BDFutbol player views as raw snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.acquisition import (
    PLAYER_VIEWS,
    PlayerAcquisitionStopped,
    acquire_player_match_variant,
    acquire_player_views,
    load_inventory_players,
    player_match_variant_url,
    player_view_url,
)
from football_data_hub.providers.bdfutbol.players.catalog import build_player_acquisition_progress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-id", type=int, action="append", required=True)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_INVENTORY",
            str(Path.home() / "FootballDataHub-data/players/inventory-2026-27/players.json"),
        )),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_CAPTURE_ROOT",
            str(Path.home() / "FootballDataHub-data/players/player-captures"),
        )),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get(
            "FDH_BDFUTBOL_PROFILE",
            str(Path.home() / ".football-data-hub-chromium-pure-cdp"),
        )),
    )
    parser.add_argument("--browser-executable", type=Path, default=Path("/usr/bin/chromium"))
    parser.add_argument("--capture-id", help="Resume an existing capture directory")
    parser.add_argument("--view", action="append", choices=PLAYER_VIEWS)
    parser.add_argument(
        "--match-url-filter",
        help="Captura una variante de URL de Partidos, por ejemplo cat=1rf",
    )
    parser.add_argument("--revisit-existing", action="store_true")
    parser.add_argument("--pause-seconds", type=float, default=5.0)
    parser.add_argument("--settle-ms", type=int, default=900)
    parser.add_argument("--no-filter-exploration", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--progress-output", type=Path)
    args = parser.parse_args(argv)
    try:
        players = load_inventory_players(args.inventory, args.player_id)
        views = tuple(args.view or PLAYER_VIEWS)
        if args.match_url_filter:
            if len(args.player_id) != 1 or args.view not in (None, ["matches"]):
                parser.error("--match-url-filter requiere un jugador y la vista matches")
            if args.revisit_existing:
                parser.error("--match-url-filter no admite --revisit-existing")
            key, separator, value = args.match_url_filter.partition("=")
            if not separator:
                parser.error("--match-url-filter requiere el formato clave=valor")
            filters = {key: value}
            urls = [{
                "player_id": args.player_id[0],
                "view": "matches",
                "snapshot_kind": "URL_VARIANT",
                "filter_parameters": filters,
                "url": player_match_variant_url(args.player_id[0], filters),
            }]
            planned_visits = 1
        else:
            if args.revisit_existing and (len(args.player_id) != 1 or len(views) != 1 or not args.capture_id):
                parser.error("--revisit-existing requiere capture_id, un jugador y una sola vista")
            urls = [
                {"player_id": player_id, "view": view, "url": player_view_url(player_id, view)}
                for player_id in args.player_id
                for view in views
            ]
            planned_visits = len(urls)
            filters = None
        plan = {
            "player_ids": args.player_id,
            "players": [
                {"player_id": player_id, "display_name": players[player_id].get("display_name")}
                for player_id in args.player_id
            ],
            "base_view_navigations": planned_visits if filters is None else 0,
            "url_variant_navigations": planned_visits if filters is not None else 0,
            "urls": urls,
            "inventory": str(args.inventory.expanduser().resolve()),
            "output_root": str(args.output_root.expanduser().resolve()),
            "profile": str(args.profile.expanduser().resolve()),
            "filter_exploration": not args.no_filter_exploration,
            "dry_run": args.dry_run,
        }
        if args.dry_run:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if filters is not None:
            result = acquire_player_match_variant(
                player_id=args.player_id[0],
                inventory_path=args.inventory,
                capture_root=args.output_root,
                profile_dir=args.profile,
                browser_executable=args.browser_executable,
                capture_id=args.capture_id,
                settle_ms=args.settle_ms,
                pause_seconds=args.pause_seconds,
                filters=filters,
            )
        else:
            result = acquire_player_views(
                player_ids=args.player_id,
                inventory_path=args.inventory,
                capture_root=args.output_root,
                profile_dir=args.profile,
                browser_executable=args.browser_executable,
                capture_id=args.capture_id,
                settle_ms=args.settle_ms,
                pause_seconds=args.pause_seconds,
                explore_filters=not args.no_filter_exploration,
                views=views,
                revisit_existing=args.revisit_existing,
            )
        progress = build_player_acquisition_progress(
            inventory_path=args.inventory,
            capture_root=args.output_root,
            output_path=args.progress_output or args.output_root / "acquisition-progress-2026-27.json",
        )
        print(json.dumps({
            **plan,
            "result": result,
            "progress": {"summary": progress["summary"], "output_path": progress.get("output_path")},
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        try:
            progress = build_player_acquisition_progress(
                inventory_path=args.inventory,
                capture_root=args.output_root,
                output_path=args.progress_output or args.output_root / "acquisition-progress-2026-27.json",
            )
        except (OSError, ValueError, json.JSONDecodeError):
            progress = None
        error = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if isinstance(exc, PlayerAcquisitionStopped):
            error.update({"player_id": exc.player_id, "view": exc.view, "access_status": exc.status})
        if progress:
            error["progress"] = {
                "summary": progress["summary"],
                "output_path": progress.get("output_path"),
            }
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
