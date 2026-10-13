"""Exit-code and completion-manifest contract for the resumable team batch CLI."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from football_data_hub.providers.bdfutbol.teams import batch_cli


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
