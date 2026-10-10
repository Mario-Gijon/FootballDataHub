"""Captura o normaliza una captura local de la pestaña Destacados."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .acquisition import (
    TopAcquisitionBundle,
    TopAcquisitionStopped,
    acquire_top,
    create_top_capture_id,
)
from .export import create_run_directory, export_top_capture
from .parser import parse_top_page
from .validation import validate_top_data
from ..context import SUPPORTED_SEASON, get_competition_context

_DEFAULT_GROUP2_TEAM_DATASET = Path(
    "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"
)


def _load_team_catalog(path: Path, *, competition=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    competition = competition or get_competition_context(group=2)
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if payload.get("schema_version") not in {1, 2} or not payload.get("teams"):
        raise ValueError(f"Catálogo de equipos inválido: {path}")
    metadata = payload.get("metadata", {})
    if (
        metadata.get("group") != competition.group_roman
        or metadata.get("season") != competition.season
    ):
        raise ValueError(
            f"El catálogo {path} es de {metadata.get('group')} {metadata.get('season')}; "
            f"se requiere {competition.group_label} {competition.season}"
        )
    reference = {
        "path": path.as_posix(),
        "group": metadata.get("group"),
        "source_capture_id": metadata.get("source_capture_id"),
        "source_captured_at_utc": metadata.get("source_captured_at_utc"),
        "sha256": hashlib.sha256(path.expanduser().read_bytes()).hexdigest(),
    }
    return payload["teams"], reference


def _offline_bundle(
    snapshot_path: Path,
    report_path: Path,
    teams: list[dict[str, Any]],
    *,
    competition=None,
) -> tuple[TopAcquisitionBundle, str]:
    competition = competition or get_competition_context(group=2)
    snapshot_path = snapshot_path.expanduser()
    report_path = report_path.expanduser()
    source_html = snapshot_path.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    access = report.get("access", {})
    requested_url = report.get("requested_url") or access.get("requested_url") or report.get("url")
    final_url = report.get("final_url") or access.get("final_url")
    title = report.get("title") or access.get("page_title", "")
    if (
        access.get("status") != "VALID"
        or access.get("http_status") != 200
        or requested_url != competition.section_url("top")
        or final_url != competition.section_url("top")
        or competition.group_label not in title
        or competition.season not in title
    ):
        raise ValueError(
            f"El informe no demuestra una captura válida de Destacados "
            f"{competition.group_label} {competition.season}"
        )
    actual_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    expected_sha256 = report.get("source_snapshot_sha256")
    if expected_sha256 and expected_sha256 != actual_sha256:
        raise ValueError("El HTML no coincide con el SHA-256 declarado en los metadatos")
    parsed = parse_top_page(
        source_html,
        team_catalog=teams,
        base_url=competition.section_url("top"),
    )
    validation = validate_top_data(parsed)
    if not validation["valid"]:
        raise ValueError(f"La captura offline no pasó validación: {validation['issues']}")
    browser = report.get("browser", {})
    normalized_access = {
        "status": access.get("status"),
        "requested_url": access.get("requested_url", report.get("requested_url")),
        "final_url": access.get("final_url", report.get("final_url")),
        "http_status": access.get("http_status"),
        "page_title": access.get("page_title", report.get("title")),
        "reason": access.get("reason"),
    }
    bundle = TopAcquisitionBundle(
        capture_id=str(report.get("capture_id") or create_top_capture_id()),
        captured_at_utc=report.get("captured_at_utc") or datetime.fromtimestamp(
            snapshot_path.stat().st_mtime, timezone.utc
        ).isoformat(),
        raw_html=source_html,
        page_title=str(title),
        access=normalized_access,
        browser=browser,
        parsed=parsed,
        validation=validation,
        competition=competition,
    )
    basis = report.get("capture_timestamp_basis") or (
        "source_html filesystem modification time; browser report omitted capture timestamp"
    )
    return bundle, basis


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=(SUPPORTED_SEASON,), default=SUPPORTED_SEASON)
    parser.add_argument("--group", type=int, choices=(1, 2), default=2)
    parser.add_argument("--team-catalog", type=Path)
    parser.add_argument(
        "--output-root", type=Path, default=None,
    )
    parser.add_argument(
        "--snapshot", type=Path,
        help="Normaliza HTML guardado en vez de abrir el navegador.",
    )
    parser.add_argument("--access-report", type=Path, help="Informe de una adquisición válida para --snapshot.")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        competition = get_competition_context(args.season, args.group)
        match_env = os.environ.get(f"FDH_BDFUTBOL_{competition.group_key.upper()}_MATCHES")
        if args.team_catalog:
            team_catalog_path = args.team_catalog
        elif match_env:
            team_catalog_path = Path(match_env)
        elif competition.group_number == 2:
            team_catalog_path = _DEFAULT_GROUP2_TEAM_DATASET
        else:
            team_catalog_path = None
        if team_catalog_path is None:
            raise ValueError(
                "Grupo I requiere --team-catalog con su propio normalized/matches.json"
            )
        teams, team_reference = _load_team_catalog(
            team_catalog_path,
            competition=competition,
        )
        output_root = args.output_root or Path(
            os.environ.get(
                f"FDH_BDFUTBOL_{competition.group_key.upper()}_TOP_OUTPUT",
                os.environ.get("FDH_BDFUTBOL_TOP_OUTPUT")
                if competition.group_number == 2
                else None,
            )
            or competition.export_directory(Path("data/exports/bdfutbol"), "top")
        )
        if args.snapshot:
            if not args.access_report:
                raise ValueError("El modo offline requiere --access-report de la captura")
            bundle, capture_basis = _offline_bundle(
                args.snapshot,
                args.access_report,
                teams,
                competition=competition,
            )
        else:
            bundle = acquire_top(
                team_catalog=teams,
                competition=competition,
                profile_dir=args.profile,
                browser="chromium",
                browser_executable_path=args.browser_executable,
                startup_timeout_seconds=args.startup_timeout_seconds,
                navigation_timeout_ms=args.navigation_timeout_ms,
                use_xvfb=args.use_xvfb,
            )
            capture_basis = "browser acquisition time"
        run_dir = create_run_directory(output_root, bundle.capture_id)
        paths = export_top_capture(
            run_dir,
            bundle,
            profile_dir=None if args.snapshot else args.profile,
            team_catalog_reference=team_reference,
            capture_timestamp_basis=capture_basis,
        )
    except TopAcquisitionStopped as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error en la captura de Destacados: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({
        "capture_id": bundle.capture_id,
        "captured_at_utc": bundle.captured_at_utc,
        "validation": bundle.validation["summary"],
        "category_source_counts": bundle.parsed.category_source_counts,
        "files": {name: str(path) for name, path in paths.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
