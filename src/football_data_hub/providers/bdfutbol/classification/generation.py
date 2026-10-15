"""Construcción offline de generaciones inmutables de partidos por grupo."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from football_data_hub.domain.classification.validation import validate_match_set

from .match_io import load_match_dataset
from .matches import extract_matches
from .parser import parse_classification_page

COMPETITION = "Primera Federación"
SEASON = "2026-27"
GROUP_URLS = {
    "I": "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
    "II": "https://www.bdfutbol.com/es/t/t2026-271rf2.html",
}
class MatchGenerationError(ValueError):
    """Una captura local no cumple el contrato para formar una generación."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"No se puede serializar {type(value).__name__} a JSON")


def _json_bytes(value: Any) -> bytes:
    content = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default
    )
    return f"{content}\n".encode("utf-8")


def _relative_path(path: Path, data_root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = data_root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise MatchGenerationError(
            f"El archivo de procedencia queda fuera de data_root: {resolved_path} "
            f"(raíz configurada: {resolved_root})"
        ) from exc


def _load_group(
    group: str,
    capture_root: Path,
    matches_path: Path,
    data_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    capture_path = capture_root / "metadata" / "capture.json"
    source_path = capture_root / "raw" / "source.html"
    for path in (capture_path, source_path, matches_path):
        if not path.is_file():
            raise MatchGenerationError(f"Falta el archivo de captura requerido: {path}")

    capture_bytes = capture_path.read_bytes()
    source_bytes = source_path.read_bytes()
    matches_bytes = matches_path.read_bytes()
    capture = json.loads(capture_bytes)
    capture_access = capture.get("access", {})
    expected_url = GROUP_URLS[group]
    expected_title_marker = f"Grupo {group} {SEASON}"
    if (
        capture.get("source") != "BDFutbol"
        or capture.get("competition") != COMPETITION
        or capture.get("season") != SEASON
        or capture.get("group") != group
        or capture.get("url") != expected_url
        or capture.get("final_url") != expected_url
        or capture_access.get("status") != "VALID"
        or capture_access.get("http_status") != 200
        or capture_access.get("final_url") != expected_url
        or expected_title_marker not in capture.get("page_title", "")
    ):
        raise MatchGenerationError(f"Metadatos de acceso o competición no válidos para Grupo {group}")

    dataset_metadata, teams, matches = load_match_dataset(matches_path)
    source_hash = _sha256(source_bytes)
    if (
        dataset_metadata.get("source_capture_id") != capture.get("capture_id")
        or dataset_metadata.get("source") != "BDFutbol"
        or dataset_metadata.get("competition") != COMPETITION
        or dataset_metadata.get("season") != SEASON
        or dataset_metadata.get("group") != group
        or dataset_metadata.get("source_snapshot_sha256") != source_hash
    ):
        raise MatchGenerationError(f"Procedencia o SHA-256 no coincide para Grupo {group}")

    source_html = source_bytes.decode("utf-8")
    parsed = parse_classification_page(source_html, base_url=expected_url)
    extracted_teams, extracted_matches = extract_matches(
        source_html,
        parsed,
        base_url=expected_url,
        captured_at=datetime.fromisoformat(capture["captured_at_utc"]),
    )
    if tuple(teams) != extracted_teams or tuple(matches) != extracted_matches:
        raise MatchGenerationError(
            f"El JSON normalizado no reproduce exactamente el HTML original del Grupo {group}"
        )

    validation = validate_match_set(
        teams,
        matches,
        expected_teams=20,
        expected_rounds=38,
        fixtures_per_round=10,
    )
    if not validation["valid"]:
        raise MatchGenerationError(f"Invariantes deportivos fallidas para Grupo {group}")

    source_files = {
        "capture_metadata": {
            "path": _relative_path(capture_path, data_root),
            "sha256": _sha256(capture_bytes),
        },
        "source_html": {
            "path": _relative_path(source_path, data_root),
            "sha256": source_hash,
        },
        "normalized_matches": {
            "path": _relative_path(matches_path, data_root),
            "sha256": _sha256(matches_bytes),
        },
    }
    source = {
        "group": group,
        "capture_id": capture["capture_id"],
        "captured_at_utc": capture["captured_at_utc"],
        "requested_url": capture["url"],
        "final_url": capture["final_url"],
        "http_status": capture_access["http_status"],
        "page_title": capture.get("page_title"),
        "source_snapshot_sha256": source_hash,
        "files": source_files,
    }
    coverage = _coverage(teams, matches)
    group_payload = {
        "group": group,
        "teams": [asdict(team) for team in teams],
        "matches": [],
    }
    for match in matches:
        record = asdict(match)
        source_match_id = record.pop("match_id")
        group_payload["matches"].append(
            {
                "internal_id": f"pf-{SEASON}-group-{group.lower()}-bdfutbol-{source_match_id}",
                "source_match_id": source_match_id,
                **record,
            }
        )
    return group_payload, {"source": source, "coverage": coverage}, validation


def _coverage(teams: tuple[Any, ...], matches: tuple[Any, ...]) -> dict[str, Any]:
    fields = {
        "bdfutbol_match_id": len(matches),
        "matchday": sum(match.matchday is not None for match in matches),
        "matchday_date": sum(match.matchday_date is not None for match in matches),
        "source_match_date": sum(match.source_match_date is not None for match in matches),
        "home_team_id": sum(match.home_team_id is not None for match in matches),
        "away_team_id": sum(match.away_team_id is not None for match in matches),
        "status": sum(match.status is not None for match in matches),
        "score": sum(match.status == "played" for match in matches),
        "individual_url": sum(bool(match.source_match_url) for match in matches),
        "yellow_cards_pair": sum(
            match.home_yellow_cards is not None and match.away_yellow_cards is not None
            for match in matches
        ),
        "red_cards_pair": sum(
            match.home_red_cards is not None and match.away_red_cards is not None
            for match in matches
        ),
        "stadium": sum(bool(match.stadium_name) for match in matches),
        "referee": sum(bool(match.referee_name) for match in matches),
    }
    statuses: dict[str, int] = {}
    for match in matches:
        statuses[match.status] = statuses.get(match.status, 0) + 1
    return {
        "teams": len(teams),
        "matches": len(matches),
        "statuses": statuses,
        "played_zero_zero": sum(
            match.status == "played" and match.home_goals == 0 and match.away_goals == 0
            for match in matches
        ),
        "fields": fields,
    }


def _write_immutable_generation(
    output_root: Path, generation_id: str, artifacts: dict[str, bytes]
) -> Path:
    generations = output_root / "generations"
    target = generations / generation_id
    if target.exists():
        if not target.is_dir() or any(
            not (target / name).is_file() or (target / name).read_bytes() != data
            for name, data in artifacts.items()
        ):
            raise FileExistsError(f"La generación existente no coincide; no se sobrescribe: {target}")
        return target

    generations.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{generation_id}.", dir=generations) as temporary:
        stage = Path(temporary)
        for name, data in artifacts.items():
            path = stage / name
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            os.rename(stage, target)
        except FileExistsError:
            if any(
                not (target / name).is_file() or (target / name).read_bytes() != data
                for name, data in artifacts.items()
            ):
                raise FileExistsError(f"La generación concurrente no coincide; no se sobrescribe: {target}")
    return target


def build_match_generation(
    *,
    group_i_root: Path,
    group_i_matches: Path,
    group_ii_root: Path,
    group_ii_matches: Path,
    output_root: Path,
    data_root: Path,
) -> Path:
    """Valida dos capturas locales y publica una generación nueva, inmutable."""
    group_payloads: dict[str, dict[str, Any]] = {}
    group_summaries: dict[str, dict[str, Any]] = {}
    group_validations: dict[str, dict[str, Any]] = {}
    for group, root, matches_path in (
        ("I", group_i_root, group_i_matches),
        ("II", group_ii_root, group_ii_matches),
    ):
        payload, summary, validation = _load_group(
            group, root.resolve(), matches_path.resolve(), data_root.resolve()
        )
        group_payloads[group] = payload
        group_summaries[group] = summary
        group_validations[group] = validation

    team_ids = [
        team["team_id"]
        for group_payload in group_payloads.values()
        for team in group_payload["teams"]
    ]
    if len(team_ids) != 40 or len(set(team_ids)) != 40:
        raise MatchGenerationError("Los dos grupos no aportan 40 IDs de equipo únicos")

    fingerprints = [
        group_summaries[group]["source"]
        for group in ("I", "II")
    ]
    generation_hash = _sha256(
        json.dumps(fingerprints, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    generation_id = f"match-00-{generation_hash[:16]}"
    matches_payload = {
        "schema_version": 1,
        "metadata": {
            "source": "BDFutbol",
            "competition": COMPETITION,
            "season": SEASON,
            "generation_id": generation_id,
            "group_count": 2,
            "identity_policy": "internal_id namespaces the source match ID by season and group",
        },
        "groups": group_payloads,
    }
    validation_payload = {
        "schema_version": 1,
        "valid": True,
        "groups": {
            group: {
                **group_validations[group],
                "coverage": group_summaries[group]["coverage"],
            }
            for group in ("I", "II")
        },
        "totals": {
            "teams": sum(item["coverage"]["teams"] for item in group_summaries.values()),
            "matches": sum(item["coverage"]["matches"] for item in group_summaries.values()),
            "played": sum(
                item["coverage"]["statuses"].get("played", 0)
                for item in group_summaries.values()
            ),
            "unplayed": sum(
                item["coverage"]["statuses"].get("unplayed", 0)
                for item in group_summaries.values()
            ),
            "incomplete": sum(
                item["coverage"]["statuses"].get("incomplete", 0)
                for item in group_summaries.values()
            ),
            "explicit_individual_urls": sum(
                item["coverage"]["fields"]["individual_url"]
                for item in group_summaries.values()
            ),
        },
    }
    matches_bytes = _json_bytes(matches_payload)
    validation_bytes = _json_bytes(validation_payload)
    manifest_payload = {
        "schema_version": 1,
        "generation_id": generation_id,
        "source": "BDFutbol",
        "competition": COMPETITION,
        "season": SEASON,
        "source_captures": [group_summaries[group]["source"] for group in ("I", "II")],
        "counts": validation_payload["totals"],
        "artifacts": {
            "matches.json": {"sha256": _sha256(matches_bytes), "bytes": len(matches_bytes)},
            "validation.json": {"sha256": _sha256(validation_bytes), "bytes": len(validation_bytes)},
        },
    }
    artifacts = {
        "matches.json": matches_bytes,
        "validation.json": validation_bytes,
        "manifest.json": _json_bytes(manifest_payload),
    }
    return _write_immutable_generation(output_root.expanduser().resolve(), generation_id, artifacts)
