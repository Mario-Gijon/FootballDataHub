#!/usr/bin/env python3
"""Compare immutable MATCH-00 generations or explicitly activate one offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from football_data_hub.providers.bdfutbol.classification.generation_activation import (
    activate_match_generation,
    compare_match_generations,
    write_diff_report,
)
from football_data_hub_api.match_details_dataset import load_published_match_details
from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import load_player_directory


def _paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-root", type=Path, default=Path.home() / "FootballDataHub-data")
    parser.add_argument("--store-root", type=Path, default=Path.home() / "FootballDataHub-data" / "matches")
    parser.add_argument("--player-inventory-root", type=Path)
    parser.add_argument("--player-compact-root", type=Path)
    parser.add_argument("--team-captures-root", type=Path)
    parser.add_argument("--team-profiles-index", type=Path)


def _player_ids(args: argparse.Namespace) -> set[int]:
    data_root = args.data_root.expanduser()
    directory = load_player_directory(
        inventory_root=(args.player_inventory_root or data_root / "players/inventory-2026-27").expanduser(),
        compact_root=(args.player_compact_root or data_root / "players/compact-2026-27").expanduser(),
        team_captures_root=(args.team_captures_root or data_root / "team-captures").expanduser(),
        published_index_path=(args.team_profiles_index or data_root / "published/team_profiles_2026-27.json").expanduser(),
    )
    return set(directory.players_by_id)


def _published_ids(root: Path) -> set[str]:
    index_path = root / "details/published/index.json"
    if not index_path.exists():
        return set()
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se puede leer el índice de publicaciones: {index_path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "football_data_hub.match_detail_publication_index.v1"
        or not isinstance(payload.get("publications"), list)
    ):
        raise ValueError("El índice de publicaciones no cumple el contrato conocido.")
    ids = [item.get("internal_id") for item in payload["publications"] if isinstance(item, dict)]
    if len(ids) != len(payload["publications"]) or any(not isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("El índice de publicaciones contiene IDs ausentes o duplicados.")
    return set(ids)


def _verify_published(args: argparse.Namespace, bundle) -> set[str]:
    ids = _published_ids(args.store_root.expanduser())
    if not ids:
        return set()
    loaded = load_published_match_details(
        args.store_root.expanduser() / "details/published",
        store_root=args.store_root.expanduser() / "details",
        generation_root=bundle.generation_root,
        data_root=args.data_root.expanduser(),
        match_bundle=bundle,
        player_ids=_player_ids(args),
    )
    if set(loaded) != ids:
        raise ValueError("El conjunto del índice no coincide con los paquetes verificados.")
    return set(loaded)


def _print_diff_summary(report: dict) -> None:
    summary = report["summary"]
    print(
        f"Diff {report['before_generation_id']} → {report['after_generation_id']} "
        f"(sha256 {report['report_sha256']})"
    )
    for label, key in (
        ("Nuevos disputados", "newly_played"),
        ("Fixture actualizado", "fixture_updated"),
        ("Marcador corregido", "result_corrected"),
        ("Revisión requerida", "review_required"),
        ("Conflictos duros", "hard_conflicts"),
        ("Disputados sin detalles aprobados", "played_without_approved_details"),
        ("Disputados con detalles aprobados", "played_with_approved_details"),
    ):
        print(f"{label}: {summary[key]}")
    for item in report["fixtures"]:
        if item["change_type"] in {
            "newly_played", "fixture_updated", "result_corrected",
            "played_to_unplayed_conflict", "identity_conflict", "fixture_added", "fixture_missing",
        }:
            review = " · revisión" if item.get("review_required") else ""
            print(f"  {item['internal_id']}: {item['change_type']}{review}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare", help="Compara dos generaciones verificadas offline.")
    _paths(compare)
    compare.add_argument("--before", type=Path, required=True, help="Directorio de generación anterior.")
    compare.add_argument("--after", type=Path, required=True, help="Directorio de generación candidata.")
    compare.add_argument("--output", type=Path, help="JSON de diferencias de solo creación.")

    activate = sub.add_parser("activate", help="Activa una generación tras revisión explícita.")
    _paths(activate)
    activate.add_argument("--candidate", type=Path, required=True)
    activate.add_argument("--expected-current-generation", help="Obligatorio al crear el primer puntero activo.")
    activate.add_argument("--reviewer", required=True)
    activate.add_argument("--confirm-report-sha256", required=True)
    args = parser.parse_args()
    data_root = args.data_root.expanduser()
    if args.command == "compare":
        before = load_match_results_dataset(args.before.expanduser(), data_root=data_root)
        after = load_match_results_dataset(args.after.expanduser(), data_root=data_root)
        approved = _verify_published(args, before)
        report = compare_match_generations(before, after, approved_detail_ids=approved)
        _print_diff_summary(report)
        if args.output:
            path = write_diff_report(report, args.output)
            print(f"Informe: {path}")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    player_ids = _player_ids(args)
    approved = _published_ids(args.store_root.expanduser())
    result = activate_match_generation(
        args.candidate.expanduser(),
        store_root=args.store_root.expanduser(),
        data_root=data_root,
        reviewer=args.reviewer,
        expected_generation_id=args.expected_current_generation,
        confirm_report_sha256=args.confirm_report_sha256,
        approved_detail_ids=approved,
        player_ids=player_ids,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
