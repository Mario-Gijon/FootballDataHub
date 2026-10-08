#!/usr/bin/env python3
"""Parse existing player snapshots and build a pending-player manifest offline."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from football_data_hub.parsers.player_pages import (
    build_player_acquisition_inventory,
    build_player_pilot_candidates,
    discover_player_snapshots,
    parse_player_snapshot_inventory,
)
from football_data_hub.parsers.player_source_audit import (
    audit_caceres_scope,
    audit_competition_exports,
)
from football_data_hub.storage.player_exports import build_player_exports

DEFAULT_RAW_ROOT = Path("data/raw/bdfutbol")
DEFAULT_CLUB_SPORTS = Path(
    "data/parsed/bdfutbol/club_team_2026_27/compact/"
    "snapshot-f36c91119a98390766ff-parser-1.3.0/sports"
)
DEFAULT_COMPETITION_ROOT = Path("data/parsed/bdfutbol/primera_federacion_2026_27")
DEFAULT_HITO1B_PARTICIPANTS = Path(
    "data/parsed/bdfutbol/primera_federacion_2026_27/"
    "snapshot-044edc9b2ef3c6026c7f-parser-1.0.0/participants.json"
)
DEFAULT_OUTPUT_ROOT = Path("data/parsed/bdfutbol/player_2026_27")


def _read_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _find_latest_valid_snapshot(raw_root: Path, url: str) -> Path:
    matches = []
    for metadata_path in raw_root.rglob("metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("requested_url") != url and metadata.get("final_url") != url:
            continue
        if metadata.get("access_status") == "VALID" and metadata.get("http_status") == 200:
            matches.append((str(metadata.get("captured_at_utc") or ""), metadata_path.parent))
    if not matches:
        raise FileNotFoundError(f"No hay snapshot local válido para {url}")
    return max(matches, key=lambda item: item[0])[1]


def _enrich_memberships(inventory: dict[str, Any], participant_path: Path) -> None:
    payload = _read_json(participant_path)
    participants = payload.get("items", [])
    by_team_id = {str(row["team_season_id"]): row for row in participants}
    for membership in inventory["memberships"]:
        participant = by_team_id.get(str(membership.get("team_season_id")), {})
        membership["group"] = participant.get("group")
        membership["team_name"] = participant.get("team_name")
    for player in inventory["players"]:
        team_rows = [by_team_id.get(team_id, {}) for team_id in player["team_season_ids"]]
        player["team_memberships"] = [
            {
                "team_season_id": membership["team_season_id"],
                "club_id": membership.get("club_id"),
                "group": by_team_id.get(str(membership["team_season_id"]), {}).get("group"),
                "team_name": by_team_id.get(str(membership["team_season_id"]), {}).get("team_name"),
                "name_raw": membership.get("name_raw"),
                "shirt_number_raw": membership.get("shirt_number_raw"),
                "position_raw": membership.get("position_raw"),
                "appearances_raw": membership.get("appearances_raw"),
                "zero_appearances": membership.get("zero_appearances"),
            }
            for membership in inventory["memberships"]
            if membership["player_id"] == player["player_id"]
        ]
        player["groups"] = sorted({str(row.get("group")) for row in team_rows if row.get("group")})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--club-sports", type=Path, default=DEFAULT_CLUB_SPORTS)
    parser.add_argument("--competition-root", type=Path, default=DEFAULT_COMPETITION_ROOT)
    parser.add_argument("--participants", type=Path, default=DEFAULT_HITO1B_PARTICIPANTS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    try:
        rosters = _read_json(args.club_sports / "rosters.json.gz").get("items", [])
        raw_inventory = discover_player_snapshots(args.raw_root)
        player_inventory = build_player_acquisition_inventory(rosters, raw_inventory)
        _enrich_memberships(player_inventory, args.participants)
        parsed_pages = parse_player_snapshot_inventory(raw_inventory, args.raw_root)
        player_inventory["player_pilot_candidates"] = build_player_pilot_candidates(
            player_inventory["memberships"],
            player_inventory["players"],
            raw_inventory,
            parsed_pages,
        )

        b2_metadata = _read_json(
            args.club_sports.parent / "dataset_metadata.json.gz"
        )
        retained_keys = b2_metadata.get("competition_crosscheck_source", {}).get("extraction_keys", [])
        retained_key = retained_keys[0] if len(retained_keys) == 1 else None
        hito1b_audit = audit_competition_exports(
            args.competition_root,
            retained_extraction_key=retained_key,
        )
        team_matches = _find_latest_valid_snapshot(
            args.raw_root, "https://www.bdfutbol.com/es/t/t2026-27149.html?tab=partits"
        )
        club_matches = _find_latest_valid_snapshot(
            args.raw_root, "https://www.bdfutbol.com/es/p/e149.html"
        )
        caceres_audit = audit_caceres_scope(
            team_matches,
            club_matches,
            args.club_sports / "coverage_by_club.json.gz",
        )
        source_audit = {"hito1b": hito1b_audit, "caceres": caceres_audit}

        output = build_player_exports(
            inventory=player_inventory,
            parsed_pages=parsed_pages,
            source_audit=source_audit,
            output_root=args.output_root,
        )
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Jugadores: {len(player_inventory['players'])}")
    print(f"Pertenencias: {len(player_inventory['memberships'])}")
    print(f"Snapshots de jugador parseados: {len(parsed_pages)}")
    print(f"Pilotos futuros preparados (sin adquirir): {len(player_inventory['player_pilot_candidates'])}")
    print(f"Pendientes de vistas jugador: {sum(not row['snapshot_available'] for row in player_inventory['acquisition_manifest'])}")
    print(f"Hito 1B: {retained_key}; estado comparativo={hito1b_audit.get('cross_candidate_comparison') is not None}")
    print(f"Cacereño: {caceres_audit['status']}")
    print(f"Export offline: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
