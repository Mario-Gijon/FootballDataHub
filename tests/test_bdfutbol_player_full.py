from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import sync_bdfutbol_player_full as player_full


def test_resource_specs_cover_canonical_and_manager_views() -> None:
    specs = player_full.build_resource_specs(209629)

    assert [spec.name for spec in specs] == [
        "player_profile",
        "player_stats",
        "player_matches",
        "player_profile_manager",
        "player_stats_manager",
        "player_matches_manager",
    ]

    assert specs[0].url == (
        "https://www.bdfutbol.com/es/j/j209629.html"
    )
    assert specs[1].url == (
        "https://www.bdfutbol.com/es/j/j209629.html?p=stats"
    )
    assert specs[2].url == (
        "https://www.bdfutbol.com/es/p/j209629.html"
    )


def test_manager_resources_are_optional_and_separate_provenance() -> None:
    specs = player_full.build_resource_specs(209629)
    manager = [spec for spec in specs if "manager" in spec.name]

    assert len(manager) == 3
    assert all(spec.optional for spec in manager)
    assert all(
        spec.provenance == "bdfutbol_manager"
        for spec in manager
    )


def test_invalid_player_id_is_rejected() -> None:
    try:
        player_full.build_resource_specs(0)
    except ValueError:
        pass
    else:
        raise AssertionError("player_id=0 must fail")


def test_same_player_profile_link_keeps_only_semantic_query_keys() -> None:
    url = player_full._canonical_player_link(
        (
            "https://www.bdfutbol.com/es/j/j209629.html"
            "?p=stats&manager=1&foo=bar"
        ),
        209629,
    )

    assert url in {
        (
            "https://www.bdfutbol.com/es/j/j209629.html"
            "?p=stats&manager=1"
        ),
        (
            "https://www.bdfutbol.com/es/j/j209629.html"
            "?manager=1&p=stats"
        ),
    }


def test_match_filters_are_not_exploded_into_discovery_urls() -> None:
    url = player_full._canonical_player_link(
        (
            "https://www.bdfutbol.com/es/p/j209629.html"
            "?temp=2024-25&rival=89&pgep=pg&manager=1"
        ),
        209629,
    )

    assert url == (
        "https://www.bdfutbol.com/es/p/j209629.html?manager=1"
    )


def test_other_player_links_are_ignored() -> None:
    assert (
        player_full._canonical_player_link(
            "https://www.bdfutbol.com/es/j/j123.html",
            209629,
        )
        is None
    )


def test_semantic_markers_require_all_required_and_one_any() -> None:
    spec = player_full.ResourceSpec(
        name="profile",
        url="https://example.invalid",
        required_markers=("Nombre completo", "Demarcación"),
        any_markers=("Altura", "Lugar de nacimiento"),
    )

    ok, missing, any_ok = player_full._markers_ok(
        "Nombre completo ... Demarcación ... Altura",
        spec,
    )

    assert ok is True
    assert missing == []
    assert any_ok is True


class _FakeControls:
    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    def all_inner_texts(self) -> list[str]:
        return self._texts


class _FakePage:
    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    def locator(self, selector: str) -> _FakeControls:
        assert selector == "button, a"
        return _FakeControls(self._texts)


def test_photo_gallery_state_reads_declared_count() -> None:
    index, count = player_full._photo_gallery_state(
        _FakePage(["Comentarios (0)", "Fotos (3)"])
    )

    assert index == 1
    assert count == 3


def test_photo_gallery_state_supports_zero_photos() -> None:
    index, count = player_full._photo_gallery_state(
        _FakePage(["Fotos (0)"])
    )

    assert index == 0
    assert count == 0



def test_extract_season_match_specs_uses_exact_t1_hrefs() -> None:
    html = """
    <html><body>
      <table id="t1">
        <tr><th>Temporada</th><th>PJ</th></tr>
        <tr>
          <td>
            <a href="/es/p/j209629.html?temp=2026-27">
              2026-27
            </a>
          </td>
          <td>
            <a href="/es/p/j209629.html?temp=2026-27">6</a>
          </td>
        </tr>
        <tr>
          <td>
            <a href="/es/p/j209629.html?temp=2025-26">
              2025-26
            </a>
          </td>
          <td>10</td>
        </tr>
      </table>
    </body></html>
    """

    specs = player_full._extract_season_match_specs_from_html(
        html,
        player_id=209629,
        provenance="bdfutbol",
        optional=False,
    )

    assert [spec.name for spec in specs] == [
        "player_matches_season_2026-27",
        "player_matches_season_2025-26",
    ]
    assert specs[0].url == (
        "https://www.bdfutbol.com/es/p/j209629.html?temp=2026-27"
    )
    assert specs[0].required_table_id == "tpartits"
    assert specs[0].min_table_rows == 2


def test_build_season_specs_prefers_canonical_and_adds_manager_only() -> None:
    canonical = """
    <table id="t1">
      <tr><th>Temporada</th><th>PJ</th></tr>
      <tr><td><a href="/es/p/j1.html?temp=2026-27">2026-27</a></td><td>6</td></tr>
      <tr><td><a href="/es/p/j1.html?temp=2025-26">2025-26</a></td><td>10</td></tr>
    </table>
    """
    manager = """
    <table id="t1">
      <tr><th>Temporada</th><th>PJ</th></tr>
      <tr><td><a href="/es/p/j1.html?temp=2026-27">2026-27</a></td><td>6</td></tr>
      <tr><td><a href="/es/p/j1.html?temp=2024-25">2024-25</a></td><td>18</td></tr>
    </table>
    """

    specs = player_full.build_season_match_specs(
        player_id=1,
        canonical_html=canonical,
        manager_html=manager,
    )

    assert [spec.scope["season"] for spec in specs] == [
        "2026-27",
        "2025-26",
        "2024-25",
    ]

    by_season = {
        spec.scope["season"]: spec
        for spec in specs
    }
    assert by_season["2026-27"].provenance == "bdfutbol"
    assert by_season["2026-27"].optional is False
    assert by_season["2024-25"].provenance == "bdfutbol_manager"
    assert by_season["2024-25"].optional is True


def test_season_specs_reject_other_player_links() -> None:
    html = """
    <table id="t1">
      <tr><th>Temporada</th></tr>
      <tr>
        <td>
          <a href="/es/p/j999.html?temp=2026-27">2026-27</a>
        </td>
      </tr>
    </table>
    """

    specs = player_full._extract_season_match_specs_from_html(
        html,
        player_id=1,
        provenance="bdfutbol",
        optional=False,
    )

    assert specs == []


class _FakeTableLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _FakeTablePage:
    def __init__(self, count: int) -> None:
        self.count_value = count
        self.selector: str | None = None

    def locator(self, selector: str) -> _FakeTableLocator:
        self.selector = selector
        return _FakeTableLocator(self.count_value)


def test_table_row_requirement_accepts_rendered_match_rows() -> None:
    spec = player_full.ResourceSpec(
        name="season",
        url="https://www.bdfutbol.com/es/p/j1.html?temp=2026-27",
        required_table_id="tpartits",
        min_table_rows=2,
    )
    page = _FakeTablePage(7)

    ok, error = player_full._table_row_requirement_ok(page, spec)

    assert ok is True
    assert error is None
    assert page.selector == "table#tpartits tr"


def test_table_row_requirement_rejects_header_only_table() -> None:
    spec = player_full.ResourceSpec(
        name="season",
        url="https://www.bdfutbol.com/es/p/j1.html?temp=2026-27",
        required_table_id="tpartits",
        min_table_rows=2,
    )

    ok, error = player_full._table_row_requirement_ok(
        _FakeTablePage(1),
        spec,
    )

    assert ok is False
    assert error is not None
    assert "1 filas" in error



def test_manager_season_link_re_attaches_manager_context() -> None:
    html = """
    <table id="t1">
      <tr><th>Temporada</th><th>PJ</th></tr>
      <tr>
        <td>
          <a href="/es/p/j209629.html?temp=2023-24">
            2023-24
          </a>
        </td>
        <td>8</td>
      </tr>
    </table>
    """

    specs = player_full._extract_season_match_specs_from_html(
        html,
        player_id=209629,
        provenance="bdfutbol_manager",
        optional=True,
    )

    assert len(specs) == 1
    assert specs[0].url == (
        "https://www.bdfutbol.com/es/p/j209629.html"
        "?temp=2023-24&manager=1"
    )
    assert specs[0].optional is True


def test_with_manager_context_preserves_existing_filters() -> None:
    url = player_full._with_manager_context(
        "https://www.bdfutbol.com/es/p/j1.html"
        "?temp=2022-23&equip=270"
    )

    assert url == (
        "https://www.bdfutbol.com/es/p/j1.html"
        "?temp=2022-23&equip=270&manager=1"
    )


def test_with_manager_context_does_not_duplicate_flag() -> None:
    url = player_full._with_manager_context(
        "https://www.bdfutbol.com/es/p/j1.html"
        "?temp=2022-23&manager=1"
    )

    assert url.count("manager=1") == 1
