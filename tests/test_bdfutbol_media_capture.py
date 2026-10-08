from __future__ import annotations

from pathlib import Path

from football_data_hub.bdfutbol.media_capture import (
    FetchResult,
    _sniff_extension,
    capture_candidates,
    fetch_image_with_browser_page,
    select_candidates,
)


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00" * 64
)


def _audit() -> dict:
    return {
        "media": [
            {
                "source_url": "https://www.bdfutbol.com/i/eg/49p.png",
                "entity_type": "team",
                "entity_id": 49,
                "role": "current_crest",
                "roles_observed": ["current_crest"],
                "decision": "accept",
                "occurrences": [
                    {
                        "source_page": "https://www.bdfutbol.com/es/e/e49.html",
                        "resource": "club_profile",
                    }
                ],
            },
            {
                "source_url": "https://www.bdfutbol.com/i/eg/18.png",
                "entity_type": "team",
                "entity_id": 18,
                "role": "team_media",
                "roles_observed": ["team_media"],
                "decision": "review",
                "occurrences": [],
            },
            {
                "source_url": "https://a.tile.openstreetmap.org/x.png",
                "entity_type": None,
                "entity_id": None,
                "role": None,
                "decision": "accept",
                "occurrences": [],
            },
        ]
    }


def test_default_selects_only_accept_and_bdfutbol_host() -> None:
    selected = select_candidates(_audit())
    assert len(selected) == 1
    assert selected[0]["entity_id"] == 49


def test_include_review_still_rejects_external_host() -> None:
    selected = select_candidates(
        _audit(),
        include_review=True,
    )
    assert [item["entity_id"] for item in selected] == [49, 18]


def test_sniff_png() -> None:
    assert _sniff_extension(PNG, "image/png") == ".png"


def test_sniff_jpeg() -> None:
    assert _sniff_extension(
        b"\xff\xd8\xff\xe0" + b"x" * 20,
        "image/jpeg",
    ) == ".jpg"


def test_capture_deduplicates_same_binary_from_two_urls(
    tmp_path: Path,
) -> None:
    audit = {
        "media": [
            {
                "source_url": "https://www.bdfutbol.com/i/m/1.png",
                "entity_type": "player",
                "entity_id": 1,
                "role": "portrait",
                "roles_observed": ["portrait"],
                "decision": "accept",
                "occurrences": [],
            },
            {
                "source_url": "https://www.bdfutbol.com/i/m/1-alt.png",
                "entity_type": "player",
                "entity_id": 1,
                "role": "portrait",
                "roles_observed": ["portrait"],
                "decision": "accept",
                "occurrences": [],
            },
        ]
    }

    def fake_fetch(url: str, **kwargs) -> FetchResult:
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            mime_type="image/png",
            data=PNG,
        )

    source = tmp_path / "media_audit.json"
    source.write_text("{}", encoding="utf-8")

    result = capture_candidates(
        audit=audit,
        project_root=tmp_path,
        source_audit=source,
        object_root=tmp_path / "objects",
        delay_seconds=0,
        fetcher=fake_fetch,
    )

    assert result["candidates_selected"] == 2
    assert result["urls_downloaded"] == 2
    assert result["urls_failed"] == 0
    assert result["unique_binary_assets"] == 1

    asset = result["assets"][0]
    assert sorted(asset["source_urls"]) == [
        "https://www.bdfutbol.com/i/m/1-alt.png",
        "https://www.bdfutbol.com/i/m/1.png",
    ]
    assert len(asset["associations"]) == 1


def test_capture_preserves_two_different_photos_for_same_player(
    tmp_path: Path,
) -> None:
    audit = {
        "media": [
            {
                "source_url": "https://www.bdfutbol.com/i/m/1.png",
                "entity_type": "player",
                "entity_id": 1,
                "role": "portrait",
                "roles_observed": ["portrait"],
                "decision": "accept",
                "occurrences": [],
            },
            {
                "source_url": "https://www.bdfutbol.com/i/m/1-2.png",
                "entity_type": "player",
                "entity_id": 1,
                "role": "portrait",
                "roles_observed": ["portrait"],
                "decision": "accept",
                "occurrences": [],
            },
        ]
    }

    def fake_fetch(url: str, **kwargs) -> FetchResult:
        data = PNG + (b"A" if url.endswith("1.png") else b"B")
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            mime_type="image/png",
            data=data,
        )

    source = tmp_path / "media_audit.json"
    source.write_text("{}", encoding="utf-8")

    result = capture_candidates(
        audit=audit,
        project_root=tmp_path,
        source_audit=source,
        object_root=tmp_path / "objects",
        delay_seconds=0,
        fetcher=fake_fetch,
    )

    assert result["unique_binary_assets"] == 2
    assert len(result["entity_index"]["player:1"]) == 2


def test_failed_download_is_preserved_in_manifest(
    tmp_path: Path,
) -> None:
    audit = {
        "media": [
            {
                "source_url": "https://www.bdfutbol.com/i/m/1.png",
                "entity_type": "player",
                "entity_id": 1,
                "role": "portrait",
                "roles_observed": ["portrait"],
                "decision": "accept",
                "occurrences": [],
            }
        ]
    }

    def fake_fetch(url: str, **kwargs) -> FetchResult:
        raise RuntimeError("HTTP 403")

    source = tmp_path / "media_audit.json"
    source.write_text("{}", encoding="utf-8")

    result = capture_candidates(
        audit=audit,
        project_root=tmp_path,
        source_audit=source,
        object_root=tmp_path / "objects",
        delay_seconds=0,
        fetcher=fake_fetch,
    )

    assert result["urls_downloaded"] == 0
    assert result["urls_failed"] == 1
    assert result["failures"][0]["error"] == "HTTP 403"


def test_existing_content_addressed_object_is_reused(
    tmp_path: Path,
) -> None:
    audit = {
        "media": [
            {
                "source_url": "https://www.bdfutbol.com/i/eg/49p.png",
                "entity_type": "team",
                "entity_id": 49,
                "role": "current_crest",
                "roles_observed": ["current_crest"],
                "decision": "accept",
                "occurrences": [],
            }
        ]
    }

    def fake_fetch(url: str, **kwargs) -> FetchResult:
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            mime_type="image/png",
            data=PNG,
        )

    source = tmp_path / "media_audit.json"
    source.write_text("{}", encoding="utf-8")

    first = capture_candidates(
        audit=audit,
        project_root=tmp_path,
        source_audit=source,
        object_root=tmp_path / "objects",
        delay_seconds=0,
        fetcher=fake_fetch,
    )
    second = capture_candidates(
        audit=audit,
        project_root=tmp_path,
        source_audit=source,
        object_root=tmp_path / "objects",
        delay_seconds=0,
        fetcher=fake_fetch,
    )

    assert first["new_objects_written"] == 1
    assert second["new_objects_written"] == 0
    assert second["existing_objects_reused"] == 1


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        url: str = "https://www.bdfutbol.com/i/m/1.png",
        headers: dict[str, str] | None = None,
        body: bytes = PNG,
    ) -> None:
        self.status = status
        self.url = url
        self.headers = headers or {"content-type": "image/png"}
        self._body = body

    def body(self) -> bytes:
        return self._body


class _FakePage:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.url = "about:blank"
        self.headers: dict[str, str] = {}
        self.goto_calls: list[tuple[str, str, int]] = []

    def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        self.headers = dict(headers)

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> _FakeResponse:
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url
        return self.response


def test_browser_fetch_uses_same_page_and_referer() -> None:
    page = _FakePage(_FakeResponse())

    result = fetch_image_with_browser_page(
        page,
        "https://www.bdfutbol.com/i/m/1.png",
        referer="https://www.bdfutbol.com/es/j/j1.html",
        timeout_seconds=3,
        max_bytes=1024,
    )

    assert result.status == 200
    assert result.data == PNG
    assert page.headers["Referer"] == (
        "https://www.bdfutbol.com/es/j/j1.html"
    )
    assert page.goto_calls == [
        (
            "https://www.bdfutbol.com/i/m/1.png",
            "commit",
            3000,
        )
    ]


def test_browser_fetch_rejects_external_host() -> None:
    page = _FakePage(_FakeResponse())

    try:
        fetch_image_with_browser_page(
            page,
            "https://a.tile.openstreetmap.org/1.png",
        )
    except ValueError as exc:
        assert "Host de media no permitido" in str(exc)
    else:
        raise AssertionError("external host must fail")


def test_browser_fetch_honours_content_length_limit() -> None:
    page = _FakePage(
        _FakeResponse(
            headers={
                "content-type": "image/png",
                "content-length": "5000",
            }
        )
    )

    try:
        fetch_image_with_browser_page(
            page,
            "https://www.bdfutbol.com/i/m/1.png",
            max_bytes=100,
        )
    except ValueError as exc:
        assert "supera max_bytes" in str(exc)
    else:
        raise AssertionError("oversized image must fail")
