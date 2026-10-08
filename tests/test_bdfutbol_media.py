from __future__ import annotations

from football_data_hub.bdfutbol.media import (
    deduplicate_observations,
    discover_media,
)


BASE = "https://www.bdfutbol.com/es/e/e49.html"


def test_player_image_linked_to_profile_is_accepted() -> None:
    html = """
    <html><body>
      <h2>Jugadores</h2>
      <a href="/es/j/j209629.html">
        <img src="/i/m/209629.png" alt="Morillas">
      </a>
    </body></html>
    """

    item = discover_media(
        html,
        page_url=BASE,
        resource="club_players_all",
        team_id=49,
    )[0]

    assert item.decision == "accept"
    assert item.entity_type == "player"
    assert item.entity_id == 209629
    assert item.role == "portrait"


def test_multiple_images_for_same_player_are_all_preserved() -> None:
    html = """
    <html><body>
      <h2>Fotos</h2>
      <a href="/es/j/j209629.html">
        <img src="/i/m/209629.png" alt="Morillas">
      </a>
      <a href="/es/j/j209629.html">
        <img src="/i/m/209629-2.jpg" alt="Morillas">
      </a>
    </body></html>
    """

    items = discover_media(
        html,
        page_url="https://www.bdfutbol.com/es/j/j209629.html",
        resource="player_profile",
        team_id=49,
    )
    unique = deduplicate_observations(items)

    accepted = [x for x in unique if x["decision"] == "accept"]
    assert len(accepted) == 2


def test_historical_crest_section_is_accepted_for_team() -> None:
    html = """
    <html><body>
      <h2>Otros escudos</h2>
      <div><img src="/i/eg/49-old.png" alt=""></div>
    </body></html>
    """

    item = discover_media(
        html,
        page_url=BASE,
        resource="club_profile",
        team_id=49,
    )[0]

    assert item.decision == "accept"
    assert item.entity_type == "team"
    assert item.entity_id == 49
    assert item.role == "historical_crest"


def test_current_crest_is_detected_from_path_on_club_profile() -> None:
    html = """
    <html><body>
      <h1>Jaén</h1>
      <img src="/i/eg/49p.png" alt="">
    </body></html>
    """

    item = discover_media(
        html,
        page_url=BASE,
        resource="club_profile",
        team_id=49,
    )[0]

    assert item.decision == "accept"
    assert item.role == "current_crest"


def test_stadium_image_linked_to_stadium_is_accepted() -> None:
    html = """
    <html><body>
      <h2>Estadios</h2>
      <a href="/es/s/100355.html">
        <img src="/i/c/49.jpg" alt="La Victoria">
      </a>
    </body></html>
    """

    item = discover_media(
        html,
        page_url=BASE,
        resource="club_profile",
        team_id=49,
    )[0]

    assert item.decision == "accept"
    assert item.entity_type == "stadium"
    assert item.entity_id == 100355
    assert item.role == "stadium_photo"


def test_stadium_profile_accepts_only_real_bdfutbol_photo_path() -> None:
    html = """
    <html><body>
      <h1>La Victoria</h1>
      <img src="/i/c/49.jpg" alt="">
      <img src="/img/logo16w.png" alt="">
      <img src="https://a.tile.openstreetmap.org/15/16039/12665.png" alt="">
      <img src="https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png" alt="">
    </body></html>
    """

    items = discover_media(
        html,
        page_url="https://www.bdfutbol.com/es/s/100355.html",
        resource="club_stadium_100355",
        team_id=49,
    )

    accepted = [x for x in items if x.decision == "accept"]
    rejected = [x for x in items if x.decision == "reject"]

    assert len(accepted) == 1
    assert accepted[0].source_url == "https://www.bdfutbol.com/i/c/49.jpg"
    assert accepted[0].entity_id == 100355
    assert len(rejected) == 3


def test_external_images_are_rejected_even_on_stadium_page() -> None:
    html = """
    <html><body>
      <img src="https://a.tile.openstreetmap.org/15/1/2.png">
    </body></html>
    """

    item = discover_media(
        html,
        page_url="https://www.bdfutbol.com/es/s/49.html",
        resource="club_stadium_49",
        team_id=49,
    )[0]

    assert item.decision == "reject"
    assert item.reason.startswith("external_host:")


def test_hero_and_loading_assets_are_rejected() -> None:
    html = """
    <html><body>
      <img src="/img/hero/Rectangle6.webp" alt="">
      <img src="/img/loading.gif" alt="Cargando">
    </body></html>
    """

    items = discover_media(
        html,
        page_url=BASE,
        resource="club_profile",
        team_id=49,
    )

    assert len(items) == 2
    assert all(item.decision == "reject" for item in items)


def test_srcset_preserves_all_variants() -> None:
    html = """
    <html><body>
      <a href="/es/j/j209629.html">
        <img
          src="/i/m/209629-small.jpg"
          srcset="/i/m/209629-small.jpg 1x, /i/m/209629.jpg 2x"
          alt="Morillas">
      </a>
    </body></html>
    """

    items = discover_media(
        html,
        page_url="https://www.bdfutbol.com/es/j/j209629.html",
        resource="player_profile",
        team_id=49,
    )

    assert {
        item.source_url
        for item in items
    } == {
        "https://www.bdfutbol.com/i/m/209629-small.jpg",
        "https://www.bdfutbol.com/i/m/209629.jpg",
    }
    assert all(item.decision == "accept" for item in items)


def test_deduplication_keeps_occurrences_from_multiple_pages() -> None:
    html = """
    <html><body>
      <a href="/es/j/j209629.html">
        <img src="/i/m/209629.png" alt="Morillas">
      </a>
    </body></html>
    """

    first = discover_media(
        html,
        page_url="https://www.bdfutbol.com/es/t/t2026-2749.html",
        resource="season_roster",
        team_id=49,
    )
    second = discover_media(
        html,
        page_url="https://www.bdfutbol.com/es/e/egols49.html",
        resource="club_players_all",
        team_id=49,
    )

    unique = deduplicate_observations(first + second)

    assert len(unique) == 1
    occurrences = unique[0]["occurrences"]
    assert isinstance(occurrences, list)
    assert len(occurrences) == 2


def test_same_crest_url_current_and_historical_is_one_asset_current_wins() -> None:
    current_html = """
    <html><body>
      <h1>Jaén</h1>
      <img src="/i/eg/49p.png" alt="">
    </body></html>
    """
    historical_html = """
    <html><body>
      <h2>Otros escudos</h2>
      <img src="/i/eg/49p.png" alt="">
    </body></html>
    """

    current = discover_media(
        current_html,
        page_url=BASE,
        resource="club_profile",
        team_id=49,
    )
    historical = discover_media(
        historical_html,
        page_url=BASE,
        resource="club_profile",
        team_id=49,
    )

    unique = deduplicate_observations(current + historical)

    assert len(unique) == 1
    assert unique[0]["role"] == "current_crest"
    assert unique[0]["roles_observed"] == [
        "current_crest",
        "historical_crest",
    ]
