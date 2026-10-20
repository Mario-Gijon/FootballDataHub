"""Revalidate the saved 272582 discovery artifact offline and create a review candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from football_data_hub.providers.bdfutbol.classification.generation_activation import (
    resolve_match_generation_root,
)
from football_data_hub.providers.bdfutbol.match_details.historical_review import (
    prepare_historical_recovery_candidate,
)
from football_data_hub.providers.bdfutbol.match_details.sampling_plan import (
    build_offline_sample_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=Path.home() / "FootballDataHub-data"
    )
    args = parser.parse_args()
    data_root = args.data_root.expanduser().resolve(strict=True)
    store_root = data_root / "matches" / "details"
    inventory_id = "match-detail-inventory-8cf339654c80c0ef"
    generation_id = "match-00-4ad1d610507e425d"
    source_generation = data_root / "matches" / "generations" / generation_id
    plan = build_offline_sample_plan(
        generation_root=source_generation,
        inventory_dir=data_root / "matches" / "details" / "inventories" / inventory_id,
        data_root=data_root,
        store_root=store_root,
    )
    active_generation = resolve_match_generation_root(
        data_root / "matches", data_root=data_root
    )
    result = prepare_historical_recovery_candidate(
        plan,
        data_root=data_root,
        generation_root=source_generation,
        inventory_dir=data_root / "matches" / "details" / "inventories" / inventory_id,
        store_root=store_root,
        active_generation_root=active_generation,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
