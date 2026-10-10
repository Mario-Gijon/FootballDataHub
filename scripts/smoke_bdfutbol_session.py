#!/usr/bin/env python3
"""Smoke test controlado del acceso a BDFutbol con el backend configurado.

No realiza scraping masivo ni gestiona verificaciones de Cloudflare.
Requiere acceso previamente autorizado y un perfil no usado por otro proceso.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import BDFutbolAccess, AccessStatus
from football_data_hub.providers.bdfutbol.classification.acquisition import CLASSIFICATION_URL
from football_data_hub.providers.bdfutbol.classification.parser import validate_page_structure


PROFILE_URL = "https://www.bdfutbol.com/es/j/j209629.html"
STATS_URL = PROFILE_URL + "?p=stats"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path.home() / ".football-data-hub-chromium-pure-cdp")
    parser.add_argument(
        "--backend",
        choices=("seleniumbase-pure-cdp", "playwright-cdp"),
        default="seleniumbase-pure-cdp",
    )
    parser.add_argument("--browser", choices=("brave", "chrome", "chromium", "auto"), default="chromium")
    parser.add_argument("--output-root", type=Path, default=Path("data/analysis/bdfutbol/session_smoke"))
    parser.add_argument("--no-stats", action="store_true", help="Solo comprobar la ficha principal")
    parser.add_argument(
        "--group2-classification",
        action="store_true",
        help="Comprobar la clasificación Grupo II (marcador de temporada 2026-27)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = args.output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    config = BrowserRuntimeConfig(
        profile_dir=args.profile,
        backend=args.backend,
        browser=args.browser,
        browser_log_path=run_dir / "browser.stderr.log",
    )
    results: list[dict] = []
    failure: str | None = None
    browser_info: dict | None = None
    if args.group2_classification:
        resources = [
            (
                "group2_classification",
                CLASSIFICATION_URL,
                ("Clasificación", "Grupo II"),
            ),
        ]
    else:
        resources = [
            ("player_profile", PROFILE_URL, ("Nombre completo", "Fecha de nacimiento", "Demarcación")),
        ]
        if not args.no_stats:
            resources.append(("player_stats", STATS_URL, ("Partidos Jugados",)))

    try:
        with BrowserSessionManager(config) as session:
            print("Navegador iniciado en la pantalla configurada y conectado por CDP.")
            browser_info = asdict(session.info) if session.info else None
            access = BDFutbolAccess(session)
            for name, url, markers in resources:
                access_options = {}
                if name == "group2_classification":
                    access_options = {
                        "required_title_markers": ("Grupo II", "2026-27"),
                        "required_selectors": ("table#classific",),
                        "document_validator": validate_page_structure,
                        "max_wait_seconds": 0,
                    }
                with access.open(url, required_markers=markers, **access_options) as result:
                    report = asdict(result.assessment)
                    report["resource"] = name
                    if result.visit is not None:
                        page = result.visit.document
                        report["table_count_diagnostic"] = page.count("table")
                        if name == "group2_classification":
                            ids = page.evaluate(
                                "Array.from(document.querySelectorAll('#classific tr[data-ideq]'))"
                                ".map(row => row.getAttribute('data-ideq'))"
                            )
                            report["classification_team_count"] = len(ids)
                            report["unique_team_ids"] = len(set(ids))
                            html = page.html()
                            report["source_markers"] = {
                                marker: marker in html for marker in ("SP", "SE", 'id="resultats"')
                            }
                            report["result_match_rows"] = page.count(
                                "#resultats tr.jornadai"
                            )
                    results.append(report)
                    print(
                        f"{name}: {result.assessment.status} "
                        f"| HTTP={result.assessment.http_status} "
                        f"| tablas={report.get('table_count_diagnostic', 0)}"
                    )
                    if name == "group2_classification":
                        print(
                            f"equipos={report.get('classification_team_count', 0)} "
                            f"| IDs únicos={report.get('unique_team_ids', 0)}"
                        )
                    if result.assessment.status is not AccessStatus.VALID:
                        print("Se detiene la prueba: el acceso no está validado.")
                        break
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        print(f"Error de arranque/sesión: {failure}")
    summary = {
        "run_id": run_id,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "browser": args.browser,
        "backend": args.backend,
        "browser_info": browser_info,
        "virtual_display_requested": config.use_xvfb,
        "planned_resources": len(resources),
        "results": results,
        "fatal_error": failure,
    }
    output = run_dir / "summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Informe: {output}")
    if failure:
        return 3
    return 0 if len(results) == len(resources) and all(r["status"] == AccessStatus.VALID for r in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
