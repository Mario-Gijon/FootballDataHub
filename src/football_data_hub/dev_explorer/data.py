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
EXPECTED_CLUB_EXPORT_SCHEMA = "football_data_hub.bdfutbol.club_team_export.v2"
EXPECTED_CLUB_SPORTS_SCHEMA = "football_data_hub.bdfutbol.club_team_sports.v3"
CLUB_EXPORT_ARRAYS = (
    "matches_from_embedded_data",
    "embedded_match_observations",
    "embedded_match_coverage_by_club",
    "rosters",
    "coaches_current",
    "coverage_by_club",
    "summary",
    "embedded_match_competition_crosscheck",
    "embedded_match_filtered_table_card_crosscheck",
)
CLUB_MATCH_VIEW_FIELDS = {
    "match_id", "date", "date_raw", "season_raw", "match_season_raw", "season_start_year_raw",
    "competition_code_raw", "round_code_raw", "round_label_raw", "home_club_id", "away_club_id",
    "home_club_id_raw", "away_club_id_raw", "home_team_name_raw", "away_team_name_raw",
    "home_goals", "away_goals", "home_goals_raw", "away_goals_raw", "referee_id_raw", "group",
    "home_team_season_id", "away_team_season_id", "match_url", "source_observation_count",
    "source_club_ids", "differing_fields_between_club_sources", "team_season_identity_status",
    "team_season_identity_evidence",
}
CLUB_OBSERVATION_VIEW_FIELDS = {
    "match_id", "source_club_id", "source_team_season_id", "source_club_is_home",
    "source_record_index", "captured_at_utc", "snapshot_sha256", "url", "source_kind",
    "source_values_raw", "source_field_map", "unmapped_values_raw", "date", "season_raw",
    "competition_code_raw", "home_club_id", "home_team_name_raw", "home_goals",
    "away_club_id", "away_team_name_raw", "away_goals", "referee_id_raw", "round_code_raw",
    "round_label_raw",
    "source_club_result_code_raw", "source_club_result_from_score", "source_club_result_validation",
    "source_club_yellow_cards_raw", "source_club_red_cards_raw",
}
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


@dataclass(frozen=True, slots=True)
class ClubExportCandidate:
    path: Path
    valid: bool
    captured_at_utc: str | None
    parser_version: str | None
    extraction_key: str | None
    selection_status: str | None
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
class ClubExplorerDataset:
    path: Path
    metadata: dict[str, Any]
    arrays: dict[str, list[dict[str, Any]]]
    profiles: dict[str, dict[str, Any]]
    profile_errors: dict[str, str]
    team_groups: dict[str, dict[str, str]]
    matches_by_club: dict[str, list[dict[str, Any]]]
    observations_by_match: dict[str, list[dict[str, Any]]]

    @property
    def matches(self) -> list[dict[str, Any]]:
        return self.arrays["matches_from_embedded_data"]

    @property
    def observations(self) -> list[dict[str, Any]]:
        return self.arrays["embedded_match_observations"]

    @property
    def clubs(self) -> list[dict[str, Any]]:
        clubs = []
        for coverage in self.arrays["embedded_match_coverage_by_club"]:
            club_id = str(coverage.get("club_id") or "")
            profile = self.profiles.get(club_id, {})
            team_id = str(coverage.get("team_season_id") or "")
            participant = self.team_groups.get(team_id, {})
            profile_title = profile.get("title")
            profile_name = profile_title.split(" |", 1)[0] if isinstance(profile_title, str) else None
            display_name = participant.get("team_name") or profile_name or club_id or "Club sin ID"
            clubs.append({
                "club_id": club_id,
                "display_name": display_name,
                "team_season_id": team_id or None,
                "team_name": participant.get("team_name"),
                "group": participant.get("group"),
                "search_text": " ".join(str(value) for value in (
                    display_name, club_id, team_id, participant.get("team_name"),
                    profile.get("title"), profile.get("hero_text"),
                ) if value),
                "profile": profile,
                "profile_error": self.profile_errors.get(club_id),
                "history_coverage": coverage,
            })
        return sorted(clubs, key=lambda item: (str(item["display_name"]).casefold(), item["club_id"]))

    def matches_for_club(self, club_id: str) -> list[dict[str, Any]]:
        return self.matches_by_club.get(club_id, [])

    def observations_for_match(self, match_id: str) -> list[dict[str, Any]]:
        return self.observations_by_match.get(match_id, [])


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
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"No se pudo leer {path.name}: {exc}") from exc


class _GzipJSONReader:
    """Lee valores JSON uno a uno desde un gzip, sin materializar el documento entero."""

    def __init__(self, source: Any) -> None:
        self.source = source
        self.buffer = ""
        self.position = 0
        self.eof = False
        self.decoder = json.JSONDecoder()

    def _fill(self) -> bool:
        if self.position:
            self.buffer = self.buffer[self.position:]
            self.position = 0
        chunk = self.source.read(64 * 1024)
        if not chunk:
            self.eof = True
            return False
        self.buffer += chunk
        return True

    def _skip_space(self) -> None:
        while True:
            while self.position < len(self.buffer) and self.buffer[self.position].isspace():
                self.position += 1
            if self.position < len(self.buffer) or not self._fill():
                return

    def peek(self) -> str | None:
        self._skip_space()
        return self.buffer[self.position] if self.position < len(self.buffer) else None

    def expect(self, token: str) -> None:
        self._skip_space()
        while self.position >= len(self.buffer) and self._fill():
            self._skip_space()
        if not self.buffer.startswith(token, self.position):
            raise DatasetValidationError(f"JSON gzip inválido; se esperaba {token!r}")
        self.position += len(token)

    def value(self) -> Any:
        while True:
            self._skip_space()
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.position)
            except json.JSONDecodeError as exc:
                if self._fill():
                    continue
                raise DatasetValidationError(f"JSON gzip incompleto: {exc}") from exc
            self.position = end
            return value


def _stream_gzip_json_items(
    path: Path,
    *,
    keep_fields: set[str] | None = None,
    retain_items: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Valida el array items sin conservar documentos anidados que no use la pantalla."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            reader = _GzipJSONReader(source)
            reader.expect("{")
            envelope: dict[str, Any] = {}
            collected: list[dict[str, Any]] = []
            item_count = 0
            items_seen = False
            first_field = True
            while reader.peek() != "}":
                if not first_field:
                    reader.expect(",")
                first_field = False
                key = reader.value()
                if not isinstance(key, str):
                    raise DatasetValidationError(f"{path.name}: la clave JSON de nivel superior no es texto")
                reader.expect(":")
                if key != "items":
                    envelope[key] = reader.value()
                    continue
                if items_seen:
                    raise DatasetValidationError(f"{path.name}: clave items repetida")
                items_seen = True
                reader.expect("[")
                if reader.peek() != "]":
                    while True:
                        item = reader.value()
                        if not isinstance(item, dict):
                            raise DatasetValidationError(f"{path.name}: todos los elementos de items deben ser objetos")
                        item_count += 1
                        if retain_items:
                            if keep_fields is None:
                                collected.append(item)
                            else:
                                collected.append({
                                    field_name: value
                                    for field_name, value in item.items()
                                    if field_name in keep_fields
                                })
                        if reader.peek() == ",":
                            reader.expect(",")
                            continue
                        reader.expect("]")
                        break
                else:
                    reader.expect("]")
            reader.expect("}")
            if reader.peek() is not None:
                raise DatasetValidationError(f"{path.name}: contenido extra tras el objeto JSON")
            if not items_seen:
                raise DatasetValidationError(f"{path.name}: falta el array items")
            return envelope, collected, item_count
    except DatasetValidationError as exc:
        raise DatasetValidationError(f"No se pudo leer {path.name}: {exc}") from exc
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


def _club_export_documents(
    path: Path,
    *,
    retain_items: bool = True,
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
    if metadata.get("schema_version") != EXPECTED_CLUB_EXPORT_SCHEMA:
        errors.append(f"schema_version no compatible: {metadata.get('schema_version')!r}")
    if metadata.get("provider") != "BDFutbol":
        errors.append("provider no corresponde a BDFutbol")
    extraction_key = metadata.get("extraction_key")
    parser_version = metadata.get("parser_version")
    if not isinstance(extraction_key, str) or not extraction_key.strip():
        errors.append("Falta extraction_key de tipo texto")
    if not isinstance(parser_version, str) or not parser_version.strip():
        errors.append("Falta parser_version de tipo texto")
    snapshots = metadata.get("source_snapshots")
    if not isinstance(snapshots, (list, dict)):
        errors.append("source_snapshots debe ser una lista o un objeto")
    crosscheck_source = metadata.get("competition_crosscheck_source")
    selection = crosscheck_source.get("selection", {}) if isinstance(crosscheck_source, dict) else {}
    if not isinstance(selection, dict) or not isinstance(selection.get("selection_status"), str):
        errors.append("Falta el estado de selección del cruce de competición")

    arrays: dict[str, list[dict[str, Any]]] = {}
    resource_counts: dict[str, int] = {}
    for resource in CLUB_EXPORT_ARRAYS:
        filename = f"sports/{resource}.json.gz"
        file_path = path / filename
        if not file_path.is_file():
            errors.append(f"Falta {filename}")
            continue
        streamed_list = resource not in {
            "summary", "embedded_match_competition_crosscheck", "embedded_match_filtered_table_card_crosscheck",
        }
        try:
            if streamed_list:
                if retain_items and resource == "matches_from_embedded_data":
                    envelope, items, item_count = _stream_gzip_json_items(
                        file_path,
                        keep_fields=CLUB_MATCH_VIEW_FIELDS,
                    )
                elif retain_items and resource == "embedded_match_observations":
                    envelope, items, item_count = _stream_gzip_json_items(
                        file_path,
                        keep_fields=CLUB_OBSERVATION_VIEW_FIELDS,
                    )
                elif not retain_items:
                    lightweight_fields = {"match_id"} if resource == "matches_from_embedded_data" else (
                        {"club_id"} if resource == "embedded_match_coverage_by_club" else set()
                    )
                    envelope, items, item_count = _stream_gzip_json_items(
                        file_path,
                        keep_fields=lightweight_fields,
                        retain_items=bool(lightweight_fields),
                    )
                else:
                    document = _read_gzip_json(file_path)
                    if not isinstance(document, dict):
                        errors.append(f"{filename} debe contener un objeto JSON")
                        continue
                    envelope = {key: value for key, value in document.items() if key != "items"}
                    items = document.get("items")
                    if not isinstance(items, list):
                        errors.append(f"{filename}: items debe ser una lista")
                        continue
                    if any(not isinstance(item, dict) for item in items):
                        errors.append(f"{filename}: todos los elementos de items deben ser objetos")
                        continue
                    item_count = len(items)
            else:
                document = _read_gzip_json(file_path)
                if not isinstance(document, dict):
                    errors.append(f"{filename} debe contener un objeto JSON")
                    continue
                envelope = document
                items = document.get("items")
                if resource == "embedded_match_competition_crosscheck":
                    items = [document]
                    item_count = 1
                elif not isinstance(items, dict):
                    errors.append(f"{filename}: items debe ser un objeto")
                    continue
                else:
                    item_count = 1
                    items = [items]
        except DatasetValidationError as exc:
            errors.append(str(exc))
            continue
        if envelope.get("schema_version") != EXPECTED_CLUB_SPORTS_SCHEMA:
            errors.append(f"{filename}: schema_version no compatible")
        if extraction_key and envelope.get("extraction_key") != extraction_key:
            errors.append(f"{filename}: extraction_key no coincide con metadata")
        if parser_version and envelope.get("parser_version") != parser_version:
            errors.append(f"{filename}: parser_version no coincide con metadata")
        resource_counts[resource] = item_count
        if resource == "embedded_match_competition_crosscheck":
            arrays[resource] = [envelope]
        elif resource in {"summary", "embedded_match_filtered_table_card_crosscheck"}:
            arrays[resource] = items
        elif retain_items or resource in {"matches_from_embedded_data", "embedded_match_coverage_by_club"}:
            arrays[resource] = items

    match_rows = arrays.get("matches_from_embedded_data", [])
    match_ids = [item.get("match_id") for item in match_rows]
    if len(match_ids) != len(set(match_ids)):
        errors.append("matches_from_embedded_data contiene match_id repetidos")
    if any(not isinstance(match_id, str) or not match_id for match_id in match_ids):
        errors.append("matches_from_embedded_data contiene un match_id ausente o inválido")
    coverage_ids = [item.get("club_id") for item in arrays.get("embedded_match_coverage_by_club", [])]
    if len(coverage_ids) != len(set(coverage_ids)):
        errors.append("embedded_match_coverage_by_club contiene club_id repetidos")
    crosscheck_rows = arrays.get("embedded_match_competition_crosscheck", [])
    if not crosscheck_rows or not isinstance(crosscheck_rows[0].get("status"), str):
        errors.append("embedded_match_competition_crosscheck no contiene un estado")
    summary_rows = arrays.get("summary", [])
    if summary_rows:
        expected_counts = {
            "embedded_unique_match_ids": resource_counts.get("matches_from_embedded_data", 0),
            "embedded_match_observations": resource_counts.get("embedded_match_observations", 0),
        }
        for field_name, actual in expected_counts.items():
            reported = summary_rows[0].get(field_name)
            if reported is not None and reported != actual:
                errors.append(f"summary.{field_name} no coincide con el recurso correspondiente")
    return metadata, arrays, tuple(errors)


def club_export_captured_at(metadata: dict[str, Any] | None) -> str | None:
    if metadata is None:
        return None
    snapshots = metadata.get("source_snapshots", [])
    if isinstance(snapshots, dict):
        iterable = snapshots.values()
    elif isinstance(snapshots, list):
        iterable = snapshots
    else:
        return None
    values = [
        item.get("captured_at_utc")
        for item in iterable
        if isinstance(item, dict) and parse_datetime(item.get("captured_at_utc")) is not None
    ]
    return max(
        values,
        key=lambda value: parse_datetime(value) or datetime.min.replace(tzinfo=timezone.utc),
        default=None,
    )


def discover_club_exports(root: Path) -> list[ClubExportCandidate]:
    """Valida exports gzip versionados de clubes y partidos históricos, sin abrir páginas raw."""
    root = root.expanduser()
    if not root.is_dir():
        return []
    candidates = []
    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        metadata, _, errors = _club_export_documents(path, retain_items=False)
        source = metadata.get("competition_crosscheck_source", {}) if metadata else {}
        selection = source.get("selection", {}) if isinstance(source, dict) else {}
        candidates.append(ClubExportCandidate(
            path=path,
            valid=metadata is not None and not errors,
            captured_at_utc=club_export_captured_at(metadata),
            parser_version=metadata.get("parser_version") if metadata else None,
            extraction_key=metadata.get("extraction_key") if metadata else None,
            selection_status=selection.get("selection_status") if isinstance(selection, dict) else None,
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


def latest_valid_club_export(candidates: list[ClubExportCandidate]) -> ClubExportCandidate | None:
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


def verified_participant_groups(datasets: list[ExplorerDataset]) -> dict[str, dict[str, str]]:
    """Cruza equipos-temporada solo si cada export válido conserva el mismo grupo."""
    if not datasets:
        return {}
    participant_maps: list[dict[str, dict[str, str]]] = []
    for dataset in datasets:
        participant_map = {
            str(item["team_season_id"]): {
                "group": str(item["group"]),
                "team_name": str(item.get("team_name") or ""),
            }
            for item in dataset.participants
            if item.get("team_season_id") and item.get("group") in GROUPS
        }
        participant_maps.append(participant_map)
    all_team_ids = set().union(*(set(participant_map) for participant_map in participant_maps))
    result: dict[str, dict[str, str]] = {}
    for team_id in all_team_ids:
        observations = [participant_map.get(team_id) for participant_map in participant_maps]
        present = [item for item in observations if item is not None]
        groups = {item["group"] for item in present}
        if len(observations) != len(datasets) or len(present) != len(datasets) or len(groups) != 1:
            continue
        names = {item["team_name"] for item in present}
        result[team_id] = {
            "group": next(iter(groups)),
            "team_name": next(iter(names)) if len(names) == 1 else "",
        }
    return result


def competition_conflict_evidence(
    datasets: list[ExplorerDataset],
    conflict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Recupera de exports locales los estados raw de ambos lados de un conflicto."""
    left_key = conflict.get("left_extraction_key")
    right_key = conflict.get("right_extraction_key")
    conflicts = conflict.get("conflicts", [])
    identity = conflicts[0].get("fixture_identity", []) if conflicts and isinstance(conflicts[0], dict) else []
    if len(identity) < 5 or identity[0] != "fixture":
        return []
    _, group, season, home_id, away_id = identity[:5]
    rows = []
    for dataset in datasets:
        extraction_key = dataset.metadata.get("extraction_key")
        if extraction_key not in {left_key, right_key}:
            continue
        match = next((
            item for item in dataset.matches.get(str(group), [])
            if item.get("home_team_season_id") == home_id
            and item.get("away_team_season_id") == away_id
        ), None)
        if match is None:
            continue
        source = dataset.capture_for_group(str(group))
        rows.append({
            "extraction_key": extraction_key,
            "season": season,
            "group": group,
            "date": match.get("date"),
            "round": match.get("round"),
            "home_team_name": match.get("home_team_name"),
            "away_team_name": match.get("away_team_name"),
            "result_status": match.get("result_status"),
            "fixture_status": match.get("fixture_status"),
            "status_in_export": match.get("fixture_status") or match.get("result_status"),
            "final_url": source.get("final_url"),
            "captured_at_utc": source.get("captured_at_utc"),
            "snapshot_sha256": source.get("snapshot_sha256"),
        })
    return sorted(rows, key=lambda item: str(item.get("extraction_key")))


def load_club_export(
    path: Path,
    *,
    team_groups: dict[str, dict[str, str]] | None = None,
) -> ClubExplorerDataset:
    """Carga los recursos deportivos compactos y perfiles de club bajo demanda local."""
    path = path.expanduser().resolve()
    metadata, arrays, errors = _club_export_documents(path)
    if errors or metadata is None:
        raise DatasetValidationError("; ".join(errors) if errors else "Metadata no disponible")
    profiles: dict[str, dict[str, Any]] = {}
    profile_errors: dict[str, str] = {}
    for item in arrays["embedded_match_coverage_by_club"]:
        club_id = item.get("club_id")
        if not isinstance(club_id, str) or not club_id:
            continue
        if not all(character.isalnum() or character in "_-" for character in club_id):
            profile_errors[club_id] = "El ID de club no es seguro para resolver la ficha local"
            continue
        profile_path = path / "pages" / "club" / club_id / "club_profile.json.gz"
        if not profile_path.is_file():
            continue
        try:
            profile = _read_gzip_json(profile_path)
        except DatasetValidationError as exc:
            profile_errors[club_id] = str(exc)
            continue
        if not isinstance(profile, dict) or profile.get("entity_type") != "club" or profile.get("entity_id") != club_id:
            profile_errors[club_id] = "La ficha no coincide con el club esperado"
            continue
        source = profile.get("source") if isinstance(profile.get("source"), dict) else {}
        profiles[club_id] = {
            "entity_type": "club",
            "entity_id": club_id,
            "title": profile.get("title"),
            "hero_text": profile.get("hero_text"),
            "url": profile.get("url"),
            "source": {
                "rendered_html_sha256": source.get("rendered_html_sha256"),
                "captured_at_utc": source.get("captured_at_utc"),
            },
        }

    matches_by_club: dict[str, list[dict[str, Any]]] = {}
    for match in arrays["matches_from_embedded_data"]:
        for club_id in {match.get("home_club_id"), match.get("away_club_id")}:
            if isinstance(club_id, str) and club_id:
                matches_by_club.setdefault(club_id, []).append(match)
    observations_by_match: dict[str, list[dict[str, Any]]] = {}
    for observation in arrays["embedded_match_observations"]:
        match_id = observation.get("match_id")
        if isinstance(match_id, str) and match_id:
            observations_by_match.setdefault(match_id, []).append(observation)
    return ClubExplorerDataset(
        path=path,
        metadata=metadata,
        arrays=arrays,
        profiles=profiles,
        profile_errors=profile_errors,
        team_groups=team_groups or {},
        matches_by_club=matches_by_club,
        observations_by_match=observations_by_match,
    )


def search_clubs(clubs: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Busca en nombre visible, identidad permanente y equipo-temporada actual."""
    normalized_query = _search_key(query).strip()
    if not normalized_query:
        return clubs
    return [
        club for club in clubs
        if normalized_query in _search_key(" ".join(str(club.get(field) or "") for field in (
            "display_name", "club_id", "team_season_id", "team_name", "search_text",
        )))
    ]


def _match_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def filter_club_matches(
    matches: list[dict[str, Any]],
    *,
    club_id: str,
    season: str | None = None,
    competition: str | None = None,
    rival: str | None = None,
    venue: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Filtra partidos únicos del índice local; conserva fechas y códigos raw."""
    query = _search_key(rival or "").strip()
    result: list[dict[str, Any]] = []
    for match in matches:
        home_id = match.get("home_club_id")
        away_id = match.get("away_club_id")
        if home_id == club_id:
            rival_id = away_id
            rival_name = match.get("away_team_name_raw")
            match_venue = "local"
        elif away_id == club_id:
            rival_id = home_id
            rival_name = match.get("home_team_name_raw")
            match_venue = "visitante"
        else:
            continue
        if season and match.get("season_raw") != season:
            continue
        if competition and match.get("competition_code_raw") != competition:
            continue
        if venue and match_venue != venue:
            continue
        if query and query not in _search_key(f"{rival_id or ''} {rival_name or ''}"):
            continue
        played_on = _match_date(match.get("date"))
        if date_from and (played_on is None or played_on < date_from):
            continue
        if date_to and (played_on is None or played_on > date_to):
            continue
        result.append(match)
    return sorted(
        result,
        key=lambda item: (
            _match_date(item.get("date")) is None,
            -(_match_date(item.get("date")) or date.min).toordinal(),
            str(item.get("match_id") or ""),
        ),
    )


def club_selection_status(dataset: ClubExplorerDataset) -> dict[str, Any]:
    """Devuelve selección y cotejo sin convertir un cotejo pendiente en discrepancia."""
    source = dataset.metadata.get("competition_crosscheck_source", {})
    selection = source.get("selection", {}) if isinstance(source, dict) else {}
    crosscheck = dataset.arrays.get("embedded_match_competition_crosscheck", [{}])[0]
    summary = dataset.arrays.get("summary", [{}])[0]
    return {
        "selection_status": selection.get("selection_status") if isinstance(selection, dict) else None,
        "selection_reason": selection.get("selection_reason") if isinstance(selection, dict) else None,
        "candidate_conflicts": selection.get("candidate_conflicts", []) if isinstance(selection, dict) else [],
        "crosscheck_status": crosscheck.get("status"),
        "crosscheck_matches_compared": crosscheck.get("matches_compared"),
        "crosscheck_expected": crosscheck.get("competition_export_played_matches"),
        "crosscheck_missing_from_embedded": crosscheck.get("competition_match_ids_missing_from_embedded"),
        "crosscheck_absent_from_competition": crosscheck.get("embedded_match_ids_absent_from_competition"),
        "historical_unique_matches": summary.get("embedded_unique_match_ids"),
        "historical_source_observations": summary.get("embedded_match_observations"),
        "shared_source_observations": summary.get("embedded_duplicate_observations"),
        "historical_seasons": summary.get("embedded_historical_seasons_observed"),
    }


def match_observation_comparison(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Resume qué campos de las observaciones coinciden, sin elegir una fuente."""
    fields = (
        "season_raw", "competition_code_raw", "date", "home_club_id", "home_team_name_raw",
        "home_goals", "away_club_id", "away_team_name_raw", "away_goals", "round_code_raw",
        "round_label_raw", "referee_id_raw",
    )
    if len(observations) < 2:
        return {"source_count": len(observations), "matching_fields": [], "differing_fields": []}
    matching = []
    differing = []
    for field_name in fields:
        values = [item.get(field_name) for item in observations]
        (matching if all(value == values[0] for value in values[1:]) else differing).append(field_name)
    return {"source_count": len(observations), "matching_fields": matching, "differing_fields": differing}
