"""Unit tests for offline entity inventory primitives (synthetic inputs)."""

from football_data_hub.audits.entity_inventory import (
    EntityInventoryBuilder,
    acquisition_status,
    build_position_code_catalog,
    deduplicate_entity_references,
    identify_entity_url,
)


def test_identifies_observed_entity_url_families_and_views() -> None:
    assert identify_entity_url("https://www.bdfutbol.com/es/p/p.php?id=272569") == {
        "entity_type": "match", "entity_id": "272569", "view": "match_detail",
    }
    assert identify_entity_url("https://www.bdfutbol.com/es/j/j23751.html") == {
        "entity_type": "player", "entity_id": "j23751", "view": "profile",
    }
    assert identify_entity_url("https://www.bdfutbol.com/es/j/j23751.html?p=stats") == {
        "entity_type": "player", "entity_id": "j23751", "view": "statistics",
    }
    assert identify_entity_url("https://www.bdfutbol.com/es/p/j23751.html") == {
        "entity_type": "player", "entity_id": "j23751", "view": "matches",
    }
    assert identify_entity_url("https://www.bdfutbol.com/es/p/jr23751.html") == {
        "entity_type": "player", "entity_id": "j23751", "view": "rivals",
    }
    assert identify_entity_url("https://www.bdfutbol.com/es/l/l1835.html")["entity_id"] == "l1835"
    assert identify_entity_url("https://www.bdfutbol.com/es/r/r602267.html")["entity_id"] == "602267"
    assert identify_entity_url("https://www.bdfutbol.com/es/s/81.html")["entity_id"] == "81"
    assert identify_entity_url("https://www.bdfutbol.com/es/e/e49.html")["entity_type"] == "club"
    assert identify_entity_url("https://www.bdfutbol.com/es/t/t2026-2749.html")["entity_id"] == "t2026-2749"
    assert identify_entity_url("https://elsewhere.invalid/es/j/j23751.html") is None
    assert identify_entity_url("https://www.bdfutbol.com/es/p/p.php?id=bad") is None


def test_deduplicates_entity_ids_without_losing_distinct_source_hashes() -> None:
    references = [
        {
            "entity_type": "coach",
            "entity_id": "l1835",
            "url": "https://www.bdfutbol.com/es/l/l1835.html",
            "source_reference": {"snapshot_sha256": "a" * 64, "source_view": "club_coaches"},
            "relationship": {"target_entity_type": "club", "target_entity_id": "e49", "source": "snapshot-a"},
        },
        {
            "entity_type": "coach",
            "entity_id": "l1835",
            "url": "https://www.bdfutbol.com/es/l/l1835.html",
            "source_reference": {"snapshot_sha256": "a" * 64, "source_view": "club_coaches"},
            "relationship": {"target_entity_type": "club", "target_entity_id": "e49", "source": "snapshot-a"},
        },
        {
            "entity_type": "coach",
            "entity_id": "l1835",
            "url": "https://www.bdfutbol.com/es/l/l1835.html",
            "source_reference": {"snapshot_sha256": "b" * 64, "source_view": "coach_profile"},
        },
    ]
    result = deduplicate_entity_references(references)
    assert len(result) == 1
    assert result[0]["entity_id"] == "l1835"
    assert result[0]["source_reference_count"] == 2
    assert len(result[0]["observed_urls"]) == 1
    assert len(result[0]["relationships"]) == 1
    assert result[0]["relationships"][0]["source"] == "snapshot-a"


def test_builder_preserves_relationship_source_and_hash() -> None:
    builder = EntityInventoryBuilder()
    builder.add(
        "match",
        "272569",
        url="https://www.bdfutbol.com/es/p/p.php?id=272569",
        source_reference={"snapshot_sha256": "f" * 64, "source_url": "https://www.bdfutbol.com/es/p/e49.html"},
        relationship={
            "source_entity_type": "match",
            "target_entity_type": "club",
            "target_entity_id": "e49",
            "relation_role": "home",
            "evidence": {"snapshot_sha256": "f" * 64},
        },
    )
    record = builder.records()[0]
    assert record["source_references"][0]["snapshot_sha256"] == "f" * 64
    assert record["relationships"][0]["evidence"]["snapshot_sha256"] == "f" * 64


def test_only_single_label_profile_joins_are_verified_in_position_catalog() -> None:
    # Synthetic fixture tests conservative classification; the generated catalog uses local parsed exports.
    memberships = [
        {"player_id": "j1", "position_raw": "1", "url": "roster-a", "snapshot_sha256": "a"},
        {"player_id": "j2", "position_raw": "10", "url": "roster-b", "snapshot_sha256": "b"},
        {"player_id": "j3", "position_raw": "10", "url": "roster-c", "snapshot_sha256": "c"},
        {"player_id": "j4", "position_raw": "6", "url": "roster-d", "snapshot_sha256": "d"},
    ]
    profiles = [
        {"player_id": "j1", "position_raw": "Portero", "source": {"access_status": "VALID", "final_url": "profile-1", "rendered_html_sha256": "1"}},
        {"player_id": "j2", "position_raw": "Delantero", "source": {"access_status": "VALID", "final_url": "profile-2", "rendered_html_sha256": "2"}},
        {"player_id": "j3", "position_raw": "Centrocampista Delantero", "source": {"access_status": "VALID", "final_url": "profile-3", "rendered_html_sha256": "3"}},
        {"player_id": "j4", "position_raw": "Defensa", "source": {"access_status": "CHALLENGE_REQUIRED", "final_url": "profile-4"}},
    ]
    catalog = {item["position_code_raw"]: item for item in build_position_code_catalog(memberships, profiles)}
    assert catalog["1"]["status"] == "VERIFIED_FOR_OBSERVED_PLAYER"
    assert catalog["1"]["position_labels_observed"] == ["Portero"]
    assert catalog["10"]["status"] == "AMBIGUOUS_RAW_LABELS"
    assert catalog["10"]["position_labels_observed"] == ["Centrocampista Delantero", "Delantero"]
    assert catalog["6"]["status"] == "UNVERIFIED_RAW"
    assert catalog["1"]["general_mapping_asserted"] is False


def test_pending_and_invalid_capture_states_are_not_promoted_to_acquired() -> None:
    assert acquisition_status([]) == "PENDING_CAPTURE"
    assert acquisition_status([{"access_status": "CHALLENGE_REQUIRED", "http_status": 403}]) == "BLOCKED_OR_INVALID"
    assert acquisition_status([{"access_status": "VALID", "http_status": 200, "rendered_html_sha256": "abc", "rendered_html_exists": False}]) == "BLOCKED_OR_INVALID"
    assert acquisition_status([{"access_status": "VALID", "http_status": 200, "rendered_html_sha256": "abc", "rendered_html_exists": True}]) == "CAPTURED_VALID"
