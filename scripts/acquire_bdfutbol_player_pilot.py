"""Acquire the explicitly selected BDFutbol player views as raw snapshots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.acquisition import (
    PLAYER_VIEWS,
    acquire_player_views,
    load_inventory_players,
    player_view_url,
)


def main() -> int:
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
    parser.add_argument("--revisit-existing", action="store_true")
    parser.add_argument("--pause-seconds", type=float, default=5.0)
    parser.add_argument("--settle-ms", type=int, default=900)
    parser.add_argument("--no-filter-exploration", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    players = load_inventory_players(args.inventory, args.player_id)
    views = tuple(args.view or PLAYER_VIEWS)
    if args.revisit_existing and (len(args.player_id) != 1 or len(views) != 1 or not args.capture_id):
        parser.error("--revisit-existing requiere capture_id, un jugador y una sola vista")
    plan = {
        "player_ids": args.player_id,
        "players": [
            {"player_id": player_id, "display_name": players[player_id].get("display_name")}
            for player_id in args.player_id
        ],
        "base_view_navigations": len(args.player_id) * len(views),
        "urls": [
            {"player_id": player_id, "view": view, "url": player_view_url(player_id, view)}
            for player_id in args.player_id
            for view in views
        ],
        "inventory": str(args.inventory.expanduser().resolve()),
        "output_root": str(args.output_root.expanduser().resolve()),
        "profile": str(args.profile.expanduser().resolve()),
        "filter_exploration": not args.no_filter_exploration,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
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
    print(json.dumps({**plan, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
