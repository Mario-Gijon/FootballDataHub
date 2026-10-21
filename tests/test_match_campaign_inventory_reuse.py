"""Publication read reuses one MATCH-00 inventory only for its exact generation."""

from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import (
    CampaignArtifactError,
    _inventory_for_generation,
)


def test_verified_inventory_is_reused_without_rebuilding(monkeypatch):
    generation = SimpleNamespace(generation_id="generation-a", manifest_sha256="sha-a")
    inventory = {"source_generation": {"generation_id": "generation-a", "manifest_sha256": "sha-a"}}
    monkeypatch.setattr(
        "football_data_hub.providers.bdfutbol.match_details.inventory.build_match_detail_inventory",
        lambda _generation: (_ for _ in ()).throw(AssertionError("rebuilt")),
    )
    assert _inventory_for_generation(generation, inventory) is inventory


def test_inventory_from_another_generation_is_rejected():
    generation = SimpleNamespace(generation_id="generation-a", manifest_sha256="sha-a")
    inventory = {"source_generation": {"generation_id": "generation-a", "manifest_sha256": "sha-b"}}
    with pytest.raises(CampaignArtifactError, match="no corresponde"):
        _inventory_for_generation(generation, inventory)
