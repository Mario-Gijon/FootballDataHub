#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from football_data_hub.bdfutbol.media import (
    MediaObservation,
    deduplicate_observations,
    discover_media,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audita offline las imágenes de un raw team_full de BDFutbol y "
            "separa media de entidad de assets de interfaz."
        )
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--team-id", required=True, type=int)
    parser.add_argument(
        "--run-dir",
        help=(
            "Run team_full exacto. Si se omite usa el más reciente de "
            "data/raw/bdfutbol/team_full_<season>_<team_id>/."
        ),
    )
    parser.add_argument(
        "--output",
        help=(
            "JSON de salida. Default: "
            "<run>/analysis/media_audit.json"
        ),
    )
    parser.add_argument(
        "--show",
        choices=("accept", "review", "all"),
        default="accept",
        help="Qué candidatos imprimir en consola.",
    )
    return parser.parse_args(argv)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _resolve_run_dir(
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

    root = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"team_full_{season}_{team_id}"
    )
    if not root.exists():
        raise FileNotFoundError(root)

    runs = sorted(path for path in root.iterdir() if path.is_dir())
    if not runs:
        raise FileNotFoundError(f"No hay runs dentro de {root}")
    return runs[-1].resolve()


def _metadata_for_html(html_path: Path) -> tuple[str, str]:
    directory = html_path.parent
    metadata = _load_json(directory / "metadata.json", {})

    resource = str(metadata.get("resource") or "")
    page_url = str(
        metadata.get("final_url")
        or metadata.get("requested_url")
        or ""
    )

    if not resource:
        # tracking_mode_* subdirectories inherit the parent resource.
        for parent in directory.parents:
            parent_meta = _load_json(parent / "metadata.json", {})
            if parent_meta.get("resource"):
                resource = str(parent_meta["resource"])
                break

    if not page_url:
        for parent in directory.parents:
            parent_meta = _load_json(parent / "metadata.json", {})
            candidate = (
                parent_meta.get("final_url")
                or parent_meta.get("requested_url")
            )
            if candidate:
                page_url = str(candidate)
                break

    return resource or directory.name, page_url


def _scan_run(
    run_dir: Path,
    *,
    team_id: int,
) -> list[MediaObservation]:
    observations: list[MediaObservation] = []

    for html_path in sorted(run_dir.rglob("page.html")):
        if "analysis" in html_path.parts:
            continue

        resource, page_url = _metadata_for_html(html_path)
        if not page_url:
            continue

        try:
            html = html_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue

        observations.extend(
            discover_media(
                html,
                page_url=page_url,
                resource=resource,
                team_id=team_id,
            )
        )

    return observations


def _summary(
    observations: list[MediaObservation],
    deduped: list[dict[str, object]],
) -> dict[str, object]:
    decisions = Counter(item.decision for item in observations)
    dedup_decisions = Counter(
        str(item.get("decision")) for item in deduped
    )
    roles = Counter(
        str(item.get("role"))
        for item in deduped
        if item.get("role")
        and item.get("decision") in {"accept", "review"}
    )
    entity_types = Counter(
        str(item.get("entity_type"))
        for item in deduped
        if item.get("entity_type")
        and item.get("decision") in {"accept", "review"}
    )

    return {
        "observations_total": len(observations),
        "observations_by_decision": dict(sorted(decisions.items())),
        "unique_media_total": len(deduped),
        "unique_by_decision": dict(sorted(dedup_decisions.items())),
        "candidate_roles": dict(sorted(roles.items())),
        "candidate_entity_types": dict(sorted(entity_types.items())),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]

    try:
        run_dir = _resolve_run_dir(
            project_root=project_root,
            season=args.season,
            team_id=args.team_id,
            requested=args.run_dir,
        )
    except FileNotFoundError as exc:
        print(f"Error: no existe {exc}")
        return 2

    observations = _scan_run(run_dir, team_id=args.team_id)
    deduped = deduplicate_observations(observations)
    summary = _summary(observations, deduped)

    output = (
        Path(args.output)
        if args.output
        else run_dir / "analysis" / "media_audit.json"
    )
    if not output.is_absolute():
        output = project_root / output

    payload = {
        "audit_version": 1,
        "season": args.season,
        "team_id": args.team_id,
        "source_run": str(run_dir.relative_to(project_root)),
        "summary": summary,
        "media": deduped,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== BDFUTBOL MEDIA AUDIT ===")
    print(f"Run:              {payload['source_run']}")
    print(f"Observaciones:    {summary['observations_total']}")
    print(f"Media únicas:     {summary['unique_media_total']}")
    print(
        "Decisiones:       "
        + ", ".join(
            f"{key}={value}"
            for key, value
            in summary["unique_by_decision"].items()
        )
    )
    print(
        "Entidades:        "
        + ", ".join(
            f"{key}={value}"
            for key, value
            in summary["candidate_entity_types"].items()
        )
    )
    print(
        "Roles:            "
        + ", ".join(
            f"{key}={value}"
            for key, value
            in summary["candidate_roles"].items()
        )
    )

    if args.show != "all":
        allowed = {args.show}
    else:
        allowed = {"accept", "review", "reject"}

    print("\n=== CANDIDATOS ===")
    printed = 0
    for item in deduped:
        if item.get("decision") not in allowed:
            continue
        if args.show == "all" and item.get("decision") == "reject":
            # Avoid flooding the terminal with generic UI assets.
            continue

        print(
            f"[{str(item.get('decision')).upper():6}] "
            f"{item.get('entity_type') or '-'}:"
            f"{item.get('entity_id') or '-'} "
            f"{item.get('role') or '-'}"
        )
        print(f"         {item.get('source_url')}")
        printed += 1

    if printed == 0:
        print("(ninguno)")

    print(f"\nInforme: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
