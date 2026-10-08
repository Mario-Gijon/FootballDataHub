#!/usr/bin/env python3
"""Parse club/team snapshots offline or acquire explicitly named pilot teams."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from football_data_hub.collectors.bdfutbol_club_team import (
    ClubTeamAccessStopped,
    InvalidClubTeamSnapshot,
    capture_club_team_snapshots,
    discover_latest_snapshots,
)
from football_data_hub.parsers.club_team_coverage import build_club_team_coverage
from football_data_hub.providers.bdfutbol.club_team import PARSER_VERSION, parse_club_team_html
from football_data_hub.providers.bdfutbol.discovery import timestamp_utc
from football_data_hub.storage.club_team_exports import write_club_team_exports

DEFAULT_RAW_ROOT = Path("data/raw/bdfutbol")
DEFAULT_OUTPUT_ROOT = Path("data/parsed/bdfutbol/club_team_2026_27")
DEFAULT_ANALYSIS_ROOT = Path("data/analysis/bdfutbol/club_team")


def _add_team_ids(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--team-id",
        action="append",
        required=True,
        help="ID de equipo-temporada de participants.json; repetible y explícito.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    offline = modes.add_parser("offline", help="Valida y procesa snapshots existentes sin red")
    _add_team_ids(offline)
    offline.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    offline.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    offline.add_argument("--compact-export", action="store_true", help="Escribe gzip lossless bajo compact/; omite CSV redundante de filas.")
    offline.add_argument("--include-table-csv", action="store_true", help="Añade table_rows.csv.gz al export compacto.")

    live = modes.add_parser("live", help="Captura las vistas conocidas para IDs explícitos")
    _add_team_ids(live)
    live.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    live.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    live.add_argument("--analysis-root", type=Path, default=DEFAULT_ANALYSIS_ROOT)
    live.add_argument(
        "--profile",
        type=Path,
        default=Path.home() / ".football-data-hub-v2-probe",
        help="Perfil persistente existente; no se leen ni exportan sus credenciales/cookies.",
    )
    live.add_argument("--browser", choices=("brave", "chrome", "chromium", "auto"), default="brave")
    live.add_argument("--settle-ms", type=int, default=1200)
    live.add_argument("--compact-export", action="store_true", help="Escribe gzip lossless bajo compact/; omite CSV redundante de filas.")
    live.add_argument("--include-table-csv", action="store_true", help="Añade table_rows.csv.gz al export compacto.")
    policy = live.add_mutually_exclusive_group()
    policy.add_argument("--reuse", dest="refresh", action="store_false", help="Reutiliza la captura válida más reciente (predeterminado).")
    policy.add_argument("--refresh", action="store_true", help="Adquiere snapshots nuevos sin sobrescribir los anteriores.")
    live.set_defaults(refresh=False)
    live.add_argument(
        "--match-result-filter",
        action="append",
        choices=("all", "pg", "pe", "pp"),
        default=[],
        help="Captura también resultados actuales de club: all omite pgep; pg/pe/pp filtran resultado.",
    )
    return parser.parse_args(argv)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _process_snapshots(
    *,
    team_season_ids: list[str],
    raw_root: Path,
    output_root: Path,
    compact_export: bool = False,
    include_table_csv: bool = False,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    started = time.perf_counter()
    snapshots = discover_latest_snapshots(raw_root, team_season_ids=set(team_season_ids))
    if not snapshots:
        raise InvalidClubTeamSnapshot(f"No hay snapshots válidos bajo {raw_root} para los IDs indicados")
    print(f"Snapshots válidos para los IDs explícitos: {len(snapshots)}")
    parsed_pages = []
    variant_pages = []
    for index, snapshot in enumerate(snapshots, start=1):
        print(f"[{index}/{len(snapshots)}] Parseando {snapshot.page['entity_type']} {snapshot.page['entity_id']} / {snapshot.page['view']}")
        page = parse_club_team_html(
            snapshot.html,
            snapshot.url,
            source_metadata=snapshot.metadata,
        )
        page["source"]["snapshot_directory"] = _relative(snapshot.directory)
        parts = urlsplit(snapshot.url)
        filters = {
            key: values[-1]
            for key, values in parse_qs(parts.query).items()
        }
        if page["view"] == "club_matches" and filters:
            variant_id = "__".join(f"{key}-{value}" for key, value in sorted(filters.items()))
            page["view_variant"] = {
                "variant_id": variant_id,
                "filter_parameters": filters,
                "scope": "; ".join(f"{key}={value}" for key, value in sorted(filters.items())),
            }
            variant_pages.append(page)
        else:
            parsed_pages.append(page)
    coverage = build_club_team_coverage(
        parsed_pages,
        team_season_ids=team_season_ids,
        variant_pages=variant_pages,
    )
    output_dir = write_club_team_exports(
        parsed_pages=parsed_pages,
        variant_pages=variant_pages,
        coverage=coverage,
        output_root=output_root,
        compact=compact_export,
        processing_seconds=time.perf_counter() - started,
        include_table_csv=include_table_csv if compact_export else None,
    )
    return output_dir, coverage, parsed_pages, variant_pages


def _write_live_status(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    team_ids = list(dict.fromkeys(args.team_id))
    if args.mode == "offline":
        try:
            output_dir, coverage, parsed_pages, variant_pages = _process_snapshots(
                team_season_ids=team_ids,
                raw_root=args.raw_root,
                output_root=args.output_root,
                compact_export=args.compact_export,
                include_table_csv=args.include_table_csv,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
        print(f"Parser: {PARSER_VERSION}")
        print(f"Snapshots procesados: {len(parsed_pages) + len(variant_pages)} ({len(variant_pages)} variantes)")
        print(f"Salida JSON/CSV: {output_dir}")
        print(
            f"Vistas capturadas: {coverage['summary']['views_captured']}/"
            f"{coverage['summary']['views_expected']}; validadas: {coverage['summary']['views_validated']}"
        )
        print(
            f"Jugadores de plantilla: {coverage['summary']['unique_team_player_ids']} IDs únicos; "
            f"entrenadores: {coverage['summary']['unique_team_coach_ids']} IDs únicos"
        )
        return 0

    if args.settle_ms < 0:
        print("ERROR: --settle-ms debe ser >= 0", file=sys.stderr)
        return 3
    capture_status: dict[str, Any] = {
        "mode": "live",
        "status": "CAPTURED",
        "team_season_ids": team_ids,
        "provider": "BDFutbol",
        "capture_policy": "BrowserSessionManager + BDFutbolAccess; stop at first non-VALID response",
        "snapshot_policy": "refresh" if args.refresh else "reuse",
        "match_result_filters": list(dict.fromkeys(args.match_result_filter)),
        "compact_export": args.compact_export,
        "parser_version": PARSER_VERSION,
    }
    access_stopped = False
    try:
        processed = capture_club_team_snapshots(
            team_season_ids=team_ids,
            raw_root=args.raw_root,
            profile_dir=args.profile,
            browser=args.browser,
            settle_ms=args.settle_ms,
            reuse_existing=not args.refresh,
            match_result_filters=tuple(dict.fromkeys(args.match_result_filter)),
        )
        capture_status["processed_snapshots"] = [
            {
                "url": snapshot.url,
                "snapshot_directory": _relative(snapshot.directory),
                "sha256": snapshot.sha256,
                "disposition": snapshot.capture_disposition,
            }
            for snapshot in processed
        ]
    except ClubTeamAccessStopped as exc:
        access_stopped = True
        capture_status.update({
            "status": exc.assessment.status.value,
            "http_status": exc.assessment.http_status,
            "url": exc.url,
            "completed_before_stop": exc.completed,
            "challenge_bypass_attempted": False,
        })
        print(
            f"ACCESO DETENIDO: {exc.assessment.status.value} HTTP {exc.assessment.http_status} "
            f"en {exc.url}; no se intentó resolver el desafío.",
            file=sys.stderr,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        capture_status["fatal_error"] = f"{type(exc).__name__}: {exc}"
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        _write_live_status(args.analysis_root / timestamp_utc() / "capture_status.json", capture_status)
        return 3

    _write_live_status(args.analysis_root / timestamp_utc() / "capture_status.json", capture_status)
    try:
        output_dir, coverage, parsed_pages, variant_pages = _process_snapshots(
            team_season_ids=team_ids,
            raw_root=args.raw_root,
            output_root=args.output_root,
            compact_export=args.compact_export,
            include_table_csv=args.include_table_csv,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR al procesar snapshots preservados: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4 if access_stopped else 3
    print(f"Parser: {PARSER_VERSION}")
    print(f"Snapshots procesados: {len(parsed_pages) + len(variant_pages)} ({len(variant_pages)} variantes)")
    print(f"Salida JSON/CSV: {output_dir}")
    return 4 if access_stopped else 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
