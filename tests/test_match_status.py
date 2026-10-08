from __future__ import annotations

import pytest

from football_data_hub.parsers.match_status import assess_match_status, normalized_match_state


CAPTURED = "2026-10-08T12:00:00+00:00"


@pytest.mark.parametrize(
    ("match", "expected"),
    [
        (
            {
                "result_status": "played", "result_raw": "2 1", "home_goals": 2,
                "away_goals": 1, "match_id": "100", "date": "2026-10-01",
            },
            "played",
        ),
        (
            {
                "result_status": "available", "fixture_status": "played",
                "result_raw": "2 1", "home_goals": 2, "away_goals": 1,
                "match_id": "100", "date": "2026-10-01",
            },
            "played",
        ),
        (
            {
                "result_status": "played", "score_raw": "2 1", "home_goals": 2,
                "away_goals": 1, "match_id": "100", "date": "2026-10-01",
            },
            "played",
        ),
        (
            {"result_status": "scheduled", "result_raw": "—", "date": "2026-10-20"},
            "scheduled",
        ),
        (
            {"result_status": "not_available", "result_raw": "—", "date": "2026-10-01"},
            "unresolved",
        ),
        (
            {"result_raw": "—", "date": "2026-10-20"},
            "scheduled",
        ),
        (
            {"result_raw": "—", "date": "2026-10-01"},
            "unresolved",
        ),
    ],
)
def test_canonical_match_status_uses_versioned_tokens_and_temporal_evidence(
    match: dict[str, object], expected: str,
) -> None:
    assert normalized_match_state(match, captured_at_utc=CAPTURED) == expected


@pytest.mark.parametrize(
    "match",
    [
        {
            "result_status": "played", "result_raw": "2 1", "home_goals": 2,
            "away_goals": 1, "match_id": "100", "date": "2026-10-20",
        },
        {
            "result_status": "available", "result_raw": "2 1", "home_goals": 2,
            "away_goals": 1, "match_id": None, "date": "2026-10-01",
        },
        {
            "result_status": "available", "result_raw": "2 1", "home_goals": 1,
            "away_goals": 1, "match_id": "100", "date": "2026-10-01",
        },
        {
            "result_status": "scheduled", "result_raw": "2 1", "home_goals": 2,
            "away_goals": 1, "match_id": "100", "date": "2026-10-01",
        },
        {
            "result_status": "available", "result_raw": "2 1", "home_goals": 2,
            "away_goals": 1, "fixture_status": "scheduled", "match_id": "100",
            "date": "2026-10-01",
        },
        {
            "result_status": "mystery", "result_raw": "—", "date": "2026-10-20",
        },
    ],
)
def test_incomplete_or_conflicting_match_evidence_is_inconsistent(
    match: dict[str, object],
) -> None:
    assessment = assess_match_status(match, captured_at_utc=CAPTURED)
    assert assessment["state"] == "inconsistent"
    assert assessment["issues"]


def test_classifier_is_pure_and_emits_json_serializable_evidence() -> None:
    source = {
        "result_status": "available", "result_raw": "0 0", "home_goals": 0,
        "away_goals": 0, "match_id": "100", "date": "2026-10-01",
    }
    before = dict(source)
    assessment = assess_match_status(source, captured_at_utc=CAPTURED)

    assert source == before
    assert assessment["state"] == "played"
    assert assessment["evidence"]["score_pair"] == [0, 0]
