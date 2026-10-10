from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.referees.cli import main as referees_cli_main
from football_data_hub.providers.bdfutbol.referees import acquisition as referee_acquisition
from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus
from football_data_hub.core.browser_session import BrowserInfo
from football_data_hub.providers.bdfutbol.referees.models import ParsedRefereePage
from football_data_hub.providers.bdfutbol.referees.parser import (
    RefereeParseError,
    merge_referee_pages,
    parse_referee_page,
)
from football_data_hub.providers.bdfutbol.referees.validation import (
    build_match_reference_report,
    validate_referee_data,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/bdfutbol_group2_referees_2026_27"
MATCHES = ROOT / (
    "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"
)
CAPTURES = ROOT / "data/exports/bdfutbol/group2_referees"
URLS = {
    "all": "https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=referees",
    "group1": "https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=referees&grups=1",
    "group2": "https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=referees&grups=1",
}


def _page(scope: str) -> ParsedRefereePage:
    html = (FIXTURES / f"{scope}.html").read_text(encoding="utf-8")
    return parse_referee_page(html, scope=scope, source_url=URLS[scope])


def _parsed():
    return merge_referee_pages(tuple(_page(scope) for scope in ("all", "group1", "group2")))


class _FakeDocument:
    def __init__(self, url: str, html: str) -> None:
        self.url = url
        self._html = html

    def html(self) -> str:
        return self._html


class _FakeVisit:
    def __init__(self, url: str, html: str) -> None:
        self.document = _FakeDocument(url, html)
        self.final_url = url
        self.response_status = 200

    def close(self) -> None:
        pass


class _FakeOpened:
    def __init__(self, assessment: AccessAssessment, visit: _FakeVisit | None) -> None:
        self.assessment = assessment
        self.visit = visit

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        if self.visit:
            self.visit.close()


class _FakeSession:
    info = BrowserInfo(
        "seleniumbase-pure-cdp", "Chromium", "/usr/bin/chromium",
        "test-version", "test-automation", ":99", True, True,
    )

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


def _install_fake_referee_acquisition(monkeypatch, *, deny_scope: str | None = None):
    visited: list[str] = []
    html_by_scope = {
        scope: (FIXTURES / f"{scope}.html").read_text(encoding="utf-8")
        for scope in ("all", "group1", "group2")
    }

    class FakeAccess:
        def __init__(self, _session) -> None:
            pass

        def open(self, url: str, **kwargs):
            visited.append(url)
            if "grups=1" not in url:
                scope = "all"
            elif "rf1" in url:
                scope = "group1"
            else:
                scope = "group2"
            assert kwargs["required_markers"] == ("2026-27",)
            assert kwargs["max_wait_seconds"] == 0
            title_group = "Grupo I" if scope == "group1" else "Grupo II"
            title = f"Clasificación 1ª RFEF {title_group} 2026-27 | BDFutbol"
            if scope == deny_scope:
                assessment = AccessAssessment(
                    status=AccessStatus.CHALLENGE_REQUIRED,
                    requested_url=url,
                    final_url=url,
                    http_status=403,
                    page_title="Just a moment",
                    reason="Desafío simulado en fixture de test",
                )
                return _FakeOpened(assessment, None)
            source_html = html_by_scope[scope]
            assert kwargs["document_validator"](source_html) == ()
            assessment = AccessAssessment(
                status=AccessStatus.VALID,
                requested_url=url,
                final_url=url,
                http_status=200,
                page_title=title,
            )
            return _FakeOpened(assessment, _FakeVisit(url, source_html))

    monkeypatch.setattr(referee_acquisition, "BrowserSessionManager", _FakeSession)
    monkeypatch.setattr(referee_acquisition, "BDFutbolAccess", FakeAccess)
    return visited


def test_real_table_headers_and_referee_fields_are_semantic():
    page = _page("group2")
    saiz = next(row for row in page.rows if row.referee.referee_id == "r601449")

    assert saiz.referee.display_name == "Saiz Villares"
    assert saiz.referee.profile_url == "https://www.bdfutbol.com/es/r/r601449.html"
    assert saiz.referee.photo_url == "https://www.bdfutbol.com/i/am/601449.png"
    assert saiz.referee.birth_date == date(1993, 11, 28)
    assert saiz.referee.birthplace == "Palma"
    assert saiz.referee.province == "Baleares"
    assert saiz.referee.nationality is None
    assert saiz.referee.flag_url is None
    assert saiz.statistics.season == "2026-27"
    assert saiz.statistics.group_scope == "group2"
    assert saiz.statistics.matches_officiated == 2
    assert saiz.statistics.yellow_cards == 4
    assert saiz.statistics.red_cards == 0
    assert saiz.statistics.statistics_url == (
        "https://www.bdfutbol.com/es/p/r601449.html?cat=rf1&temp=2026-27"
    )


def test_filter_options_retain_observed_values_and_navigation_targets():
    page = _page("all")
    group_options = {option.label: option for option in page.group_options}
    season_options = {option.label: option for option in page.season_options}

    assert group_options["Todos"].scope == "all"
    assert group_options["Todos"].target_url == URLS["all"]
    assert group_options["Grupo 1"].scope == "group1"
    assert group_options["Grupo 1"].target_url == URLS["group1"]
    assert group_options["Grupo 2"].scope == "group2"
    assert group_options["Grupo 2"].target_url == URLS["group2"]
    assert season_options["2026-27"].selected is True
    assert any(option.label == "1928-29" for option in page.season_options)


def test_acquisition_visits_only_the_three_scope_urls_once(monkeypatch, tmp_path):
    visited = _install_fake_referee_acquisition(monkeypatch)

    bundle = referee_acquisition.acquire_referee_pages(profile_dir=tmp_path / "profile")

    assert visited == [URLS["all"], URLS["group1"], URLS["group2"]]
    assert [page.scope for page in bundle.pages] == ["all", "group1", "group2"]
    assert all(page.http_status == 200 for page in bundle.pages)


def test_acquisition_stops_at_first_access_denial_without_retry(monkeypatch, tmp_path):
    visited = _install_fake_referee_acquisition(monkeypatch, deny_scope="group1")

    with pytest.raises(referee_acquisition.RefereeAcquisitionStopped):
        referee_acquisition.acquire_referee_pages(profile_dir=tmp_path / "profile")

    assert visited == [URLS["all"], URLS["group1"]]


def test_empty_values_remain_null_and_published_zero_remains_zero():
    page = _page("group2")
    bejar = next(row for row in page.rows if row.referee.referee_id == "r602675")
    saiz = next(row for row in page.rows if row.referee.referee_id == "r601449")

    assert bejar.referee.age_years is None
    assert bejar.referee.birth_date is None
    assert saiz.statistics.red_cards == 0


def test_published_age_is_not_recalculated_from_birth_date():
    page = _page("all")
    referee = next(row.referee for row in page.rows if row.referee.referee_id == "r601577")

    assert referee.display_name == "Monterrubio Torres"
    assert referee.age_years == 30
    assert referee.birth_date == date(1995, 10, 6)


def test_three_real_scopes_merge_by_bdfutbol_id_and_reconcile_aggregation():
    parsed = _parsed()
    result = validate_referee_data(parsed)

    assert result["valid"] is True
    assert len(parsed.referees) == len({referee.referee_id for referee in parsed.referees})
    assert len(parsed.statistics) == len({
        (item.referee_id, item.season, item.group_scope) for item in parsed.statistics
    })
    assert parsed.scope_counts == {
        "all": len([item for item in parsed.statistics if item.group_scope == "all"]),
        "group1": len([item for item in parsed.statistics if item.group_scope == "group1"]),
        "group2": len([item for item in parsed.statistics if item.group_scope == "group2"]),
    }
    for check in result["checks"]["all_equals_group_sum"].values():
        assert check["compared"] > 0
        assert check["mismatches"] == []


def test_duplicate_source_ids_are_rejected():
    html = (FIXTURES / "group2.html").read_text(encoding="utf-8")
    table_start = html.index('<table class="taula_estil taulestemp sortable autonumeric-first-col" id="tab_arb">')
    table_end = html.index("</table>", table_start) + len("</table>")
    table = html[table_start:table_end]
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", table, flags=re.DOTALL)
    duplicate_table = table.replace("</table>", rows[1] + "</table>")
    broken = html[:table_start] + duplicate_table + html[table_end:]

    with pytest.raises(RefereeParseError, match="ID duplicado"):
        parse_referee_page(broken, scope="group2", source_url=URLS["group2"])


def test_same_id_with_conflicting_identity_is_reported_without_name_merge():
    pages = [_page(scope) for scope in ("all", "group1", "group2")]
    group2 = pages[2]
    first_row = group2.rows[0]
    changed_referee = replace(first_row.referee, display_name="Nombre que no es fuente")
    changed_page = replace(
        group2,
        rows=(replace(first_row, referee=changed_referee), *group2.rows[1:]),
    )
    pages[2] = changed_page
    parsed = merge_referee_pages(tuple(pages))

    assert parsed.identity_conflicts
    assert parsed.identity_conflicts[0]["referee_id"] == first_row.referee.referee_id
    assert validate_referee_data(parsed)["valid"] is False


def test_invalid_or_wrong_season_document_is_rejected():
    with pytest.raises(RefereeParseError):
        parse_referee_page(
            "<html><body>Just a moment...</body></html>",
            scope="group2",
            source_url=URLS["group2"],
        )


def test_group2_ids_names_urls_and_statistics_match_results_capture():
    parsed = _parsed()
    matches_payload = json.loads(MATCHES.read_text(encoding="utf-8"))
    report = build_match_reference_report(
        parsed,
        matches_payload,
        reference_path=MATCHES.relative_to(ROOT).as_posix(),
        reference_sha256=hashlib.sha256(MATCHES.read_bytes()).hexdigest(),
    )

    assert report["status"] == "consistent"
    assert report["counts"]["matched_referee_ids"] == report["counts"]["unique_match_referee_ids"]
    assert report["counts"]["group2_table_referees_without_played_match"] == 0
    assert report["counts"]["played_match_referees_missing_from_group2_table"] == 0
    assert report["identity_conflicts"] == []
    assert report["statistic_differences"] == []


def test_versioned_capture_can_be_normalized_offline_and_read_back(tmp_path):
    capture_dirs = sorted(path for path in CAPTURES.iterdir() if path.is_dir() and not path.name.startswith("."))
    assert capture_dirs, "La adquisición validada de REF-01 debe existir en el repositorio"
    output_root = tmp_path / "offline-export"
    result = referees_cli_main([
        "--snapshot-dir", str(capture_dirs[-1]),
        "--matches", str(MATCHES),
        "--output-root", str(output_root),
    ])

    assert result == 0
    run_dir = next(output_root.iterdir())
    referees = json.loads((run_dir / "normalized/referees.json").read_text(encoding="utf-8"))
    stats = json.loads((run_dir / "normalized/statistics.json").read_text(encoding="utf-8"))
    options = json.loads((run_dir / "normalized/filter_options.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "validation/match_reference.json").read_text(encoding="utf-8"))

    assert referees["records"]
    assert stats["records"]
    assert {record["group_scope"] for record in stats["records"]} == {"all", "group1", "group2"}
    assert all(record["age_years"] is None or isinstance(record["age_years"], int) for record in referees["records"])
    assert {option["label"] for option in options["group_options"]} == {"Todos", "Grupo 1", "Grupo 2"}
    assert report["status"] == "consistent"
