#!/usr/bin/env python3
"""Acquire and validate the supported Primera Federación group sequentially.

Each BDFutbol visit is a separate subprocess using the existing serialized
Pure CDP profile. This command never launches section visits concurrently and
never promotes a capture to the API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

from football_data_hub.providers.bdfutbol.context import (
    SUPPORTED_SEASON,
    CompetitionContext,
    get_competition_context,
)
from football_data_hub.providers.bdfutbol.referees.models import RefereeScope
from football_data_hub.providers.bdfutbol.referees.parser import (
    merge_referee_pages,
    parse_referee_page,
)
from football_data_hub.providers.bdfutbol.referees.validation import (
    build_match_reference_report,
    validate_referee_data,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFEREES_CAPTURE = Path(
    "data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc"
)
_SCOPES: tuple[RefereeScope, ...] = ("all", "group1", "group2")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_exclusive(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _capture_directories(root: Path) -> set[Path]:
    if not root.is_dir():
        return set()
    return {path for path in root.iterdir() if path.is_dir()}


def _run_cli(
    *,
    section: str,
    command: list[str],
    capture_root: Path,
    expect_capture: bool = True,
) -> dict[str, Any]:
    """Run one acquisition to completion before the next can start."""
    before = _capture_directories(capture_root)
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return {
            "section": section,
            "status": "error",
            "return_code": None,
            "error": f"{type(exc).__name__}: {exc}",
            "command": command,
        }
    after = _capture_directories(capture_root)
    created = sorted(after - before)
    status = "valid" if completed.returncode == 0 else "error"
    result: dict[str, Any] = {
        "section": section,
        "status": status,
        "return_code": completed.returncode,
        "command": command,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    if len(created) == 1:
        result["capture_path"] = created[0].as_posix()
        result["capture_id"] = created[0].name
    elif len(created) > 1:
        result["status"] = "error"
        result["error"] = f"La CLI creó {len(created)} capturas para una sola sección"
    if expect_capture and completed.returncode == 0 and len(created) != 1:
        result["status"] = "error"
        result["error"] = "La CLI no produjo exactamente una captura versionada"
    if not expect_capture and completed.returncode == 0 and created:
        result["status"] = "error"
        result["error"] = "La normalización offline creó una captura duplicada"
    return result


def _require_capture_context(path: Path, competition: CompetitionContext) -> dict[str, Any]:
    metadata_path = path / "metadata" / "capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("source") != "BDFutbol"
        or metadata.get("competition") != competition.competition
        or metadata.get("season") != competition.season
        or metadata.get("group") != competition.group_roman
        or metadata.get("group_number") != competition.group_number
        or metadata.get("bdfutbol_code") != competition.bdfutbol_code
    ):
        raise ValueError(
            f"La captura {path} no identifica {competition.group_label} {competition.season}"
        )
    return metadata


def _reuse_referee_capture(
    capture_root: Path,
    matches_path: Path,
    competition: CompetitionContext,
    report_output: Path,
) -> dict[str, Any]:
    """Validate the shared seasonal referee catalog and join by referee_id."""
    metadata_path = capture_root / "metadata" / "capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("source") != "BDFutbol" or metadata.get("season") != competition.season:
        raise ValueError("La captura compartida de árbitros no corresponde a la temporada")
    scope_metadata = metadata.get("scope_captures")
    if not isinstance(scope_metadata, dict) or set(scope_metadata) != set(_SCOPES):
        raise ValueError("La captura de árbitros debe incluir all, group1 y group2")

    pages = []
    for scope in _SCOPES:
        item = scope_metadata[scope]
        relative = Path(str(item.get("file", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Ruta inválida en snapshot de árbitros {scope}")
        source_path = (capture_root / relative).resolve()
        if capture_root.resolve() not in source_path.parents:
            raise ValueError(f"Snapshot de árbitros fuera de la captura: {source_path}")
        if item.get("access", {}).get("status") != "VALID" or item.get("http_status") != 200:
            raise ValueError(f"La captura compartida de árbitros no validó el ámbito {scope}")
        if _sha256(source_path) != item.get("source_snapshot_sha256"):
            raise ValueError(f"El hash del snapshot de árbitros {scope} no coincide")
        parsed_page = parse_referee_page(
            source_path.read_text(encoding="utf-8"),
            scope=scope,
            source_url=str(item.get("requested_url")),
        )
        pages.append(parsed_page)
    parsed = merge_referee_pages(tuple(pages))
    referee_validation = validate_referee_data(parsed)
    if not referee_validation.get("valid"):
        raise ValueError("La captura reutilizada de árbitros no pasa su validación")
    matches_payload = json.loads(matches_path.read_text(encoding="utf-8"))
    match_metadata = matches_payload.get("metadata", {})
    if (
        match_metadata.get("competition") != competition.competition
        or match_metadata.get("season") != competition.season
        or match_metadata.get("group") != competition.group_roman
    ):
        raise ValueError("No se cruzarán árbitros con un dataset de otro grupo")
    report = build_match_reference_report(
        parsed,
        matches_payload,
        reference_path=matches_path.as_posix(),
        reference_sha256=_sha256(matches_path),
        group_scope=competition.group_key,
    )
    report["reused_referee_capture"] = {
        "capture_id": metadata.get("capture_id"),
        "captured_at_utc": metadata.get("captured_at_utc"),
        "path": capture_root.as_posix(),
        "sha256": _sha256(metadata_path),
        "scope_counts": parsed.scope_counts,
    }
    _write_json_exclusive(report_output, report)
    return {
        "status": "valid" if report.get("status") == "consistent" else "discrepancies",
        "group_scope": competition.group_key,
        "capture_id": metadata.get("capture_id"),
        "scope_count": parsed.scope_counts.get(competition.group_key),
        "reference_report": report_output.as_posix(),
        "counts": report.get("counts", {}),
        "identity_conflicts": len(report.get("identity_conflicts", [])),
        "statistic_differences": len(report.get("statistic_differences", [])),
    }


def _group_manifest(
    competition: CompetitionContext,
    *,
    profile: Path,
    output_root: Path,
    referees_capture: Path,
    browser_executable: Path | None,
    no_xvfb: bool,
) -> dict[str, Any]:
    classification_root = competition.export_directory(output_root, "classification")
    top_root = competition.export_directory(output_root, "top")
    statistics_root = competition.export_directory(output_root, "statistics")
    manifest: dict[str, Any] = {
        "group": competition.group_roman,
        "group_number": competition.group_number,
        "season": competition.season,
        "bdfutbol_code": competition.bdfutbol_code,
        "source_url": competition.base_url,
        "profile_dir": profile.as_posix(),
        "status": "running",
        "sections": {},
    }

    def browser_options() -> list[str]:
        options = ["--profile", profile.as_posix()]
        if browser_executable:
            options.extend(("--browser-executable", browser_executable.as_posix()))
        if no_xvfb:
            options.append("--no-xvfb")
        return options

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/scrape_bdfutbol_classification.py"),
        "--season",
        competition.season,
        "--group",
        str(competition.group_number),
        "--output-root",
        classification_root.as_posix(),
        *browser_options(),
    ]
    classification = _run_cli(
        section="classification",
        command=command,
        capture_root=classification_root,
    )
    manifest["sections"]["classification"] = classification
    if classification.get("status") != "valid":
        manifest["sections"]["results"] = {
            "status": "skipped",
            "reason": "No existe una clasificación válida de este grupo para extraer resultados.",
        }
        manifest["sections"]["top"] = {
            "status": "skipped",
            "reason": "No existe catálogo de equipos y partidos validado.",
        }
        manifest["sections"]["statistics"] = {
            "status": "skipped",
            "reason": "No existe dataset de partidos validado.",
        }
        manifest["sections"]["referees"] = {
            "status": "skipped",
            "reason": "No existe dataset de partidos para cruzar referee_id.",
        }
        manifest["status"] = "blocked_or_failed"
        return manifest

    classification_path = Path(str(classification["capture_path"])).resolve()
    capture_metadata = _require_capture_context(classification_path, competition)
    classification_validation = json.loads(
        (classification_path / "validation/results.json").read_text(encoding="utf-8")
    )
    if not classification_validation.get("valid"):
        classification["status"] = "invalid"
        manifest["sections"]["results"] = {"status": "skipped", "reason": "Clasificación no válida."}
        manifest["sections"]["top"] = {"status": "skipped", "reason": "Clasificación no válida."}
        manifest["sections"]["statistics"] = {"status": "skipped", "reason": "Clasificación no válida."}
        manifest["sections"]["referees"] = {"status": "skipped", "reason": "Clasificación no válida."}
        manifest["status"] = "invalid"
        return manifest

    matches_path = classification_path / "normalized" / "matches.json"
    match_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/extract_bdfutbol_matches.py"),
        "--snapshot",
        str(classification_path / "raw/source.html"),
        "--capture",
        str(classification_path / "metadata/capture.json"),
        "--output",
        str(matches_path),
    ]
    match_result = _run_cli(
        section="results",
        command=match_command,
        capture_root=classification_root,
        expect_capture=False,
    )
    manifest["sections"]["results"] = match_result
    if match_result.get("status") == "valid":
        matches_payload = json.loads(matches_path.read_text(encoding="utf-8"))
        matches_metadata = matches_payload.get("metadata", {})
        if (
            matches_metadata.get("source_capture_id") != capture_metadata.get("capture_id")
            or matches_metadata.get("group") != competition.group_roman
            or matches_metadata.get("season") != competition.season
        ):
            match_result["status"] = "invalid"
            match_result["error"] = "matches.json no coincide con el grupo/captura de origen"
        else:
            match_result["counts"] = matches_payload.get("counts", {})
            match_result["sha256"] = _sha256(matches_path)

    if match_result.get("status") != "valid":
        manifest["sections"]["top"] = {"status": "skipped", "reason": "Resultados no validados."}
        manifest["sections"]["statistics"] = {"status": "skipped", "reason": "Resultados no validados."}
        manifest["sections"]["referees"] = {"status": "skipped", "reason": "Resultados no validados."}
        manifest["status"] = "partial_failure"
        return manifest

    top_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/scrape_bdfutbol_top.py"),
        "--season",
        competition.season,
        "--group",
        str(competition.group_number),
        "--team-catalog",
        str(matches_path),
        "--output-root",
        top_root.as_posix(),
        *browser_options(),
    ]
    top_result = _run_cli(section="top", command=top_command, capture_root=top_root)
    manifest["sections"]["top"] = top_result
    if top_result.get("status") == "valid":
        top_path = Path(str(top_result["capture_path"]))
        top_metadata = _require_capture_context(top_path, competition)
        top_result["counts"] = top_metadata.get("category_source_counts", {})
        players_payload = json.loads(
            (top_path / "normalized/players.json").read_text(encoding="utf-8")
        )
        top_result["player_count"] = len(players_payload.get("records", []))
        top_result["snapshot_sha256"] = top_metadata.get("source_snapshot_sha256")

    statistics_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/scrape_bdfutbol_statistics.py"),
        "--season",
        competition.season,
        "--group",
        str(competition.group_number),
        "--matches",
        str(matches_path),
        "--output-root",
        statistics_root.as_posix(),
        *browser_options(),
    ]
    statistics = _run_cli(
        section="statistics",
        command=statistics_command,
        capture_root=statistics_root,
    )
    manifest["sections"]["statistics"] = statistics

    referee_report_path = classification_path / "validation" / "referee_reference.json"
    try:
        referee_result = _reuse_referee_capture(
            referees_capture,
            matches_path,
            competition,
            referee_report_path,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        referee_result = {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    manifest["sections"]["referees"] = referee_result

    required_statuses = {
        "classification": "valid",
        "results": "valid",
        "top": "valid",
        "statistics": "valid",
    }
    acquisition_valid = all(
        manifest["sections"].get(name, {}).get("status") == status
        for name, status in required_statuses.items()
    )
    manifest["status"] = (
        "complete"
        if acquisition_valid and referee_result.get("status") == "valid"
        else "complete_with_referee_differences"
        if acquisition_valid and referee_result.get("status") == "discrepancies"
        else "partial_failure"
    )
    return manifest


def run_groups_sequentially(
    groups: Sequence[CompetitionContext],
    runner: Callable[[CompetitionContext], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sequential by construction; a group exception does not skip later groups."""
    results = []
    for competition in groups:
        try:
            results.append(runner(competition))
        except Exception as exc:  # Keep the other selected group's run independent.
            results.append({
                "group": competition.group_roman,
                "group_number": competition.group_number,
                "season": competition.season,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            })
    return results


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=(SUPPORTED_SEASON,), default=SUPPORTED_SEASON)
    parser.add_argument("--group", choices=("1", "2", "both"), required=True)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path.home() / ".football-data-hub-chromium-pure-cdp",
    )
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--no-xvfb", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("data/exports/bdfutbol"))
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("data/analysis/bdfutbol/acquisition_runs"),
    )
    parser.add_argument(
        "--referees-capture",
        type=Path,
        default=Path(
            str(
                os.environ.get(
                    "FDH_BDFUTBOL_REFEREES_CAPTURE", str(DEFAULT_REFEREES_CAPTURE)
                )
            )
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected = (1, 2) if args.group == "both" else (int(args.group),)
    groups = tuple(get_competition_context(args.season, value) for value in selected)
    output_root = args.output_root.expanduser()
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    profile = args.profile.expanduser().resolve()
    referees_capture = args.referees_capture.expanduser()
    if not referees_capture.is_absolute():
        referees_capture = PROJECT_ROOT / referees_capture
    run_root = args.run_root.expanduser()
    if not run_root.is_absolute():
        run_root = PROJECT_ROOT / run_root
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    def runner(competition: CompetitionContext) -> dict[str, Any]:
        return _group_manifest(
            competition,
            profile=profile,
            output_root=output_root,
            referees_capture=referees_capture,
            browser_executable=args.browser_executable,
            no_xvfb=args.no_xvfb,
        )

    group_results = run_groups_sequentially(groups, runner)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at_utc": run_id.split("-")[0],
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "season": args.season,
        "requested_groups": list(selected),
        "execution_order": [item.get("group_number") for item in group_results],
        "browser_backend": "seleniumbase-pure-cdp",
        "profile_dir": profile.as_posix(),
        "xvfb_external": not args.no_xvfb,
        "published_to_api": False,
        "groups": group_results,
    }
    manifest_path = run_dir / "manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    print(json.dumps({"manifest": manifest_path.as_posix(), **manifest}, ensure_ascii=False, indent=2))
    return 0 if all(group.get("status") == "complete" for group in group_results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
