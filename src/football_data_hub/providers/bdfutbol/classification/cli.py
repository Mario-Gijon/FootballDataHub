"""CLI para una captura explícita de clasificación de un grupo."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from .acquisition import AcquisitionStopped, acquire_classification, create_capture_id
from .export import create_run_directory, export_acquisition, write_access_failure
from .models import ClassificationRequest
from ..context import SUPPORTED_SEASON, get_competition_context


def _parse_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError("Usa YYYY-MM-DD o DD/MM/YYYY")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=(SUPPORTED_SEASON,), default=SUPPORTED_SEASON)
    parser.add_argument("--group", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get(
            "FDH_BDFUTBOL_PROFILE", str(Path.home() / ".football-data-hub-chromium-pure-cdp")
        )),
        help="Perfil persistente ya autorizado (o FDH_BDFUTBOL_PROFILE)",
    )
    parser.add_argument(
        "--backend",
        choices=("seleniumbase-pure-cdp", "playwright-cdp"),
        default=os.environ.get("FDH_BDFUTBOL_BROWSER_BACKEND", "seleniumbase-pure-cdp"),
    )
    parser.add_argument(
        "--browser",
        choices=("brave", "chrome", "chromium", "auto"),
        default=os.environ.get("FDH_BDFUTBOL_BROWSER", "chromium"),
    )
    parser.add_argument(
        "--browser-executable",
        type=Path,
        default=Path(os.environ["FDH_BDFUTBOL_BROWSER_EXECUTABLE"])
        if os.environ.get("FDH_BDFUTBOL_BROWSER_EXECUTABLE") else None,
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=float,
        default=os.environ.get("FDH_BDFUTBOL_BROWSER_STARTUP_TIMEOUT_SECONDS", 35.0),
    )
    parser.add_argument(
        "--navigation-timeout-ms",
        type=int,
        default=os.environ.get("FDH_BDFUTBOL_NAVIGATION_TIMEOUT_MS", 45_000),
    )
    parser.add_argument(
        "--no-xvfb",
        action="store_false",
        dest="use_xvfb",
        help="Usa un DISPLAY ya disponible; por defecto se espera Xvfb externo.",
    )
    parser.set_defaults(use_xvfb=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--classification-type", choices=("general", "local", "visitor"), default="general"
    )
    parser.add_argument("--matchday", type=int, help="Jornada 1–38; si se omite se usa la selección actual")
    parser.add_argument("--exclude-postponed", action="store_true")
    parser.add_argument("--range-type", choices=("all", "dates", "rounds"), default="all")
    parser.add_argument("--date-start", type=_parse_date)
    parser.add_argument("--date-end", type=_parse_date)
    parser.add_argument("--round-start", type=int)
    parser.add_argument("--round-end", type=int)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    competition = get_competition_context(args.season, args.group)
    try:
        request = ClassificationRequest(
            classification_type=args.classification_type,
            matchday=args.matchday,
            include_postponed=not args.exclude_postponed,
            range_type=args.range_type,
            date_start=args.date_start,
            date_end=args.date_end,
            round_start=args.round_start,
            round_end=args.round_end,
        )
    except ValueError as exc:
        print(f"Parámetros inválidos: {exc}", file=sys.stderr)
        return 2

    capture_id = create_capture_id()
    output_root = args.output_root
    if output_root is None:
        group_env = f"FDH_BDFUTBOL_{competition.group_key.upper()}_CLASSIFICATION_OUTPUT"
        configured_root = os.environ.get(group_env)
        if not configured_root and competition.group_number == 2:
            configured_root = os.environ.get("FDH_BDFUTBOL_CLASSIFICATION_OUTPUT")
        output_root = Path(
            configured_root
            or competition.export_directory(
                Path("data/exports/bdfutbol"), "classification"
            )
        )
    run_dir = create_run_directory(output_root, capture_id)
    browser_log = run_dir / "logs" / "browser.stderr.log"
    browser_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        bundle = acquire_classification(
            request=request,
            competition=competition,
            profile_dir=args.profile,
            backend=args.backend,
            browser=args.browser,
            browser_executable_path=args.browser_executable,
            startup_timeout_seconds=args.startup_timeout_seconds,
            navigation_timeout_ms=args.navigation_timeout_ms,
            use_xvfb=args.use_xvfb,
            browser_log_path=browser_log,
            capture_id=capture_id,
        )
    except AcquisitionStopped as exc:
        assessment = asdict(exc.assessment)
        failure_path = write_access_failure(run_dir, assessment)
        print(f"{exc}\nDiagnóstico: {failure_path}", file=sys.stderr)
        return 4
    except Exception as exc:
        failure_path = run_dir / "metadata" / "failure.json"
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        with failure_path.open("x", encoding="utf-8") as failure_file:
            failure_file.write(json.dumps(
                {"capture_id": capture_id, "error_type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ) + "\n")
        print(f"Error de adquisición: {type(exc).__name__}: {exc}\nDiagnóstico: {failure_path}", file=sys.stderr)
        return 3

    paths = export_acquisition(
        run_dir,
        bundle,
        request,
        browser=args.browser,
        profile_dir=args.profile,
    )
    print(json.dumps({
        "capture_id": capture_id,
        "classification_rows": len(bundle.parsed.standings),
        "group": competition.group_label,
        "season": competition.season,
        "progress_records": len(bundle.parsed.progress),
        "played_matchdays": bundle.parsed.played_matchdays,
        "validation": bundle.validation["summary"],
        "files": {name: str(path) for name, path in paths.items()},
    }, ensure_ascii=False, indent=2))
    return 0 if bundle.validation["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
