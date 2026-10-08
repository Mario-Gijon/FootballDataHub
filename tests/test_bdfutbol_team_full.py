from __future__ import annotations

import json
from pathlib import Path

from scripts import sync_bdfutbol_team_full as full


def test_resource_specs_cover_full_static_inventory() -> None:
    specs = full.build_resource_specs("2026-27", 49, "1rf")
    names = [spec.name for spec in specs]

    assert names == [
        "season_alignment",
        "season_roster",
        "season_stats",
        "season_tracking",
        "season_transfers",
        "season_matches",
        "club_profile",
        "club_stats",
        "club_matches",
        "club_coaches_all",
        "club_goals_discovery",
        "club_referees_discovery",
        "club_competition_players",
        "club_competition_coaches",
    ]


def test_resource_urls_for_real_jaen() -> None:
    specs = {
        spec.name: spec
        for spec in full.build_resource_specs(
            "2026-27",
            49,
            "1rf",
        )
    }

    assert specs["season_alignment"].url == (
        "https://www.bdfutbol.com/es/t/t2026-2749.html"
    )
    assert specs["season_roster"].url.endswith(
        "t2026-2749.html?t=plantilla"
    )
    assert specs["season_stats"].url.endswith(
        "t2026-2749.html?t=lista"
    )
    assert specs["season_tracking"].url.endswith(
        "t2026-2749.html?t=seg"
    )
    assert specs["season_transfers"].url.endswith(
        "t2026-2749.html?t=altas"
    )
    assert specs["season_matches"].url.endswith(
        "t2026-2749.html?tab=partits"
    )
    assert specs["club_profile"].url == (
        "https://www.bdfutbol.com/es/e/e49.html"
    )
    assert specs["club_stats"].url.endswith(
        "/es/e/e49.html?p=stats"
    )

    # This MUST be the unfiltered page. The previous audit accidentally
    # captured only lost matches versus one rival.
    assert specs["club_matches"].url == (
        "https://www.bdfutbol.com/es/p/e49.html"
    )

    assert specs["club_coaches_all"].url == (
        "https://www.bdfutbol.com/es/e/eentr49.html"
    )
    assert specs["club_goals_discovery"].url == (
        "https://www.bdfutbol.com/es/e/egols49.html"
    )
    assert specs["club_referees_discovery"].url == (
        "https://www.bdfutbol.com/es/p/er49.html"
    )
    assert specs["club_competition_players"].url.endswith(
        "/es/e/e1rf49.html"
    )
    assert specs["club_competition_coaches"].url.endswith(
        "/es/e/eentr1rf49.html"
    )


def test_tracking_inventory_includes_all_four_real_modes() -> None:
    assert full.TRACKING_MODE_LABELS == (
        "partidos",
        "tarjetas",
        "goles",
        "todo",
    )


def test_semantic_markers_require_all_required_and_one_any() -> None:
    spec = full.ResourceSpec(
        name="x",
        url="https://example.invalid",
        required_markers=("Altas", "Bajas"),
        any_markers=("Equipo origen", "Equipo destino"),
    )

    ok, missing, any_ok = full._markers_ok(
        "Altas ... Bajas ... Equipo origen",
        spec,
    )
    assert ok is True
    assert missing == []
    assert any_ok is True

    ok, missing, any_ok = full._markers_ok(
        "Altas ... Equipo origen",
        spec,
    )
    assert ok is False
    assert missing == ["Bajas"]
    assert any_ok is True


def test_optional_discovery_resources_do_not_become_required() -> None:
    specs = full.build_resource_specs("2026-27", 49, "1rf")
    optional = {
        spec.name
        for spec in specs
        if spec.optional
    }

    assert optional == {
        "club_coaches_all",
        "club_goals_discovery",
        "club_referees_discovery",
        "club_competition_players",
        "club_competition_coaches",
    }


def test_stadium_discovery_uses_real_link_ids_not_team_id(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "club_profile"
    snapshot.mkdir()

    (snapshot / "links.json").write_text(
        json.dumps(
            [
                {
                    "href": "https://www.bdfutbol.com/es/s/49.html",
                },
                {
                    "href": "https://www.bdfutbol.com/es/s/777.html",
                },
                {
                    "href": "https://www.bdfutbol.com/es/e/e49.html",
                },
                {
                    "href": "https://example.com/es/s/999.html",
                },
            ]
        ),
        encoding="utf-8",
    )

    specs = full._discover_stadium_specs_from_snapshot(snapshot)

    assert [(spec.name, spec.url) for spec in specs] == [
        (
            "club_stadium_49",
            "https://www.bdfutbol.com/es/s/49.html",
        ),
        (
            "club_stadium_777",
            "https://www.bdfutbol.com/es/s/777.html",
        ),
    ]
    assert all(spec.optional for spec in specs)


def test_same_team_link_extraction_accepts_independent_stadium_ids() -> None:
    class FakeLocator:
        def evaluate_all(self, script: str) -> list[str]:
            return [
                "https://www.bdfutbol.com/es/e/e49.html",
                "https://www.bdfutbol.com/es/s/777.html",
                "https://www.bdfutbol.com/es/e/e123.html",
                "https://example.com/es/s/777.html",
            ]

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            assert selector == "a[href]"
            return FakeLocator()

    links = full._extract_same_team_links(
        FakePage(),
        team_id=49,
        season="2026-27",
    )

    assert "https://www.bdfutbol.com/es/e/e49.html" in links
    assert "https://www.bdfutbol.com/es/s/777.html" in links
    assert "https://www.bdfutbol.com/es/e/e123.html" not in links
    assert "https://example.com/es/s/777.html" not in links


def test_invalid_configuration_is_rejected() -> None:
    try:
        full.build_resource_specs("bad-season", 49, "1rf")
    except ValueError:
        pass
    else:
        raise AssertionError("bad season must fail")

    try:
        full.build_resource_specs("2026-27", 0, "1rf")
    except ValueError:
        pass
    else:
        raise AssertionError("team_id=0 must fail")
