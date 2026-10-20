from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from football_data_hub.domain.matches.details import (
    MatchDetail,
    MatchDetailIdentity,
    MatchEvent,
    MatchScore,
    MatchTeam,
    MatchPlayerAppearance,
)
from football_data_hub_api.match_details_dataset import (
    APPROVAL_SCHEMA,
    INDEX_SCHEMA,
    PACKAGE_SCHEMA,
    MatchDetailsLoadError,
    load_published_match_details,
    project_verified_detail,
    _published_match,
    _validate_detail_against_active_fixture,
    _validate_detail_against_inventory,
)
from football_data_hub_api.match_results_dataset import build_match_page
from tests.test_match_page_api import _bundle


def _detail() -> MatchDetail:
    return MatchDetail(
        schema_version="football_data_hub.match_detail.v1",
        identity=MatchDetailIdentity(
            internal_id="pf-2026-27-group-ii-bdfutbol-272582",
            source_match_id="272582",
            season="2026-27",
            competition="Primera Federación",
            group="II",
            matchday=6,
            home_team_id=49,
            away_team_id=88,
        ),
        source="BDFutbol",
        source_url="https://www.bdfutbol.com/es/p/p.php?id=272582",
        source_generation_id="match-00-test-generation",
        source_capture_id="capture-II",
        match_date="2026-10-10",
        home_team=MatchTeam(
            team_id=49,
            starters=(MatchPlayerAppearance(
                role="starter",
                player_id=123,
                player_name="Jugador Uno",
                profile_url="https://www.bdfutbol.com/es/j/j123.html",
                photo_url="https://www.bdfutbol.com/i/m/123.jpg",
                shirt_number=9,
            ),),
            substitutes=(MatchPlayerAppearance(
                role="substitute",
                player_id=124,
                player_name="Jugador Dos",
                participation_status="entered",
            ),),
        ),
        away_team=MatchTeam(team_id=88),
        score=MatchScore(home_goals=3, away_goals=3),
        events=(
            MatchEvent(
                event_kind="substitution_in",
                minute_literal="90+1",
                minute_base=90,
                minute_added=1,
                team_id=49,
                player_id=124,
                player_name="Jugador Dos",
            ),
            MatchEvent(
                event_kind="substitution_out",
                minute_literal="90+1",
                minute_base=90,
                minute_added=1,
                team_id=49,
                player_id=123,
                player_name="Jugador Uno",
            ),
        ),
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _publication(root, *, approved: bool = True):
    publication_id = "publication-test-01"
    package = root / "packages" / publication_id
    detail_hash = "d" * 64
    html_hash = "e" * 64
    details = project_verified_detail(
        _detail(), source_html_sha256=html_hash, player_ids={123}
    )
    details_raw = _write_json(package / "details.json", details.model_dump(mode="json"))
    details_hash = _sha(details_raw)
    approval = {
        "schema_version": APPROVAL_SCHEMA,
        "publication_status": "approved" if approved else "not_approved",
        "publication_id": publication_id,
        "approved_by": "reviewer@example.test",
        "approved_at_utc": "2026-10-18T12:00:00Z",
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "inventory_id": "match-detail-inventory-test0000000000",
        "capture_id": "20261018T120000.000000Z-aabbccdd",
        "source_capture_id": "capture-II",
        "source_generation_id": "match-00-test-generation",
        "source_generation_manifest_sha256": "a" * 64,
        "match_detail_sha256": detail_hash,
        "source_html_sha256": html_hash,
        "details_sha256": details_hash,
    }
    approval_raw = _write_json(package / "approval.json", approval)
    manifest = {
        "schema_version": PACKAGE_SCHEMA,
        "publication_id": publication_id,
        "internal_id": approval["internal_id"],
        "inventory_id": approval["inventory_id"],
        "capture_id": approval["capture_id"],
        "source_generation_id": approval["source_generation_id"],
        "source_generation_manifest_sha256": approval["source_generation_manifest_sha256"],
        "source_capture_id": "capture-II",
        "match_detail_sha256": detail_hash,
        "source_html_sha256": html_hash,
        "details_sha256": details_hash,
        "approval_sha256": _sha(approval_raw),
    }
    manifest_raw = _write_json(package / "manifest.json", manifest)
    _write_json(root / "index.json", {
        "schema_version": INDEX_SCHEMA,
        "publications": [{
            "internal_id": approval["internal_id"],
            "publication_id": publication_id,
            "package_path": f"packages/{publication_id}",
            "manifest_sha256": _sha(manifest_raw),
        }],
    })


def test_projection_preserves_separate_substitution_events_and_verified_links() -> None:
    document = project_verified_detail(
        _detail(), source_html_sha256="f" * 64, player_ids={123}
    )

    assert document.home.team_id == 49
    assert document.home.starters[0].player_profile_available is True
    assert document.home.substitutes[0].player_profile_available is False
    assert document.home.substitutes[0].participation_status == "entered"
    assert [item.event_kind for item in document.events] == ["substitution_in", "substitution_out"]
    assert [item.minute for item in document.events] == ["90+1", "90+1"]
    assert all(item.related_player_id is None for item in document.events)


def test_projection_labels_only_explicit_penalty_and_own_goal_facts() -> None:
    detail = replace(
        _detail(),
        events=(
            MatchEvent(event_kind="goal", is_penalty=True, team_id=49, player_name="Jugador Uno"),
            MatchEvent(event_kind="goal", is_own_goal=True, team_id=88, player_name="Jugador Tres"),
        ),
    )
    document = project_verified_detail(detail, source_html_sha256="f" * 64, player_ids=set())
    assert [event.event_kind for event in document.events or []] == ["penalty", "own_goal"]


def test_projection_preserves_source_description_for_other_event():
    detail = replace(
        _detail(),
        events=(MatchEvent(
            event_kind="other",
            minute_literal="9",
            minute_base=9,
            team_id=49,
            player_id=123,
            player_name="Jugador Uno",
            source_text="9",
            source_description="Lesión",
        ),),
    )
    document = project_verified_detail(detail, source_html_sha256="f" * 64, player_ids={123})
    assert document.events is not None
    assert document.events[0].source_description == "Lesión"


def test_public_match_projection_rejects_preview_details() -> None:
    from football_data_hub_api.match_details_dataset import project_verified_detail

    preview = project_verified_detail(
        _detail(), source_html_sha256="f" * 64, player_ids=set(), publication_status="preview_only"
    )
    with pytest.raises(ValueError, match="solo acepta detalles aprobados"):
        build_match_page(_bundle(), "pf-2026-27-group-ii-bdfutbol-272582", details=preview)


def test_historically_published_details_remain_valid_with_a_new_active_generation() -> None:
    from football_data_hub_api.match_results_dataset import MatchResultsBundle

    original = _bundle()
    metadata = original.bootstrap.metadata.model_copy(update={
        "generation_id": "match-00-active-generation-2",
        "generation_sha256": "b" * 64,
    })
    active = MatchResultsBundle(
        original.bootstrap.model_copy(update={"metadata": metadata}),
        '"active-generation-2"',
    )
    historical = project_verified_detail(_detail(), source_html_sha256="e" * 64, player_ids=set())

    page = build_match_page(
        active, "pf-2026-27-group-ii-bdfutbol-272582", details=historical
    )
    assert page.metadata.generation_id == "match-00-active-generation-2"
    assert page.details is not None
    assert page.details.source_generation_id == "match-00-test-generation"


def test_historical_generation_context_resolves_the_declared_source_not_the_active_one(tmp_path, monkeypatch) -> None:
    import football_data_hub_api.match_details_dataset as dataset
    import football_data_hub_api.match_results_dataset as results_dataset

    source_bundle = _bundle()
    active_metadata = source_bundle.bootstrap.metadata.model_copy(update={
        "generation_id": "match-00-active-g2",
        "generation_sha256": "b" * 64,
    })
    active_bundle = source_bundle.__class__(
        source_bundle.bootstrap.model_copy(update={"metadata": active_metadata}),
        '"g2"',
        tmp_path / "matches/generations/match-00-active-g2",
    )
    source_generation = type("Verified", (), {
        "generation_id": "match-00-test-generation",
        "manifest_sha256": "a" * 64,
        "manifest_payload": {"source_captures": []},
    })()
    calls: list[str] = []

    def load_generation(path, **_kwargs):
        calls.append(Path(path).name)
        return source_generation

    monkeypatch.setattr(dataset, "load_verified_match_generation", load_generation)
    monkeypatch.setattr(results_dataset, "build_match_results_bundle", lambda *_args, **_kwargs: source_bundle)

    source_root, verified, resolved_bundle = dataset._historical_generation_context(
        {
            "source_generation_id": "match-00-test-generation",
            "source_generation_manifest_sha256": "a" * 64,
        },
        generation_root=active_bundle.generation_root,
        data_root=tmp_path,
        match_bundle=active_bundle,
    )

    assert source_root == tmp_path / "matches/generations/match-00-test-generation"
    assert verified is source_generation
    assert resolved_bundle is source_bundle
    assert calls == ["match-00-test-generation"]


def test_active_fixture_check_accepts_same_identity_and_rejects_result_or_date_conflicts() -> None:
    document = project_verified_detail(_detail(), source_html_sha256="e" * 64, player_ids=set())
    active_match = _published_match(_bundle(), document.internal_id)
    _validate_detail_against_active_fixture(document, active_match)

    wrong_score = active_match.model_copy(update={"home_goals": 2})
    with pytest.raises(MatchDetailsLoadError, match="fixture activo"):
        _validate_detail_against_active_fixture(document, wrong_score)

    wrong_date = active_match.model_copy(update={"source_match_date": "2026-10-11"})
    with pytest.raises(MatchDetailsLoadError, match="fixture activo"):
        _validate_detail_against_active_fixture(document, wrong_date)


def test_kickoff_api_field_requires_verified_source_evidence() -> None:
    from football_data_hub_api.schemas import MatchPublishedDetailsResponse

    raw = project_verified_detail(_detail(), source_html_sha256="e" * 64, player_ids=set()).model_dump(mode="json")
    raw.update({
        "kickoff_time_local": "19:15",
        "kickoff_state": "observed",
        "kickoff_source_text": "Sábado 29/08/2026 (19:15)",
        "kickoff_source_reference": "div.hero.hero-partit .f14 label='Fecha'",
        "kickoff_parser_version": "match-detail-semantic-0.3.0",
        "kickoff_source_html_sha256": "e" * 64,
    })
    valid = MatchPublishedDetailsResponse.model_validate(raw)
    assert valid.kickoff_time_local == "19:15"
    raw["kickoff_source_html_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="HTML verificado"):
        MatchPublishedDetailsResponse.model_validate(raw)

    old_payload = project_verified_detail(_detail(), source_html_sha256="e" * 64, player_ids=set()).model_dump(mode="json")
    for key in (
        "kickoff_time_local", "kickoff_state", "kickoff_timezone", "kickoff_source_text",
        "kickoff_source_reference", "kickoff_parser_version", "kickoff_source_html_sha256",
    ):
        old_payload.pop(key, None)
    assert MatchPublishedDetailsResponse.model_validate(old_payload).kickoff_time_local is None


def test_loader_ignores_diagnostics_when_publication_index_is_absent(tmp_path) -> None:
    root = tmp_path / "published"
    (root / "diagnostics").mkdir(parents=True)
    (root / "diagnostics" / "discovery.json").write_text("{}", encoding="utf-8")
    assert load_published_match_details(
        root,
        store_root=tmp_path / "store",
        generation_root=tmp_path / "generation",
        data_root=tmp_path,
        match_bundle=_bundle(),
        player_ids=set(),
    ) == {}


def test_loader_rejects_dangling_index_symlink_instead_of_treating_it_as_absent(tmp_path) -> None:
    root = tmp_path / "published"
    root.mkdir()
    (root / "index.json").symlink_to(root / "missing-index.json")
    with pytest.raises(MatchDetailsLoadError, match="symlink"):
        load_published_match_details(
            root,
            store_root=tmp_path / "store",
            generation_root=tmp_path / "generation",
            data_root=tmp_path,
            match_bundle=_bundle(),
            player_ids=set(),
        )


def test_inventory_identity_check_rejects_wrong_round_or_match_score() -> None:
    record = {
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "source_match_id": "272582",
        "season": "2026-27",
        "competition": "Primera Federación",
        "group": "II",
        "matchday": 6,
        "home_team_id": 49,
        "away_team_id": 88,
        "source_generation_id": "match-00-test-generation",
        "source_match_date": "2026-10-10",
        "reference_result": {"home_goals": 3, "away_goals": 3},
    }
    _validate_detail_against_inventory(_detail(), record)
    with pytest.raises(MatchDetailsLoadError, match="MATCH-00"):
        _validate_detail_against_inventory(replace(_detail(), identity=replace(_detail().identity, matchday=7)), record)
    with pytest.raises(MatchDetailsLoadError, match="MATCH-00"):
        _validate_detail_against_inventory(
            replace(_detail(), score=replace(_detail().score, away_goals=2)), record
        )


@pytest.mark.parametrize("approved", [True, False])
def test_publication_requires_independent_approval_receipt(tmp_path, monkeypatch, approved) -> None:
    import football_data_hub_api.match_details_dataset as dataset

    root = tmp_path / "published"
    _publication(root, approved=approved)

    @dataclass
    class Generation:
        generation_id: str = "match-00-test-generation"
        manifest_sha256: str = "a" * 64
        manifest_payload: dict = None  # type: ignore[assignment]

    generation = Generation(manifest_payload={"source_captures": [
        {"group": "I", "capture_id": "capture-I"},
        {"group": "II", "capture_id": "capture-II"},
    ]})
    record = {
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "source_match_id": "272582",
        "season": "2026-27",
        "competition": "Primera Federación",
        "group": "II",
        "matchday": 6,
        "home_team_id": 49,
        "away_team_id": 88,
        "source_match_date": "2026-10-10",
        "reference_result": {"home_goals": 3, "away_goals": 3},
        "source_generation_id": "match-00-test-generation",
        "source_generation_manifest_sha256": "a" * 64,
    }
    monkeypatch.setattr(dataset, "load_verified_match_generation", lambda *_args, **_kwargs: generation)
    monkeypatch.setattr(dataset, "build_match_detail_inventory", lambda _generation: {
        "inventory_id": "match-detail-inventory-test0000000000",
        "matches": [record],
    })
    monkeypatch.setattr(dataset.MatchDetailStore, "verify_capture_read_only", lambda *_args, **_kwargs: {
        "internal_id": record["internal_id"],
        "detail": _detail(),
        "metadata": {"source_generation_manifest_sha256": "a" * 64},
        "match_detail_sha256": "d" * 64,
        "source_html_sha256": "e" * 64,
    })

    if not approved:
        with pytest.raises(MatchDetailsLoadError, match="aprobación independiente"):
            load_published_match_details(
                root, store_root=tmp_path / "store", generation_root=tmp_path / "generation",
                data_root=tmp_path, match_bundle=_bundle(), player_ids={123},
            )
    else:
        loaded = load_published_match_details(
            root, store_root=tmp_path / "store", generation_root=tmp_path / "generation",
            data_root=tmp_path, match_bundle=_bundle(), player_ids={123},
        )
        assert loaded[record["internal_id"]].publication_status == "approved"
        index_path = root / "index.json"
        index = json.loads(index_path.read_bytes())
        index["publications"].append({
            "internal_id": "pf-2026-27-group-i-bdfutbol-269409",
            "publication_id": "unselected-package",
            "package_path": "packages/unselected-package",
            "manifest_sha256": "f" * 64,
        })
        index["publications"].sort(key=lambda item: item["internal_id"])
        index_path.write_bytes(dataset._canonical_json(index))
        selected = load_published_match_details(
            root,
            store_root=tmp_path / "store",
            generation_root=tmp_path / "generation",
            data_root=tmp_path,
            match_bundle=_bundle(),
            player_ids={123},
            internal_ids={record["internal_id"]},
        )
        assert set(selected) == {record["internal_id"]}
        with pytest.raises(MatchDetailsLoadError, match="paquete publicado falta"):
            load_published_match_details(
                root,
                store_root=tmp_path / "store",
                generation_root=tmp_path / "generation",
                data_root=tmp_path,
                match_bundle=_bundle(),
                player_ids={123},
            )


def test_campaign_loader_reuses_verified_generation_and_inventory_for_139_publications(
    tmp_path, monkeypatch
) -> None:
    """A publication set shares one verified MATCH-00 context per generation."""
    import football_data_hub_api.match_details_dataset as dataset

    bundle = _bundle()
    generation_id = bundle.bootstrap.metadata.generation_id
    generation_sha256 = bundle.bootstrap.metadata.generation_sha256
    generation = type("VerifiedGeneration", (), {
        "generation_id": generation_id,
        "manifest_sha256": generation_sha256,
        "manifest_payload": {"source_captures": [
            {"group": "I", "capture_id": "capture-I"},
            {"group": "II", "capture_id": "capture-II"},
        ]},
    })()

    internal_ids = [f"pf-2026-27-group-i-bdfutbol-{260000 + index}" for index in range(139)]
    publications = []
    for index, internal_id in enumerate(internal_ids):
        publication_id = f"campaign-test-{index:03d}"
        package = tmp_path / "published" / "packages" / publication_id
        manifest = {
            "schema_version": dataset.CAMPAIGN_PACKAGE_SCHEMA,
            "source_generation_id": generation_id,
            "source_generation_manifest_sha256": generation_sha256,
        }
        manifest_raw = _write_json(package / "manifest.json", manifest)
        _write_json(package / "approval.json", {})
        _write_json(package / "details.json", {})
        publications.append({
            "internal_id": internal_id,
            "publication_id": publication_id,
            "package_path": f"packages/{publication_id}",
            "manifest_sha256": _sha(manifest_raw),
        })
    index_raw = _write_json(tmp_path / "published" / "index.json", {
        "schema_version": INDEX_SCHEMA,
        "publications": publications,
    })
    assert index_raw

    generation_calls = 0
    inventory_calls = 0
    campaign_calls: list[str] = []
    inventory = {
        "inventory_id": "match-detail-inventory-test0000000000",
        "matches": [{"internal_id": internal_id, "test_record": index} for index, internal_id in enumerate(internal_ids)],
    }
    records_by_id = {record["internal_id"]: record for record in inventory["matches"]}

    def load_generation(*_args, **_kwargs):
        nonlocal generation_calls
        generation_calls += 1
        return generation

    def build_inventory(verified_generation):
        nonlocal inventory_calls
        inventory_calls += 1
        assert verified_generation is generation
        return inventory

    def load_campaign(**kwargs):
        campaign_calls.append(kwargs["indexed_internal_id"])
        assert kwargs["generation"] is generation
        assert kwargs["source_record"] is records_by_id[kwargs["indexed_internal_id"]]
        return project_verified_detail(
            _detail(), source_html_sha256="e" * 64, player_ids=set()
        ), object()

    monkeypatch.setattr(dataset, "load_verified_match_generation", load_generation)
    monkeypatch.setattr(dataset, "build_match_detail_inventory", build_inventory)
    monkeypatch.setattr(dataset, "_load_campaign_publication_document", load_campaign)
    monkeypatch.setattr(dataset, "_published_match", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(dataset, "_validate_detail_against_match", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dataset, "_validate_detail_against_active_fixture", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dataset, "_with_verified_kickoff", lambda document, _observation: document)

    loaded = load_published_match_details(
        tmp_path / "published",
        store_root=tmp_path / "store",
        generation_root=tmp_path / "generation",
        data_root=tmp_path,
        match_bundle=bundle,
        player_ids=set(),
    )

    assert len(loaded) == 139
    assert set(loaded) == set(internal_ids)
    assert campaign_calls == internal_ids
    assert generation_calls == 1
    assert inventory_calls == 1
