import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.bdfutbol import acquisition as acquisition_module
from football_data_hub.bdfutbol.acquisition import (
    AcquisitionStatus,
    AttemptRecord,
    BDFutbolAcquirer,
    _classify_page,
)
from football_data_hub.bdfutbol.validation import assess_snapshot


class FakePage:
    def __init__(self, url: str, final_url_after_goto: str) -> None:
        self.url = url
        self.final_url_after_goto = final_url_after_goto
        self.goto_calls: list[tuple[str, str, int]] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append((url, wait_until, timeout))
        self.url = self.final_url_after_goto

    def wait_for_timeout(self, timeout_ms: int) -> None:
        pass


def _assessment(*, challenge: bool = False):
    return assess_snapshot(
        title="Just a moment..." if challenge else "BDFutbol",
        body_text=(
            "Performing security verification " + ("contenido " * 40)
            if challenge
            else "Actualidad Competiciones " + ("contenido " * 40)
        ),
        link_count=120,
        table_count=3,
        image_count=25,
    )


def _run_warmup_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_url: str,
    final_url_after_goto: str,
    final_assessment,
    capture_statuses: list[AcquisitionStatus] | None = None,
) -> tuple[object, FakePage, list[int]]:
    requested_url = "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    acquirer = BDFutbolAcquirer(
        project_root=tmp_path,
        max_attempts=2,
        warmup_seconds=0,
        retry_delay_seconds=0,
        timeout_ms=12_345,
        settle_ms=27,
    )
    page = FakePage(initial_url, final_url_after_goto)
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])
    statuses = capture_statuses or [
        AcquisitionStatus.BLOCKED,
        AcquisitionStatus.INVALID_CONTENT,
    ]
    captures: list[int] = []

    class FakePlaywrightManager:
        def __enter__(self) -> SimpleNamespace:
            return SimpleNamespace(
                chromium=SimpleNamespace(
                    connect_over_cdp=lambda cdp_url: browser,
                )
            )

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        acquisition_module,
        "start_browser",
        lambda **kwargs: SimpleNamespace(
            cdp_url="http://127.0.0.1:1",
            browser_path="fake-browser",
            profile=tmp_path / "profile",
            using_xvfb=False,
        ),
    )
    monkeypatch.setattr(acquisition_module, "stop_browser", lambda runtime: None)
    monkeypatch.setattr(
        acquisition_module,
        "sync_playwright",
        lambda: FakePlaywrightManager(),
    )
    monkeypatch.setattr(
        acquisition_module,
        "assess_page",
        lambda current_page, texts=(): (
            _assessment() if current_page.url == initial_url else final_assessment
        ),
    )
    monkeypatch.setattr(acquisition_module.time, "sleep", lambda seconds: None)

    def save_page_artifacts(current_page: FakePage, output_dir: Path, assessment) -> None:
        (output_dir / "page.html").write_text(
            f"<html>{current_page.url}</html>",
            encoding="utf-8",
        )

    monkeypatch.setattr(acquirer, "_save_page_artifacts", save_page_artifacts)

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
            status=statuses[attempt_number - 1],
            directory=str(output_dir),
            requested_url=url,
            final_url=url,
            url_matches_target=True,
        )

    monkeypatch.setattr(acquirer, "_capture_attempt", capture)
    result = acquirer.acquire(
        url=requested_url,
        name="competition_2026-27_1rf_group1",
    )
    return result, page, captures


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
    initial_url = (
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=referees"
    )
    requested_url = "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    result, page, captures = _run_warmup_case(
        tmp_path,
        monkeypatch,
        initial_url=initial_url,
        final_url_after_goto=requested_url,
        final_assessment=_assessment(),
    )

    expected_snapshot = result.run_directory / "warmup_01"
    assert result.status is AcquisitionStatus.VALID
    assert result.valid_snapshot_directory == expected_snapshot
    assert expected_snapshot.name == "warmup_01"
    assert captures == [1]
    assert page.goto_calls == [(requested_url, "domcontentloaded", 12_345)]
    assert page.url == requested_url
    assert [(item.phase, item.number) for item in result.attempts] == [
        ("capture", 1),
        ("warmup", 1),
    ]
    assert result.attempts[1].final_url == requested_url
    assert result.attempts[1].url_matches_target is True

    latest_valid = (
        tmp_path
        / "data/raw/bdfutbol/competition_2026-27_1rf_group1/latest_valid.json"
    )
    pointer = json.loads(latest_valid.read_text(encoding="utf-8"))
    assert pointer["snapshot_directory"].endswith("/warmup_01")
    assert pointer["page_html"].endswith("/warmup_01/page.html")
    assert (tmp_path / pointer["page_html"]).is_file()
    saved_html = (tmp_path / pointer["page_html"]).read_text(encoding="utf-8")
    assert requested_url in saved_html


def test_find_target_page_chooses_exact_competition_page() -> None:
    home_page = SimpleNamespace(url="https://www.bdfutbol.com/")
    target_page = SimpleNamespace(
        url="https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    )

    assert BDFutbolAcquirer._find_target_page(
        [home_page, target_page],
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
    ) is target_page


def test_find_target_page_returns_none_when_only_homepage_exists() -> None:
    home_page = SimpleNamespace(url="https://www.bdfutbol.com/")

    assert (
        BDFutbolAcquirer._find_target_page(
            [home_page],
            "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
        )
        is None
    )


def test_valid_bdfutbol_content_at_wrong_final_url_is_invalid() -> None:
    assessment = assess_snapshot(
        title="Primera Federación 2026-27 - BDFutbol",
        body_text="Clasificación Jornada Resultados " + ("contenido " * 40),
        link_count=120,
        table_count=3,
        image_count=25,
    )

    status = _classify_page(
        assessment,
        requested_url="https://www.bdfutbol.com/es/t/t2026-271rf1.html",
        final_url="https://www.bdfutbol.com/",
    )

    assert status is AcquisitionStatus.INVALID_CONTENT


def test_capture_with_valid_homepage_redirect_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_url = "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    home_url = "https://www.bdfutbol.com/"

    class FakePage:
        url = requested_url

        def set_default_navigation_timeout(self, timeout_ms: int) -> None:
            pass

        def goto(self, url: str, *, wait_until: str, timeout: int) -> SimpleNamespace:
            self.url = home_url
            return SimpleNamespace(status=200)

        def wait_for_timeout(self, timeout_ms: int) -> None:
            pass

    page = FakePage()
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])

    class FakePlaywrightManager:
        def __enter__(self) -> SimpleNamespace:
            return SimpleNamespace(
                chromium=SimpleNamespace(
                    connect_over_cdp=lambda cdp_url: browser,
                )
            )

        def __exit__(self, *args: object) -> None:
            return None

    acquirer = BDFutbolAcquirer(project_root=tmp_path, settle_ms=0)
    valid_assessment = assess_snapshot(
        title="Primera Federación 2026-27 - BDFutbol",
        body_text="Clasificación Jornada Resultados " + ("contenido " * 40),
        link_count=120,
        table_count=3,
        image_count=25,
    )
    monkeypatch.setattr(
        acquisition_module,
        "start_browser",
        lambda **kwargs: SimpleNamespace(
            cdp_url="http://127.0.0.1:1",
            browser_path="fake-browser",
            profile=tmp_path / "profile",
            using_xvfb=False,
        ),
    )
    monkeypatch.setattr(acquisition_module, "stop_browser", lambda runtime: None)
    monkeypatch.setattr(
        acquisition_module,
        "sync_playwright",
        lambda: FakePlaywrightManager(),
    )
    monkeypatch.setattr(
        acquisition_module,
        "assess_page",
        lambda current_page, texts: valid_assessment,
    )
    monkeypatch.setattr(acquirer, "_save_page_artifacts", lambda *args: None)

    record = acquirer._capture_attempt(
        url=requested_url,
        output_dir=tmp_path / "attempt_01",
        attempt_number=1,
        expected_texts=(),
    )

    assert record.assessment is not None
    assert record.assessment["accessible"] is True
    assert record.status is AcquisitionStatus.INVALID_CONTENT
    assert record.requested_url == requested_url
    assert record.final_url == home_url
    assert record.url_matches_target is False


def test_homepage_warmup_cannot_become_latest_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://www.bdfutbol.com/"
    home_assessment = _assessment()
    assert home_assessment.accessible is True
    result, page, captures = _run_warmup_case(
        tmp_path,
        monkeypatch,
        initial_url=home_url,
        final_url_after_goto=home_url,
        final_assessment=home_assessment,
    )

    warmup = result.attempts[1]
    assert warmup.status is AcquisitionStatus.INVALID_CONTENT
    assert warmup.requested_url == "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    assert warmup.final_url == home_url
    assert warmup.url_matches_target is False
    assert page.goto_calls == [
        (
            "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
            "domcontentloaded",
            12_345,
        )
    ]
    assert captures == [1, 2]
    assert result.valid_snapshot_directory is None
    assert not (
        tmp_path
        / "data/raw/bdfutbol/competition_2026-27_1rf_group1/latest_valid.json"
    ).exists()


def test_warmup_target_navigation_that_shows_challenge_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_url = (
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=referees"
    )
    requested_url = "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    result, page, captures = _run_warmup_case(
        tmp_path,
        monkeypatch,
        initial_url=initial_url,
        final_url_after_goto=requested_url,
        final_assessment=_assessment(challenge=True),
        capture_statuses=[
            AcquisitionStatus.BLOCKED,
            AcquisitionStatus.BLOCKED,
        ],
    )

    warmup = result.attempts[1]
    assert warmup.status is AcquisitionStatus.BLOCKED
    assert warmup.url_matches_target is True
    assert result.status is AcquisitionStatus.BLOCKED
    assert captures == [1, 2]
    assert page.goto_calls == [(requested_url, "domcontentloaded", 12_345)]
    assert not (
        tmp_path
        / "data/raw/bdfutbol/competition_2026-27_1rf_group1/latest_valid.json"
    ).exists()


def test_warmup_accessible_but_wrong_final_url_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    referees_url = (
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=referees"
    )
    result, page, captures = _run_warmup_case(
        tmp_path,
        monkeypatch,
        initial_url=referees_url,
        final_url_after_goto=referees_url,
        final_assessment=_assessment(),
    )

    warmup = result.attempts[1]
    assert warmup.status is AcquisitionStatus.INVALID_CONTENT
    assert warmup.url_matches_target is False
    assert result.status is AcquisitionStatus.INVALID_CONTENT
    assert captures == [1, 2]
    assert page.goto_calls[0][0] == (
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    )
    assert not (
        tmp_path
        / "data/raw/bdfutbol/competition_2026-27_1rf_group1/latest_valid.json"
    ).exists()
