from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.classification import generation_activation as activation
from football_data_hub_api.match_results_dataset import MatchResultsBundle
from tests.test_match_page_api import _bundle


def _bundle_with_id(generation_id: str, digest: str, *, updates: dict[str, object] | None = None) -> MatchResultsBundle:
    base = _bundle()
    groups = dict(base.bootstrap.groups)
    if updates:
        group = groups["II"]
        matches = [
            match.model_copy(update=updates) if match.source_match_id == "272525" else match
            for match in group.matches
        ]
        groups["II"] = group.model_copy(update={"matches": matches})
    metadata = base.bootstrap.metadata.model_copy(update={
        "generation_id": generation_id,
        "generation_sha256": digest,
    })
    bootstrap = base.bootstrap.model_copy(update={"metadata": metadata, "groups": groups})
    return MatchResultsBundle(bootstrap, f'"{generation_id}"')


def test_generation_diff_reports_newly_played_and_pending_detail_queue() -> None:
    before = _bundle_with_id("generation-before", "a" * 64, updates={
        "status": "unplayed", "home_goals": None, "away_goals": None,
        "unplayed_state": "scheduled", "source_match_url": None,
    })
    after = _bundle_with_id("generation-after", "b" * 64, updates={
        "status": "played", "home_goals": 1, "away_goals": 0,
        "unplayed_state": None, "source_match_url": "https://www.bdfutbol.com/es/p/p.php?id=272525",
    })

    report = activation.compare_match_generations(before, after)
    row = next(item for item in report["fixtures"] if item["internal_id"].endswith("272525"))
    assert row["change_type"] == "newly_played"
    assert row["detail_status"] == "details_pending"
    assert report["summary"]["newly_played"] == 1
    assert report["summary"]["played_without_approved_details"] == 2


def test_generation_diff_treats_null_as_unobserved_not_deleted() -> None:
    before = _bundle_with_id("generation-before", "a" * 64)
    after = _bundle_with_id("generation-after", "b" * 64, updates={"source_match_url": None})
    report = activation.compare_match_generations(before, after)
    row = next(item for item in report["fixtures"] if item["internal_id"].endswith("272525"))
    change = next(item for item in row["changes"] if item["field"] == "source_match_url")
    assert change["interpretation"] == "not_observed_in_new_capture"
    assert row["change_type"] == "fixture_updated"


def test_generation_diff_marks_played_to_unplayed_as_review_conflict() -> None:
    before = _bundle_with_id("generation-before", "a" * 64)
    after = _bundle_with_id("generation-after", "b" * 64, updates={
        "status": "unplayed", "home_goals": None, "away_goals": None,
        "unplayed_state": "unknown",
    })
    report = activation.compare_match_generations(before, after)
    row = next(item for item in report["fixtures"] if item["internal_id"].endswith("272525"))
    assert row["change_type"] == "played_to_unplayed_conflict"
    assert row["review_required"] is True


def test_generation_diff_incomplete_to_played_is_newly_played() -> None:
    before = _bundle_with_id("generation-before", "a" * 64, updates={
        "status": "incomplete", "home_goals": None, "away_goals": None,
        "unplayed_state": None,
    })
    after = _bundle_with_id("generation-after", "b" * 64, updates={
        "status": "played", "home_goals": 1, "away_goals": 0,
        "unplayed_state": None,
    })
    report = activation.compare_match_generations(before, after)
    row = next(item for item in report["fixtures"] if item["internal_id"].endswith("272525"))
    assert row["change_type"] == "newly_played"
    assert row["detail_status"] == "details_pending"


def test_generation_diff_records_kickoff_change_and_unknown_is_not_deletion() -> None:
    before = _bundle_with_id("generation-before", "a" * 64)
    after = _bundle_with_id("generation-after", "b" * 64, updates={"kickoff_time_local": "21:15"})
    report = activation.compare_match_generations(before, after)
    row = next(item for item in report["fixtures"] if item["internal_id"].endswith("272525"))
    kickoff = next(item for item in row["changes"] if item["field"] == "kickoff_time_local")
    assert kickoff == {"field": "kickoff_time_local", "before": None, "after": "21:15"}
    assert row["change_type"] == "fixture_updated"
    assert row["review_required"] is True


def test_generation_diff_rejects_fixture_identity_changes_as_hard_conflicts() -> None:
    before = _bundle_with_id("generation-before", "a" * 64)
    after = _bundle_with_id("generation-after", "b" * 64, updates={"home_team_id": 204})
    report = activation.compare_match_generations(before, after)
    assert report["summary"]["hard_conflicts"] == 1
    assert any(row["change_type"] == "identity_conflict" for row in report["fixtures"])


def test_activation_writes_pointer_only_after_verified_receipt_and_is_idempotent(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    store_root = data_root / "matches"
    old_root = data_root / "matches/generations/generation-old"
    new_root = data_root / "matches/generations/generation-new"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    data_root.mkdir(exist_ok=True)
    old_bundle = _bundle_with_id("generation-old", "a" * 64)
    new_bundle = _bundle_with_id("generation-new", "b" * 64)
    bundles = {"generation-old": old_bundle, "generation-new": new_bundle}

    monkeypatch.setattr(
        activation,
        "load_verified_match_generation",
        lambda root, **_kw: SimpleNamespace(generation_id=Path(root).name, manifest_sha256=bundles[Path(root).name].bootstrap.metadata.generation_sha256),
    )
    import football_data_hub_api.match_results_dataset as results_dataset
    import football_data_hub_api.match_details_dataset as details_dataset

    monkeypatch.setattr(results_dataset, "load_match_results_dataset", lambda root, **_kw: bundles[Path(root).name])
    monkeypatch.setattr(details_dataset, "load_published_match_details", lambda *_a, **_kw: {})
    report = activation.compare_match_generations(old_bundle, new_bundle)

    result = activation.activate_match_generation(
        new_root,
        store_root=store_root,
        data_root=data_root,
        reviewer="operator",
        expected_generation_id="generation-old",
        confirm_report_sha256=report["report_sha256"],
        approved_detail_ids=set(),
        player_ids=set(),
    )
    assert result["status"] == "activated"
    assert (store_root / "active-generation.json").is_file()
    assert activation.resolve_match_generation_root(store_root, data_root=data_root) == new_root

    repeated = activation.activate_match_generation(
        new_root,
        store_root=store_root,
        data_root=data_root,
        reviewer="operator",
        expected_generation_id=None,
        confirm_report_sha256="not-needed-for-idempotent-repeat",
        approved_detail_ids=set(),
        player_ids=set(),
    )
    assert repeated["status"] == "already_active"

    next_root = data_root / "matches/generations/generation-next"
    next_root.mkdir(parents=True)
    next_bundle = _bundle_with_id("generation-next", "c" * 64)
    bundles["generation-next"] = next_bundle
    next_report = activation.compare_match_generations(new_bundle, next_bundle)
    with pytest.raises(activation.MatchGenerationActivationError, match="hash exacto"):
        activation.activate_match_generation(
            next_root,
            store_root=store_root,
            data_root=data_root,
            reviewer="operator",
            expected_generation_id="generation-new",
            confirm_report_sha256="bad-confirmation",
            approved_detail_ids=set(),
            player_ids=set(),
        )
    assert activation.resolve_match_generation_root(store_root, data_root=data_root) == new_root
    assert next_report["report_sha256"] != report["report_sha256"]

    report_path = store_root / "diffs" / f"diff-{report['report_sha256'][:24]}.json"
    report_path.write_text("{}", encoding="utf-8")
    with pytest.raises(activation.MatchGenerationActivationError, match="informe de diferencias"):
        activation.resolve_match_generation_root(store_root, data_root=data_root)


def test_activation_requires_exact_diff_confirmation_and_leaves_no_pointer(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    store_root = data_root / "matches"
    old_root = data_root / "matches/generations/generation-old"
    new_root = data_root / "matches/generations/generation-new"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    old_bundle = _bundle_with_id("generation-old", "a" * 64)
    new_bundle = _bundle_with_id("generation-new", "b" * 64)
    bundles = {"generation-old": old_bundle, "generation-new": new_bundle}
    monkeypatch.setattr(activation, "load_verified_match_generation", lambda root, **_kw: SimpleNamespace(
        generation_id=Path(root).name,
        manifest_sha256=bundles[Path(root).name].bootstrap.metadata.generation_sha256,
    ))
    import football_data_hub_api.match_results_dataset as results_dataset
    import football_data_hub_api.match_details_dataset as details_dataset

    monkeypatch.setattr(results_dataset, "load_match_results_dataset", lambda root, **_kw: bundles[Path(root).name])
    monkeypatch.setattr(details_dataset, "load_published_match_details", lambda *_a, **_kw: {})
    with pytest.raises(activation.MatchGenerationActivationError, match="hash exacto"):
        activation.activate_match_generation(
            new_root, store_root=store_root, data_root=data_root, reviewer="operator",
            expected_generation_id="generation-old", confirm_report_sha256="wrong",
            approved_detail_ids=set(), player_ids=set(),
        )
    assert not (store_root / "active-generation.json").exists()


def test_active_pointer_rejects_tampered_activation_receipt(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    store_root = data_root / "matches"
    old_root = data_root / "matches/generations/generation-old"
    new_root = data_root / "matches/generations/generation-new"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    old_bundle = _bundle_with_id("generation-old", "a" * 64)
    new_bundle = _bundle_with_id("generation-new", "b" * 64)
    bundles = {"generation-old": old_bundle, "generation-new": new_bundle}
    monkeypatch.setattr(activation, "load_verified_match_generation", lambda root, **_kw: SimpleNamespace(
        generation_id=Path(root).name,
        manifest_sha256=bundles[Path(root).name].bootstrap.metadata.generation_sha256,
    ))
    import football_data_hub_api.match_results_dataset as results_dataset
    import football_data_hub_api.match_details_dataset as details_dataset

    monkeypatch.setattr(results_dataset, "load_match_results_dataset", lambda root, **_kw: bundles[Path(root).name])
    monkeypatch.setattr(details_dataset, "load_published_match_details", lambda *_a, **_kw: {})
    report = activation.compare_match_generations(old_bundle, new_bundle)
    result = activation.activate_match_generation(
        new_root, store_root=store_root, data_root=data_root, reviewer="operator",
        expected_generation_id="generation-old", confirm_report_sha256=report["report_sha256"],
        approved_detail_ids=set(), player_ids=set(),
    )
    event_path = store_root / "activations/events" / f"{result['activation_id']}.json"
    event_path.write_text("{}", encoding="utf-8")
    with pytest.raises(activation.MatchGenerationActivationError, match="no coinciden"):
        activation.resolve_match_generation_root(store_root, data_root=data_root)


def test_store_root_never_guesses_latest_generation(tmp_path) -> None:
    (tmp_path / "matches/generations/newest-looking/manifest.json").parent.mkdir(parents=True)
    (tmp_path / "matches/generations/newest-looking/manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(activation.MatchGenerationActivationError, match="active-generation.json"):
        activation.resolve_match_generation_root(tmp_path / "matches", data_root=tmp_path)
