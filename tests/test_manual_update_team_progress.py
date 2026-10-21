"""A running team batch reports evidence without promoting unverified files."""

import json
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from football_data_hub_api.manual_updates import ManualUpdateManager, _team_batch_progress


def test_team_batch_progress_uses_only_current_run_evidence(tmp_path):
    root = tmp_path / "teams"
    old = root / "2026-27" / "10" / "old" / "validation" / "results.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"valid": true}')
    started = time.time_ns()
    good = root / "2026-27" / "11" / "new" / "validation" / "results.json"
    good.parent.mkdir(parents=True)
    good.write_text('{"valid": true}')
    bad = root / "2026-27" / "12" / "new" / "validation" / "results.json"
    bad.parent.mkdir(parents=True)
    bad.write_text('{"valid": false}')
    failure = root / "2026-27" / "12" / "diagnostics" / "attempt" / "metadata" / "evidence.json"
    failure.parent.mkdir(parents=True)
    failure.write_text(json.dumps({"status": "access_denied"}))
    current = root / "2026-27" / "13" / "diagnostics" / "attempt" / "metadata" / "evidence.json"
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({"status": "acquiring"}))

    result = _team_batch_progress(
        root, {10, 11, 12, 13}, started_ns=started,
        log_tail="FDH_TEAM_PREFLIGHT 3/4 12\n",
    )
    assert result == {
        "total": 4, "preflight_checked": 3, "captured": 1,
        "failed": 1, "current_team_id": 13,
    }


def test_subprocess_progress_callback_does_not_skip_exit_validation(tmp_path):
    owner = SimpleNamespace(
        project_root=tmp_path, _env=lambda: os.environ.copy(),
        _mutex=threading.Lock(), _active_processes=set(),
    )
    ticks: list[int] = []
    output = ManualUpdateManager._command(
        owner, [sys.executable, "-c", "print('done')"], tmp_path / "worker.log",
        timeout=10, on_tick=lambda: ticks.append(1),
    )
    assert ticks and "done" in output
    assert not owner._active_processes


def test_progress_persistence_failure_does_not_orphan_acquisition(tmp_path):
    owner = SimpleNamespace(
        project_root=tmp_path, _env=lambda: os.environ.copy(),
        _mutex=threading.Lock(), _active_processes=set(),
    )
    child_pids: list[int] = []

    def cannot_persist() -> None:
        child_pids.append(next(iter(owner._active_processes)).pid)
        raise OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        ManualUpdateManager._command(
            owner, [sys.executable, "-c", "import time; time.sleep(60)"],
            tmp_path / "worker.log", timeout=12, on_tick=cannot_persist,
        )
    assert child_pids and not owner._active_processes
    with pytest.raises(ProcessLookupError):
        os.kill(child_pids[0], 0)
