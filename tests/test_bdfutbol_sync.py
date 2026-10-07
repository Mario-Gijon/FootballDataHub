from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.bdfutbol.acquisition import (
    LatestValidSnapshotError,
    resolve_latest_valid_snapshot,
)
from football_data_hub.bdfutbol.cli import _assessment_diagnostic
from scripts import parse_bdfutbol_competition as parse_cli
from scripts import sync_bdfutbol_competition as sync_cli


def test_resolve_latest_valid_snapshot(tmp_path: Path) -> None:
    snapshot_dir = (
        tmp_path
        / "data/raw/bdfutbol/competition_2026-27_1rf_group2/run_001/attempt_01"
    )
    snapshot_dir.mkdir(parents=True)
    page = snapshot_dir / "page.html"
    page.write_text("<html>ok</html>", encoding="utf-8")
    resource_dir = snapshot_dir.parents[1]
    resource_dir.joinpath("latest_valid.json").write_text(
        json.dumps(
            {
                "status": "VALID",
                "snapshot_directory": snapshot_dir.relative_to(tmp_path).as_posix(),
                "page_html": page.relative_to(tmp_path).as_posix(),
            }
        ),
        encoding="utf-8",
    )

    assert (
        resolve_latest_valid_snapshot(
            tmp_path,
            "competition_2026-27_1rf_group2",
        )
        == page
    )


def test_resolve_latest_valid_snapshot_missing_pointer_is_clear(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        LatestValidSnapshotError,
        match="No existe latest_valid.json",
    ):
        resolve_latest_valid_snapshot(
            tmp_path,
            "competition_2026-27_1rf_group2",
        )


def test_parse_cli_rejects_html_and_snapshot_name_together() -> None:
    with pytest.raises(SystemExit):
        parse_cli.parse_args(
            [
                "--html",
                "page.html",
                "--snapshot-name",
                "competition_2026-27_1rf_group2",
                "--url",
                "https://www.bdfutbol.com/es/t/t2026-271rf2.html",
            ]
        )


def test_builds_group_two_url_and_snapshot_name() -> None:
    assert sync_cli.build_url_and_snapshot_name(
        "2026-27",
        "1rf",
        2,
    ) == (
        "https://www.bdfutbol.com/es/t/t2026-271rf2.html",
        "competition_2026-27_1rf_group2",
    )


def test_invalid_content_diagnostic_reports_real_assessment_fields() -> None:
    lines = _assessment_diagnostic(
        {
            "title_looks_real": True,
            "structural_content": True,
            "expected_texts_ok": False,
            "expected_texts": {"Primera Federación": False},
        }
    )

    assert lines == (
        "title_looks_real=True structural_content=True expected_texts_ok=False",
        "missing_expected=['Primera Federación']",
    )


def test_sync_does_not_complete_when_session_is_not_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_session_attempt(
        *,
        args: argparse.Namespace,
        project_root: Path,
        url: str,
        session_dir: Path,
        session_number: int,
    ) -> tuple[str, None, None, list[dict[str, object]]]:
        calls.append(session_number)

        assert project_root == tmp_path.resolve()
        assert url == "https://www.bdfutbol.com/es/t/t2026-271rf2.html"

        return (
            sync_cli.STATUS_BLOCKED,
            None,
            None,
            [
                {
                    "phase": "preflight",
                    "status": sync_cli.STATUS_BLOCKED,
                    "challenge": True,
                }
            ],
        )

    def unexpected_parser(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "El CompetitionParser no debe ejecutarse tras una sesión fallida."
        )

    monkeypatch.setattr(
        sync_cli,
        "_session_attempt",
        fake_session_attempt,
    )
    monkeypatch.setattr(
        sync_cli,
        "parse_competition",
        unexpected_parser,
    )

    args = sync_cli.parse_args(
        [
            "--season",
            "2026-27",
            "--group",
            "2",
            "--browser-sessions",
            "1",
        ]
    )

    assert sync_cli.run_sync(
        args,
        project_root=tmp_path,
    ) == 3
    assert calls == [1]

    latest_valid = (
        tmp_path
        / "data/raw/bdfutbol/"
        "competition_2026-27_1rf_group2/"
        "latest_valid.json"
    )
    assert not latest_valid.exists()


def test_sync_uses_valid_snapshot_returned_by_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = SimpleNamespace(
        context=SimpleNamespace(
            competition_code="1rf",
            season="2026-27",
            group=2,
        ),
        standings=(object(),) * 20,
        fixtures=(
            SimpleNamespace(played=True),
            SimpleNamespace(played=False),
        ),
        warnings=(),
    )

    def fake_session_attempt(
        *,
        args: argparse.Namespace,
        project_root: Path,
        url: str,
        session_dir: Path,
        session_number: int,
    ) -> tuple[str, object, Path, list[dict[str, object]]]:
        assert project_root == tmp_path.resolve()
        assert session_number == 1
        assert url == "https://www.bdfutbol.com/es/t/t2026-271rf2.html"

        target_dir = session_dir / "target_01"
        target_dir.mkdir(parents=True)
        (target_dir / "page.html").write_text(
            "<html>validated competition</html>",
            encoding="utf-8",
        )

        return (
            sync_cli.STATUS_VALID,
            snapshot,
            target_dir,
            [
                {
                    "phase": "target",
                    "target_attempt": 1,
                    "status": sync_cli.STATUS_VALID,
                    "final_url": url,
                    "url_matches_target": True,
                    "challenge": False,
                }
            ],
        )

    monkeypatch.setattr(
        sync_cli,
        "_session_attempt",
        fake_session_attempt,
    )

    args = sync_cli.parse_args(
        [
            "--season",
            "2026-27",
            "--group",
            "2",
            "--expect-fixtures",
            "2",
            "--browser-sessions",
            "1",
        ]
    )

    assert sync_cli.run_sync(
        args,
        project_root=tmp_path,
    ) == 0

    latest_valid = (
        tmp_path
        / "data/raw/bdfutbol/"
        "competition_2026-27_1rf_group2/"
        "latest_valid.json"
    )
    pointer = json.loads(
        latest_valid.read_text(encoding="utf-8")
    )

    assert pointer["status"] == "VALID"
    assert pointer["page_html"].endswith(
        "/session_01/target_01/page.html"
    )

    output = capsys.readouterr().out
    assert "=== SYNC COMPLETADO ===" in output
    assert "Equipos:      20" in output
    assert "Partidos:     2" in output
