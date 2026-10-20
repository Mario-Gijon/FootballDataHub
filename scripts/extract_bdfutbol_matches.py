"""Normaliza partidos desde un snapshot local ya capturado de BDFutbol."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from football_data_hub.providers.bdfutbol.classification.match_io import (
    export_match_dataset,
    make_match_dataset,
)
from football_data_hub.providers.bdfutbol.classification.matches import extract_matches
from football_data_hub.providers.bdfutbol.classification.parser import (
    parse_classification_page,
)
from football_data_hub.domain.classification.validation import validate_match_set

MATCH_EXTRACTOR_VERSION = "0.2.0"


def _repo_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="raw/source.html")
    parser.add_argument("--capture", type=Path, required=True, help="metadata/capture.json")
    parser.add_argument("--output", type=Path, required=True, help="Nueva ruta matches.json")
    parser.add_argument(
        "--validation-output",
        type=Path,
        help=(
            "Ruta explícita para el informe de validación. Si se omite, "
            "se conserva la ubicación histórica relativa al archivo de salida."
        ),
    )
    args = parser.parse_args()

    snapshot_path = args.snapshot.expanduser().resolve()
    capture_path = args.capture.expanduser().resolve()
    source_html = snapshot_path.read_text(encoding="utf-8")
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    url = str(capture["url"])
    parsed = parse_classification_page(source_html, base_url=url)
    captured_at = datetime.fromisoformat(capture["captured_at_utc"])
    teams, matches = extract_matches(
        source_html, parsed, base_url=url, captured_at=captured_at
    )
    repository_root = Path(__file__).resolve().parents[1]
    metadata = {
        "source": capture["source"],
        "url": url,
        "competition": capture["competition"],
        "season": capture["season"],
        "group": capture["group"],
        "source_capture_id": capture["capture_id"],
        "source_captured_at_utc": capture["captured_at_utc"],
        "extractor_version": MATCH_EXTRACTOR_VERSION,
        "parent_extractor_version": capture.get("extractor_version"),
        "source_snapshot": _repo_relative(snapshot_path, repository_root),
        "source_snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "matchday_dates": parsed.matchday_dates,
        "played_matchdays_in_source": parsed.played_matchdays,
    }
    payload = make_match_dataset(teams=teams, matches=matches, metadata=metadata)
    output = export_match_dataset(args.output.expanduser(), payload)
    validation = validate_match_set(
        teams,
        matches,
        expected_teams=20,
        expected_rounds=38,
        fixtures_per_round=10,
    )
    validation["metadata"] = {
        "source_capture_id": capture["capture_id"],
        "source_snapshot": metadata["source_snapshot"],
        "source_snapshot_sha256": metadata["source_snapshot_sha256"],
    }
    validation_path = (
        args.validation_output.expanduser()
        if args.validation_output is not None
        else output.parents[1] / "validation" / "matches.json"
    )
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    with validation_path.open("x", encoding="utf-8") as stream:
        json.dump(validation, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if not validation["valid"]:
        raise SystemExit(f"Validación fallida; revise {validation_path}")
    print(
        f"Exportados {len(matches)} partidos ({payload['counts']['played']} disputados) "
        f"a {output}; validación: {validation_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
