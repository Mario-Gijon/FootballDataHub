#!/usr/bin/env python3
"""Parse club/team snapshots offline or acquire explicitly named pilot teams."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from football_data_hub.collectors.bdfutbol_club_team import (
    ClubTeamAccessStopped,
    InvalidClubTeamSnapshot,
    capture_club_team_snapshots,
    discover_latest_snapshots,
)
from football_data_hub.collectors.bdfutbol_competition import load_competition_export
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
DEFAULT_COMPETITION_ROOT = Path("data/parsed/bdfutbol/primera_federacion_2026_27")


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
    offline.add_argument("--competition-root", type=Path, default=DEFAULT_COMPETITION_ROOT)
    offline.add_argument("--competition-extraction-key", help="Selecciona explícitamente una extracción Hito 1B validada.")
    offline.add_argument("--compact-export", action="store_true", help="Escribe gzip lossless bajo compact/; omite CSV redundante de filas.")
    offline.add_argument("--include-table-csv", action="store_true", help="Añade table_rows.csv.gz al export compacto.")

    live = modes.add_parser("live", help="Captura las vistas conocidas para IDs explícitos")
    _add_team_ids(live)
    live.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    live.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    live.add_argument("--competition-root", type=Path, default=DEFAULT_COMPETITION_ROOT)
    live.add_argument("--competition-extraction-key", help="Selecciona explícitamente una extracción Hito 1B validada.")
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
    competition_root: Path = DEFAULT_COMPETITION_ROOT,
    competition_extraction_key: str | None = None,
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
    competition_selection = _load_competition_selection(
        competition_root,
        extraction_key=competition_extraction_key,
        independent_match_evidence=_independent_competition_evidence(parsed_pages),
    )
    competition_matches = competition_selection["matches"]
    selection = competition_selection["selection"]
    print(
        "Fuente de competición: "
        f"{selection.get('selection_status')} / {selection.get('selection_mode')} / "
        f"{selection.get('selected_extraction_key') or 'sin selección automática'}"
    )
    if selection.get("selection_status") == "AMBIGUOUS_VALID_SOURCES":
        print("AVISO: fuentes Hito 1B válidas en conflicto; export sin cruce de competición.", file=sys.stderr)
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
        competition_selection=selection,
    )
    return output_dir, coverage, parsed_pages, variant_pages


def _write_live_status(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_competition_matches(
    root: Path = DEFAULT_COMPETITION_ROOT,
    *,
    extraction_key: str | None = None,
) -> list[dict[str, Any]] | None:
    """Return one local Hito 1B extraction after integrity and coherence checks."""
    return load_competition_export(root, extraction_key=extraction_key)["matches"]


def _load_competition_selection(
    root: Path = DEFAULT_COMPETITION_ROOT,
    *,
    extraction_key: str | None = None,
    independent_match_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return load_competition_export(
        root,
        extraction_key=extraction_key,
        independent_match_evidence=independent_match_evidence,
    )


def _independent_competition_evidence(parsed_pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Build corroboration from canonical club P arrays, without mixing page captures."""
    team_by_club = {
        str(page.get("club_id")): str(page.get("entity_id"))
        for page in parsed_pages
        if page.get("entity_type") == "team_season"
        and page.get("view") == "team_alignment"
        and page.get("club_id")
    }
    canonical_pages = [
        page for page in parsed_pages
        if page.get("entity_type") == "club"
        and page.get("view") == "club_matches"
        and not urlsplit(str(page.get("url", ""))).query
    ]
    by_match: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in canonical_pages:
        data = page.get("club_data", {}).get("embedded_match_data", {})
        if data.get("parse_status") != "PARSED_19_POSITION_TUPLES":
            continue
        club_id = str(page.get("entity_id"))
        source = page.get("source", {})
        for item in data.get("records", []):
            values = item.get("source_values_raw")
            if not isinstance(values, list) or len(values) != 19:
                continue
            if str(values[18]) != "2026-27" or str(values[1]) != "1rf":
                continue
            try:
                match_id = str(int(values[8]))
                home_club_id = f"e{int(values[10])}"
                away_club_id = f"e{int(values[11])}"
            except (TypeError, ValueError):
                continue
            date_match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", str(values[3] or ""))
            date_iso = (
                f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
                if date_match else None
            )
            try:
                home_goals, away_goals = int(values[6]), int(values[7])
            except (TypeError, ValueError):
                home_goals = away_goals = None
            round_match = re.fullmatch(r"Jornada\s+(\d+)", str(values[14] or "").strip(), re.IGNORECASE)
            round_code = str(values[15]).strip() if values[15] is not None else ""
            round_number = int(round_match.group(1)) if round_match and round_code == round_match.group(1) else None
            referee_id = str(values[13]).strip().removeprefix("r") if values[13] is not None else None
            by_match[match_id].append({
                "match_id": match_id,
                "date": date_iso,
                "season": "2026/27",
                "competition_code": "1rf",
                "home_club_id": home_club_id,
                "away_club_id": away_club_id,
                "home_team_name": str(values[5]) if values[5] is not None else None,
                "away_team_name": str(values[9]) if values[9] is not None else None,
                "home_team_season_id": team_by_club.get(home_club_id),
                "away_team_season_id": team_by_club.get(away_club_id),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "referee_id": referee_id,
                "round": round_number,
                "source_club_id": club_id,
                "source_values_raw": values,
                "source_observation": {
                    "source_club_id": club_id,
                    "source_record_index": item.get("source_record_index"),
                    "url": page.get("url"),
                    "snapshot_directory": source.get("snapshot_directory"),
                    "snapshot_sha256": source.get("rendered_html_sha256"),
                    "captured_at_utc": source.get("captured_at_utc"),
                },
            })

    evidence_items = []
    invalid_ids = []
    neutral_positions = (0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 18)
    for match_id, rows in sorted(by_match.items()):
        first = rows[0]
        expected_clubs = {first["home_club_id"], first["away_club_id"]}
        same_payload = all(
            [row["source_values_raw"][index] for index in neutral_positions]
            == [first["source_values_raw"][index] for index in neutral_positions]
            for row in rows[1:]
        )
        observed_clubs = {row["source_club_id"] for row in rows}
        if (
            len(rows) != 2 or not same_payload or observed_clubs != expected_clubs
            or not first.get("date") or first.get("home_goals") is None
            or not first.get("home_team_season_id") or not first.get("away_team_season_id")
        ):
            invalid_ids.append(match_id)
            continue
        evidence_items.append({
            **{key: first[key] for key in (
                "match_id", "date", "season", "competition_code", "home_club_id", "away_club_id",
                "home_team_name", "away_team_name", "home_team_season_id", "away_team_season_id",
                "home_goals", "away_goals", "referee_id", "round",
            )},
            "source_observations": [row["source_observation"] for row in rows],
        })

    source_pages = []
    for page in canonical_pages:
        data = page.get("club_data", {}).get("embedded_match_data", {})
        if data.get("parse_status") != "PARSED_19_POSITION_TUPLES":
            continue
        source = page.get("source", {})
        source_pages.append({
            "club_id": str(page.get("entity_id")),
            "url": page.get("url"),
            "snapshot_directory": source.get("snapshot_directory"),
            "snapshot_sha256": source.get("rendered_html_sha256"),
            "captured_at_utc": source.get("captured_at_utc"),
        })
    is_validated = bool(evidence_items) and not invalid_ids and len(source_pages) == len(canonical_pages)
    return {
        "status": "VALIDATED" if is_validated else "INCOMPLETE",
        "items": evidence_items,
        "source": {
            "source_family": "canonical_club_pages.embedded_match_data.P",
            "same_publisher_as_competition_source": True,
            "canonical_club_pages": len(canonical_pages),
            "pages_with_supported_P": len(source_pages),
            "unique_current_1rf_matches": len(by_match),
            "validated_matches": len(evidence_items),
            "invalid_match_ids": invalid_ids,
            "club_page_sources": source_pages,
        },
    }


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
                competition_root=args.competition_root,
                competition_extraction_key=args.competition_extraction_key,
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
            competition_root=args.competition_root,
            competition_extraction_key=args.competition_extraction_key,
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
