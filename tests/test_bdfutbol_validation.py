from football_data_hub.bdfutbol.validation import assess_snapshot, url_matches_target


def test_cloudflare_verification_is_blocked() -> None:
    assessment = assess_snapshot(
        title="Just a moment...",
        body_text=(
            "www.bdfutbol.com Performing security verification "
            "Verifying... This website uses a security service."
        ),
        link_count=2,
        table_count=0,
        image_count=1,
    )

    assert assessment.accessible is False
    assert assessment.challenge_visible is True
    assert "just a moment" in assessment.visible_challenge_markers


def test_real_bdfutbol_page_is_accessible() -> None:
    body = "Clasificación Jornada Resultados " + ("contenido " * 40)
    assessment = assess_snapshot(
        title="Primera Federación 2026-27 - BDFutbol",
        body_text=body,
        link_count=120,
        table_count=3,
        image_count=25,
        expected_texts=("Clasificación",),
    )

    assert assessment.accessible is True
    assert assessment.challenge_visible is False
    assert assessment.expected_texts_ok is True


def test_expected_text_can_reject_wrong_bdfutbol_page() -> None:
    body = "BDFutbol contenido de otra página " + ("contenido " * 40)
    assessment = assess_snapshot(
        title="BDFutbol",
        body_text=body,
        link_count=50,
        table_count=1,
        image_count=5,
        expected_texts=("Real Jaén",),
    )

    assert assessment.accessible is False
    assert assessment.challenge_visible is False
    assert assessment.expected_texts_ok is False


def test_url_match_normalizes_host_trailing_slash_and_fragment() -> None:
    assert url_matches_target(
        "HTTPS://WWW.BDFUTBOL.COM/es/t/t2026-271rf1.html/#tabla",
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
    )


def test_url_match_treats_requested_query_parameters_as_significant() -> None:
    requested = "https://www.bdfutbol.com/es/t/table.html?a=1&b=2"

    assert url_matches_target(
        requested,
        "https://www.bdfutbol.com/es/t/table.html?b=2&a=1#fixtures",
    )
    assert not url_matches_target(
        requested,
        "https://www.bdfutbol.com/es/t/table.html?a=1&b=3",
    )
