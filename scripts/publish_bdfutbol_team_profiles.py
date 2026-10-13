#!/usr/bin/env python3
"""Verify a completed team batch and atomically publish its local API index."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

from football_data_hub.providers.bdfutbol.context import get_competition_context  # noqa: E402
from football_data_hub.providers.bdfutbol.teams.acquisition import DEFAULT_VIEWS, FOLLOW_STATES  # noqa: E402
from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog  # noqa: E402
from football_data_hub.providers.bdfutbol.teams.parser import _parse_match_ids_by_competition  # noqa: E402
from football_data_hub_api.team_catalog_compatibility import verify_team_catalog_compatibility  # noqa: E402

SEASON = "2026-27"
ROSTER_FILES = (
    "metadata/capture.json",
    "validation/results.json",
    "raw/access.json",
    "normalized/team_identity.json",
    "normalized/team_season.json",
    "normalized/players.json",
    "normalized/memberships.json",
    "normalized/player_statistics.json",
)
FOLLOW_FILES = (
    "normalized/player_match_minutes.json",
    "normalized/player_match_metrics.json",
    "raw/follow.html.gz",
    *(f"raw/follow_states/{state}.html.gz" for state in FOLLOW_STATES),
)
TRANSFERS_FILES = (
    "metadata/capture.json",
    "validation/results.json",
    "raw/access.json",
    "raw/transfers.html.gz",
    "normalized/team_identity.json",
    "normalized/team_season.json",
    "normalized/transfers.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Se esperaba un objeto JSON: {path}")
    return value


def _capture_file(capture_dir: Path, relative: str) -> Path:
    root = capture_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"La referencia sale del directorio de captura: {relative}")
    return path


def _verify_capture(
    *,
    capture_dir: Path,
    item: dict[str, Any],
    team: dict[str, Any],
    group: str,
    matches_path: Path,
    active_capture_id: str,
    active_team_ids: set[int],
    active_matches: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    capture_id = str(item["capture_id"])
    team_id = int(item["team_id"])
    capture = _read_json(_capture_file(capture_dir, "metadata/capture.json"))
    validation = _read_json(_capture_file(capture_dir, "validation/results.json"))
    access = _read_json(_capture_file(capture_dir, "raw/access.json"))
    if any(capture.get(key) != expected for key, expected in {
        "schema_version": 1,
        "capture_id": capture_id,
        "source": "BDFutbol",
        "section": "team_profile",
        "team_id": team_id,
        "team_name": team["name"],
        "team_url": team["team_url"],
        "season": SEASON,
        "competition": "Primera Federación",
        "competition_scope": "Liga",
        "group": group,
    }.items()):
        raise ValueError(f"Metadatos de identidad incompatibles para team_id={team_id}.")
    if validation.get("valid") is not True or validation.get("summary", {}).get("team_id") != team_id:
        raise ValueError(f"La validación original no confirma team_id={team_id}.")
    if capture.get("requested_views") != list(DEFAULT_VIEWS):
        raise ValueError(f"No constan las seis vistas requeridas para team_id={team_id}.")
    if set(capture.get("follow_states", {})) != set(FOLLOW_STATES):
        raise ValueError(f"No constan los cuatro estados de Seguimiento para team_id={team_id}.")
    if access.get("capture_id") != capture_id or access.get("views") != capture.get("access_by_view"):
        raise ValueError(f"raw/access.json contradice metadata/capture.json para team_id={team_id}.")

    raw_hashes: dict[str, str] = {"raw/access.json": _sha256(_capture_file(capture_dir, "raw/access.json"))}
    snapshot_hashes: dict[str, str] = {}
    matches_html: str | None = None
    access_by_view = capture["access_by_view"]
    source_snapshots = capture["source_snapshots"]
    for view in DEFAULT_VIEWS:
        evidence = source_snapshots.get(view)
        report = access_by_view.get(view)
        if not isinstance(evidence, dict) or not isinstance(report, dict):
            raise ValueError(f"Falta evidencia de la vista {view} para team_id={team_id}.")
        relative = evidence.get("path")
        if not isinstance(relative, str) or not relative.startswith("raw/"):
            raise ValueError(f"Ruta de snapshot inválida para {view}/team_id={team_id}.")
        stored_path = _capture_file(capture_dir, relative)
        stored = stored_path.read_bytes()
        raw_hashes[relative] = hashlib.sha256(stored).hexdigest()
        original = gzip.decompress(stored) if evidence.get("compression") == "gzip" or relative.endswith(".gz") else stored
        original_hash = hashlib.sha256(original).hexdigest()
        if original_hash != evidence.get("sha256"):
            raise ValueError(f"El snapshot original {view} no supera SHA-256 para team_id={team_id}.")
        if evidence.get("http_status") != 200 or evidence.get("access_status", evidence.get("status")) != "VALID":
            raise ValueError(f"La vista {view} no tiene estado 200/VALID para team_id={team_id}.")
        requested = report.get("requested_url")
        if (
            report.get("status") != "VALID" or report.get("http_status") != 200
            or requested != report.get("final_url") or requested != evidence.get("url")
            or SEASON not in str(evidence.get("title") or "")
            or team["name"].casefold() not in str(evidence.get("title") or "").casefold()
        ):
            raise ValueError(f"URL, título o acceso no verificable para {view}/team_id={team_id}.")
        snapshot_hashes[relative] = original_hash
        if view == "matches":
            matches_html = original.decode("utf-8", errors="replace")

    follow_state_hashes: dict[str, str] = {}
    for state in FOLLOW_STATES:
        evidence = capture["follow_states"][state]
        if evidence.get("selected_value") != state or evidence.get("status") not in {"VALID", "DERIVED_OFFLINE"}:
            raise ValueError(f"Estado de Seguimiento {state} inválido para team_id={team_id}.")
        relative = evidence.get("path")
        if not isinstance(relative, str) or not relative.startswith("raw/follow_states/"):
            raise ValueError(f"Falta el HTML de Seguimiento {state} para team_id={team_id}.")
        stored = _capture_file(capture_dir, relative).read_bytes()
        raw_hashes[relative] = hashlib.sha256(stored).hexdigest()
        html = gzip.decompress(stored).decode("utf-8", errors="replace")
        html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if html_hash != evidence.get("sha256"):
            raise ValueError(f"El estado de Seguimiento {state} no supera SHA-256 para team_id={team_id}.")
        if not re.search(r"id=[\"']taula-seguiment[\"']", html, re.IGNORECASE):
            raise ValueError(f"El DOM de Seguimiento {state} no contiene la tabla para team_id={team_id}.")
        if evidence.get("status") == "DERIVED_OFFLINE" and (
            evidence.get("origin") != "derived_offline"
            or evidence.get("derivation_method") != "embedded_javascript_matrices_v1"
            or not evidence.get("derived_at_utc")
        ):
            raise ValueError(f"Derivación offline sin procedencia para estado {state}/team_id={team_id}.")
        follow_state_hashes[state] = html_hash
        snapshot_hashes[relative] = html_hash

    normalized_hashes: dict[str, str] = {}
    normalized_manifest = capture.get("normalized_snapshots") or {}
    normalized_paths = sorted(_capture_file(capture_dir, "normalized").glob("*.json"))
    if not normalized_paths:
        raise ValueError(f"Faltan JSON normalizados para team_id={team_id}.")
    for path in normalized_paths:
        relative = path.relative_to(capture_dir).as_posix()
        digest = _sha256(path)
        declared = normalized_manifest.get(path.name, {}).get("sha256")
        if declared != digest:
            raise ValueError(f"normalized/{path.name} no coincide con metadata/capture.json para team_id={team_id}.")
        normalized_hashes[relative] = digest
    identity = _read_json(_capture_file(capture_dir, "normalized/team_identity.json"))["record"]
    season_record = _read_json(_capture_file(capture_dir, "normalized/team_season.json"))["record"]
    if identity.get("team_id") != team_id or identity.get("name") != team["name"] or identity.get("team_url") != team["team_url"]:
        raise ValueError(f"normalized/team_identity.json no coincide con team_id={team_id}.")
    if any(season_record.get(key) != value for key, value in {"team_id": team_id, "season": SEASON, "group": group}.items()):
        raise ValueError(f"normalized/team_season.json no coincide con team_id={team_id}.")

    references = _read_json(_capture_file(capture_dir, "normalized/profile_references.json"))
    profile_team_ids = references.get("team_ids_from_profile")
    if not isinstance(profile_team_ids, list) or set(profile_team_ids) != active_team_ids or len(profile_team_ids) != len(active_team_ids):
        raise ValueError(f"La vista de equipo no confirma el catálogo completo para team_id={team_id}.")
    match_ids = references.get("match_ids_from_profile")
    if not isinstance(match_ids, list) or len(match_ids) != len(set(match_ids)):
        raise ValueError(f"Referencias de partidos ausentes o duplicadas para team_id={team_id}.")
    if matches_html is None:
        raise ValueError(f"Falta el HTML de Partidos para team_id={team_id}.")
    all_profile_ids, league_match_ids, _other_match_ids = _parse_match_ids_by_competition(
        BeautifulSoup(matches_html, "html.parser")
    )
    if set(match_ids) != set(all_profile_ids):
        raise ValueError(f"Las referencias normalizadas no coinciden con la vista Partidos para team_id={team_id}.")
    for match_id in league_match_ids:
        match = active_matches.get(str(match_id))
        if match is None or team_id not in {match.get("home_team_id"), match.get("away_team_id")}:
            raise ValueError(f"match_id={match_id} no se enlaza al equipo/catálogo para team_id={team_id}.")

    verify_team_catalog_compatibility(
        capture,
        matches_path=matches_path,
        group=group,
        season=SEASON,
        active_capture_id=active_capture_id,
    )
    transfers = _read_json(_capture_file(capture_dir, "normalized/transfers.json"))
    summary_sections = validation.get("summary", {}).get("transfer_sections")
    sections = transfers.get("sections")
    records = transfers.get("records")
    if (
        not isinstance(sections, list) or len(sections) != 2
        or not isinstance(summary_sections, dict) or not isinstance(records, list)
    ):
        raise ValueError(f"Las secciones Altas/Bajas no están demostradas para team_id={team_id}.")
    direction_counts = {"incoming": 0, "outgoing": 0}
    for record in records:
        direction = record.get("direction")
        if direction not in direction_counts:
            raise ValueError(f"Dirección de movimiento inválida para team_id={team_id}.")
        direction_counts[direction] += 1
    for section in sections:
        direction = section.get("direction")
        if direction not in {"incoming", "outgoing"}:
            raise ValueError(f"Dirección de movimiento inválida para team_id={team_id}.")
        expected_section = summary_sections.get(direction)
        if (
            not isinstance(expected_section, dict)
            or expected_section.get("status") not in {"verified_with_rows", "verified_empty"}
            or expected_section.get("rows") != section.get("row_count")
            or direction_counts[direction] != section.get("row_count")
        ):
            raise ValueError(f"La evidencia de {direction} no coincide con la validación para team_id={team_id}.")
    return capture, raw_hashes, normalized_hashes, follow_state_hashes, snapshot_hashes


def _atomic_write(path: Path, payload: bytes) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def build_index(
    *,
    store_root: Path,
    manifest_path: Path,
    group1_catalog_path: Path,
    group2_catalog_path: Path,
) -> dict[str, Any]:
    root = store_root.expanduser().resolve()
    manifest = _read_json(manifest_path.expanduser().resolve())
    if manifest.get("season") != SEASON or manifest.get("batch_complete") is not True:
        raise ValueError("El manifiesto no declara un lote completo de 2026/27.")
    if manifest.get("stopped_on_access_denial") is not False or manifest.get("stop_reason") is not None:
        raise ValueError("El manifiesto contiene una denegación o una causa de parada.")
    teams = manifest.get("teams")
    if not isinstance(teams, list) or len(teams) != 40:
        raise ValueError("El lote debe contener exactamente 40 entradas.")
    team_ids = [entry.get("team_id") for entry in teams]
    if len(set(team_ids)) != 40 or any(type(team_id) is not int for team_id in team_ids):
        raise ValueError("El lote contiene IDs de equipo ausentes o duplicados.")
    if any(entry.get("status") != "complete" for entry in teams):
        raise ValueError("Todas las entradas del lote deben estar completas.")
    if {group: sum(item.get("group") == group for item in teams) for group in ("I", "II")} != {"I": 20, "II": 20}:
        raise ValueError("El lote no contiene 20 equipos de cada grupo.")
    if tuple(manifest.get("requested_views") or ()) != DEFAULT_VIEWS:
        raise ValueError("El manifiesto no cubre las seis vistas requeridas.")
    if tuple(manifest.get("required_follow_states") or ()) != FOLLOW_STATES:
        raise ValueError("El manifiesto no declara los cuatro estados de Seguimiento.")

    catalog_paths = {1: group1_catalog_path.expanduser().resolve(), 2: group2_catalog_path.expanduser().resolve()}
    catalogs: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]] = {}
    active_matches_by_group: dict[int, dict[str, dict[str, Any]]] = {}
    for group_number, path in catalog_paths.items():
        competition = get_competition_context(group=group_number)
        catalogs[group_number] = load_team_catalog(path, competition=competition)
        active_matches_by_group[group_number] = {
            str(match["match_id"]): match for match in catalogs[group_number][1]
        }
    entries: dict[str, Any] = {}
    for item in teams:
        team_id = int(item["team_id"])
        group_number = 1 if item["group"] == "I" else 2
        group_teams, _group_matches, catalog_reference = catalogs[group_number]
        catalog_by_id = {int(team["team_id"]): team for team in group_teams}
        if team_id not in catalog_by_id or catalog_by_id[team_id].get("name") != item.get("team_name"):
            raise ValueError(f"El catálogo no confirma la identidad de team_id={team_id}.")
        capture_id = item.get("capture_id")
        if not isinstance(capture_id, str) or not capture_id:
            raise ValueError(f"Falta capture_id para team_id={team_id}.")
        capture_dir = (root / SEASON / str(team_id) / capture_id).resolve()
        if not capture_dir.is_relative_to(root):
            raise ValueError(f"La captura de team_id={team_id} sale de la raíz autorizada.")
        declared_dir = (item.get("coverage") or {}).get("capture_path")
        if declared_dir and Path(declared_dir).expanduser().resolve() != capture_dir:
            raise ValueError(f"El manifiesto apunta a otra ruta para team_id={team_id}.")
        capture_metadata, raw_hashes, normalized_hashes, follow_state_hashes, snapshot_hashes = _verify_capture(
            capture_dir=capture_dir,
            item=item,
            team=catalog_by_id[team_id],
            group=item["group"],
            matches_path=catalog_paths[group_number],
            active_capture_id=str(catalog_reference.get("source_capture_id") or ""),
            active_team_ids={int(team["team_id"]) for team in group_teams},
            active_matches=active_matches_by_group[group_number],
        )
        print(f"Verificada captura {team_id}/40 · {item['team_name']}", file=sys.stderr, flush=True)

        hashes = {
            "files_sha256": {relative: _sha256(capture_dir / relative) for relative in ROSTER_FILES},
            "follow_files_sha256": {
                relative: _sha256(capture_dir / relative)
                for relative in (*FOLLOW_FILES, "raw/follow_states/p.html.gz")
            },
            "transfers_files_sha256": {
                relative: _sha256(capture_dir / relative) for relative in TRANSFERS_FILES
            },
        }
        capture_metadata = _read_json(capture_dir / "metadata/capture.json")
        related_catalog = capture_metadata.get("related_team_catalog")
        if not isinstance(related_catalog, dict):
            raise ValueError(f"La captura de team_id={team_id} no fija el catálogo de origen.")
        transfers_document = _read_json(capture_dir / "normalized/transfers.json")
        transfers_sections = transfers_document.get("sections")
        transfers_hash = _sha256(capture_dir / "normalized/transfers.json")
        transfer_source = capture_metadata["source_snapshots"]["transfers"]
        transfers_evidence = {
            "capture_id": capture_id,
            "team_id": team_id,
            "season": SEASON,
            "group": item["group"],
            "source_snapshot": {
                "path": "raw/transfers.html.gz",
                "sha256": transfer_source["sha256"],
                "url": transfer_source["url"],
            },
            "normalized": {
                "path": "normalized/transfers.json",
                "sha256": transfers_hash,
            },
            "sections": transfers_sections,
        }
        entries[str(team_id)] = {
            "capture_id": capture_id,
            "directory": str(capture_dir),
            **hashes,
            "raw_files_sha256": raw_hashes,
            "normalized_files_sha256": normalized_hashes,
            "source_snapshots_sha256": snapshot_hashes,
            "related_team_catalog": related_catalog,
            "follow_states_sha256": follow_state_hashes,
            "transfers_evidence": transfers_evidence,
            "publication_validation": {
                "classification": "complete",
                "active_catalog_compatible": True,
                "valid_views": list(DEFAULT_VIEWS),
                "valid_follow_states": list(FOLLOW_STATES),
                "capture_id": capture_metadata["capture_id"],
            },
        }

    if len(entries) != 40:
        raise ValueError("No se generaron exactamente 40 perfiles.")
    return {"schema_version": 1, "season": SEASON, "profiles": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--group1-catalog", type=Path, required=True)
    parser.add_argument("--group2-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Validar y mostrar resumen sin escribir el índice.")
    args = parser.parse_args()
    index = build_index(
        store_root=args.store_root,
        manifest_path=args.manifest,
        group1_catalog_path=args.group1_catalog,
        group2_catalog_path=args.group2_catalog,
    )
    serialized = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.dry_run:
        print(json.dumps({"valid": True, "profiles": len(index["profiles"]), "output": str(args.output)}, ensure_ascii=False))
        return 0
    backup = _atomic_write(args.output.expanduser().resolve(), serialized)
    print(json.dumps({
        "published": str(args.output.expanduser().resolve()),
        "profiles": len(index["profiles"]),
        "backup": str(backup) if backup else None,
        "sha256": hashlib.sha256(serialized).hexdigest(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
