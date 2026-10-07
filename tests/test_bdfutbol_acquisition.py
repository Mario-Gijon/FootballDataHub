import json
from pathlib import Path

import pytest

from football_data_hub.bdfutbol.acquisition import (
    AcquisitionStatus,
    AttemptRecord,
    BDFutbolAcquirer,
)


def test_safe_name_normalizes_path_characters() -> None:
    assert BDFutbolAcquirer._safe_name("group 2 / competition") == (
        "group_2_competition"
    )


def test_safe_name_rejects_empty_value() -> None:
    with pytest.raises(ValueError):
        BDFutbolAcquirer._safe_name("../../")


def test_constructor_rejects_zero_attempts(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BDFutbolAcquirer(project_root=tmp_path, max_attempts=0)


def test_valid_warmup_completes_acquisition_without_another_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquirer = BDFutbolAcquirer(
        project_root=tmp_path,
        max_attempts=3,
        retry_delay_seconds=0,
    )
    captures: list[int] = []
    warmups: list[Path] = []

    def capture(
        *,
        url: str,
        output_dir: Path,
        attempt_number: int,
        expected_texts: tuple[str, ...],
    ) -> AttemptRecord:
        captures.append(attempt_number)
        output_dir.mkdir(parents=True)
        return AttemptRecord(
            number=attempt_number,
            phase="capture",
            status=AcquisitionStatus.BLOCKED,
            directory=str(output_dir),
        )

    def warmup(
        *,
        url: str,
        output_dir: Path,
        attempt_number: int,
        expected_texts: tuple[str, ...],
    ) -> AttemptRecord:
        warmups.append(output_dir)
        output_dir.mkdir(parents=True)
        (output_dir / "page.html").write_text("<html>valid</html>", encoding="utf-8")
        return AttemptRecord(
            number=attempt_number,
            phase="warmup",
            status=AcquisitionStatus.VALID,
            directory=str(output_dir),
        )

    monkeypatch.setattr(acquirer, "_capture_attempt", capture)
    monkeypatch.setattr(acquirer, "_warm_profile", warmup)

    result = acquirer.acquire(
        url="https://www.bdfutbol.com/es/t/t2026-271rf2.html",
        name="competition_2026-27_1rf_group2",
    )

    expected_snapshot = warmups[0]
    assert result.status is AcquisitionStatus.VALID
    assert result.valid_snapshot_directory == expected_snapshot
    assert expected_snapshot.name == "warmup_01"
    assert captures == [1]
    assert [(item.phase, item.number) for item in result.attempts] == [
        ("capture", 1),
        ("warmup", 1),
    ]

    latest_valid = (
        tmp_path
        / "data/raw/bdfutbol/competition_2026-27_1rf_group2/latest_valid.json"
    )
    pointer = json.loads(latest_valid.read_text(encoding="utf-8"))
    assert pointer["snapshot_directory"].endswith("/warmup_01")
    assert pointer["page_html"].endswith("/warmup_01/page.html")
    assert (tmp_path / pointer["page_html"]).is_file()
