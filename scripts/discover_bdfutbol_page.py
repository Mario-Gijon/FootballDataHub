#!/usr/bin/env python3
"""Hito 0A: captura no interactiva de páginas representativas de BDFutbol.

Requiere la sesión previamente autorizada del Hito 1A. No pulsa controles,
no cambia filtros y no intenta resolver desafíos anti-bot.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import AccessStatus, BDFutbolAccess
from football_data_hub.providers.bdfutbol.discovery import (
    InventoryLimits,
    assert_safe_token,
    capture_dom_snapshot,
    timestamp_utc,
    write_json,
)


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    url: str
    markers: tuple[str, ...]


# El primer piloto se limita a las dos vistas de un mismo jugador.
# Los demás tipos de entidad se incorporan en hitos posteriores, una vez auditados.
TARGETS: dict[str, Target] = {
    "morillas": Target(
        "morillas", "https://www.bdfutbol.com/es/j/j209629.html",
        ("Nombre completo", "Fecha de nacimiento", "Demarcación"),
    ),
    "morillas_stats": Target(
        "morillas_stats", "https://www.bdfutbol.com/es/j/j209629.html?p=stats",
        ("Partidos Jugados",),
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", choices=tuple(TARGETS), help="Repetible; por defecto solo morillas")
    parser.add_argument("--profile", type=Path, default=Path.home() / ".football-data-hub-v2-probe")
    parser.add_argument("--browser", choices=("brave", "chrome", "chromium", "auto"), default="brave")
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/bdfutbol/discovery_0a"))
    parser.add_argument("--analysis-root", type=Path, default=Path("data/analysis/bdfutbol/discovery_0a"))
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--max-links", type=int, default=1500)
    parser.add_argument("--max-tables", type=int, default=180)
    parser.add_argument("--max-images", type=int, default=500)
    parser.add_argument("--max-controls", type=int, default=500)
    parser.add_argument("--max-options", type=int, default=500)
    parser.add_argument("--settle-ms", type=int, default=1000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    limits = InventoryLimits(
        max_links=args.max_links,
        max_tables=args.max_tables,
        max_images=args.max_images,
        max_controls=args.max_controls,
        max_options=args.max_options,
    )
    if args.settle_ms < 0:
        raise ValueError("--settle-ms debe ser >= 0")
    target_names = tuple(dict.fromkeys(args.target or ["morillas"]))
    for name in target_names:
        assert_safe_token(name)
    run_id = timestamp_utc()
    raw_dir = args.raw_root / run_id
    analysis_dir = args.analysis_root / run_id
    raw_dir.mkdir(parents=True, exist_ok=False)
    analysis_dir.mkdir(parents=True, exist_ok=False)
    config = BrowserRuntimeConfig(
        profile_dir=args.profile,
        browser=args.browser,
        browser_log_path=analysis_dir / "browser.stderr.log",
    )
    reports: list[dict] = []
    error: str | None = None
    try:
        with BrowserSessionManager(config) as session:
            print("[0A] Brave/Xvfb/CDP conectado; modo solo lectura.")
            access = BDFutbolAccess(session)
            for name in target_names:
                target = TARGETS[name]
                with access.open(target.url, required_markers=target.markers,
                                 settle_ms=args.settle_ms) as result:
                    assessment = result.assessment
                    entry = {
                        "target": target.name,
                        "url": target.url,
                        "assessment": asdict(assessment),
                        "snapshot": None,
                    }
                    reports.append(entry)
                    if assessment.status is not AccessStatus.VALID or result.visit is None:
                        print(f"[0A] {name}: {assessment.status} — sin captura válida")
                        break  # No seguir insistiendo si el acceso se ha bloqueado.
                    output = raw_dir / assert_safe_token(name)
                    metadata = capture_dom_snapshot(
                        page=result.visit.page, assessment=assessment,
                        output_dir=output, limits=limits, screenshot=args.screenshots,
                    )
                    entry["snapshot"] = str(output)
                    entry["summary"] = metadata["inventory_summary"]
                    counts = metadata["inventory_summary"]["counts"]
                    print(
                        f"[0A] {name}: VALID | tablas={counts['tables']} "
                        f"selects={counts['selects']} tabs={counts['tabs']} "
                        f"imagenes={counts['images']} enlaces={counts['links']}"
                    )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"[0A] ERROR: {error}")
    finally:
        summary_path = analysis_dir / "summary.json"
        write_json(summary_path, {
            "hito": "0A", "run_id": run_id,
            "scope": "DOM_SNAPSHOT_ONLY", "complete": False,
            "targets_requested": list(target_names), "results": reports,
            "fatal_error": error, "raw_directory": str(raw_dir),
        })
        print(f"[0A] Informe: {summary_path}")
    if error:
        return 3
    return 0 if len(reports) == len(target_names) and all(
        item["assessment"]["status"] == AccessStatus.VALID.value and item["snapshot"]
        for item in reports
    ) else 4


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
