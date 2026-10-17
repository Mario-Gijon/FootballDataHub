"""Read-only preflight for the MATCH-01C-D0 campaign ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .campaign import MatchCampaignError, MatchDetailCampaignLedger
from .sampling_plan import MatchSamplePlanError, build_offline_sample_plan


def main(argv: list[str] | None = None) -> int:
    data_root = Path.home() / "FootballDataHub-data"
    default_inventory = (
        data_root
        / "matches/details/inventories/match-detail-inventory-8cf339654c80c0ef"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=data_root)
    parser.add_argument(
        "--generation-root",
        type=Path,
        default=data_root / "matches/generations/match-00-4ad1d610507e425d",
    )
    parser.add_argument("--inventory-dir", type=Path, default=default_inventory)
    parser.add_argument("--store-root", type=Path, default=data_root / "matches/details")
    parser.add_argument(
        "--campaign-root",
        type=Path,
        default=data_root / "matches/details/campaigns",
        help="Ledger independiente; el preflight no lo crea ni modifica.",
    )
    args = parser.parse_args(argv)
    try:
        plan = build_offline_sample_plan(
            generation_root=args.generation_root,
            inventory_dir=args.inventory_dir,
            data_root=args.data_root,
            store_root=args.store_root,
        )
        report = MatchDetailCampaignLedger(args.campaign_root).preflight(plan)
    except (MatchCampaignError, MatchSamplePlanError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "football_data_hub.match_detail_campaign_preflight_error.v1",
                    "status": "BLOCKED",
                    "http_enabled": False,
                    "browser_started": False,
                    "navigation_enabled": False,
                    "real_access_adapter_enabled": False,
                    "capture_promotion_enabled": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_FUTURE_HUMAN_AUTHORIZATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
