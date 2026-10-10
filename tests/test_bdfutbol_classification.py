from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.classification.acquisition import (
    AcquisitionBundle,
    _redact_browser_log,
)
from football_data_hub.providers.bdfutbol.classification.export import (
    create_run_directory,
    export_acquisition,
)
from football_data_hub.providers.bdfutbol.classification.models import (
    ClassificationContext,
    ClassificationRequest,
)
from football_data_hub.providers.bdfutbol.classification.navigation import apply_filters
from football_data_hub.providers.bdfutbol.classification.parser import (
    ClassificationParseError,
    parse_classification_page,
    validate_page_structure,
)
from football_data_hub.providers.bdfutbol.classification.validation import (
    validate_classification,
)
from football_data_hub.providers.bdfutbol.access import assess_bdfutbol_access, AccessStatus

FIXTURE = Path(__file__).parent / "fixtures" / "group2_classification_2026_27.html"
URL = "https://www.bdfutbol.com/es/t/t2026-271rf2.html"


@pytest.fixture(scope="module")
def source_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(source_html):
    return parse_classification_page(source_html, base_url=URL)


def test_recognizes_the_classification_table_and_all_20_teams(source_html, parsed):
    assert validate_page_structure(source_html) == ()
    assert len(parsed.standings) == 20
    assert len({row.team_id for row in parsed.standings}) == 20
    assert parsed.standings[0].team_id == 39
    assert parsed.standings[0].team_name == "Zaragoza"


def test_group2_access_marker_uses_hyphenated_season():
    result = assess_bdfutbol_access(
        requested_url=URL,
        final_url=URL,
        http_status=200,
        page_title="Clasificación 1ª RFEF Grupo II 2026-27 | BDFutbol",
        body_text="Clasificación · Grupo II",
        required_markers=("Clasificación", "Grupo II"),
        required_title_markers=("Grupo II", "2026-27"),
        required_selectors=("table#classific",),
        present_selectors=("table#classific",),
    )
    assert result.status is AccessStatus.VALID


def test_maps_header_semantics_and_numeric_types(parsed):
    jaen = next(row for row in parsed.standings if row.team_id == 49)
    assert (jaen.position, jaen.points, jaen.matches_played) == (5, 11, 6)
    assert (jaen.wins, jaen.draws, jaen.losses) == (3, 2, 1)
    assert (jaen.goals_for, jaen.goals_against) == (8, 5)
    assert (jaen.yellow_cards, jaen.red_cards) == (13, 2)
    numeric_fields = (
        "team_id", "position", "points", "matches_played", "wins", "draws", "losses",
        "goals_for", "goals_against", "yellow_cards", "red_cards",
    )
    for row in parsed.standings:
        for field in numeric_fields:
            value = getattr(row, field)
            assert value is None or type(value) is int


def test_extracts_stable_team_id_urls_crest_and_visual_semantics(parsed):
    zaragoza = parsed.standings[0]
    assert zaragoza.team_id == 39
    assert zaragoza.team_url == "https://www.bdfutbol.com/es/t/t2026-2739.html"
    assert zaragoza.crest_url == "https://www.bdfutbol.com/i/eg/39.png"
    assert zaragoza.position_change == "up"
    assert zaragoza.zone_code == "prom_puja1"
    assert zaragoza.sports_zone == "direct_promotion"


def test_preserves_missing_values_as_null_without_inventing_zero(source_html):
    changed, count = re.subn(
        r"(onclick=\"datp\('Jaén',4,event\)\">)11(</a>)",
        r"\1—\2",
        source_html,
        count=1,
    )
    assert count == 1
    parsed_missing = parse_classification_page(changed, base_url=URL)
    jaen = next(row for row in parsed_missing.standings if row.team_id == 49)
    assert jaen.points is None
    assert jaen.raw_values["points"] == "—"


def test_rejects_malformed_or_incomplete_tables(source_html):
    malformed = source_html.replace('id="classific"', 'id="other-table"', 1)
    assert "No se encontró table#classific" in validate_page_structure(malformed)
    with pytest.raises(ClassificationParseError, match="No se encontró table#classific"):
        parse_classification_page(malformed, base_url=URL)

    missing_team, count = re.subn(
        r'<tr data-ideq="488">.*?</tr>', "", source_html, count=1
    )
    assert count == 1
    assert any("19 equipos" in issue for issue in validate_page_structure(missing_team))
    with pytest.raises(ClassificationParseError, match="19 equipos"):
        parse_classification_page(missing_team, base_url=URL)

    wrong_header = source_html.replace('title="Puntos"', 'title="Partidos"', 1)
    assert any("Encabezado inesperado" in issue for issue in validate_page_structure(wrong_header))
    with pytest.raises(ClassificationParseError, match="Encabezado inesperado"):
        parse_classification_page(wrong_header, base_url=URL)

    duplicate_id = source_html.replace('data-ideq="94"', 'data-ideq="39"', 1)
    with pytest.raises(ClassificationParseError, match="team_id duplicado"):
        parse_classification_page(duplicate_id, base_url=URL)


def test_progress_series_are_numeric_and_keep_source_gaps(parsed):
    assert parsed.played_matchdays == 6
    assert len(parsed.progress) == 120
    jaen = [record for record in parsed.progress if record.team_id == 49]
    assert [record.position for record in jaen] == [1, 3, 4, 2, 3, 5]
    assert [record.points for record in jaen] == [3, 4, 7, 10, 10, 11]
    assert [record.goals_for for record in jaen] == [3, 5, 6, 8, 8, 8]
    assert [record.goals_against for record in jaen] == [0, 2, 2, 3, 5, 5]
    for record in parsed.progress:
        for field in ("position", "points", "goals_for", "goals_against"):
            value = getattr(record, field)
            assert value is None or type(value) is int
    missing_j6 = {
        (record.team_id, field)
        for record in parsed.progress
        if record.matchday == 6
        for field in ("goals_for", "goals_against")
        if getattr(record, field) is None
    }
    assert missing_j6 == {(40, "goals_for"), (40, "goals_against"), (176, "goals_for"), (176, "goals_against")}


def test_sporting_coherence_and_points_exceptions_are_not_repaired(parsed):
    report = validate_classification(
        parsed.standings, parsed.progress, played_matchdays=parsed.played_matchdays
    )
    assert report["valid"]
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["matches_played_equation"]["status"] == "pass"
    assert checks["ordinary_points_formula"]["status"] == "pass"
    assert checks["progress_values_present"]["status"] == "warning"

    original = parsed.standings[0]
    changed = (replace(original, points=(original.points or 0) + 1), *parsed.standings[1:])
    exception_report = validate_classification(
        changed, parsed.progress, played_matchdays=parsed.played_matchdays
    )
    point_check = next(
        item for item in exception_report["checks"] if item["name"] == "ordinary_points_formula"
    )
    assert point_check["status"] == "exception"
    assert point_check["auto_corrected"] is False
    assert changed[0].points == original.points + 1

    broken_row = replace(original, matches_played=(original.matches_played or 0) + 1)
    broken_report = validate_classification(
        (broken_row, *parsed.standings[1:]), parsed.progress,
        played_matchdays=parsed.played_matchdays,
    )
    match_check = next(
        item for item in broken_report["checks"] if item["name"] == "matches_played_equation"
    )
    assert match_check["status"] == "fail"


def test_request_validates_and_retains_filter_context():
    request = ClassificationRequest(
        classification_type="visitor",
        matchday=6,
        include_postponed=False,
        range_type="dates",
        date_start=date(2026, 8, 29),
        date_end=date(2026, 9, 27),
    )
    assert request.classification_type == "visitor"
    assert request.matchday == 6
    assert request.include_postponed is False
    assert request.date_start.isoformat() == "2026-08-29"
    with pytest.raises(ValueError, match="ambos límites"):
        ClassificationRequest(range_type="rounds")


def test_redacts_ephemeral_cdp_websocket_path(tmp_path):
    path = tmp_path / "browser.stderr.log"
    path.write_text(
        "DevTools listening on ws://127.0.0.1:49365/devtools/browser/"
        "54c2f854-e9b9-43e8-bda4-37b3634b14b0\n",
        encoding="utf-8",
    )
    _redact_browser_log(path)
    text = path.read_text(encoding="utf-8")
    assert "54c2f854-e9b9-43e8-bda4-37b3634b14b0" not in text
    assert "<port>" in text and "[redacted]" in text


class _FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def count(self):
        return 1 if self.selector in self.page.values else 0

    def evaluate_all(self, _script):
        return self.page.options[self.selector.removesuffix(" option")]

    def select_option(self, value):
        self.page.values[self.selector] = value

    def input_value(self):
        return self.page.values[self.selector]

    def fill(self, value):
        self.page.values[self.selector] = value


class _FakeFilterPage:
    def __init__(self):
        jornada = {
            str(number): f"Jornada {number} ({date(2026, 8, 30).isoformat()})"
            for number in range(1, 39)
        }
        jornada.update({
            "1": "Jornada 1 (30/08/2026)",
            "2": "Jornada 2 (05/09/2026)",
            "3": "Jornada 3 (12/09/2026)",
            "4": "Jornada 4 (20/09/2026)",
            "5": "Jornada 5 (27/09/2026)",
            "6": "Jornada 6 (04/10/2026)",
        })
        self.options = {
            "#classitip": {"1": "Local", "2": "Visitante", "3": "General"},
            "#jornada": jornada,
            "#postposat": {"1": "Incluidos", "2": "No incluidos"},
            "#filtre_dates": {"1": "Todas", "2": "Filtrar fechas", "3": "Filtrar jornadas"},
        }
        self.values = {
            "#classitip": "3",
            "#jornada": "6",
            "#postposat": "1",
            "#filtre_dates": "1",
            "#date1": "29/08/2026",
            "#date2": "23/05/2027",
            "#jorn1": "1",
            "#jorn2": "38",
        }
        self.recalculations = 0
        self.waits = []

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def evaluate(self, _script):
        self.recalculations += 1

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


def test_filter_navigation_maps_local_visitor_and_postponed_values():
    page = _FakeFilterPage()
    context = apply_filters(
        page,
        ClassificationRequest(
            classification_type="visitor", matchday=6, include_postponed=False
        ),
    )
    assert page.values["#classitip"] == "2"
    assert page.values["#jornada"] == "6"
    assert page.values["#postposat"] == "2"
    assert page.values["#filtre_dates"] == "1"
    assert context.classification_type == "visitor"
    assert context.matchday_date == "2026-10-04"
    assert context.postponed_policy == "exclude"
    assert page.recalculations == 0


def test_filter_navigation_applies_date_and_round_ranges():
    dates_page = _FakeFilterPage()
    dates_context = apply_filters(
        dates_page,
        ClassificationRequest(
            matchday=6,
            range_type="dates",
            date_start=date(2026, 8, 29),
            date_end=date(2026, 9, 27),
        ),
    )
    assert dates_page.values["#filtre_dates"] == "2"
    assert dates_page.values["#date1"] == "29/08/2026"
    assert dates_page.values["#date2"] == "27/09/2026"
    assert dates_page.recalculations == 1
    assert dates_context.range_start_date == "2026-08-29"
    assert dates_context.range_end_date == "2026-09-27"

    rounds_page = _FakeFilterPage()
    rounds_context = apply_filters(
        rounds_page,
        ClassificationRequest(
            range_type="rounds", round_start=2, round_end=4
        ),
    )
    assert rounds_page.values["#filtre_dates"] == "3"
    assert rounds_page.values["#jorn1"] == "2"
    assert rounds_page.values["#jorn2"] == "4"
    assert rounds_page.recalculations == 1
    assert rounds_context.matchday == 6
    assert rounds_context.range_start_round == 2
    assert rounds_context.range_end_round == 4


def test_exports_snapshot_metadata_standings_progress_and_validation(tmp_path, source_html, parsed):
    context = ClassificationContext(
        classification_type="local",
        matchday=6,
        matchday_date="2026-10-04",
        postponed_policy="exclude",
        range_type="rounds",
        range_start_round=2,
        range_end_round=4,
    )
    request = ClassificationRequest(
        classification_type="local",
        matchday=6,
        include_postponed=False,
        range_type="rounds",
        round_start=2,
        round_end=4,
    )
    validation = validate_classification(
        parsed.standings, parsed.progress, played_matchdays=parsed.played_matchdays
    )
    bundle = AcquisitionBundle(
        capture_id="capture-test",
        captured_at_utc="2026-10-10T00:00:00+00:00",
        raw_html=source_html,
        page_title="Clasificación 1ª RFEF Grupo II 2026-27 | BDFutbol",
        access={"status": "VALID", "final_url": URL, "http_status": 200},
        context=context,
        parsed=parsed,
        validation=validation,
        browser_executable="/usr/bin/brave",
    )
    run_dir = create_run_directory(tmp_path / "captures", "capture-test")
    paths = export_acquisition(
        run_dir,
        bundle,
        request,
        browser="brave",
        profile_dir=Path("/tmp/profile"),
    )
    assert paths["raw_snapshot"].read_text(encoding="utf-8") == source_html
    classification = json.loads(paths["classification"].read_text(encoding="utf-8"))
    progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    validation_json = json.loads(paths["validation"].read_text(encoding="utf-8"))
    assert classification["context"]["classification_type"] == "local"
    assert classification["context"]["postponed_policy"] == "exclude"
    assert classification["context"]["range_start_round"] == 2
    assert progress["table_context_at_capture"] == classification["context"]
    assert progress["series_context"]["source_independent_of_standings_filters"] is True
    assert metadata["season"] == "2026-27"
    assert metadata["group"] == "II"
    assert metadata["requested_filters"]["round_end"] == 4
    assert validation_json["valid"] is True

    with pytest.raises(FileExistsError):
        export_acquisition(
            run_dir,
            bundle,
            request,
            browser="brave",
            profile_dir=Path("/tmp/profile"),
        )
