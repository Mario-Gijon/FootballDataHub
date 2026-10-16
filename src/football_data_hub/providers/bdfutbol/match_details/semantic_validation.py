"""Pure validation rules shared by the offline match-detail parser.

The functions in this module receive normalized observations only. They do not
inspect HTML, access the network, or persist data.
"""

from __future__ import annotations

from typing import Mapping

from football_data_hub.domain.matches.semantic_detail import MatchEvent, PlayerAppearance


def goal_progression_is_consistent(
    goals: list[MatchEvent], final_home: int, final_away: int
) -> tuple[bool, str]:
    """Validate partial scores without inventing order for equal-minute goals."""

    if any(
        goal.minute_base is None
        or goal.score_after_home is None
        or goal.score_after_away is None
        for goal in goals
    ):
        return False, "a goal is missing an interpretable minute or partial score"

    groups: dict[tuple[int, int], list[MatchEvent]] = {}
    for goal in goals:
        assert goal.minute_base is not None
        minute_key = (goal.minute_base, goal.minute_added or 0)
        groups.setdefault(minute_key, []).append(goal)

    possible_scores: set[tuple[int, int]] = {(0, 0)}
    for minute_key in sorted(groups):
        minute_goals = groups[minute_key]
        initial_mask = (1 << len(minute_goals)) - 1
        memo: dict[tuple[int, int, int], frozenset[tuple[int, int]]] = {}

        def consume(
            score_home: int, score_away: int, remaining: int
        ) -> frozenset[tuple[int, int]]:
            memo_key = (score_home, score_away, remaining)
            if memo_key in memo:
                return memo[memo_key]
            if remaining == 0:
                return frozenset({(score_home, score_away)})
            reachable: set[tuple[int, int]] = set()
            for index, goal in enumerate(minute_goals):
                bit = 1 << index
                if not remaining & bit:
                    continue
                expected_after = (
                    (score_home + 1, score_away)
                    if goal.side == "home"
                    else (score_home, score_away + 1)
                )
                observed_after = (goal.score_after_home, goal.score_after_away)
                if observed_after == expected_after:
                    reachable.update(consume(*expected_after, remaining ^ bit))
            memo[memo_key] = frozenset(reachable)
            return memo[memo_key]

        group_results: set[tuple[int, int]] = set()
        for prior_score in possible_scores:
            group_results.update(consume(*prior_score, initial_mask))
        if not group_results:
            return False, f"impossible partial-score progression at minute {minute_key}"
        possible_scores = group_results

    if (final_home, final_away) not in possible_scores:
        return False, "ordered goal progression does not finish at the match result"
    return True, "goal partial scores admit a valid chronological ordering"


def roster_identity_errors(
    starters: Mapping[str, tuple[PlayerAppearance, ...] | None],
    substitutes: Mapping[str, tuple[PlayerAppearance, ...] | None],
) -> list[str]:
    """Report duplicate appearances without reconciling players by name."""

    errors: list[str] = []
    all_sides_by_player: dict[int, set[str]] = {}
    for side in ("home", "away"):
        role_ids: dict[str, set[int]] = {}
        for role, rosters in (("starters", starters), ("substitutes", substitutes)):
            ids = [item.player_id for item in (rosters[side] or ())]
            seen: set[int] = set()
            for player_id in ids:
                if player_id in seen:
                    errors.append(f"duplicate_player_id:{role}:{side}:{player_id}")
                seen.add(player_id)
                all_sides_by_player.setdefault(player_id, set()).add(side)
            role_ids[role] = seen
        for player_id in sorted(role_ids["starters"] & role_ids["substitutes"]):
            errors.append(f"player_id_in_starters_and_substitutes:{side}:{player_id}")
    for player_id, sides in sorted(all_sides_by_player.items()):
        if len(sides) > 1:
            errors.append(f"player_id_appears_for_both_teams:{player_id}")
    return errors
