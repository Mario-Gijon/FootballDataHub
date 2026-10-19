from __future__ import annotations

from scripts.build_bdfutbol_match_review_html import render_review_html


def test_review_html_is_readable_read_only_and_escapes_source_text():
    html = render_review_html([
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
            "warnings": ["advertencia <no verificada>"],
            "missing_fields": [],
            "source_html_sha256": "a" * 64,
            "details_sha256": "b" * 64,
            "draft_sha256": "c" * 64,
            "draft_path": "matches/details/review/draft.json",
        }
    ])

    assert "1 borradores con hashes verificados" in html
    assert "solo lectura" in html
    assert "Lesión" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "APPROVE-" not in html
    assert "PUBLISHED" not in html
