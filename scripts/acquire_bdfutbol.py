#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from football_data_hub.bdfutbol.acquisition import (
    AcquisitionStatus,
    BDFutbolAcquirer,
)
from football_data_hub.bdfutbol.cli import _assessment_diagnostic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Adquiere una URL de BDFutbol con navegador real, perfil persistente "
            "y warm-up/reintentos automáticos frente a verificaciones pasivas."
        )
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--profile",
        default=str(Path.home() / ".football-data-hub-browser"),
    )
    parser.add_argument(
        "--browser",
        choices=("auto", "brave", "chrome", "chromium"),
        default="auto",
    )
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--settle-ms", type=int, default=3_000)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--warmup-seconds", type=float, default=10.0)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.5)
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help="Texto visible que debe estar presente. Puede repetirse.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]

    acquirer = BDFutbolAcquirer(
        project_root=project_root,
        profile=Path(args.profile),
        browser=args.browser,
        timeout_ms=args.timeout_ms,
        settle_ms=args.settle_ms,
        max_attempts=args.max_attempts,
        warmup_seconds=args.warmup_seconds,
        retry_delay_seconds=args.retry_delay_seconds,
    )

    print("=== BDFUTBOL AUTOMATIC ACQUISITION ===")
    print(f"URL:           {args.url}")
    print(f"Nombre:        {args.name}")
    print(f"Perfil:        {Path(args.profile).expanduser()}")
    print(f"Intentos máx.: {args.max_attempts}")
    print(f"Warm-up:       {args.warmup_seconds:.1f}s")
    print()

    result = acquirer.acquire(
        url=args.url,
        name=args.name,
        expected_texts=args.expect,
    )

    for item in result.attempts:
        detail = ""
        if item.http_status_diagnostic is not None:
            detail += f" http={item.http_status_diagnostic}"
        if item.assessment:
            detail += (
                f" challenge={item.assessment['challenge_visible']}"
                f" links={item.assessment['link_count']}"
            )
        if item.url_matches_target is not None:
            detail += f" url_matches_target={item.url_matches_target}"
        if item.browser_error:
            detail += f" error={item.browser_error}"
        print(
            f"[{item.phase:<7}] #{item.number} {item.status.value:<18}{detail}"
        )
        if item.status is not AcquisitionStatus.VALID and item.assessment:
            for line in _assessment_diagnostic(item.assessment):
                print(f"           {line}")
        if item.requested_url is not None:
            print(f"           requested_url={item.requested_url}")
        if item.final_url is not None:
            print(f"           final_url={item.final_url}")

    print()
    print(f"Estado final: {result.status.value}")
    print(f"Run:          {result.run_directory}")

    if result.valid_snapshot_directory is not None:
        print(f"Snapshot:     {result.valid_snapshot_directory}")
        print(f"HTML válido:  {result.valid_snapshot_directory / 'page.html'}")
        return 0

    if result.status is AcquisitionStatus.BLOCKED:
        print(
            "Cloudflare siguió mostrando una verificación tras los reintentos. "
            "El run queda registrado y no se entrega ese HTML al parser."
        )
        return 3

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
