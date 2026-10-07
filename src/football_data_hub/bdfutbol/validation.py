from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


VISIBLE_CHALLENGE_MARKERS = (
    "just a moment",
    "performing security verification",
    "security verification",
    "verifying...",
    "enable javascript and cookies to continue",
    "verificación de seguridad en curso",
    "verificacion de seguridad en curso",
    "verifique que es un ser humano",
    "verify you are human",
)


@dataclass(frozen=True, slots=True)
class PageAssessment:
    accessible: bool
    challenge_visible: bool
    visible_challenge_markers: tuple[str, ...]
    title_looks_real: bool
    structural_content: bool
    expected_texts_ok: bool
    expected_texts: dict[str, bool]
    title: str
    body_text_chars: int
    link_count: int
    table_count: int
    image_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_snapshot(
    *,
    title: str,
    body_text: str,
    link_count: int,
    table_count: int,
    image_count: int,
    expected_texts: Iterable[str] = (),
) -> PageAssessment:
    """Evalúa si un DOM visible parece una página BDFutbol utilizable.

    La decisión no depende del status HTTP. BDFutbol puede devolver un 403
    diagnóstico mientras el navegador termina mostrando contenido válido.
    """

    title = title.strip()
    body_text = body_text or ""
    title_lower = title.casefold()
    body_lower = body_text.casefold()

    challenge_markers = tuple(
        marker
        for marker in VISIBLE_CHALLENGE_MARKERS
        if marker.casefold() in title_lower or marker.casefold() in body_lower
    )

    expected_results = {
        text: text.casefold() in body_lower
        for text in expected_texts
    }
    expected_ok = all(expected_results.values())

    title_looks_real = (
        "bdfutbol" in title_lower
        and "just a moment" not in title_lower
    )
    structural_content = len(body_text.strip()) >= 200 and link_count >= 10
    challenge_visible = bool(challenge_markers)

    accessible = (
        title_looks_real
        and structural_content
        and not challenge_visible
        and expected_ok
    )

    return PageAssessment(
        accessible=accessible,
        challenge_visible=challenge_visible,
        visible_challenge_markers=challenge_markers,
        title_looks_real=title_looks_real,
        structural_content=structural_content,
        expected_texts_ok=expected_ok,
        expected_texts=expected_results,
        title=title,
        body_text_chars=len(body_text),
        link_count=link_count,
        table_count=table_count,
        image_count=image_count,
    )


def assess_page(page: Any, expected_texts: Iterable[str] = ()) -> PageAssessment:
    try:
        title = page.title().strip()
    except Exception:
        title = ""

    try:
        body_text = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body_text = ""

    def count(selector: str) -> int:
        try:
            return int(page.locator(selector).count())
        except Exception:
            return 0

    return assess_snapshot(
        title=title,
        body_text=body_text,
        link_count=count("a"),
        table_count=count("table"),
        image_count=count("img"),
        expected_texts=expected_texts,
    )
