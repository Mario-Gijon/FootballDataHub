from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

import pytest

from football_data_hub.domain.matches.details import (
    FieldEvidence,
    MatchDetail,
    MatchDetailIdentity,
    MatchDetailValidation,
    MatchEvent,
    MatchScore,
    MatchTeam,
    match_detail_from_payload,
    parse_literal_minute,
    validate_match_detail_contract,
)
from football_data_hub.providers.bdfutbol.match_details.policy import assess_capture
from football_data_hub.providers.bdfutbol.match_details.store import (
    MatchDetailStore,
    MatchDetailStoreError,
    MatchDetailStoreLocked,
)
from tests.match_detail_fixtures import inventory_record, make_inventory


def _detail(record, *, match_date=None, score=None):
    return MatchDetail(
        schema_version="football_data_hub.match_detail.v1",
        identity=MatchDetailIdentity(
            internal_id=record["internal_id"],
            source_match_id=record["source_match_id"],
            season=record["season"],
            competition=record["competition"],
            group=record["group"],
            matchday=record["matchday"],
            home_team_id=record["home_team_id"],
            away_team_id=record["away_team_id"],
        ),
        source="BDFutbol",
        source_url=record["source_match_url"],
        source_generation_id=record["source_generation_id"],
        source_capture_id=record["source_capture_id"],
        match_date=match_date or record["source_match_date"],
        home_team=MatchTeam(team_id=record["home_team_id"]),
        away_team=MatchTeam(team_id=record["away_team_id"]),
        score=score or MatchScore(**record["reference_result"]),
        field_evidence=(
            FieldEvidence(field_path="score.home_goals", state="observed", raw_value="0"),
            FieldEvidence(field_path="kickoff_time", state="not_observed"),
        ),
    )


def _validation(
    record,
    *,
    status=200,
    valid=True,
    identity=True,
    evidence=("match_detail_root", "source_match_id", "home_team", "away_team"),
):
    return MatchDetailValidation(
        schema_version="football_data_hub.match_detail_validation.v1",
        valid=valid,
        http_status=status,
        requested_url=record["source_match_url"],
        final_url=record["source_match_url"] if status == 200 else None,
        identity_verified=identity,
        structural_evidence=evidence,
    )


def _source_html(record, label="synthetic-detail"):
    return (
        '<html data-detail-root="match-detail"><body '
        f'data-match-id="{record["source_match_id"]}" '
        f'data-home-team-id="{record["home_team_id"]}" '
        f'data-away-team-id="{record["away_team_id"]}">{label}</body></html>'
    ).encode()


def _detail_with_source_evidence(record, html, parser_version="synthetic-test-parser-v1"):
    source_hash = hashlib.sha256(html).hexdigest()
    evidence = (
        FieldEvidence(
            field_path="structure.match_detail_root",
            state="observed",
            source_reference="fixture://match-detail-root",
            raw_value='data-detail-root="match-detail"',
            source_html_sha256=source_hash,
            parser_version=parser_version,
        ),
        FieldEvidence(
            field_path="identity.source_match_id",
            state="observed",
            source_reference="fixture://match-id",
            raw_value=str(record["source_match_id"]),
            source_html_sha256=source_hash,
            parser_version=parser_version,
        ),
        FieldEvidence(
            field_path="home_team.team_id",
            state="observed",
            source_reference="fixture://home-team-id",
            raw_value=str(record["home_team_id"]),
            source_html_sha256=source_hash,
            parser_version=parser_version,
        ),
        FieldEvidence(
            field_path="away_team.team_id",
            state="observed",
            source_reference="fixture://away-team-id",
            raw_value=str(record["away_team_id"]),
            source_html_sha256=source_hash,
            parser_version=parser_version,
        ),
    )
    return replace(_detail(record), field_evidence=(*_detail(record).field_evidence, *evidence))


def _store_one(tmp_path):
    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    html = _source_html(record)
    capture_id = store.store_valid_capture(
        inventory,
        record,
        html,
        _detail_with_source_evidence(record, html),
        _validation(record),
        parser_version="synthetic-test-parser-v1",
    )
    return inventory, record, store, capture_id


def test_valid_capture_is_atomic_hashed_and_reusable_after_resume(tmp_path):
    inventory, record, store, capture_id = _store_one(tmp_path)
    snapshot = tmp_path / "store/captures" / inventory["inventory_id"] / capture_id
    metadata = json.loads((snapshot / "metadata.json").read_text())
    snapshot_manifest = json.loads((snapshot / "manifest.json").read_text())
    assert metadata["http_status"] == 200
    assert metadata["source_match_id"] == record["source_match_id"]
    assert len(metadata["source_html_sha256"]) == 64
    assert (snapshot / "raw/source.html").read_bytes().startswith(b"<html ")
    assert set(snapshot_manifest["files"]) == {
        "raw/source.html",
        "match_detail.json",
        "validation.json",
        "metadata.json",
    }

    reconciliation = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert reconciliation["blocked"] is False
    assert reconciliation["integrity_blocked"] is False
    assert reconciliation["active_stop"] is False
    assert reconciliation["verified_by_internal_id"][record["internal_id"]]["capture_id"] == capture_id
    assert reconciliation["invalid_snapshots"] == []


def test_repeated_store_for_already_verified_match_is_idempotent(tmp_path):
    inventory, record, store, capture_id = _store_one(tmp_path)
    before = {
        path.relative_to(tmp_path / "store"): path.read_bytes()
        for path in (
            tmp_path / "store/captures" / inventory["inventory_id"] / capture_id
        ).rglob("*")
        if path.is_file()
    }
    repeated = store.store_valid_capture(
        inventory,
        record,
        b"<html>different retry must not overwrite</html>",
        _detail(record),
        _validation(record),
        parser_version="synthetic-test-parser-v1",
    )
    after = {
        path.relative_to(tmp_path / "store"): path.read_bytes()
        for path in (
            tmp_path / "store/captures" / inventory["inventory_id"] / capture_id
        ).rglob("*")
        if path.is_file()
    }
    assert repeated == capture_id
    assert before == after
    assert len(
        list((tmp_path / "store/captures" / inventory["inventory_id"]).iterdir())
    ) == 1


def test_corrupted_or_truncated_html_is_never_reused(tmp_path):
    inventory, record, _, capture_id = _store_one(tmp_path)
    raw_path = (
        tmp_path
        / "store/captures"
        / inventory["inventory_id"]
        / capture_id
        / "raw/source.html"
    )
    raw_path.write_bytes(b"<html><body>truncated")

    reconciliation = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert reconciliation["verified_by_internal_id"] == {}
    assert reconciliation["blocked"] is True
    assert reconciliation["integrity_blocked"] is True
    assert reconciliation["active_stop"] is False
    assert "manifiesto" in reconciliation["invalid_snapshots"][0]["reason"]


def test_corrupted_snapshot_manifest_is_never_reused(tmp_path):
    inventory, _, _, capture_id = _store_one(tmp_path)
    manifest_path = (
        tmp_path
        / "store/captures"
        / inventory["inventory_id"]
        / capture_id
        / "manifest.json"
    )
    manifest_path.write_text("{}\n", encoding="utf-8")

    reconciliation = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert reconciliation["verified_by_internal_id"] == {}
    assert reconciliation["blocked"] is True
    assert "Manifiesto" in reconciliation["invalid_snapshots"][0]["reason"]


@pytest.mark.parametrize("status", [None, 403, 404, 429, 500, 503])
def test_unverified_http_status_is_stop_only(status):
    inventory = make_inventory()
    record = inventory_record(inventory)
    decision = assess_capture(record, _detail(record), _validation(record, status=status))
    assert decision.accepted is False
    assert decision.stop_acquisition is True


def test_challenge_identity_and_structure_failures_stop(tmp_path):
    inventory = make_inventory()
    record = inventory_record(inventory)
    detail = _detail(record)
    validation = _validation(record)
    assert assess_capture(
        record,
        detail,
        MatchDetailValidation(
            schema_version=validation.schema_version,
            valid=False,
            http_status=200,
            requested_url=record["source_match_url"],
            final_url=record["source_match_url"],
            identity_verified=True,
            structural_evidence=("table#classific",),
            challenge_detected=True,
        ),
    ).code == "CHALLENGE_REQUIRED"

    bad_identity = MatchDetailIdentity(
        internal_id=detail.identity.internal_id,
        source_match_id="999999",
        season=detail.identity.season,
        competition=detail.identity.competition,
        group=detail.identity.group,
        matchday=detail.identity.matchday,
        home_team_id=detail.identity.home_team_id,
        away_team_id=detail.identity.away_team_id,
    )
    from dataclasses import replace

    assert assess_capture(record, replace(detail, identity=bad_identity), validation).code == "IDENTITY_MISMATCH"
    assert assess_capture(record, detail, _validation(record, evidence=())).code == "STRUCTURE_UNVERIFIED"

    store = MatchDetailStore(tmp_path / "store")
    with pytest.raises(MatchDetailStoreError, match="HTTP_404"):
        store.store_valid_capture(
            inventory,
            record,
            b"<html>not promoted</html>",
            detail,
            _validation(record, status=404),
            parser_version="test",
        )
    assert not (tmp_path / "store/captures" / inventory["inventory_id"]).exists()


def test_access_failure_diagnostic_stops_and_survives_resume(tmp_path):
    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    decision = store.stop_for_validation(
        inventory,
        record,
        _detail(record),
        _validation(record, status=404),
    )
    resumed = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert decision.code == "HTTP_404"
    assert resumed["diagnostics"][0]["source_match_id"] == record["source_match_id"]
    assert resumed["diagnostics"][0]["requested_url"] == record["source_match_url"]
    assert resumed["diagnostics"][0]["expected_url"] == record["source_match_url"]
    assert resumed["diagnostics"][0]["http_status"] == 404
    assert resumed["diagnostics"][0]["stop_acquisition"] is True


@pytest.mark.parametrize(
    ("validation", "expected_code"),
    [
        (lambda record: _validation(record, status=403), "HTTP_403"),
        (
            lambda record: _validation(record, valid=False, evidence=("match_detail_root",)),
            "STRUCTURE_UNVERIFIED",
        ),
    ],
)
def test_active_access_or_structure_stop_blocks_later_capture_and_preserves_checkpoint(
    tmp_path, validation, expected_code
):
    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    rejected_validation = validation(record)
    decision = store.stop_for_validation(
        inventory, record, _detail(record), rejected_validation
    )
    before = store.reconcile(inventory)
    state_path = tmp_path / "store/states" / f"{inventory['inventory_id']}.json"
    state_before = json.loads(state_path.read_text())
    capture_root = tmp_path / "store/captures" / inventory["inventory_id"]
    files_before = sorted(path.relative_to(capture_root) for path in capture_root.rglob("*"))

    html = _source_html(record, "later-valid-looking-attempt")
    with pytest.raises(MatchDetailStoreError, match="parada activa"):
        store.store_valid_capture(
            inventory,
            record,
            html,
            _detail_with_source_evidence(record, html),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )

    after = store.reconcile(inventory)
    state_after = json.loads(state_path.read_text())
    files_after = sorted(path.relative_to(capture_root) for path in capture_root.rglob("*"))
    assert decision.code == expected_code
    assert before["integrity_blocked"] is False
    assert before["blocked"] is False
    assert before["active_stop"] is True
    assert after["active_stop"] is True
    assert state_before["status"] == state_after["status"] == "stopped"
    assert state_after["diagnostics"] == state_before["diagnostics"]
    assert state_after["diagnostics"][-1]["error_code"] == expected_code
    assert files_after == files_before


def test_verified_snapshot_cannot_be_reused_to_bypass_active_stop(tmp_path):
    inventory, record, store, capture_id = _store_one(tmp_path)
    decision = store.stop_for_validation(
        inventory,
        record,
        _detail(record),
        _validation(record, status=403),
    )
    state_path = tmp_path / "store/states" / f"{inventory['inventory_id']}.json"
    stopped_state = json.loads(state_path.read_text())
    capture_root = tmp_path / "store/captures" / inventory["inventory_id"]
    capture_files_before = {
        path.relative_to(capture_root): path.read_bytes()
        for path in capture_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(MatchDetailStoreError, match="parada activa"):
        store.store_valid_capture(
            inventory,
            record,
            b"different payload must not replace the verified capture",
            _detail(record),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )

    after_state = json.loads(state_path.read_text())
    capture_files_after = {
        path.relative_to(capture_root): path.read_bytes()
        for path in capture_root.rglob("*")
        if path.is_file()
    }
    assert decision.code == "HTTP_403"
    assert after_state["status"] == "stopped"
    assert after_state["diagnostics"] == stopped_state["diagnostics"]
    assert after_state["diagnostics"][-1]["http_status"] == 403
    assert capture_files_after == capture_files_before
    assert store.reconcile(inventory)["verified_by_internal_id"][record["internal_id"]][
        "capture_id"
    ] == capture_id


def test_stopped_checkpoint_blocks_even_without_diagnostic_entries(tmp_path):
    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    store.prepare_inventory(inventory)
    state_path = tmp_path / "store/states" / f"{inventory['inventory_id']}.json"
    state = json.loads(state_path.read_text())
    state["status"] = "stopped"
    json_bytes = json.dumps(state, separators=(",", ":"), sort_keys=True).encode()
    state_path.write_bytes(json_bytes + b"\n")

    html = _source_html(record)
    with pytest.raises(MatchDetailStoreError, match="parada activa"):
        store.store_valid_capture(
            inventory,
            record,
            html,
            _detail_with_source_evidence(record, html),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )

    reconciliation = store.reconcile(inventory)
    assert reconciliation["active_stop"] is True
    assert reconciliation["diagnostics"] == []
    assert json.loads(state_path.read_text())["status"] == "stopped"


def test_validation_flags_alone_cannot_promote_without_source_bound_evidence(tmp_path):
    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    html = _source_html(record)

    with pytest.raises(MatchDetailStoreError, match="SOURCE_EVIDENCE_UNVERIFIED"):
        store.store_valid_capture(
            inventory,
            record,
            html,
            _detail(record),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )

    reconciliation = store.reconcile(inventory)
    assert reconciliation["verified_by_internal_id"] == {}
    assert reconciliation["active_stop"] is True
    assert reconciliation["diagnostics"][-1]["error_code"] == "SOURCE_EVIDENCE_UNVERIFIED"


@pytest.mark.parametrize(
    ("field_path", "replacement", "expected_fragment"),
    [
        ("home_team.team_id", "999", "raw-value-not-in-source-html"),
        ("away_team.team_id", "0" * 64, "source-html-hash-mismatch"),
    ],
)
def test_source_evidence_must_match_html_and_inventory(
    tmp_path, field_path, replacement, expected_fragment
):
    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    html = _source_html(record)
    detail = _detail_with_source_evidence(record, html)
    evidence = tuple(
        replace(item, raw_value=replacement)
        if item.field_path == field_path and expected_fragment == "raw-value-not-in-source-html"
        else replace(item, source_html_sha256=replacement)
        if item.field_path == field_path
        else item
        for item in detail.field_evidence
    )

    with pytest.raises(MatchDetailStoreError, match=expected_fragment):
        store.store_valid_capture(
            inventory,
            record,
            html,
            replace(detail, field_evidence=evidence),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )

    reconciliation = store.reconcile(inventory)
    assert reconciliation["verified_by_internal_id"] == {}
    assert reconciliation["diagnostics"][-1]["stop_acquisition"] is True


def test_calendar_mismatches_are_preserved_as_discrepancies(tmp_path):
    inventory = make_inventory()
    record = inventory_record(inventory)
    detail = _detail(record, match_date="2026-09-01", score=MatchScore(1, 0))
    decision = assess_capture(record, detail, _validation(record))
    assert decision.accepted is True
    assert {item.field_path for item in decision.discrepancies} == {
        "match_date",
        "score.home_goals",
    }


def test_generation_manifest_and_checkpoint_are_immutable_and_resumable(tmp_path):
    inventory = make_inventory()
    store = MatchDetailStore(tmp_path / "store")
    generation_dir = store.prepare_inventory(inventory)
    original = (generation_dir / "inventory.json").read_bytes()
    assert store.prepare_inventory(inventory) == generation_dir
    assert (generation_dir / "inventory.json").read_bytes() == original

    (generation_dir / "inventory.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(MatchDetailStoreError, match="no coincide"):
        store.prepare_inventory(inventory)
    assert (generation_dir / "inventory.json").read_bytes() == b"{}\n"


def test_dry_reconciliation_blocks_a_corrupted_persisted_inventory(tmp_path):
    inventory = make_inventory()
    store = MatchDetailStore(tmp_path / "store")
    generation_dir = store.prepare_inventory(inventory)
    (generation_dir / "manifest.json").write_text("{}\n", encoding="utf-8")

    result = store.reconcile(inventory)
    assert result["blocked"] is True
    assert result["invalid_snapshots"][0]["capture_id"] == "inventory"


def test_failed_atomic_snapshot_publish_leaves_no_partial_capture(monkeypatch, tmp_path):
    import football_data_hub.providers.bdfutbol.match_details.store as store_module

    inventory = make_inventory()
    record = inventory_record(inventory)
    store = MatchDetailStore(tmp_path / "store")
    store.prepare_inventory(inventory)

    def fail_rename(*args, **kwargs):
        raise OSError("synthetic atomic rename failure")

    monkeypatch.setattr(store_module.os, "rename", fail_rename)
    html = _source_html(record)
    with pytest.raises(OSError, match="synthetic"):
        store.store_valid_capture(
            inventory,
            record,
            html,
            _detail_with_source_evidence(record, html),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )
    captures = (
        tmp_path / "store/captures" / inventory["inventory_id"]
    )
    assert captures.exists()
    assert list(captures.iterdir()) == []


def test_store_lock_prevents_concurrent_store_instances_and_is_reentrant(tmp_path):
    inventory = make_inventory()
    root = tmp_path / "store"
    first = MatchDetailStore(root)
    second = MatchDetailStore(root)
    with first.exclusive_lock():
        # Métodos del mismo almacén son reentrantes para una futura sesión secuencial.
        first.prepare_inventory(inventory)
        with pytest.raises(MatchDetailStoreLocked):
            with second.exclusive_lock():
                pass


def test_orphan_snapshot_and_symlink_directory_block_reuse(tmp_path):
    inventory = make_inventory()
    root = tmp_path / "store"
    orphan = root / "captures" / inventory["inventory_id"] / "orphan"
    orphan.mkdir(parents=True)
    result = MatchDetailStore(root).reconcile(inventory)
    assert result["blocked"] is True
    assert result["verified_by_internal_id"] == {}

    outside = tmp_path / "outside"
    outside.mkdir()
    another_root = tmp_path / "symlink-store"
    another_root.mkdir()
    (another_root / "captures").mkdir()
    (another_root / "captures" / inventory["inventory_id"]).symlink_to(
        outside, target_is_directory=True
    )
    result = MatchDetailStore(another_root).reconcile(inventory)
    assert result["blocked"] is True
    assert "symlink" in result["invalid_snapshots"][0]["reason"]


def test_storage_path_through_symlink_is_rejected_before_writing(tmp_path):
    inventory = make_inventory()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MatchDetailStoreError, match="symlinks"):
        MatchDetailStore(link / "store").prepare_inventory(inventory)
    assert list(outside.iterdir()) == []


def test_finalize_requires_every_snapshot_and_rechecks_hashes(tmp_path):
    inventory = make_inventory()
    store = MatchDetailStore(tmp_path / "store")
    store.prepare_inventory(inventory)
    with pytest.raises(MatchDetailStoreError, match="0/2"):
        store.finalize_inventory(inventory)
    assert store.reconcile(inventory)["blocked"] is False

    for record in inventory["matches"]:
        html = _source_html(record)
        store.store_valid_capture(
            inventory,
            record,
            html,
            _detail_with_source_evidence(record, html),
            _validation(record),
            parser_version="synthetic-test-parser-v1",
        )
    result = store.finalize_inventory(inventory)
    assert result == {
        "status": "complete",
        "inventory_id": inventory["inventory_id"],
        "verified_snapshots": 2,
    }


def test_minutes_and_field_states_preserve_source_semantics():
    assert parse_literal_minute("45+2") == (45, 2)
    assert parse_literal_minute("90+6'") == (90, 6)
    assert parse_literal_minute("90+6") == (90, 6)
    assert parse_literal_minute("90+6 (pen.)") is None
    assert parse_literal_minute(None) is None

    zero = FieldEvidence(field_path="score.home_goals", state="observed", raw_value="0")
    empty = FieldEvidence(field_path="coach.name", state="observed", raw_value="")
    absent = FieldEvidence(field_path="timezone", state="explicitly_absent")
    unknown = FieldEvidence(field_path="events", state="not_observed")
    assert zero.raw_value == "0"
    assert empty.raw_value == ""
    assert absent.raw_value is None
    assert unknown.state == "not_observed"


def test_typed_event_contract_roundtrips_literal_added_time_and_rejects_unknown_kind():
    inventory = make_inventory()
    record = inventory_record(inventory)
    detail = replace(
        _detail(record),
        events=(
            MatchEvent(
                event_kind="goal",
                event_order=0,
                minute_literal="45+2",
                minute_base=45,
                minute_added=2,
                team_id=record["home_team_id"],
                source_player_id="12345",
            ),
        ),
    )
    restored = match_detail_from_payload(json.loads(json.dumps(asdict(detail))))
    assert restored.events[0].minute_literal == "45+2"
    assert restored.events[0].minute_base == 45
    assert validate_match_detail_contract(restored) == ()

    missed_penalty = replace(
        detail,
        events=(replace(detail.events[0], event_kind="missed_penalty"),),
    )
    assert validate_match_detail_contract(missed_penalty) == ()

    invalid = replace(detail, events=(replace(detail.events[0], event_kind="mystery"),))
    assert "events[0].event_kind" in validate_match_detail_contract(invalid)
