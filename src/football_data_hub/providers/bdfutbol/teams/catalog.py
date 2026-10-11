"""Catalog loading and the versioned 40-club identity inventory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.context import CompetitionContext

from .acquisition import create_team_capture_id
from .parser import team_id_from_url
from .validation import validate_team_catalogs


def load_team_catalog(
    path: Path,
    *,
    competition: CompetitionContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    path = path.expanduser()
    content = path.read_bytes()
    payload = json.loads(content)
    metadata = payload.get("metadata", {})
    if payload.get("schema_version") not in {1, 2} or not isinstance(payload.get("teams"), list):
        raise ValueError(f"Catálogo de equipos inválido: {path}")
    if metadata.get("group") != competition.group_roman or metadata.get("season") != competition.season:
        raise ValueError(
            f"El catálogo {path} es de Grupo {metadata.get('group')} "
            f"{metadata.get('season')}; se requiere {competition.group_label} {competition.season}"
        )
    teams = payload["teams"]
    if len(teams) != 20:
        raise ValueError(f"El catálogo debe contener 20 equipos; contiene {len(teams)}: {path}")
    ids: set[int] = set()
    for record in teams:
        team_id = int(record["team_id"])
        if team_id in ids:
            raise ValueError(f"team_id duplicado en {path}: {team_id}")
        ids.add(team_id)
        if team_id_from_url(str(record.get("team_url") or "")) != team_id:
            raise ValueError(f"team_url no corresponde a team_id={team_id} en {path}")
    matches = payload.get("matches", [])
    if not isinstance(matches, list):
        raise ValueError(f"El campo matches no es una lista: {path}")
    reference = {
        "path": path.as_posix(),
        "group": competition.group_roman,
        "season": competition.season,
        "source_capture_id": metadata.get("source_capture_id"),
        "source_captured_at_utc": metadata.get("source_captured_at_utc"),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    return teams, matches, reference


def write_team_inventory(
    output_root: Path,
    catalogs: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]],
    *,
    season: str,
) -> dict[str, Path]:
    validation = validate_team_catalogs(catalogs, season=season)
    if not validation["valid"]:
        raise ValueError(f"Inventario de equipos inválido: {validation['issues']}")
    records: list[dict[str, Any]] = []
    for group, (teams, reference) in sorted(catalogs.items()):
        for team in teams:
            records.append({
                **team,
                "season": season,
                "competition": "Primera Federación",
                "group": "I" if group == 1 else "II",
                "group_number": group,
                "team_catalog_source": reference,
            })
    capture_id = create_team_capture_id()
    base = output_root.expanduser() / season / "catalog"
    base.mkdir(parents=True, exist_ok=True)
    run_dir = base / capture_id
    staging = base / f".{capture_id}.tmp"
    staging.mkdir(exist_ok=False)
    try:
        metadata = {
            "schema_version": 1,
            "capture_id": capture_id,
            "source": "existing BDFutbol group match catalogs",
            "season": season,
            "competition": "Primera Federación",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "team_count": len(records),
            "sources": {"group1": catalogs[1][1], "group2": catalogs[2][1]},
        }
        for relative, value in (
            (Path("metadata/inventory.json"), metadata),
            (Path("normalized/teams.json"), {"schema_version": 1, "metadata": metadata, "records": records}),
            (Path("validation/results.json"), validation),
        ):
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as target:
                json.dump(value, target, ensure_ascii=False, indent=2)
                target.write("\n")
        if run_dir.exists():
            raise FileExistsError(f"El inventario ya existe y no se sobrescribirá: {run_dir}")
        os.rename(staging, run_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "run_directory": run_dir,
        "teams": run_dir / "normalized" / "teams.json",
        "metadata": run_dir / "metadata" / "inventory.json",
        "validation": run_dir / "validation" / "results.json",
    }
