from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details.historical_review import (
    verify_historical_stop_evidence,
)
from tests.match_detail_semantic_fixtures import (
    DISCOVERY_ID,
    GENERATION_ID,
    INVENTORY_ID,
    MATCH_ID,
    expected_match,
    saved_artifact,
)
from tests.test_match_detail_campaign import _canonical, _plan, _sha
from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
    parse_saved_artifact,
)


GENERATION_SHA = "e" * 64


def _rekey_plan(plan, inventory, inventory_manifest_sha, checkpoint_sha):
    source = plan["source"]
    source["inventory_id"] = INVENTORY_ID
    source["inventory_sha256"] = _sha(_canonical(inventory))
    source["inventory_manifest_sha256"] = inventory_manifest_sha
    source["generation_id"] = GENERATION_ID
    source["generation_manifest_sha256"] = GENERATION_SHA
    source["record_count"] = 5
    for candidate in plan["candidates"]:
        candidate["source_generation_id"] = GENERATION_ID
        candidate["source_generation_manifest_sha256"] = GENERATION_SHA
    basis = plan["campaign"]["campaign_basis"]
    basis["inventory_id"] = INVENTORY_ID
    basis["inventory_sha256"] = source["inventory_sha256"]
    basis["source_generation_id"] = GENERATION_ID
    basis["source_generation_manifest_sha256"] = GENERATION_SHA
    basis["selected_internal_ids"] = [item["internal_id"] for item in plan["candidates"]]
    plan["campaign"]["campaign_id"] = "match-detail-sample-campaign-" + _sha(
        _canonical(basis)
    )[:16]
    plan["campaign"]["legacy_pilot_stop"]["checkpoint_sha256"] = checkpoint_sha
    plan["campaign"]["legacy_pilot_stop"]["checkpoint_revision"] = 4
    plan["campaign_digest"] = _sha(
        _canonical({key: value for key, value in plan.items() if key != "campaign_digest"})
    )
    return plan


def _fixture(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.historical_review as review

    record = expected_match()
    inventory = {
        "inventory_id": INVENTORY_ID,
        "source_generation": {
            "generation_id": GENERATION_ID,
            "manifest_sha256": GENERATION_SHA,
        },
        "matches": [record],
    }
    inventory_dir = tmp_path / "inventories" / INVENTORY_ID
    inventory_dir.mkdir(parents=True)
    inventory_raw = _canonical(inventory)
    (inventory_dir / "inventory.json").write_bytes(inventory_raw)
    inventory_manifest = {
        "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
        "inventory_id": INVENTORY_ID,
        "inventory_sha256": _sha(inventory_raw),
        "record_count": len(inventory["matches"]),
        "source_generation": inventory["source_generation"],
    }
    manifest_raw = _canonical(inventory_manifest)
    (inventory_dir / "manifest.json").write_bytes(manifest_raw)

    store_root = tmp_path / "match-store"
    artifact_parent = store_root / "diagnostics" / INVENTORY_ID
    artifact_dir = saved_artifact(artifact_parent)
    artifact_manifest_raw = (artifact_dir / "manifest.json").read_bytes()
    html_sha = hashlib.sha256((artifact_dir / "raw/source.html").read_bytes()).hexdigest()
    monkeypatch.setattr(review, "HISTORICAL_272582_HTML_SHA256", html_sha)
    attempt_id = "synthetic-original-attempt-reference"
    diagnostic = {
        "source_match_id": MATCH_ID,
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "http_status": 200,
        "error_code": "IDENTITY_OR_CONTENT_UNVERIFIED",
        "navigation_attempt_id": attempt_id,
        "stop_acquisition": True,
    }
    checkpoint = {
        "schema_version": "football_data_hub.match_detail_state.v1",
        "inventory_id": INVENTORY_ID,
        "status": "stopped",
        "revision": 4,
        "verified_snapshots": [],
        "discovery_artifacts": [
            {
                "discovery_id": DISCOVERY_ID,
                "internal_id": diagnostic["internal_id"],
                "manifest_sha256": _sha(artifact_manifest_raw),
                "navigation_attempt_id": attempt_id,
                "source_html_sha256": html_sha,
            }
        ],
        "diagnostics": [diagnostic],
        "navigation_attempts": [
            {
                "attempt_id": attempt_id,
                "inventory_id": INVENTORY_ID,
                "internal_id": diagnostic["internal_id"],
                "source_match_id": MATCH_ID,
                "requested_url": "https://www.bdfutbol.com/es/p/p.php?id=272582",
                "started_at_utc": "2026-10-16T16:39:27Z",
                "resolved_at_utc": "2026-10-16T16:39:42Z",
                "status": "resolved",
                "resolution_evidence": "diagnostic",
                "outcome_code": "IDENTITY_OR_CONTENT_UNVERIFIED",
            }
        ],
        "active_navigation_attempt_id": None,
        "updated_at_utc": "2026-10-16T16:39:42Z",
    }
    states = store_root / "states"
    states.mkdir(parents=True)
    checkpoint_raw = _canonical(checkpoint)
    (states / f"{INVENTORY_ID}.json").write_bytes(checkpoint_raw)

    plan = _rekey_plan(
        _plan(), inventory, _sha(manifest_raw), _sha(checkpoint_raw)
    )
    monkeypatch.setattr(
        review,
        "load_verified_match_generation",
        lambda generation_root, *, data_root: SimpleNamespace(
            generation_id=GENERATION_ID, manifest_sha256=GENERATION_SHA
        ),
    )
    monkeypatch.setattr(review, "build_match_detail_inventory", lambda _: inventory)
    return plan, tmp_path, inventory_dir, store_root, artifact_dir


def test_historical_review_rebuilds_checkpoint_artifact_and_semantics_offline(tmp_path, monkeypatch):
    plan, data_root, inventory_dir, store_root, _ = _fixture(tmp_path, monkeypatch)

    evidence = verify_historical_stop_evidence(
        plan,
        data_root=data_root,
        generation_root=data_root / "generation",
        inventory_dir=inventory_dir,
        store_root=store_root,
    )

    assert evidence["source_match_id"] == "272582"
    assert evidence["semantic_valid"] is True
    assert evidence["promotion_eligible"] is False
    assert evidence["artifact_id"] == DISCOVERY_ID


def test_historical_review_rejects_mutated_artifact_bytes(tmp_path, monkeypatch):
    plan, data_root, inventory_dir, store_root, artifact_dir = _fixture(tmp_path, monkeypatch)
    html_path = artifact_dir / "raw/source.html"
    html_path.write_bytes(html_path.read_bytes() + b"<!-- tampered -->")

    with pytest.raises(Exception, match="Hash/tamaño no coincide"):
        verify_historical_stop_evidence(
            plan,
            data_root=data_root,
            generation_root=data_root / "generation",
            inventory_dir=inventory_dir,
            store_root=store_root,
        )


def test_historical_review_rejects_changed_checkpoint_hash(tmp_path, monkeypatch):
    plan, data_root, inventory_dir, store_root, _ = _fixture(tmp_path, monkeypatch)
    checkpoint = store_root / "states" / f"{INVENTORY_ID}.json"
    checkpoint.write_bytes(checkpoint.read_bytes() + b" ")

    with pytest.raises(Exception, match="hash actual del checkpoint cambió"):
        verify_historical_stop_evidence(
            plan,
            data_root=data_root,
            generation_root=data_root / "generation",
            inventory_dir=inventory_dir,
            store_root=store_root,
        )


def test_historical_review_rejects_semantic_result_marked_invalid(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.historical_review as review

    plan, data_root, inventory_dir, store_root, artifact_dir = _fixture(tmp_path, monkeypatch)
    valid = parse_saved_artifact(artifact_dir, expected_match=expected_match())
    invalid = replace(
        valid,
        validation=replace(valid.validation, semantic_valid=False),
    )
    monkeypatch.setattr(review, "parse_saved_artifact", lambda *a, **k: invalid)

    with pytest.raises(Exception, match="no confirma la identidad histórica"):
        verify_historical_stop_evidence(
            plan,
            data_root=data_root,
            generation_root=data_root / "generation",
            inventory_dir=inventory_dir,
            store_root=store_root,
        )
