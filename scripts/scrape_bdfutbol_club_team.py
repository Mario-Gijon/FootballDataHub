#!/usr/bin/env python3
"""Parse club/team snapshots offline or acquire explicitly named pilot teams."""

from __future__ import annotations

import argparse
import gzip
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
from football_data_hub.providers.bdfutbol.club_team import (
    PARSER_VERSION,
    expected_views_for_club,
    expected_views_for_team,
    parse_club_team_html,
)
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


def _base_capture_gaps(
    coverage: dict[str, Any],
    team_season_ids: list[str],
    parsed_pages: list[dict[str, Any]],
) -> list[str]:
    """Return capture/raw-integrity gaps; semantic PARSED views can still pass."""
    entities = {
        (str(row.get("entity_type")), str(row.get("entity_id"))): row
        for row in coverage.get("entity_coverage", [])
    }
    views = {
        (str(row.get("entity_type")), str(row.get("entity_id")), str(row.get("view"))): row
        for row in coverage.get("views", [])
    }
    page_by_key = {
        (str(page.get("entity_type")), str(page.get("entity_id")), str(page.get("view"))): page
        for page in parsed_pages
    }
    gaps: list[str] = []

    def check_entity(entity_type: str, entity_id: str, expected_views: tuple[str, ...]) -> None:
        entity = entities.get((entity_type, entity_id))
        if entity is None:
            gaps.append(f"{entity_type} {entity_id}: sin fila de cobertura")
            return
        if (
            entity.get("views_captured") != len(expected_views)
            or entity.get("views_access_valid") != len(expected_views)
            or entity.get("base_capture_status") != "COMPLETE"
        ):
            gaps.append(
                f"{entity_type} {entity_id}: cobertura base "
                f"{entity.get('views_access_valid', 0)}/{len(expected_views)} válida"
            )
        for view_name in expected_views:
            row = views.get((entity_type, entity_id, view_name))
            if row is None or row.get("access_status") != "VALID":
                gaps.append(f"{entity_type} {entity_id}/{view_name}: snapshot ausente o inválido")
                continue
            if row.get("table_integrity_status") != "VALIDATED":
                gaps.append(
                    f"{entity_type} {entity_id}/{view_name}: integridad raw "
                    f"{row.get('table_integrity_status', 'desconocida')}"
                )
                continue
            table_checks = row.get("table_integrity", {})
            if not table_checks or any(
                check.get("raw_cell_values_preserved") is not True
                for check in table_checks.values()
            ):
                gaps.append(f"{entity_type} {entity_id}/{view_name}: celdas raw sin verificar")

    unique_clubs: set[str] = set()
    for team_id in team_season_ids:
        check_entity("team_season", team_id, expected_views_for_team())
        team_row = entities.get(("team_season", team_id))
        club_id = str(team_row.get("club_id") or "") if team_row else ""
        if not club_id:
            gaps.append(f"team_season {team_id}: relación con club permanente no identificada")
            continue
        unique_clubs.add(club_id)
        alignment = page_by_key.get(("team_season", team_id, "team_alignment"))
        linked_clubs = {
            str(item.get("entity_id"))
            for item in (alignment or {}).get("relationships", [])
            if item.get("entity_type") == "club"
        }
        if club_id not in linked_clubs:
            gaps.append(f"team_season {team_id}: club_id {club_id} no coincide con el enlace raw")

    for club_id in sorted(unique_clubs):
        check_entity("club", club_id, expected_views_for_club())
    return gaps


def _base_raw_integrity_validated_count(coverage: dict[str, Any]) -> int:
    """Count views whose access and original table-cell preservation were validated."""
    return sum(
        1
        for row in coverage.get("views", [])
        if row.get("access_status") == "VALID"
        and row.get("table_integrity_status") == "VALIDATED"
        and row.get("table_integrity")
        and all(
            check.get("raw_cell_values_preserved") is True
            for check in row["table_integrity"].values()
        )
    )


def _process_snapshots(
    *,
    team_season_ids: list[str],
    raw_root: Path,
    output_root: Path,
    compact_export: bool = False,
    include_table_csv: bool = False,
    competition_matches: list[dict[str, Any]] | None = None,
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
        competition_matches=competition_matches,
    )
    return output_dir, coverage, parsed_pages, variant_pages


def _write_live_status(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_competition_matches(
    root: Path = Path("data/parsed/bdfutbol/primera_federacion_2026_27"),
) -> list[dict[str, Any]] | None:
    """Read the strongest complete local Hito 1B export; never accesses the network."""
    candidates = list(root.glob("snapshot-*/dataset_metadata.json"))
    if not candidates:
        return None
    ranked: list[tuple[int, int, float, str, list[dict[str, Any]]]] = []
    for metadata_path in candidates:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        export_dir = metadata_path.parent
        export_matches: list[dict[str, Any]] = []
        groups_complete = True
        for group, suffix in (("I", "i"), ("II", "ii")):
            plain = export_dir / f"matches_group_{suffix}.json"
            compressed = plain.with_name(f"{plain.name}.gz")
            source_path = plain if plain.is_file() else compressed
            if not source_path.is_file():
                groups_complete = False
                break
            opener = gzip.open if source_path.suffix == ".gz" else open
            with opener(source_path, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
            captured_at = payload.get("source_snapshots", {}).get(group, {}).get("captured_at_utc")
            export_matches.extend({
                **item,
                "_captured_at_utc": captured_at,
                "_competition_extraction_key": metadata.get("extraction_key"),
            } for item in payload.get("items", []))
        if groups_complete and export_matches:
            played_count = sum(item.get("result_status") == "played" for item in export_matches)
            linked_id_count = sum(item.get("match_id") is not None for item in export_matches)
            ranked.append((played_count, linked_id_count, metadata_path.stat().st_mtime,
                           str(metadata.get("extraction_key") or ""), export_matches))
    return max(ranked, key=lambda item: item[:4])[4] if ranked else None


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
                competition_matches=_load_competition_matches(),
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
        gaps = _base_capture_gaps(coverage, team_ids, parsed_pages)
        if gaps:
            print("CAPTURA BASE INCOMPLETA:", file=sys.stderr)
            for gap in gaps:
                print(f"- {gap}", file=sys.stderr)
            return 5
        print("Estado de captura base: BASE_CAPTURED")
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

    status_path = args.analysis_root / timestamp_utc() / "capture_status.json"
    _write_live_status(status_path, capture_status)
    try:
        output_dir, coverage, parsed_pages, variant_pages = _process_snapshots(
            team_season_ids=team_ids,
            raw_root=args.raw_root,
            output_root=args.output_root,
            compact_export=args.compact_export,
            include_table_csv=args.include_table_csv,
            competition_matches=_load_competition_matches(),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR al procesar snapshots preservados: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4 if access_stopped else 3
    gaps = _base_capture_gaps(coverage, team_ids, parsed_pages)
    capture_status.update({
        "base_capture_status": "BASE_CAPTURED" if not gaps else "PARTIAL",
        "base_views_expected": coverage["summary"]["views_expected"],
        "base_views_captured": coverage["summary"]["views_captured"],
        "base_views_raw_integrity_validated": _base_raw_integrity_validated_count(coverage),
        "base_views_validated": coverage["summary"]["views_validated"],
        "base_view_pipeline_states": coverage["summary"].get("pipeline_states", {}),
        "missing_base_views": gaps,
        "export_directory": _relative(output_dir),
    })
    _write_live_status(status_path, capture_status)
    print(f"Parser: {PARSER_VERSION}")
    print(f"Snapshots procesados: {len(parsed_pages) + len(variant_pages)} ({len(variant_pages)} variantes)")
    print(f"Salida JSON/CSV: {output_dir}")
    if gaps:
        print(f"Captura base incompleta: {len(gaps)} incidencia(s)", file=sys.stderr)
    return 4 if access_stopped else 5 if gaps else 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
