"""Cached match documents are invalidated by exact source and package changes."""

import json

import pytest

from football_data_hub_api import match_details_cache
from football_data_hub_api.match_details_cache import _publication_fingerprint
from football_data_hub_api.match_details_dataset import CAMPAIGN_PACKAGE_SCHEMA, MatchDetailsLoadError


def _fixture(tmp_path):
    data = tmp_path / "data"
    published = data / "matches/details/published"
    item = {
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272525",
        "publication_id": "campaign-272525-one", "package_path": "packages/campaign-272525-one",
        "manifest_sha256": "a" * 64,
    }
    package = published / item["package_path"]
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(json.dumps({
        "schema_version": CAMPAIGN_PACKAGE_SCHEMA,
        "campaign_id": "campaign-one", "inventory_id": "inventory-one",
        "source_generation_id": "generation-one",
    }))
    (package / "details.json").write_text("{}")
    (package / "approval.json").write_text("{}")
    campaign = data / "matches/details/campaigns/campaign-one"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_text("{}")
    candidate = campaign / "candidates" / item["internal_id"]
    candidate.mkdir(parents=True)
    source = candidate / "source.html"
    source.write_text("original")
    inventory = data / "matches/details/inventories/inventory-one"
    inventory.mkdir(parents=True)
    (inventory / "inventory.json").write_text("{}")
    generation = data / "matches/generations/generation-one"
    generation.mkdir(parents=True)
    (generation / "manifest.json").write_text(json.dumps({
        "source_captures": [{"files": {"source_html": {"path": "sources/source.html"}}}],
    }))
    catalog = data / "sources/source.html"
    catalog.parent.mkdir()
    catalog.write_text("catalog")
    return data, published, item, source, catalog, campaign


def test_fingerprint_tracks_exact_sources_not_other_candidates(tmp_path):
    data, published, item, source, catalog, campaign = _fixture(tmp_path)

    def fingerprint():
        return _publication_fingerprint(item, data_root=data, published_root=published, known={})

    original = fingerprint()
    unrelated = campaign / "candidates" / "another-match"
    unrelated.mkdir()
    (unrelated / "source.html").write_text("unrelated")
    assert fingerprint() == original
    source.write_text("changed")
    assert fingerprint() != original
    changed = fingerprint()
    catalog.write_text("corrected catalog")
    assert fingerprint() != changed


def test_corrupt_or_symlinked_source_cannot_hit_cache(tmp_path):
    data, published, item, source, catalog, _campaign = _fixture(tmp_path)
    source.unlink()
    source.symlink_to(catalog)
    with pytest.raises(MatchDetailsLoadError, match="symlink"):
        _publication_fingerprint(item, data_root=data, published_root=published, known={})


def test_symlinked_cache_directory_falls_back_to_strict_loader(tmp_path, monkeypatch):
    backing = tmp_path / "backing"
    backing.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.symlink_to(backing, target_is_directory=True)
    calls = []

    def strict_loader(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(match_details_cache, "load_published_match_details", strict_loader)
    result = match_details_cache.load_cached_published_match_details(
        tmp_path / "published", store_root=tmp_path / "store",
        generation_root=tmp_path / "generation", data_root=tmp_path,
        match_bundle=None, player_ids=set(), cache_root=cache_root,
        project_root=tmp_path,
    )
    assert result == {}
    assert len(calls) == 1
