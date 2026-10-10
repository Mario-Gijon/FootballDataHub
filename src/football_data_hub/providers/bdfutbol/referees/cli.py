"""Captura una vez o vuelve a normalizar una captura local de Árbitros."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlsplit

from .acquisition import (
    RefereeAcquisitionBundle,
    RefereeAcquisitionStopped,
    RefereeScopeSnapshot,
    acquire_referee_pages,
    create_referee_capture_id,
)
from .export import create_run_directory, export_referee_capture
from .models import ParsedReferees, RefereeScope
from .parser import parse_referee_page, merge_referee_pages
from .validation import build_match_reference_report, validate_referee_data

_DEFAULT_MATCHES = Path(
    "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"
)
_SCOPES: tuple[RefereeScope, ...] = ("all", "group1", "group2")
_EXPECTED_SCOPE_PATH = {
    "all": "t2026-271rf2.html",
    "group1": "t2026-271rf1.html",
    "group2": "t2026-271rf2.html",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_match_reference(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError(f"Dataset de partidos sin una lista matches: {path}")
    metadata = payload.get("metadata", {})
    reference = {
        "path": path.as_posix(),
        "source_capture_id": metadata.get("source_capture_id"),
        "source_captured_at_utc": metadata.get("source_captured_at_utc"),
        "sha256": _sha256(path),
    }
    return payload, reference


def _read_offline_bundle(snapshot_dir: Path, access_report: Path | None) -> RefereeAcquisitionBundle:
    snapshot_dir = snapshot_dir.expanduser().resolve()
    report_path = (access_report.expanduser() if access_report else snapshot_dir / "metadata" / "capture.json")
    metadata = json.loads(report_path.read_text(encoding="utf-8"))
    if metadata.get("source") != "BDFutbol" or metadata.get("season") != "2026-27":
        raise ValueError("El informe no describe una captura de BDFutbol 2026-27")
    scope_metadata = metadata.get("scope_captures")
    if not isinstance(scope_metadata, dict) or set(scope_metadata) != set(_SCOPES):
        raise ValueError("El informe debe validar los tres ámbitos: all, group1 y group2")

    pages: list[RefereeScopeSnapshot] = []
    for scope in _SCOPES:
        item = scope_metadata[scope]
        access = item.get("access", {})
        requested_url = item.get("requested_url")
        final_url = item.get("final_url")
        parts = urlsplit(str(requested_url or ""))
        if (
            access.get("status") != "VALID"
            or item.get("http_status") != 200
            or requested_url != final_url
            or parts.scheme != "https"
            or parts.hostname != "www.bdfutbol.com"
            or not parts.path.endswith(_EXPECTED_SCOPE_PATH[scope])
            or parse_qs(parts.query).get("tab") != ["referees"]
            or (scope != "all" and parse_qs(parts.query).get("grups") != ["1"])
        ):
            raise ValueError(f"El informe no demuestra acceso válido para {scope}")
        expected_group_title = "Grupo I" if scope == "group1" else "Grupo II"
        if expected_group_title not in str(item.get("page_title", "")):
            raise ValueError(f"El título no confirma el ámbito {scope}")
        relative_file = Path(str(item.get("file", "")))
        if relative_file.is_absolute() or ".." in relative_file.parts:
            raise ValueError(f"Ruta de snapshot inválida para {scope}")
        source_path = (snapshot_dir / relative_file).resolve()
        if snapshot_dir not in source_path.parents:
            raise ValueError(f"Snapshot fuera del directorio de captura: {source_path}")
        source_html = source_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(source_html.encode("utf-8")).hexdigest()
        if digest != item.get("source_snapshot_sha256"):
            raise ValueError(f"El hash del snapshot {scope} no coincide con el informe")
        if "2026-27" not in str(item.get("page_title", "")):
            raise ValueError(f"Título de temporada incorrecto en el snapshot {scope}")
        page = RefereeScopeSnapshot(
            scope=scope,
            requested_url=requested_url,
            final_url=final_url,
            captured_at_utc=str(item.get("captured_at_utc") or metadata.get("captured_at_utc")),
            page_title=str(item.get("page_title", "")),
            http_status=item.get("http_status"),
            access=access,
            raw_html=source_html,
        )
        parse_referee_page(source_html, scope=scope, source_url=requested_url)
        pages.append(page)
    source_capture_time = min(
        datetime.fromisoformat(page.captured_at_utc)
        for page in pages
    ).astimezone(timezone.utc).isoformat()
    return RefereeAcquisitionBundle(
        capture_id=create_referee_capture_id(),
        captured_at_utc=source_capture_time,
        pages=tuple(pages),
        browser=metadata.get("browser", {}),
        profile_dir=None,
        parent_capture_id=metadata.get("capture_id"),
    )


def _normalize_bundle(bundle: RefereeAcquisitionBundle) -> ParsedReferees:
    parsed_pages = tuple(
        parse_referee_page(page.raw_html, scope=page.scope, source_url=page.requested_url)
        for page in bundle.pages
    )
    return merge_referee_pages(parsed_pages)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matches",
        type=Path,
        default=Path(os.environ.get("FDH_BDFUTBOL_GROUP2_MATCHES", _DEFAULT_MATCHES)),
        help="Dataset RES-01 para el cruce offline por referee_id.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get(
            "FDH_BDFUTBOL_GROUP2_REFEREES_OUTPUT",
            "data/exports/bdfutbol/group2_referees",
        )),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get(
            "FDH_BDFUTBOL_PROFILE",
            str(Path.home() / ".football-data-hub-chromium-pure-cdp"),
        )),
    )
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--startup-timeout-seconds", type=float, default=35.0)
    parser.add_argument("--navigation-timeout-ms", type=int, default=45_000)
    parser.add_argument("--no-xvfb", action="store_false", dest="use_xvfb")
    parser.set_defaults(use_xvfb=True)
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        help="Normaliza offline una captura REF-01 existente, en vez de abrir Chromium.",
    )
    parser.add_argument(
        "--access-report",
        type=Path,
        help="Informe metadata/capture.json asociado a --snapshot-dir.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        match_payload, _ = _load_match_reference(args.matches)
        if args.snapshot_dir:
            bundle = _read_offline_bundle(args.snapshot_dir, args.access_report)
        else:
            bundle = acquire_referee_pages(
                profile_dir=args.profile,
                browser_executable_path=args.browser_executable,
                startup_timeout_seconds=args.startup_timeout_seconds,
                navigation_timeout_ms=args.navigation_timeout_ms,
                use_xvfb=args.use_xvfb,
            )
        parsed = _normalize_bundle(bundle)
        validation = validate_referee_data(parsed)
        if not validation["valid"]:
            raise ValueError(f"Validación de Árbitros fallida: {validation['issues']}")
        matches_reference_report = build_match_reference_report(
            parsed,
            match_payload,
            reference_path=args.matches.as_posix(),
            reference_sha256=_sha256(args.matches.expanduser()),
        )
        run_dir = create_run_directory(args.output_root, bundle.capture_id)
        paths = export_referee_capture(
            run_dir,
            bundle,
            parsed,
            validation=validation,
            match_reference_report=matches_reference_report,
        )
    except RefereeAcquisitionStopped as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps(asdict(exc.assessment), ensure_ascii=False, default=str), file=sys.stderr)
        return 4
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error en la captura de Árbitros: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({
        "capture_id": bundle.capture_id,
        "parent_capture_id": bundle.parent_capture_id,
        "captured_at_utc": bundle.captured_at_utc,
        "referee_count": len(parsed.referees),
        "scope_counts": parsed.scope_counts,
        "statistics_count": len(parsed.statistics),
        "validation": validation["valid"],
        "match_reference_status": matches_reference_report["status"],
        "match_reference_counts": matches_reference_report["counts"],
        "files": {name: str(path) for name, path in paths.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
