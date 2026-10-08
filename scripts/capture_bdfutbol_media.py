#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from football_data_hub.bdfutbol.browser import (
    BrowserRuntimeError,
    start_browser,
    stop_browser,
)
from football_data_hub.bdfutbol.media_capture import (
    capture_candidates,
    fetch_image_with_browser_page,
    load_json,
)
from football_data_hub.bdfutbol.validation import (
    assess_page,
)

if __package__:
    from . import sync_bdfutbol_team_season as team_sync
else:
    import sync_bdfutbol_team_season as team_sync


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga únicamente media de entidad aceptada por "
            "audit_bdfutbol_media.py, la deduplica por SHA-256 y "
            "genera un manifest auditable."
        )
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--team-id", required=True, type=int)
    parser.add_argument(
        "--run-dir",
        help=(
            "Run team_full exacto. Si se omite, usa el más reciente."
        ),
    )
    parser.add_argument(
        "--audit",
        help=(
            "Ruta a media_audit.json. Default: "
            "<run>/analysis/media_audit.json"
        ),
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help=(
            "Incluye candidatos REVIEW. Por defecto SOLO descarga ACCEPT."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
    )
    parser.add_argument(
        "--max-mb",
        type=float,
        default=20.0,
        help="Tamaño máximo por imagen. Default: 20 MB.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.05,
        help="Pausa entre URLs. Default: 0.05 s.",
    )
    parser.add_argument(
        "--challenge-wait-seconds",
        type=float,
        default=12.0,
        help="Espera pasiva máxima del preflight BDFutbol.",
    )
    parser.add_argument(
        "--browser",
        choices=("auto", "brave", "chrome", "chromium"),
        default="auto",
    )
    parser.add_argument(
        "--profile",
        default=str(Path.home() / ".football-data-hub-browser"),
    )
    return parser.parse_args(argv)


def _resolve_run(
    *,
    project_root: Path,
    season: str,
    team_id: int,
    requested: str | None,
) -> Path:
    if requested:
        path = Path(requested)
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            raise FileNotFoundError(path)
        return path.resolve()

    base = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"team_full_{season}_{team_id}"
    )
    if not base.exists():
        raise FileNotFoundError(base)

    runs = sorted(path for path in base.iterdir() if path.is_dir())
    if not runs:
        raise FileNotFoundError(f"No hay runs en {base}")

    return runs[-1].resolve()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]

    try:
        run_dir = _resolve_run(
            project_root=project_root,
            season=args.season,
            team_id=args.team_id,
            requested=args.run_dir,
        )
    except FileNotFoundError as exc:
        print(f"Error: no existe {exc}")
        return 2

    audit_path = (
        Path(args.audit)
        if args.audit
        else run_dir / "analysis" / "media_audit.json"
    )
    if not audit_path.is_absolute():
        audit_path = project_root / audit_path

    if not audit_path.exists():
        print(
            "Error: falta media_audit.json. Ejecuta primero "
            "scripts/audit_bdfutbol_media.py"
        )
        return 2

    if args.max_mb <= 0:
        print("Error: --max-mb debe ser > 0")
        return 2
    if args.timeout_seconds <= 0:
        print("Error: --timeout-seconds debe ser > 0")
        return 2
    if args.delay_seconds < 0:
        print("Error: --delay-seconds debe ser >= 0")
        return 2

    audit = load_json(audit_path)
    object_root = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / "media"
        / "objects"
    )

    print("=== BDFUTBOL MEDIA CAPTURE ===")
    print(f"Run:          {run_dir.relative_to(project_root)}")
    print(f"Audit:        {audit_path.relative_to(project_root)}")
    print(
        "Decisiones:    "
        + ("ACCEPT + REVIEW" if args.include_review else "solo ACCEPT")
    )

    base_url = (
        f"https://www.bdfutbol.com/es/t/"
        f"t{args.season}{args.team_id}.html"
    )

    try:
        runtime = start_browser(
            profile=Path(args.profile),
            preference=args.browser,
            start_url=base_url,
        )
    except BrowserRuntimeError as exc:
        print(f"No se pudo iniciar navegador: {exc}")
        return 3

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                runtime.cdp_url
            )
            if not browser.contexts:
                print("El navegador no expone ningún contexto.")
                return 3

            context = browser.contexts[0]
            preflight_page = team_sync._find_same_origin_page(
                context.pages,
                base_url,
            )

            if preflight_page is None:
                deadline = time.monotonic() + 5.0
                while (
                    time.monotonic() < deadline
                    and preflight_page is None
                ):
                    time.sleep(0.25)
                    preflight_page = team_sync._find_same_origin_page(
                        context.pages,
                        base_url,
                    )

            if preflight_page is None:
                print("No apareció ninguna pestaña BDFutbol.")
                return 3

            assessment, preflight_status = (
                team_sync._wait_for_bdfutbol_session(
                    preflight_page,
                    url=base_url,
                    wait_seconds=args.challenge_wait_seconds,
                )
            )
            print(
                f"[preflight] {preflight_status:<18} "
                f"challenge={assessment.challenge_visible} "
                f"links={assessment.link_count}"
            )
            print(f"            final_url={preflight_page.url}")

            if preflight_status != "VALID":
                print(
                    "La sesión persistente no está válida. "
                    "No se intentará descargar media."
                )
                return 3

            media_page = context.new_page()
            try:
                def browser_fetcher(
                    url: str,
                    *,
                    referer: str | None = None,
                    timeout_seconds: float = 20.0,
                    max_bytes: int = 20 * 1024 * 1024,
                ):
                    return fetch_image_with_browser_page(
                        media_page,
                        url,
                        referer=referer,
                        timeout_seconds=timeout_seconds,
                        max_bytes=max_bytes,
                    )

                result = capture_candidates(
                    audit=audit,
                    project_root=project_root,
                    source_audit=audit_path,
                    object_root=object_root,
                    include_review=args.include_review,
                    timeout_seconds=args.timeout_seconds,
                    max_bytes=int(args.max_mb * 1024 * 1024),
                    delay_seconds=args.delay_seconds,
                    fetcher=browser_fetcher,
                )
            finally:
                try:
                    media_page.close()
                except Exception:
                    pass
    finally:
        stop_browser(runtime)

    manifest_path = run_dir / "analysis" / "media_capture.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("=== RESULTADO ===")
    print(f"Candidatos:       {result['candidates_selected']}")
    print(f"URLs descargadas: {result['urls_downloaded']}")
    print(f"Fallidas:         {result['urls_failed']}")
    print(f"Binarios únicos:  {result['unique_binary_assets']}")
    print(f"Objetos nuevos:   {result['new_objects_written']}")
    print(f"Objetos reusados: {result['existing_objects_reused']}")
    print(f"Manifest:         {manifest_path}")

    if result["failures"]:
        print("\n=== FALLOS ===")
        for failure in result["failures"]:
            print(
                f"{failure['source_url']} "
                f"-> {failure['error']}"
            )

    return 0 if result["urls_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
