"""JSON versionado de equipos y partidos; no requiere Playwright para leerlo."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from football_data_hub.domain.classification.models import MatchResult, Team


def _default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"No se puede serializar {type(value).__name__} a JSON")


def export_match_dataset(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, default=_default)
        output.write("\n")
    return path


def make_match_dataset(
    *, teams: tuple[Team, ...], matches: tuple[MatchResult, ...], metadata: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": metadata,
        "counts": {
            "teams": len(teams),
            "matches": len(matches),
            "played": sum(match.status == "played" for match in matches),
            "unplayed": sum(match.status == "unplayed" for match in matches),
            "incomplete": sum(match.status == "incomplete" for match in matches),
            "postponed_by_source_rule": sum(
                match.postponed_by_source_rule is True for match in matches
            ),
            "unplayed_states": dict(
                Counter(
                    match.unplayed_state
                    for match in matches
                    if match.unplayed_state is not None
                )
            ),
        },
        "teams": [asdict(team) for team in teams],
        "matches": [asdict(match) for match in matches],
    }


def load_match_dataset(path: Path) -> tuple[dict[str, Any], tuple[Team, ...], tuple[MatchResult, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Versión de matches.json no compatible")
    teams = tuple(Team(**item) for item in payload["teams"])
    matches = tuple(
        MatchResult(
            **{
                **item,
                "matchday_date": date.fromisoformat(item["matchday_date"])
                if item.get("matchday_date")
                else None,
                "source_match_date": date.fromisoformat(item["source_match_date"])
                if item.get("source_match_date")
                else None,
                "source_references": tuple(item.get("source_references", ())),
            }
        )
        for item in payload["matches"]
    )
    return payload["metadata"], teams, matches
