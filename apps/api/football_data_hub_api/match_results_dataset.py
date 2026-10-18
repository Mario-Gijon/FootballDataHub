"""Read-only API projection of a verified MATCH-00 generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.match_details.inventory import (
    MatchDetailInventoryError,
    load_verified_match_generation,
)
from football_data_hub_api.schemas import (
    MatchGenerationBootstrapResponse,
    MatchPageResponse,
    MatchPublishedDetailsResponse,
)


class MatchResultsLoadError(ValueError):
    """MATCH-00 could not be verified as a complete two-group dataset."""


@dataclass(frozen=True, slots=True)
class MatchResultsBundle:
    bootstrap: MatchGenerationBootstrapResponse
    etag: str


def build_match_page(
    bundle: MatchResultsBundle,
    internal_id: str,
    *,
    details: MatchPublishedDetailsResponse | None = None,
) -> MatchPageResponse | None:
    """Project one identity-checked fixture; exploratory artifacts are never read here."""

    if details is not None and details.publication_status != "approved":
        raise MatchResultsLoadError("El endpoint público solo acepta detalles aprobados.")

    bootstrap = bundle.bootstrap
    for group_code, group in bootstrap.groups.items():
        match = next(
            (item for item in group.matches if item.internal_id == internal_id),
            None,
        )
        if match is None:
            continue
        teams_by_id = {team.team_id: team for team in group.teams}
        home = teams_by_id.get(match.home_team_id)
        away = teams_by_id.get(match.away_team_id)
        if home is None or away is None:
            raise MatchResultsLoadError("El partido apunta a un equipo ausente en MATCH-00.")
        return MatchPageResponse.model_validate({
            "metadata": {
                "contract_version": 2,
                "source": bootstrap.metadata.source,
                "competition": bootstrap.metadata.competition,
                "season": bootstrap.metadata.season,
                "group": group_code,
                "generation_id": bootstrap.metadata.generation_id,
                "generation_sha256": bootstrap.metadata.generation_sha256,
                "source_capture_id": group.source_capture_id,
                "source_captured_at": group.source_captured_at,
            },
            "match": {
                "internal_id": match.internal_id,
                "source_match_id": match.source_match_id,
                "matchday": match.matchday,
                "matchday_date": match.matchday_date,
                "source_match_date": match.source_match_date,
                "home_team": home.model_dump(),
                "away_team": away.model_dump(),
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "status": match.status,
                "unplayed_state": match.unplayed_state,
                "stadium_name": match.stadium_name,
                "stadium_url": match.stadium_url,
                "referee_name": match.referee_name,
                "referee_url": match.referee_url,
                "source_match_url": match.source_match_url,
            },
            "detail_status": "available" if details is not None else "not_available",
            "details": details.model_dump() if details is not None else None,
        })
    return None


def load_match_results_dataset(
    generation_root: Path, *, data_root: Path
) -> MatchResultsBundle:
    try:
        verified = load_verified_match_generation(generation_root, data_root=data_root)
    except (MatchDetailInventoryError, OSError, ValueError, KeyError, TypeError) as exc:
        raise MatchResultsLoadError(f"La generación MATCH-00 no superó la verificación: {exc}") from exc

    manifest = verified.manifest_payload
    sources = {item["group"]: item for item in manifest["source_captures"]}
    groups: dict[str, dict[str, Any]] = {}
    for code in ("I", "II"):
        source = sources[code]
        source_group = verified.matches_payload["groups"][code]
        teams = source_group.get("teams")
        source_matches = source_group.get("matches")
        if not isinstance(teams, list) or not isinstance(source_matches, list):
            raise MatchResultsLoadError(f"MATCH-00 no contiene las colecciones del Grupo {code}.")
        matches = []
        for item in source_matches:
            matches.append({
                "internal_id": item.get("internal_id"),
                "source_match_id": str(item.get("source_match_id")),
                "matchday": item.get("matchday"),
                "matchday_date": item.get("matchday_date"),
                "source_match_date": item.get("source_match_date"),
                "home_team_id": item.get("home_team_id"),
                "away_team_id": item.get("away_team_id"),
                "home_goals": item.get("home_goals"),
                "away_goals": item.get("away_goals"),
                "home_yellow_cards": item.get("home_yellow_cards"),
                "away_yellow_cards": item.get("away_yellow_cards"),
                "home_red_cards": item.get("home_red_cards"),
                "away_red_cards": item.get("away_red_cards"),
                "status": item.get("status"),
                "unplayed_state": item.get("unplayed_state"),
                "postponed_by_source_rule": item.get("postponed_by_source_rule"),
                "source_match_url": item.get("source_match_url"),
                "stadium_id": item.get("stadium_id"),
                "stadium_name": item.get("stadium_name"),
                "stadium_url": item.get("stadium_url"),
                "referee_id": item.get("referee_id"),
                "referee_name": item.get("referee_name"),
                "referee_url": item.get("referee_url"),
            })
        groups[code] = {
            "group": code,
            "source_capture_id": source["capture_id"],
            "source_captured_at": source["captured_at_utc"],
            "teams": teams,
            "matches": matches,
            "scheduled_matchdays": sorted({item["matchday"] for item in matches}),
            "counts": {
                "teams": len(teams),
                "matches": len(matches),
                "played": sum(item["status"] == "played" for item in matches),
                "unplayed": sum(item["status"] == "unplayed" for item in matches),
                "incomplete": sum(item["status"] == "incomplete" for item in matches),
            },
        }

    counts = manifest["counts"]
    captured_at = max(item["captured_at_utc"] for item in sources.values())
    payload = MatchGenerationBootstrapResponse.model_validate({
        "metadata": {
            "schema_version": 1,
            "source": "BDFutbol",
            "competition": manifest["competition"],
            "season": manifest["season"],
            "generation_id": verified.generation_id,
            "generation_sha256": verified.manifest_sha256,
            "captured_at": captured_at,
            "team_count": counts["teams"],
            "match_count": counts["matches"],
            "played_count": counts["played"],
            "unplayed_count": counts["unplayed"],
            "incomplete_count": counts["incomplete"],
        },
        "groups": groups,
    })
    if (payload.metadata.team_count, payload.metadata.match_count) != (40, 760):
        raise MatchResultsLoadError("La generación verificada no contiene 40 equipos y 760 partidos.")
    representation = payload.model_dump_json().encode("utf-8")
    etag = (
        f'"match-results-v1-{verified.generation_id}-'
        f'{hashlib.sha256(representation).hexdigest()[:24]}"'
    )
    return MatchResultsBundle(payload, etag)
