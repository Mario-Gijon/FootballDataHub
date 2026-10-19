from __future__ import annotations

from types import SimpleNamespace

from scripts import build_bdfutbol_match_review_html as review_html


def test_review_html_is_grouped_read_only_and_escapes_source_text():
    rows = [
        {
            "campaign_id": "match-detail-campaign-v2-test",
            "internal_id": "pf-2026-27-group-i-bdfutbol-269409",
            "source_match_id": "269409",
            "group": "I",
            "matchday": 2,
            "source_match_date": "2026-08-30",
            "home_team_name": "Equipo <script>alert(1)</script>",
            "away_team_name": "Visitante",
            "reference_result": {"home_goals": 1, "away_goals": 0},
            "observed_result": {"home_goals": 1, "away_goals": 0},
            "lineups": {"home": {"starters": [], "substitutes": []}, "away": {}},
            "coaches": {},
            "events": [{"event_kind": "other", "source_description": "Lesión", "minute": "9"}],
            "warnings": [review_html._ADMINISTRATIVE_WARNING],
            "missing_fields": [],
            "source_context": {
                "stadium_name": "Estadio seguro",
                "stadium_url": "https://www.bdfutbol.com/es/s/149.html",
                "referee_name": "Árbitro",
                "referee_url": "https://www.bdfutbol.com/es/r/r602714.html",
            },
            "source_html_sha256": "a" * 64,
            "details_sha256": "b" * 64,
            "draft_sha256": "c" * 64,
            "draft_path": "matches/details/review/draft.json",
        },
        {
            "campaign_id": "match-detail-campaign-v2-test",
            "internal_id": "pf-2026-27-group-i-bdfutbol-269410",
            "source_match_id": "269410",
            "group": "I",
            "matchday": 2,
            "source_match_date": "2026-08-30",
            "home_team_name": "Aviso",
            "away_team_name": "Visitante",
            "reference_result": {"home_goals": 1, "away_goals": 0},
            "observed_result": {"home_goals": 1, "away_goals": 0},
            "lineups": {"home": {}, "away": {}},
            "coaches": {},
            "events": [],
            "warnings": ["direct_red_card_absence_not_asserted_second_yellow_present"],
            "missing_fields": ["kickoff_time_local"],
            "source_context": {"stadium_name": "Campo", "referee_name": "Árbitro"},
        },
    ]
    html = review_html.render_review_html(rows)

    assert "2 borradores con fuente y generación verificadas" in html
    assert "1</b> sin discrepancias deportivas específicas" in html
    assert "1</b> con advertencias que requieren atención" in html
    assert 'data-category="clean"' in html
    assert 'data-category="flagged"' in html
    assert "L-001" in html and "A-001" in html
    assert "Bloques de hasta 15" in html
    assert "Vista solo de lectura" in html
    assert "Lesión" in html
    assert "Estadio seguro" in html
    assert "https://www.bdfutbol.com/es/s/149.html" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "APPROVE-" not in html
    assert "PUBLISHED" not in html
    assert "confirmar aprobación" not in html.casefold()


def test_source_context_comes_from_parser_verified_html(monkeypatch, tmp_path):
    parsed = SimpleNamespace(
        source=SimpleNamespace(source_html_sha256="a" * 64, parser_version="test-parser"),
        stadium_name=SimpleNamespace(value="Campo", state="observed"),
        stadium_id=SimpleNamespace(value="39b", state="observed"),
        stadium_url=SimpleNamespace(value="https://www.bdfutbol.com/es/s/39b.html", state="observed"),
        referee_name=SimpleNamespace(value="Árbitro", state="observed"),
        referee_id=SimpleNamespace(value=123, state="observed"),
        referee_url=SimpleNamespace(value="https://www.bdfutbol.com/es/r/r123.html", state="observed"),
        kickoff_time_local=SimpleNamespace(value=None, state="not_observed", raw_value=None),
    )
    calls = []
    monkeypatch.setattr(review_html, "load_verified_match_generation", lambda *_args, **_kwargs: "verified-generation")
    monkeypatch.setattr(review_html, "build_match_detail_inventory", lambda _generation: {"matches": [{"internal_id": "match-1"}]})
    monkeypatch.setattr(review_html, "parse_campaign_saved_artifact", lambda path, **kwargs: calls.append((path, kwargs)) or parsed)

    class Ledger:
        def preflight(self, _campaign_id):
            return {"source_generation_id": "generation-1"}

    artifact_dir = tmp_path / "artifacts" / "artifact-1"
    row = {
        "campaign_id": "match-detail-campaign-v2-test",
        "internal_id": "match-1",
        "artifact_manifest_path": str(artifact_dir / "manifest.json"),
        "source_html_sha256": "a" * 64,
    }
    review_html._verify_source_context([row], Ledger(), tmp_path)

    assert row["source_context"]["stadium_name"] == "Campo"
    assert row["source_context"]["stadium_id"] == "39b"
    assert row["source_context"]["referee_name"] == "Árbitro"
    assert row["source_context"]["kickoff_time_local"] is None
    assert calls[0][0] == artifact_dir
    assert calls[0][1]["expected_match"] == {"internal_id": "match-1"}
