"""Shared evidence-based interpretation of result and fixture statuses."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

_SCORE = re.compile(r"^(\d+)\s+(\d+)$")
_RESULT_PLAYED = {"played", "available"}
_RESULT_SCHEDULED = {"scheduled"}
_RESULT_NO_RESULT = {"not_available", "unscored"}
_RESULT_UNCLEAR = {"unknown", "unresolved", "unconfirmed"}
_FIXTURE_PLAYED = {"played"}
_FIXTURE_SCHEDULED = {"scheduled"}
_FIXTURE_UNCLEAR = {"unresolved", "unconfirmed", "unknown"}
_PLACEHOLDERS = {"", "-", "—", "–"}


def _token(value: Any) -> str:
    return str(value or "").strip().casefold()


def _date_value(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            return None


def _captured_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        captured = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if captured.tzinfo is not None:
            captured = captured.astimezone(ZoneInfo("Europe/Madrid"))
        return captured.date()
    except ValueError:
        return None


def assess_match_status(
    match: dict[str, Any], *, captured_at_utc: str | None = None
) -> dict[str, Any]:
    """Classify a match from its status tokens and result evidence.

    ``played`` requires a parseable source score, matching numeric goals, a
    match ID, and no contradictory status or future-date evidence. Explicit
    scheduled/unclear states are retained as such when no result is present.
    The returned evidence is JSON serializable and does not alter ``match``.
    """
    # Competition exports call this result_raw; club/team rows historically use
    # score_raw. Both represent the original source cell.
    result_raw_value = match.get("result_raw")
    if result_raw_value is None:
        result_raw_value = match.get("score_raw")
    result_raw = str(result_raw_value if result_raw_value is not None else "").strip()
    score_match = _SCORE.fullmatch(result_raw)
    raw_is_placeholder = result_raw in _PLACEHOLDERS
    score_pair = (
        (int(score_match.group(1)), int(score_match.group(2)))
        if score_match else None
    )

    home_raw = match.get("home_goals")
    away_raw = match.get("away_goals")
    home_valid = isinstance(home_raw, int) and not isinstance(home_raw, bool) and home_raw >= 0
    away_valid = isinstance(away_raw, int) and not isinstance(away_raw, bool) and away_raw >= 0
    goals_pair = (home_raw, away_raw) if home_valid and away_valid else None
    goals_partial = (home_raw is not None or away_raw is not None) and goals_pair is None
    match_id = match.get("match_id")
    match_id_present = match_id is not None and bool(str(match_id).strip())

    result_token = _token(match.get("result_status"))
    fixture_token = _token(match.get("fixture_status"))
    result_class = (
        "absent" if not result_token
        else "played" if result_token in _RESULT_PLAYED
        else "scheduled" if result_token in _RESULT_SCHEDULED
        else "no_result" if result_token in _RESULT_NO_RESULT
        else "unresolved" if result_token in _RESULT_UNCLEAR
        else "unknown"
    )
    fixture_class = (
        "absent" if not fixture_token
        else "played" if fixture_token in _FIXTURE_PLAYED
        else "scheduled" if fixture_token in _FIXTURE_SCHEDULED
        else "unresolved" if fixture_token in _FIXTURE_UNCLEAR
        else "unknown"
    )

    match_date = _date_value(match.get("date") or match.get("date_raw"))
    captured_value = (
        captured_at_utc or match.get("_captured_at_utc")
        or match.get("captured_at_utc")
    )
    capture_date = _captured_date(captured_value)
    future_date = bool(match_date and capture_date and match_date > capture_date)

    issues: list[str] = []
    if result_raw and not raw_is_placeholder and score_pair is None:
        issues.append("malformed_score")
    if goals_partial:
        issues.append("incomplete_numeric_goals")
    if goals_pair is not None and score_pair is None:
        issues.append("numeric_goals_without_source_score")
    if score_pair is not None and goals_pair is None:
        issues.append("source_score_without_complete_numeric_goals")
    if score_pair is not None and goals_pair is not None and score_pair != goals_pair:
        issues.append("source_score_numeric_goals_mismatch")
    if score_pair is not None and not match_id_present:
        issues.append("scored_match_missing_id")
    if result_class == "unknown" or fixture_class == "unknown":
        issues.append("unrecognized_status_token")

    positive_status = result_class == "played" or fixture_class == "played"
    no_result_status = result_class in {"scheduled", "no_result"} or fixture_class == "scheduled"
    any_result_evidence = score_pair is not None or goals_pair is not None or goals_partial
    status_conflict = (
        result_class == "played" and fixture_class in {"scheduled", "unresolved", "unknown"}
        or fixture_class == "played" and result_class in {"scheduled", "no_result", "unresolved", "unknown"}
        or result_class == "scheduled" and fixture_class == "unknown"
        or no_result_status and any_result_evidence
        or result_class == "scheduled" and fixture_class == "unresolved"
    )
    if status_conflict:
        issues.append(
            "scheduled_status_with_result_evidence"
            if no_result_status and any_result_evidence
            else "result_and_fixture_status_conflict"
        )

    complete_score_evidence = (
        score_pair is not None
        and goals_pair is not None
        and score_pair == goals_pair
        and match_id_present
    )
    if future_date and (complete_score_evidence or positive_status):
        issues.append("played_evidence_on_future_date")

    hard_issue_codes = {
        "malformed_score",
        "incomplete_numeric_goals",
        "numeric_goals_without_source_score",
        "source_score_without_complete_numeric_goals",
        "source_score_numeric_goals_mismatch",
        "scored_match_missing_id",
        "unrecognized_status_token",
        "result_and_fixture_status_conflict",
        "scheduled_status_with_result_evidence",
        "played_evidence_on_future_date",
    }
    if any(issue in hard_issue_codes for issue in issues):
        state = "inconsistent"
    elif complete_score_evidence:
        state = "played"
    elif positive_status:
        issues.append("played_status_without_complete_result_evidence")
        state = "inconsistent"
    elif any_result_evidence:
        issues.append("partial_result_evidence")
        state = "inconsistent"
    elif fixture_class == "unresolved" or result_class in {"unresolved", "unknown"}:
        state = "unresolved"
    elif future_date:
        state = "scheduled"
    elif result_class == "scheduled" or fixture_class == "scheduled":
        state = "scheduled"
    else:
        state = "unresolved"

    return {
        "state": state,
        "issues": issues,
        "evidence": {
            "result_status_raw": match.get("result_status"),
            "result_status_class": result_class,
            "fixture_status_raw": match.get("fixture_status"),
            "fixture_status_class": fixture_class,
            "result_raw": result_raw_value,
            "score_pair": list(score_pair) if score_pair is not None else None,
            "numeric_goals_pair": list(goals_pair) if goals_pair is not None else None,
            "goals_partial": goals_partial,
            "score_and_goals_match": (
                score_pair == goals_pair if score_pair is not None and goals_pair is not None else None
            ),
            "match_id_present": match_id_present,
            "date": match.get("date"),
            "captured_at_utc": captured_value,
            "date_after_capture": future_date,
        },
    }


def normalized_match_state(
    match: dict[str, Any], *, captured_at_utc: str | None = None
) -> str:
    """Return one canonical state: played, scheduled, unresolved, inconsistent."""
    return str(assess_match_status(match, captured_at_utc=captured_at_utc)["state"])
