"""Calcula una clasificación local leyendo matches.json, sin navegador ni red."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from football_data_hub.domain.classification.engine import calculate_standings
from football_data_hub.domain.classification.models import ClassificationFilter
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"No se puede serializar {type(value).__name__} a JSON")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--classification", choices=("general", "local", "visitor"), default="general")
    parser.add_argument("--matchday", type=int)
    parser.add_argument("--exclude-postponed", action="store_true")
    parser.add_argument("--range", choices=("all", "dates", "rounds"), default="all")
    parser.add_argument("--date-start", type=date.fromisoformat)
    parser.add_argument("--date-end", type=date.fromisoformat)
    parser.add_argument("--round-start", type=int)
    parser.add_argument("--round-end", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    metadata, teams, matches = load_match_dataset(args.matches)
    filters = ClassificationFilter(
        classification_type=args.classification,
        matchday_cap=args.matchday,
        include_postponed=not args.exclude_postponed,
        range_type=args.range,
        date_start=args.date_start,
        date_end=args.date_end,
        round_start=args.round_start,
        round_end=args.round_end,
    )
    table = calculate_standings(
        teams,
        matches,
        filters,
        source_capture_id=metadata.get("source_capture_id"),
        source_snapshot=metadata.get("source_snapshot"),
    )
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(asdict(table), stream, ensure_ascii=False, indent=2, default=_json_default)
        stream.write("\n")
    print(f"Clasificación de {len(table.rows)} equipos escrita en {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
