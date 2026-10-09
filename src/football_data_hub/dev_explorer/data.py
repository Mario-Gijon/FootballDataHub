"""Carga, validación y transformaciones offline para FootballDataHub Dev Explorer."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from unicodedata import combining, normalize
from zoneinfo import ZoneInfo

REQUIRED_JSON_FILES = (
    "dataset_metadata.json",
    "competition_groups.json",
    "participants.json",
    "standings_group_i.json",
    "standings_group_ii.json",
    "matches_group_i.json",
    "matches_group_ii.json",
    "quality_coverage.json",
)
GROUPS = ("I", "II")
FIXTURE_STATES = ("played", "scheduled", "unresolved", "unconfirmed", "unknown")
EXPECTED_EXPORT_SCHEMA = "football_data_hub.competition_export.v1"
EXPECTED_PLAYER_EXPORT_SCHEMA = "football_data_hub.bdfutbol.player_pages.v3"
PLAYER_EXPORT_ARRAYS = (
    "players",
    "profiles",
    "trajectory",
    "statistics",
    "matches",
    "individual_matches",
    "rivals",
    "coverage",
    "acquisition_manifest",
    "memberships",
    "relationships",
    "filtered_variants",
    "player_pilot_candidates",
    "summary",
)

STAT_LABELS = {
    "points": "Puntos",
    "played": "PJ",
    "wins": "PG",
    "draws": "PE",
    "losses": "PP",
    "goals_for": "GF",
    "goals_against": "GC",
    "yellow_cards": "TA",
    "red_cards": "TR",
}


class DatasetValidationError(ValueError):
    """El dataset no cumple la estructura mínima para inspeccionarlo."""


@dataclass(frozen=True, slots=True)
class DatasetCandidate:
    path: Path
    valid: bool
    captured_at_utc: str | None
    parser_version: str | None
    extraction_key: str | None
    errors: tuple[str, ...] = ()

    @property
    def captured_at(self) -> datetime | None:
        return parse_datetime(self.captured_at_utc)

    @property
    def label(self) -> str:
        captured = self.captured_at
        capture_label = captured.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if captured else "sin fecha"
        state_label = "válido" if self.valid else "incompleto"
        version_label = self.parser_version or "parser desconocido"
        return f"{capture_label} · parser {version_label} · {self.path.name} · {state_label}"


@dataclass(slots=True)
class ExplorerDataset:
    path: Path
    metadata: dict[str, Any]
    competition_groups: list[dict[str, Any]]
    participants: list[dict[str, Any]]
    standings: dict[str, list[dict[str, Any]]]
    matches: dict[str, list[dict[str, Any]]]
    quality: dict[str, Any]
    json_files: dict[str, dict[str, Any]]

    def capture_for_group(self, group: str) -> dict[str, Any]:
        captures = self.metadata.get("source_snapshots", {})
        value = captures.get(group, {}) if isinstance(captures, dict) else {}
        return value if isinstance(value, dict) else {}

    @property
    def captured_at_utc(self) -> str | None:
        values = [
            value.get("captured_at_utc")
            for value in self.metadata.get("source_snapshots", {}).values()
            if isinstance(value, dict) and value.get("captured_at_utc")
        ]
        parsed = [parse_datetime(value) for value in values]
        valid = [value for value in parsed if value is not None]
        return max(valid).isoformat() if valid else None


@dataclass(frozen=True, slots=True)
class PlayerExportCandidate:
    path: Path
    valid: bool
    captured_at_utc: str | None
    parser_version: str | None
    schema_version: str | None
    errors: tuple[str, ...] = ()

    @property
    def captured_at(self) -> datetime | None:
        return parse_datetime(self.captured_at_utc)

    @property
    def label(self) -> str:
        captured = self.captured_at
        capture_label = captured.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if captured else "sin fecha"
        return f"{capture_label} · parser {self.parser_version or 'desconocido'} · {self.path.name}"


@dataclass(slots=True)
class PlayerExplorerDataset:
    path: Path
    metadata: dict[str, Any]
    arrays: dict[str, list[dict[str, Any]]]

    @property
    def players(self) -> list[dict[str, Any]]:
        return self.arrays["players"]

    def records_for(self, resource: str, player_id: str) -> list[dict[str, Any]]:
        return [
            record for record in self.arrays.get(resource, [])
            if record.get("player_id") == player_id
        ]

    def player(self, player_id: str) -> dict[str, Any] | None:
        return next((record for record in self.players if record.get("player_id") == player_id), None)

    def profile(self, player_id: str) -> dict[str, Any] | None:
        return next((record for record in self.arrays["profiles"] if record.get("player_id") == player_id), None)

    def coverage_for(self, player_id: str, view: str) -> dict[str, Any] | None:
        return next((
            record for record in self.arrays["coverage"]
            if record.get("player_id") == player_id and record.get("view") == view
        ), None)


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"No se pudo leer {path.name}: {exc}") from exc


def _validate_dataset(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any], tuple[str, ...]]:
    errors: list[str] = []
    documents: dict[str, Any] = {}
    metadata_path = path / "dataset_metadata.json"
    if not metadata_path.is_file():
        return None, documents, ("Falta dataset_metadata.json",)
    try:
        metadata = _read_json(metadata_path)
    except DatasetValidationError as exc:
        return None, documents, (str(exc),)
    if not isinstance(metadata, dict):
        return None, documents, ("dataset_metadata.json debe contener un objeto JSON",)

    if metadata.get("schema_version") != EXPECTED_EXPORT_SCHEMA:
        errors.append(f"schema_version no compatible: {metadata.get('schema_version')!r}")
    if not isinstance(metadata.get("parser_version"), str):
        errors.append("Falta parser_version de tipo texto")
    if not isinstance(metadata.get("extraction_key"), str):
        errors.append("Falta extraction_key de tipo texto")

    snapshots = metadata.get("source_snapshots")
    if not isinstance(snapshots, dict):
        errors.append("source_snapshots debe ser un objeto")
        snapshots = {}
    for group in GROUPS:
        source = snapshots.get(group)
        if not isinstance(source, dict):
            errors.append(f"Falta metadata de origen para Grupo {group}")
            continue
        if parse_datetime(source.get("captured_at_utc")) is None:
            errors.append(f"Fecha de captura ausente o inválida para Grupo {group}")
        for field in ("access_status", "requested_url", "final_url", "snapshot_sha256"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"{field} ausente o inválido en metadata del Grupo {group}")

    for filename in REQUIRED_JSON_FILES[1:]:
        file_path = path / filename
        if not file_path.is_file():
            errors.append(f"Falta {filename}")
            continue
        try:
            document = _read_json(file_path)
        except DatasetValidationError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(document, dict):
            errors.append(f"{filename} debe contener un objeto JSON")
            continue
        documents[filename] = document
        if filename != "quality_coverage.json":
            items = document.get("items")
            if not isinstance(items, list):
                errors.append(f"{filename}: items debe ser una lista")
            elif any(not isinstance(item, dict) for item in items):
                errors.append(f"{filename}: todos los elementos de items deben ser objetos")
        else:
            groups = document.get("groups")
            if not isinstance(groups, list):
                errors.append("quality_coverage.json: groups debe ser una lista")
            elif any(not isinstance(group, dict) for group in groups):
                errors.append("quality_coverage.json: todos los grupos deben ser objetos")
    return metadata, documents, tuple(errors)


def discover_datasets(root: Path) -> list[DatasetCandidate]:
    """Inspecciona datasets hijos del directorio, sin depender del nombre de carpeta."""
    root = root.expanduser()
    if not root.is_dir():
        return []
    candidates: list[DatasetCandidate] = []
    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        metadata, _, errors = _validate_dataset(path)
        snapshots = metadata.get("source_snapshots", {}) if metadata else {}
        captured_values = [
            source.get("captured_at_utc")
            for source in snapshots.values()
            if isinstance(source, dict) and parse_datetime(source.get("captured_at_utc"))
        ] if isinstance(snapshots, dict) else []
        latest_capture = max(
            captured_values,
            key=lambda value: parse_datetime(value) or datetime.min.replace(tzinfo=timezone.utc),
            default=None,
        )
        candidates.append(DatasetCandidate(
            path=path,
            valid=not errors and metadata is not None,
            captured_at_utc=latest_capture,
            parser_version=metadata.get("parser_version") if metadata else None,
            extraction_key=metadata.get("extraction_key") if metadata else None,
            errors=errors,
        ))
    return sorted(
        candidates,
        key=lambda item: (
            item.valid,
            item.captured_at or datetime.min.replace(tzinfo=timezone.utc),
            item.path.name,
        ),
        reverse=True,
    )


def latest_valid_dataset(candidates: list[DatasetCandidate]) -> DatasetCandidate | None:
    valid = [candidate for candidate in candidates if candidate.valid and candidate.captured_at]
    return max(valid, key=lambda candidate: candidate.captured_at) if valid else None


def load_dataset(path: Path) -> ExplorerDataset:
    path = path.expanduser().resolve()
    metadata, documents, errors = _validate_dataset(path)
    if errors or metadata is None:
        raise DatasetValidationError("; ".join(errors) if errors else "Metadata no disponible")
    quality = documents["quality_coverage.json"]
    return ExplorerDataset(
        path=path,
        metadata=metadata,
        competition_groups=documents["competition_groups.json"]["items"],
        participants=documents["participants.json"]["items"],
        standings={
            "I": documents["standings_group_i.json"]["items"],
            "II": documents["standings_group_ii.json"]["items"],
        },
        matches={
            "I": documents["matches_group_i.json"]["items"],
            "II": documents["matches_group_ii.json"]["items"],
        },
        quality=quality,
        json_files={"dataset_metadata.json": metadata, **documents},
    )


def _capture_date(dataset: ExplorerDataset, group: str) -> date | None:
    timestamp = dataset.capture_for_group(group).get("captured_at_utc")
    parsed = parse_datetime(timestamp)
    if parsed is None:
        return None
    try:
        return parsed.astimezone(ZoneInfo("Europe/Madrid")).date()
    except Exception:
        return parsed.date()


def fixture_status(match: dict[str, Any], dataset: ExplorerDataset) -> str:
    """Devuelve estado normalizado; versiones antiguas se derivan sin editar el raw parsed."""
    explicit = match.get("fixture_status")
    if explicit in FIXTURE_STATES:
        return explicit
    result_status = match.get("result_status")
    if result_status in {"played", "available"}:
        return "played"
    if result_status == "unknown":
        return "unknown"
    if result_status not in {"scheduled", "not_available", None, ""}:
        return "unknown"
    raw_date = match.get("date")
    if not isinstance(raw_date, str):
        return "unconfirmed"
    try:
        match_date = date.fromisoformat(raw_date)
    except ValueError:
        return "unconfirmed"
    group = str(match.get("group", ""))
    capture_date = _capture_date(dataset, group)
    if capture_date is None:
        return "unconfirmed"
    return "scheduled" if match_date > capture_date else "unresolved"


def has_result(match: dict[str, Any]) -> bool:
    result_status = match.get("result_status")
    if result_status not in {"available", "played"}:
        return False
    return isinstance(match.get("home_goals"), int) and isinstance(match.get("away_goals"), int)


def _search_key(value: Any) -> str:
    decomposed = normalize("NFKD", str(value).casefold())
    return "".join(character for character in decomposed if not combining(character))


def score_label(match: dict[str, Any]) -> str:
    if has_result(match):
        return f"{match['home_goals']}–{match['away_goals']}"
    return "—"


def filter_matches(
    dataset: ExplorerDataset,
    *,
    group: str | None = None,
    round_number: int | None = None,
    team_season_id: str | None = None,
    statuses: set[str] | None = None,
    search: str = "",
) -> list[dict[str, Any]]:
    groups = (group,) if group in GROUPS else GROUPS
    query = _search_key(search).strip()
    output: list[dict[str, Any]] = []
    for selected_group in groups:
        for match in dataset.matches.get(selected_group, []):
            if round_number is not None and match.get("round") != round_number:
                continue
            if team_season_id and team_season_id not in {
                match.get("home_team_season_id"), match.get("away_team_season_id")
            }:
                continue
            state = fixture_status(match, dataset)
            if statuses is not None and state not in statuses:
                continue
            if query and query not in _search_key(" ".join(str(value) for value in match.values())):
                continue
            output.append({**match, "_display_fixture_status": state, "_display_score": score_label(match)})
    return output


def recent_results(
    dataset: ExplorerDataset, *, group: str | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    """Partidos con resultado, ordenados del más reciente al más antiguo."""
    matches = [
        match
        for match in filter_matches(dataset, group=group, statuses={"played"})
        if has_result(match)
    ]
    matches.sort(
        key=lambda match: (str(match.get("date") or ""), int(match.get("round") or 0)),
        reverse=True,
    )
    return matches[: max(0, limit)]


def upcoming_matches(
    dataset: ExplorerDataset, *, group: str | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    """Partidos programados futuros, ordenados por fecha ascendente."""
    matches = [
        match
        for match in filter_matches(dataset, group=group, statuses={"scheduled"})
        if isinstance(match.get("date"), str) and match.get("date")
    ]
    matches.sort(
        key=lambda match: (str(match.get("date")), int(match.get("round") or 0))
    )
    return matches[: max(0, limit)]


def team_records(dataset: ExplorerDataset, team_season_id: str) -> dict[str, Any] | None:
    participants = [
        team for team in dataset.participants if team.get("team_season_id") == team_season_id
    ]
    if len(participants) != 1:
        return None
    participant = participants[0]
    group = str(participant.get("group", ""))
    standings = [
        row for row in dataset.standings.get(group, [])
        if row.get("team_season_id") == team_season_id
    ]
    matches = [
        match for match in dataset.matches.get(group, [])
        if team_season_id in {
            match.get("home_team_season_id"), match.get("away_team_season_id")
        }
    ]
    return {
        "participant": participant,
        "standing": standings[0] if len(standings) == 1 else None,
        "standing_ambiguous": len(standings) > 1,
        "matches": matches,
    }


def group_quality(dataset: ExplorerDataset, group: str) -> dict[str, Any]:
    quality_group = next(
        (item for item in dataset.quality.get("groups", []) if item.get("group") == group),
        {},
    )
    observed = quality_group.get("observed", {})
    expected_root = dataset.quality.get("expected", {})
    expected = quality_group.get("expected", {})
    matches = dataset.matches.get(group, [])
    standings = dataset.standings.get(group, [])
    rounds = {match.get("round") for match in matches if isinstance(match.get("round"), int)}
    states = Counter(fixture_status(match, dataset) for match in matches)
    missing_ids = [match for match in matches if not match.get("match_id")]
    missing_relations = [
        match for match in matches
        if not match.get("home_team_season_id") or not match.get("away_team_season_id")
    ]
    ids = Counter(str(match["match_id"]) for match in matches if match.get("match_id"))
    duplicate_ids = {match_id: count for match_id, count in ids.items() if count > 1}
    fixture_keys = Counter(
        (match.get("round"), match.get("home_team_name"), match.get("away_team_name"))
        for match in matches
    )
    duplicate_fixtures = [
        {"round": key[0], "home_team_name": key[1], "away_team_name": key[2], "count": count}
        for key, count in fixture_keys.items() if count > 1
    ]
    metadata = dataset.capture_for_group(group)
    return {
        "group": group,
        "teams": len(standings),
        "expected_teams": expected.get("teams", expected_root.get("teams_per_group")),
        "rounds": len(rounds),
        "expected_rounds": expected.get("rounds", expected_root.get("rounds_per_group")),
        "matches": len(matches),
        "expected_matches": expected.get("matches", expected_root.get("matches_per_group")),
        "states": states,
        "results_available": sum(has_result(match) for match in matches),
        "results_missing": sum(not has_result(match) for match in matches),
        "missing_match_ids": missing_ids,
        "duplicate_match_ids": duplicate_ids,
        "duplicate_fixture_keys": duplicate_fixtures,
        "missing_team_relations": missing_relations,
        "reported_unresolved_team_refs": observed.get("fixture_team_references_unresolved"),
        "structural_complete": quality_group.get("fixture_coverage_complete"),
        "coverage_checks": quality_group.get("coverage_checks", {}),
        "parser_diagnostics": quality_group.get("parser_diagnostics", []),
        "access_status": metadata.get("access_status"),
        "http_status": metadata.get("http_status"),
        "requested_url": metadata.get("requested_url"),
        "final_url": metadata.get("final_url"),
        "captured_at_utc": metadata.get("captured_at_utc"),
        "snapshot_sha256": metadata.get("snapshot_sha256"),
    }


def null_counts(value: Any, prefix: str = "") -> dict[str, int]:
    """Cuenta null por ruta de campo; listas se agregan por nombre, no por índice."""
    counts: Counter[str] = Counter()
    if value is None:
        counts[prefix or "(raíz)"] += 1
    elif isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            counts.update(null_counts(child, child_prefix))
    elif isinstance(value, list):
        for child in value:
            counts.update(null_counts(child, prefix))
    return dict(counts)


def flatten_record(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        flattened: dict[str, Any] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(flatten_record(child, child_prefix))
        return flattened
    if isinstance(value, list):
        return {prefix: json.dumps(value, ensure_ascii=False)} if prefix else {"valor": json.dumps(value, ensure_ascii=False)}
    return {prefix or "valor": value}


def search_records(
    records: list[dict[str, Any]], field: str | None = None, query: str = ""
) -> list[dict[str, Any]]:
    query = _search_key(query).strip()
    if not query:
        return records
    found = []
    for record in records:
        flattened = flatten_record(record)
        values = [flattened.get(field)] if field else list(flattened.values())
        if any(query in _search_key(value) for value in values if value is not None):
            found.append(record)
    return found


def diagnostic_rows(dataset: ExplorerDataset) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in GROUPS:
        report = group_quality(dataset, group)
        for check, passed in report["coverage_checks"].items():
            if not passed:
                rows.append({"group": group, "kind": "coverage_check_failed", "field": check})
        for issue in report["parser_diagnostics"]:
            rows.append({"group": group, "kind": "parser_diagnostic", **issue})
        for match_id, count in report["duplicate_match_ids"].items():
            rows.append({"group": group, "kind": "duplicate_match_id", "match_id": match_id, "count": count})
        for duplicate in report["duplicate_fixture_keys"]:
            rows.append({"group": group, "kind": "duplicate_fixture_key", **duplicate})
        for match in report["missing_team_relations"]:
            rows.append({
                "group": group,
                "kind": "team_relation_unresolved",
                "round": match.get("round"),
                "home_team_name": match.get("home_team_name"),
                "home_team_season_id": match.get("home_team_season_id"),
                "away_team_name": match.get("away_team_name"),
                "away_team_season_id": match.get("away_team_season_id"),
                "match_id": match.get("match_id"),
            })
    return rows


def standings_table_rows(dataset: ExplorerDataset, group: str) -> list[dict[str, Any]]:
    output = []
    for row in dataset.standings.get(group, []):
        stats = row.get("stats", {})
        output.append({
            "Posición": row.get("position"),
            "Equipo": row.get("team_name"),
            **{STAT_LABELS.get(key, key): value for key, value in stats.items()},
            "ID equipo/temporada": row.get("team_season_id"),
        })
    return sorted(output, key=lambda row: (row.get("Posición") is None, row.get("Posición") or 0))


def _read_gzip_json(path: Path) -> Any:
    try:
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"No se pudo leer {path.name}: {exc}") from exc


def _player_export_documents(
    path: Path,
) -> tuple[dict[str, Any] | None, dict[str, list[dict[str, Any]]], tuple[str, ...]]:
    errors: list[str] = []
    metadata_path = path / "dataset_metadata.json.gz"
    if not metadata_path.is_file():
        return None, {}, ("Falta dataset_metadata.json.gz",)
    try:
        metadata = _read_gzip_json(metadata_path)
    except DatasetValidationError as exc:
        return None, {}, (str(exc),)
    if not isinstance(metadata, dict):
        return None, {}, ("dataset_metadata.json.gz debe contener un objeto JSON",)
    if metadata.get("schema_version") != EXPECTED_PLAYER_EXPORT_SCHEMA:
        errors.append(f"schema_version no compatible: {metadata.get('schema_version')!r}")
    if not isinstance(metadata.get("parser_version"), str):
        errors.append("Falta parser_version de tipo texto")
    if metadata.get("provider") != "BDFutbol":
        errors.append("provider no corresponde a BDFutbol")
    if not isinstance(metadata.get("source_page_snapshots"), list):
        errors.append("source_page_snapshots debe ser una lista")

    arrays: dict[str, list[dict[str, Any]]] = {}
    for resource in PLAYER_EXPORT_ARRAYS:
        filename = f"{resource}.json.gz"
        file_path = path / filename
        if not file_path.is_file():
            errors.append(f"Falta {filename}")
            continue
        try:
            document = _read_gzip_json(file_path)
        except DatasetValidationError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(document, dict):
            errors.append(f"{filename} debe contener un objeto JSON")
            continue
        if document.get("schema_version") != EXPECTED_PLAYER_EXPORT_SCHEMA:
            errors.append(f"{filename}: schema_version no compatible")
        if document.get("resource") != resource:
            errors.append(f"{filename}: resource no coincide con {resource}")
        items = document.get("items")
        if not isinstance(items, list):
            errors.append(f"{filename}: items debe ser una lista")
        elif any(not isinstance(item, dict) for item in items):
            errors.append(f"{filename}: todos los elementos de items deben ser objetos")
        else:
            arrays[resource] = items

    return metadata, arrays, tuple(errors)


def player_export_captured_at(metadata: dict[str, Any] | None) -> str | None:
    if metadata is None:
        return None
    snapshots = metadata.get("source_page_snapshots", [])
    if not isinstance(snapshots, list):
        return None
    values = [
        item.get("captured_at_utc")
        for item in snapshots
        if isinstance(item, dict) and parse_datetime(item.get("captured_at_utc")) is not None
    ]
    return max(
        values,
        key=lambda value: parse_datetime(value) or datetime.min.replace(tzinfo=timezone.utc),
        default=None,
    )


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parts: list[int] = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def discover_player_exports(root: Path) -> list[PlayerExportCandidate]:
    """Valida exports gzip versionados de jugadores sin leer snapshots raw ni usar red."""
    root = root.expanduser()
    if not root.is_dir():
        return []
    candidates: list[PlayerExportCandidate] = []
    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        metadata, _, errors = _player_export_documents(path)
        candidates.append(PlayerExportCandidate(
            path=path,
            valid=metadata is not None and not errors,
            captured_at_utc=player_export_captured_at(metadata),
            parser_version=metadata.get("parser_version") if metadata else None,
            schema_version=metadata.get("schema_version") if metadata else None,
            errors=errors,
        ))
    return sorted(
        candidates,
        key=lambda item: (
            item.valid,
            item.captured_at or datetime.min.replace(tzinfo=timezone.utc),
            _version_key(item.parser_version),
            item.path.name,
        ),
        reverse=True,
    )


def latest_valid_player_export(
    candidates: list[PlayerExportCandidate],
) -> PlayerExportCandidate | None:
    valid = [candidate for candidate in candidates if candidate.valid]
    return max(
        valid,
        key=lambda item: (
            item.captured_at or datetime.min.replace(tzinfo=timezone.utc),
            _version_key(item.parser_version),
            item.path.name,
        ),
        default=None,
    )


def load_player_export(path: Path) -> PlayerExplorerDataset:
    path = path.expanduser().resolve()
    metadata, arrays, errors = _player_export_documents(path)
    if errors or metadata is None:
        raise DatasetValidationError("; ".join(errors) if errors else "Metadata no disponible")
    return PlayerExplorerDataset(path=path, metadata=metadata, arrays=arrays)


def player_search_label(player: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    """Elige el nombre disponible conservando el raw de plantilla si no hay perfil."""
    name = (profile or {}).get("display_name_raw")
    if not name:
        values = player.get("name_raw_values", [])
        name = values[0] if isinstance(values, list) and values else "Jugador sin nombre raw"
    return f"{name} · {player.get('player_id', 'ID desconocido')}"


def player_match_counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuenta registros, IDs y flags de participación sin borrar duplicados fuente."""
    ids = Counter(str(record["match_id"]) for record in records if record.get("match_id") not in (None, ""))
    appeared_ids = {
        str(record["match_id"])
        for record in records
        if record.get("match_id") not in (None, "")
        and record.get("player_appearance_status") == "APPEARED_PER_SOURCE_FLAGS"
    }
    non_appeared_ids = {
        str(record["match_id"])
        for record in records
        if record.get("match_id") not in (None, "")
        and record.get("player_appearance_status") == "NO_APPEARANCE_PER_SOURCE_FLAGS"
    }
    duplicate_ids = {match_id: count for match_id, count in ids.items() if count > 1}
    return {
        "source_records": len(records),
        "records_with_match_id": sum(ids.values()),
        "unique_match_ids": len(ids),
        "records_without_match_id": sum(record.get("match_id") in (None, "") for record in records),
        "appearance_flag_records": sum(
            record.get("player_appearance_status") == "APPEARED_PER_SOURCE_FLAGS"
            for record in records
        ),
        "non_appearance_flag_records": sum(
            record.get("player_appearance_status") == "NO_APPEARANCE_PER_SOURCE_FLAGS"
            for record in records
        ),
        "unknown_appearance_flag_records": sum(
            record.get("player_appearance_status") not in {
                "APPEARED_PER_SOURCE_FLAGS", "NO_APPEARANCE_PER_SOURCE_FLAGS"
            }
            for record in records
        ),
        "unique_match_ids_with_appearance_flag": len(appeared_ids),
        "unique_match_ids_with_non_appearance_flag": len(non_appeared_ids),
        "duplicate_match_ids": duplicate_ids,
        "duplicate_source_rows": sum(count - 1 for count in duplicate_ids.values()),
    }


def filter_player_matches(
    records: list[dict[str, Any]],
    *,
    season: str | None = None,
    team: str | None = None,
    competition: str | None = None,
) -> list[dict[str, Any]]:
    """Filtra solo filas de fuente ya parseadas; mantiene orden y duplicados."""
    selected: list[dict[str, Any]] = []
    for record in records:
        if season and record.get("season_raw") != season:
            continue
        if team and team not in {
            record.get("player_team_raw"), record.get("home_team_raw"), record.get("away_team_raw")
        }:
            continue
        if competition and record.get("competition_raw") != competition:
            continue
        selected.append(record)
    return selected
