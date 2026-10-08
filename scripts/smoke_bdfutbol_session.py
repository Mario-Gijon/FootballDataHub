#!/usr/bin/env python3
"""Smoke test sin interfaz: Brave externo + Xvfb + CDP + BDFutbol.

No realiza scraping masivo ni gestiona verificaciones de Cloudflare.
Requiere una sesión previamente autorizada y un perfil no usado por otro Brave.
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


PROFILE_URL = "https://www.bdfutbol.com/es/j/j209629.html"
STATS_URL = PROFILE_URL + "?p=stats"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path.home() / ".football-data-hub-v2-probe")
    parser.add_argument("--browser", choices=("brave", "chrome", "chromium", "auto"), default="brave")
    parser.add_argument("--output-root", type=Path, default=Path("data/analysis/bdfutbol/session_smoke"))
    parser.add_argument("--no-stats", action="store_true", help="Solo comprobar la ficha principal")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = args.output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    config = BrowserRuntimeConfig(
        profile_dir=args.profile,
        browser=args.browser,
        browser_log_path=run_dir / "browser.stderr.log",
    )
    results: list[dict] = []
    failure: str | None = None
    resources = [
        ("player_profile", PROFILE_URL, ("Nombre completo", "Fecha de nacimiento", "Demarcación")),
    ]
    if not args.no_stats:
        resources.append(("player_stats", STATS_URL, ("Partidos Jugados",)))

    try:
        with BrowserSessionManager(config) as session:
            print("Navegador invisible conectado por CDP.")
            access = BDFutbolAccess(session)
            for name, url, markers in resources:
                with access.open(url, required_markers=markers) as result:
                    report = asdict(result.assessment)
                    report["resource"] = name
                    if result.visit is not None:
                        page = result.visit.page
                        report["table_count_diagnostic"] = page.locator("table").count()
                    results.append(report)
                    print(
                        f"{name}: {result.assessment.status} "
                        f"| HTTP={result.assessment.http_status} "
                        f"| tablas={report.get('table_count_diagnostic', 0)}"
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
        "virtual_display": True,
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
