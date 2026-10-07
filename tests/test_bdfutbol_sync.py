from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.bdfutbol.acquisition import (
    AcquisitionResult,
    AcquisitionStatus,
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
        resolve_latest_valid_snapshot(tmp_path, "competition_2026-27_1rf_group2")
        == page
    )


def test_resolve_latest_valid_snapshot_missing_pointer_is_clear(
    tmp_path: Path,
) -> None:
    with pytest.raises(LatestValidSnapshotError, match="No existe latest_valid.json"):
        resolve_latest_valid_snapshot(tmp_path, "competition_2026-27_1rf_group2")


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
    assert sync_cli.build_url_and_snapshot_name("2026-27", "1rf", 2) == (
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


def test_sync_does_not_parse_when_acquisition_is_not_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAcquirer:
        def __init__(self, **kwargs: object) -> None:
            pass

        def acquire(self, **kwargs: object) -> AcquisitionResult:
            return AcquisitionResult(
                status=AcquisitionStatus.BLOCKED,
                run_directory=tmp_path / "run",
                valid_snapshot_directory=None,
                attempts=(),
            )

    def unexpected_parser(*args: object, **kwargs: object) -> object:
        raise AssertionError("parser must not run after failed acquisition")

    monkeypatch.setattr(sync_cli, "BDFutbolAcquirer", FakeAcquirer)
    monkeypatch.setattr(sync_cli, "parse_competition", unexpected_parser)
    args = sync_cli.parse_args(["--season", "2026-27", "--group", "2"])

    assert sync_cli.run_sync(args, project_root=tmp_path) == 3


def test_sync_parses_the_snapshot_returned_by_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_dir = tmp_path / "data/raw/bdfutbol/resource/run/attempt_01"
    snapshot_dir.mkdir(parents=True)
    page = snapshot_dir / "page.html"
    page.write_text("<html>valid snapshot</html>", encoding="utf-8")
    parsed: list[tuple[str, str, int | None, int | None]] = []

    class FakeAcquirer:
        def __init__(self, **kwargs: object) -> None:
            pass

        def acquire(self, **kwargs: object) -> AcquisitionResult:
            assert kwargs == {
                "url": "https://www.bdfutbol.com/es/t/t2026-271rf2.html",
                "name": "competition_2026-27_1rf_group2",
            }
            return AcquisitionResult(
                status=AcquisitionStatus.VALID,
                run_directory=snapshot_dir.parent,
                valid_snapshot_directory=snapshot_dir,
                attempts=(),
            )

    def fake_parser(
        html: str,
        url: str,
        *,
        expected_team_count: int | None = None,
        expected_fixture_count: int | None = None,
    ) -> object:
        parsed.append((html, url, expected_team_count, expected_fixture_count))
        return SimpleNamespace(
            context=SimpleNamespace(competition_code="1rf", season="2026-27", group=2),
            standings=(object(),) * 20,
            fixtures=(SimpleNamespace(played=True), SimpleNamespace(played=False)),
            warnings=(),
        )

    monkeypatch.setattr(sync_cli, "BDFutbolAcquirer", FakeAcquirer)
    monkeypatch.setattr(sync_cli, "parse_competition", fake_parser)
    args = sync_cli.parse_args(
        ["--season", "2026-27", "--group", "2", "--expect-fixtures", "2"]
    )

    assert sync_cli.run_sync(args, project_root=tmp_path) == 0
    assert parsed == [
        (
            "<html>valid snapshot</html>",
            "https://www.bdfutbol.com/es/t/t2026-271rf2.html",
            20,
            2,
        )
    ]
    output = capsys.readouterr().out
    assert "=== SYNC COMPLETADO ===" in output
    assert "Snapshot:     data/raw/bdfutbol/resource/run/attempt_01" in output
