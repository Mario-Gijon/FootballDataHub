"""Exit-code and completion-manifest contract for the resumable team batch CLI."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

from football_data_hub.providers.bdfutbol.teams import batch_cli
from football_data_hub.providers.bdfutbol.access import AccessStatus


def _install_fake_batch(monkeypatch, tmp_path: Path, statuses: list[str], *, stopped: bool = False):
    catalogs = {
        group: [
            {"team_id": group * 100 + index, "name": f"Team {group}-{index}", "team_url": "fixture"}
            for index in range(1, 21)
        ]
        for group in (1, 2)
    }

    def load_catalog(_path, *, competition):
        group = competition.group_number
        return catalogs[group], [], {
            "group": competition.group_roman,
            "season": competition.season,
            "sha256": f"group-{group}",
        }

    monkeypatch.setattr(batch_cli, "load_team_catalog", load_catalog)
    monkeypatch.setattr(batch_cli, "_inspect_best", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_cli, "find_pending_evidence", lambda *_args, **_kwargs: None)
    written: list[dict] = []

    def run_batch(*, teams_by_group, groups, requested_views, **_kwargs):
        selected = [
            (group, record)
            for group in groups
            for record in teams_by_group.get(group, [])
        ]
        entries = []
        for index, (group, record) in enumerate(selected):
            status = statuses[min(index, len(statuses) - 1)]
            entries.append({
                "group": "I" if group == 1 else "II",
                "team_id": int(record["team_id"]),
                "team_name": record["name"],
                "status": status,
                "requested_views": list(requested_views),
            })
        return {
            "run_id": "fixture-run",
            "summary": dict(Counter(entry["status"] for entry in entries)),
            "teams": entries,
            "stop_reason": {"kind": "challenge_required"} if stopped else None,
            "stopped_on_access_denial": stopped,
        }

    def write_manifest(_root, manifest):
        written.append(json.loads(json.dumps(manifest)))
        return tmp_path / "manifest.json"

    monkeypatch.setattr(batch_cli, "run_team_batch", run_batch)
    monkeypatch.setattr(batch_cli, "write_batch_manifest", write_manifest)
    return written


def test_selected_subset_can_succeed_without_marking_full_batch_complete(monkeypatch, tmp_path, capsys):
    written = _install_fake_batch(monkeypatch, tmp_path, ["complete"])

    exit_code = batch_cli.main([
        "--groups", "I",
        "--team-id", "101",
        "--output-root", str(tmp_path / "captures"),
        "--pause-seconds", "0",
    ])

    assert exit_code == 0
    assert written[0]["batch_complete"] is False
    assert written[0]["teams"][0]["status"] == "complete"
    assert json.loads(capsys.readouterr().out)["summary"] == {"complete": 1}


def test_all_40_complete_sets_batch_complete_and_exit_zero(monkeypatch, tmp_path):
    written = _install_fake_batch(monkeypatch, tmp_path, ["complete"])

    exit_code = batch_cli.main([
        "--groups", "both",
        "--output-root", str(tmp_path / "captures"),
        "--pause-seconds", "0",
    ])

    assert exit_code == 0
    assert written[0]["batch_scope"]["selected_team_count"] == 40
    assert written[0]["batch_complete"] is True


def test_controlled_stop_writes_incomplete_manifest_and_returns_nonzero(monkeypatch, tmp_path):
    written = _install_fake_batch(monkeypatch, tmp_path, ["failed", "pending"], stopped=True)

    exit_code = batch_cli.main([
        "--groups", "both",
        "--output-root", str(tmp_path / "captures"),
        "--pause-seconds", "0",
    ])

    assert exit_code != 0
    assert len(written) == 1
    assert written[0]["stopped_on_access_denial"] is True
    assert written[0]["batch_complete"] is False
    assert written[0]["summary"] == {"failed": 1, "pending": 39}


def test_refresh_views_force_selected_reacquisition_for_complete_profiles() -> None:
    views = ("squad", "statistics", "follow")
    assessment = SimpleNamespace(
        valid_views=views,
        valid_follow_states=("p", "t", "go", "tot"),
        complete_for_current_policy=True,
        manifest_summary=lambda: {"complete": True},
    )
    args = batch_cli.parse_args([
        "--groups", "II", "--team-id", "49",
        "--view", "squad", "--view", "statistics", "--view", "follow",
        "--refresh-view", "squad", "--refresh-view", "statistics", "--refresh-view", "follow",
    ])

    plan = batch_cli._team_plan(
        record={"team_id": 49, "name": "Real Jaén"},
        group=2,
        views=views,
        assessment=assessment,
        catalog_reference={"group": "II"},
        refresh_views=tuple(args.refresh_view),
    )

    assert plan["action"] == "refresh_selected_views"
    assert plan["missing_views"] == []
    assert plan["missing_follow_states"] == []
    assert plan["planned_page_visits"] == ["squad", "statistics", "follow"]
    assert plan["follow_state_transitions"] == 4
    assert plan["planned_navigation_count"] == 3


def test_explicit_seed_skips_historical_scan_and_reuses_verified_payload(monkeypatch, tmp_path):
    written = _install_fake_batch(monkeypatch, tmp_path, ["complete"])
    seed_id = "20261012T131518.543469Z-43ff1122"
    seed = {"raw_views": {"alignment": "verified"}}
    inspection = SimpleNamespace(
        reusable_as_seed=True, seed=seed, complete_for_current_policy=True,
        valid_views=("alignment",), valid_follow_states=(),
        manifest_summary=lambda: {"capture_id": seed_id},
    )
    selected = []

    def inspect_selected(*_args, **kwargs):
        selected.append(kwargs["capture_id"])
        return inspection

    monkeypatch.setattr(batch_cli, "_inspect_selected_seed", inspect_selected)
    monkeypatch.setattr(batch_cli, "_inspect_best", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("history scanned")))
    assert batch_cli.main([
        "--groups", "I", "--team-id", "101", "--seed-capture", f"101:{seed_id}",
        "--output-root", str(tmp_path / "captures"), "--pause-seconds", "0",
    ]) == 0
    assert selected == [seed_id]
    assert written[0]["teams"][0]["status"] == "complete"


def test_seed_ids_reject_other_team_duplicate_and_unsafe_paths():
    seed = "20261012T131518.543469Z-43ff1122"
    for values in ([f"102:{seed}"], [f"101:{seed}", f"101:{seed}"], ["101:../../other"]):
        try:
            batch_cli._seed_capture_ids(values, {101})
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe explicit seed accepted: {values}")


def test_corrupt_explicit_seed_fails_before_any_acquisition(monkeypatch, tmp_path):
    _install_fake_batch(monkeypatch, tmp_path, ["complete"])
    seed_id = "20261012T131518.543469Z-43ff1122"
    seed_dir = tmp_path / "captures" / "2026-27" / "101" / seed_id
    seed_dir.mkdir(parents=True)
    monkeypatch.setattr(batch_cli, "inspect_team_capture", lambda *_args, **_kwargs: SimpleNamespace(
        reusable_as_seed=False, seed=None, reasons=("SHA-256 incorrecto",),
    ))
    try:
        batch_cli.main([
            "--groups", "I", "--team-id", "101", "--seed-capture", f"101:{seed_id}",
            "--output-root", str(tmp_path / "captures"), "--pause-seconds", "0",
        ])
    except ValueError as exc:
        assert "SHA-256 incorrecto" in str(exc)
    else:
        raise AssertionError("Corrupt explicit seed did not stop preflight")


def test_invalid_content_is_not_misreported_as_access_denial():
    assert batch_cli._access_failure_kind(AccessStatus.INVALID_CONTENT, 200) == "invalid_content"
    assert batch_cli._access_failure_kind(AccessStatus.HTTP_ERROR, 403) == "http_denial"
    assert batch_cli._access_failure_kind(AccessStatus.CHALLENGE_REQUIRED, 200) == "challenge_required"
