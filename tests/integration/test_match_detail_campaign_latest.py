from __future__ import annotations

import os
import socket
import urllib.request
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign import (
    MatchDetailCampaignLedger,
)
from football_data_hub.providers.bdfutbol.match_details.sampling_plan import (
    build_offline_sample_plan,
    tree_sha256,
)

pytestmark = pytest.mark.integration


def test_latest_campaign_preflight_is_read_only_and_keeps_272525_review_pending(monkeypatch):
    if os.environ.get("FDH_MATCH_01C_D0_INTEGRATION") != "1":
        pytest.skip("Activa FDH_MATCH_01C_D0_INTEGRATION=1 para usar los datos locales")

    def forbidden(*args, **kwargs):
        raise AssertionError("El preflight D0 no puede utilizar la red")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    data_root = Path(
        os.environ.get("FDH_MATCH_01C_D0_DATA_ROOT", Path.home() / "FootballDataHub-data")
    ).expanduser()
    generation_root = data_root / "matches/generations/match-00-4ad1d610507e425d"
    inventory_dir = (
        data_root
        / "matches/details/inventories/match-detail-inventory-8cf339654c80c0ef"
    )
    store_root = data_root / "matches/details"
    campaign_root = store_root / "campaigns"
    targets = [generation_root, inventory_dir, store_root]
    if campaign_root.exists():
        targets.append(campaign_root)
    before = {str(path): tree_sha256(path) for path in targets}

    plan = build_offline_sample_plan(
        generation_root=generation_root,
        inventory_dir=inventory_dir,
        data_root=data_root,
        store_root=store_root,
    )
    result = MatchDetailCampaignLedger(campaign_root).preflight(plan)

    after = {str(path): tree_sha256(path) for path in targets}
    assert before == after
    assert [item["source_match_id"] for item in result["candidates"]] == [
        "272525",
        "272517",
        "272577",
        "272524",
        "269411",
    ]
    assert result["candidates"][0]["state"] == "DISCOVERY_REVIEW_REQUIRED"
    assert result["candidates"][0]["acquisition_state"] == "DISCOVERY_REVIEW_REQUIRED"
    assert result["candidates"][0]["navigation_count"] == 1
    assert result["candidates"][0]["authorization_consumed"] is True
    assert result["candidates"][0]["capture_promoted"] is False
    assert "DISCOVERY_REVIEW_REQUIRED:272525" in result["blocked_reasons"]
    assert all(item["state"] == "NOT_AUTHORIZED" for item in result["candidates"][1:])
    assert result["navigation_enabled"] is False
    assert result["real_access_adapter_enabled"] is False
    assert result["real_access_adapter_implemented"] is True
    assert result["capture_promotion_enabled"] is False
