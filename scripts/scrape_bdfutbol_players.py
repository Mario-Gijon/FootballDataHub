#!/usr/bin/env python3
"""Prepare an offline player-pilot plan or acquire explicitly named players."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from football_data_hub.collectors.bdfutbol_player import (
    PlayerAcquisitionStopped,
    build_player_acquisition_plan,
    capture_player_snapshots,
)
from football_data_hub.parsers.player_pages import (
    PLAYER_VIEWS,
    build_player_acquisition_inventory,
    discover_player_snapshots,
    parse_player_snapshot_inventory,
)

DEFAULT_RAW_ROOT = Path("data/raw/bdfutbol")
DEFAULT_CLUB_SPORTS = Path(
    "data/parsed/bdfutbol/club_team_2026_27/compact/"
    "snapshot-f36c91119a98390766ff-parser-1.3.0/sports"
)
DEFAULT_PROFILE = Path.home() / ".football-data-hub-v2-probe"


def _read_json_gzip(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    offline = modes.add_parser("dry-run", help="Genera y valida un plan sin navegador ni red")
    offline.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    offline.add_argument("--club-sports", type=Path, default=DEFAULT_CLUB_SPORTS)
    offline.add_argument("--batch-size", type=int, default=3)
    offline.add_argument("--refresh", action="store_true", help="Marca los snapshots actuales para recaptura")

    live = modes.add_parser("live", help="Captura hasta tres IDs indicados explícitamente")
    live.add_argument("--player-id", action="append", required=True, help="ID jNNN; repetir para varios")
    live.add_argument(
        "--view", choices=PLAYER_VIEWS, action="append", default=None,
        help="Vista a capturar; repetir para varias. Si se omite, captura las cuatro vistas base.",
    )
    live.add_argument(
        "--filter", action="append", default=[], metavar="CONTROL=VALOR",
        help="Captura una variante interactiva verificada; requiere --view statistics.",
    )
    live.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    live.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    live.add_argument("--browser", choices=("brave", "chrome", "chromium", "auto"), default="brave")
    live.add_argument("--settle-ms", type=int, default=1200)
    live.add_argument("--refresh", action="store_true", help="Captura nuevos snapshots sin sobrescribir")
    live.add_argument("--screenshot", action="store_true", help="Guarda una captura visual por vista")
    return parser.parse_args(argv)


def _add_parse_coverage(plan: dict[str, Any], parsed_pages: list[dict[str, Any]]) -> None:
    parsed = {
        (str(page.get("player_id")), str(page.get("view"))): page
        for page in parsed_pages
    }
    interpreted_rows = {
        "profile": ("career_rows",),
        "statistics": ("statistics_rows",),
        "matches": ("match_summary_rows", "individual_match_rows"),
        "rivals": ("rival_records",),
    }
    for row in plan["views"]:
        page = parsed.get((row["player_id"], row["view"]))
        if page is None:
            row["parse_status"] = "PENDING_PARSE" if row["snapshot_available"] else "NOT_AVAILABLE"
            row["interpreted_row_count"] = 0
            row["interpreted_row_counts"] = {}
            row["raw_table_row_count"] = None
            row["row_interpretation_status"] = "RAW_ONLY" if row["snapshot_available"] else "NOT_AVAILABLE"
            row["required_tables_missing"] = []
            row["filters_seen"] = []
            row["coverage_status"] = (
                "CAPTURED_FILTERED_VARIANT_BASE_PENDING" if row["filtered_variant_count"]
                else "CAPTURED_NON_VALID_REQUIRES_REVALIDATION" if row["invalid_snapshot_count"]
                else "CAPTURED_RAW_ONLY" if row["snapshot_available"]
                else "PENDING_CAPTURE"
            )
            row["fields_not_investigated"] = ["Sin snapshot base parseado"]
            continue
        view_data = page.get("view_data", {})
        row["parse_status"] = page.get("coverage", {}).get("parse_status", "PARSED")
        row["interpreted_row_counts"] = {
            collection: len(view_data.get(collection, []))
            for collection in interpreted_rows[row["view"]]
        }
        row["interpreted_row_count"] = sum(row["interpreted_row_counts"].values())
        row["raw_table_row_count"] = sum(len(table.get("rows", [])) for table in page.get("tables", []))
        row["row_interpretation_status"] = "PARSED_WITH_RAW_TABLE_CELLS_PRESERVED"
        row["required_tables_missing"] = page.get("coverage", {}).get("required_table_roles_missing", [])
        row["filters_seen"] = [
            item.get("id") or item.get("name")
            for item in page.get("filter_controls", [])
        ]
        row["coverage_status"] = "CAPTURED_AND_PARSED"
        row["fields_not_investigated"] = page.get("coverage", {}).get("fields_not_investigated", [])


def _parse_filter_arguments(
    raw_filters: list[str], views: list[str] | None
) -> dict[str, str] | None:
    if not raw_filters:
        return None
    if views != ["statistics"]:
        raise ValueError("--filter requiere exactamente --view statistics")
    parsed: dict[str, str] = {}
    for item in raw_filters:
        control, separator, value = item.partition("=")
        if not separator or not control.strip() or not value.strip():
            raise ValueError(f"Filtro no válido {item!r}; usa CONTROL=VALOR")
        control = control.strip()
        value = value.strip()
        if control in parsed:
            raise ValueError(f"No repitas el control de filtro {control}")
        parsed[control] = value
    return parsed


def dry_run(*, raw_root: Path, club_sports: Path, batch_size: int, refresh: bool) -> dict[str, Any]:
    """Validate local player snapshots and report the planned pilot; never opens a browser."""
    roster_path = club_sports / "rosters.json.gz"
    rosters = _read_json_gzip(roster_path).get("items", [])
    raw_snapshots = discover_player_snapshots(raw_root)
    inventory = build_player_acquisition_inventory(rosters, raw_snapshots)
    plan = build_player_acquisition_plan(
        inventory["player_pilot_candidates"],
        raw_snapshots,
        batch_size=batch_size,
        refresh=refresh,
    )
    parsed_pages = parse_player_snapshot_inventory(raw_snapshots, raw_root)
    _add_parse_coverage(plan, parsed_pages)
    plan["input_roster_path"] = roster_path.as_posix()
    plan["raw_root"] = raw_root.as_posix()
    plan["validated_raw_snapshot_count"] = sum(
        item.get("usable") is True
        and item.get("is_base_view_snapshot") is True
        for candidates in raw_snapshots.values()
        for item in candidates
    )
    plan["parsed_snapshot_count"] = len(parsed_pages)
    plan["browser_started"] = False
    plan["network_requested"] = False
    return plan


def run(args: argparse.Namespace) -> int:
    try:
        if args.mode == "dry-run":
            report = dry_run(
                raw_root=args.raw_root,
                club_sports=args.club_sports,
                batch_size=args.batch_size,
                refresh=args.refresh,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        records = capture_player_snapshots(
            player_ids=args.player_id,
            views=args.view,
            filters=_parse_filter_arguments(args.filter, args.view),
            raw_root=args.raw_root,
            profile_dir=args.profile,
            browser=args.browser,
            settle_ms=args.settle_ms,
            refresh=args.refresh,
            screenshot=args.screenshot,
        )
    except PlayerAcquisitionStopped as exc:
        print(json.dumps({
            "status": "STOPPED",
            "player_id": exc.player_id,
            "view": exc.view,
            "url": exc.url,
            "access_status": exc.status,
            "reason": exc.reason,
            "completed_and_retained": exc.records,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "COMPLETE", "records": records}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
