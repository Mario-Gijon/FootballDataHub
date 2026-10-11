"""Capture one BDFutbol team profile or normalize an authorized local snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from football_data_hub.providers.bdfutbol.context import SUPPORTED_SEASON, get_competition_context

from .acquisition import (
    DEFAULT_VIEWS,
    TeamAcquisitionBundle,
    TeamAcquisitionStopped,
    acquire_team_profile,
    create_team_capture_id,
)
from .catalog import load_team_catalog, write_team_inventory
from .export import export_team_capture
from .parser import parse_team_profile_pages, resolve_team_view_urls
from .validation import validate_team_profile

_DEFAULT_MATCH_CATALOGS = {
    1: Path("data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json"),
    2: Path("data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"),
}
CORE_VIEWS = ("alignment", "statistics")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=(SUPPORTED_SEASON,), default=SUPPORTED_SEASON)
    parser.add_argument("--group", type=int, choices=(1, 2), default=2)
    parser.add_argument("--team-id", type=int)
    parser.add_argument("--team-catalog", type=Path, help="normalized/matches.json del grupo seleccionado.")
    parser.add_argument("--group1-catalog", type=Path, help="Catálogo del Grupo I, necesario para --inventory-only.")
    parser.add_argument("--group2-catalog", type=Path, help="Catálogo del Grupo II, necesario para --inventory-only.")
    parser.add_argument("--output-root", type=Path, default=Path("data/exports/bdfutbol/teams"))
    parser.add_argument("--snapshot-dir", type=Path, help="Carpeta offline con alignment.html y vistas seleccionadas.")
    parser.add_argument("--access-report", type=Path, help="Informe de acceso offline; por defecto <snapshot-dir>/access.json.")
    parser.add_argument("--views", choices=("core", "all"), default="all")
    parser.add_argument("--inventory-only", action="store_true", help="Genera un inventario versionado de los 40 equipos.")
    parser.add_argument(
        "--profile", type=Path,
        default=Path(os.environ.get("FDH_BDFUTBOL_PROFILE", str(Path.home() / ".football-data-hub-chromium-pure-cdp"))),
    )
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--startup-timeout-seconds", type=float, default=35.0)
    parser.add_argument("--navigation-timeout-ms", type=int, default=45_000)
    parser.add_argument("--no-xvfb", action="store_false", dest="use_xvfb")
    parser.set_defaults(use_xvfb=True)
    return parser.parse_args(argv)


def _catalog_path(args: argparse.Namespace, group: int) -> Path:
    supplied = args.group1_catalog if group == 1 else args.group2_catalog
    if supplied:
        return supplied
    env_key = f"FDH_BDFUTBOL_GROUP{group}_MATCHES"
    configured = os.environ.get(env_key) or os.environ.get(f"FDH_GROUP{group}_MATCHES")
    return Path(configured).expanduser() if configured else _DEFAULT_MATCH_CATALOGS[group]


def _load_catalogs(args: argparse.Namespace) -> dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]]:
    catalogs = {}
    for group in (1, 2):
        context = get_competition_context(args.season, group)
        catalogs[group] = load_team_catalog(_catalog_path(args, group), competition=context)
    return catalogs


def _offline_bundle(
    snapshot_dir: Path,
    access_report_path: Path,
    *,
    team_catalog_record: dict[str, Any],
    team_catalog_reference: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    competition,
    requested_views: tuple[str, ...],
) -> TeamAcquisitionBundle:
    snapshot_dir = snapshot_dir.expanduser()
    report_path = access_report_path.expanduser()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    alignment_path = snapshot_dir / "alignment.html"
    if not alignment_path.is_file():
        raise ValueError("El modo offline requiere alignment.html para resolver las URLs reales de las vistas")
    alignment = alignment_path.read_text(encoding="utf-8")
    all_view_urls = resolve_team_view_urls(alignment, str(team_catalog_record["team_url"]))
    views: dict[str, str] = {}
    access_by_view: dict[str, dict[str, Any]] = {}
    page_titles: dict[str, str] = {}
    timestamps: list[datetime] = []
    report_views = report.get("views", {})
    browser: dict[str, Any] = report.get("browser", {})
    for view in requested_views:
        source_path = snapshot_dir / f"{view}.html"
        if not source_path.is_file():
            raise ValueError(f"Falta el snapshot requerido: {source_path}")
        html_bytes = source_path.read_bytes()
        html = html_bytes.decode("utf-8")
        view_report = report_views.get(view, {})
        status = view_report.get("status") or view_report.get("access", {}).get("status")
        http_status = view_report.get("http_status") or view_report.get("access", {}).get("http_status")
        requested_url = view_report.get("requested_url") or view_report.get("access", {}).get("requested_url")
        final_url = view_report.get("final_url") or view_report.get("access", {}).get("final_url")
        title = view_report.get("page_title") or view_report.get("title") or view_report.get("access", {}).get("page_title") or view_report.get("access", {}).get("title")
        expected_url = all_view_urls[view]
        actual_sha = hashlib.sha256(html_bytes).hexdigest()
        expected_sha = view_report.get("sha256") or view_report.get("source_snapshot_sha256")
        if status != "VALID" or http_status != 200:
            raise ValueError(f"El informe no demuestra acceso válido para {view}: status={status}, HTTP={http_status}")
        if requested_url != expected_url or final_url != expected_url:
            raise ValueError(f"URL del informe offline no coincide con la vista {view}: {requested_url} / {final_url}; se esperaba {expected_url}")
        if expected_sha and actual_sha != expected_sha:
            raise ValueError(f"El HTML de {view} no coincide con el SHA-256 del informe")
        if competition.season not in str(title or ""):
            raise ValueError(f"El título del informe para {view} no confirma {competition.season}")
        capture_time = view_report.get("captured_at_utc")
        timestamp_basis = view_report.get("capture_timestamp_basis")
        if capture_time:
            parsed_time = datetime.fromisoformat(str(capture_time).replace("Z", "+00:00"))
        else:
            # A filesystem mtime is only a timestamp for the local evidence file;
            # metadata preserves this basis rather than implying server time.
            parsed_time = datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc)
            timestamp_basis = timestamp_basis or "snapshot file modification time; source navigation time not recorded"
        timestamps.append(parsed_time)
        views[view] = html
        page_titles[view] = str(title)
        access_by_view[view] = {
            "status": status,
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": http_status,
            "page_title": title,
            "reason": view_report.get("reason"),
            "captured_at_utc": parsed_time.astimezone(timezone.utc).isoformat(),
            "capture_timestamp_basis": timestamp_basis,
            "source_snapshot_sha256": actual_sha,
        }
        if view_report.get("browser"):
            browser = view_report["browser"]

    parsed = parse_team_profile_pages(
        views,
        team_catalog_record=team_catalog_record,
        competition_context=competition,
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=team_catalog_record,
        group_team_catalog=group_team_catalog,
        known_matches=known_matches,
        requested_views=requested_views,
    )
    if not validation["valid"]:
        raise ValueError(f"La captura offline no pasó validación: {validation['issues']}")
    return TeamAcquisitionBundle(
        capture_id=str(report.get("capture_id") or create_team_capture_id()),
        captured_at_utc=min(timestamps).astimezone(timezone.utc).isoformat(),
        requested_views=requested_views,
        raw_views=views,
        view_urls={view: all_view_urls[view] for view in requested_views},
        access_by_view=access_by_view,
        page_titles=page_titles,
        browser=browser,
        team_catalog_reference=team_catalog_reference,
        parsed=parsed,
        validation=validation,
        competition=competition,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.inventory_only:
            catalogs = _load_catalogs(args)
            inventory_catalogs = {group: (items, reference) for group, (items, _, reference) in catalogs.items()}
            paths = write_team_inventory(args.output_root, inventory_catalogs, season=args.season)
            print(json.dumps({"teams": 40, "files": {key: str(path) for key, path in paths.items()}}, ensure_ascii=False, indent=2))
            return 0
        if args.team_id is None:
            raise ValueError("--team-id es obligatorio salvo cuando se usa --inventory-only")
        competition = get_competition_context(args.season, args.group)
        path = Path(args.team_catalog).expanduser() if args.team_catalog else _catalog_path(args, args.group)
        group_teams, matches, team_catalog_reference = load_team_catalog(path, competition=competition)
        team_catalog_record = next((team for team in group_teams if int(team["team_id"]) == args.team_id), None)
        if team_catalog_record is None:
            raise ValueError(f"team_id={args.team_id} no está en el catálogo del Grupo {competition.group_roman}")
        requested_views = CORE_VIEWS if args.views == "core" else DEFAULT_VIEWS
        if args.snapshot_dir:
            report_path = args.access_report or args.snapshot_dir.expanduser() / "access.json"
            bundle = _offline_bundle(
                args.snapshot_dir,
                report_path,
                team_catalog_record=team_catalog_record,
                team_catalog_reference=team_catalog_reference,
                group_team_catalog=group_teams,
                known_matches=matches,
                competition=competition,
                requested_views=requested_views,
            )
            timestamp_basis = "per-view access diagnostic timestamp or local snapshot mtime; see raw/access.json"
            profile_dir = None
        else:
            bundle = acquire_team_profile(
                team_catalog_record=team_catalog_record,
                team_catalog_reference=team_catalog_reference,
                group_team_catalog=group_teams,
                known_matches=matches,
                competition=competition,
                profile_dir=args.profile,
                requested_views=requested_views,
                browser="chromium",
                browser_executable_path=args.browser_executable,
                startup_timeout_seconds=args.startup_timeout_seconds,
                navigation_timeout_ms=args.navigation_timeout_ms,
                use_xvfb=args.use_xvfb,
            )
            timestamp_basis = "browser navigation capture time"
            profile_dir = args.profile
        paths = export_team_capture(
            args.output_root,
            bundle,
            profile_dir=profile_dir,
            capture_timestamp_basis=timestamp_basis,
        )
    except TeamAcquisitionStopped as exc:
        diagnostic = {
            "view": exc.view,
            "status": str(exc.assessment.status),
            "http_status": exc.assessment.http_status,
            "requested_url": exc.assessment.requested_url,
            "final_url": exc.assessment.final_url,
            "title": exc.assessment.page_title,
            "reason": exc.assessment.reason,
        }
        print(json.dumps(diagnostic, ensure_ascii=False, indent=2), file=sys.stderr)
        return 4
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"Error en la adquisición de ficha: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({
        "capture_id": bundle.capture_id,
        "team_id": bundle.parsed.identity.team_id,
        "team_name": bundle.parsed.identity.name,
        "captured_at_utc": bundle.captured_at_utc,
        "views": list(bundle.raw_views),
        "validation": bundle.validation["summary"],
        "warnings": bundle.validation["warnings"],
        "files": {name: str(path) for name, path in paths.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
