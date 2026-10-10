"""Navegación por los controles observados de la clasificación."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import ClassificationContext, ClassificationRequest


class FilterSelectionError(ValueError):
    """No se pudo seleccionar un filtro en el DOM observado."""


_CLASSIFICATION_VALUES = {"local": "1", "visitor": "2", "general": "3"}


def _option_map(page: Any, selector: str) -> dict[str, str]:
    if page.locator(selector).count() != 1:
        raise FilterSelectionError(f"Falta el control {selector}")
    return page.locator(f"{selector} option").evaluate_all(
        "options => Object.fromEntries(options.map(option => [option.value, option.textContent.trim()]))"
    )


def _format_site_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _date_from_option(label: str) -> str | None:
    import re

    match = re.search(r"\((\d{2}/\d{2}/\d{4})\)", label)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()


def apply_filters(page: Any, request: ClassificationRequest) -> ClassificationContext:
    """Select one explicit table state and return the values applied."""
    classifications = _option_map(page, "#classitip")
    jornada_options = _option_map(page, "#jornada")
    postponed_options = _option_map(page, "#postposat")
    range_options = _option_map(page, "#filtre_dates")

    classification_value = _CLASSIFICATION_VALUES[request.classification_type]
    if classification_value not in classifications:
        raise FilterSelectionError("El control no ofrece el tipo de clasificación pedido")
    page.locator("#classitip").select_option(classification_value)

    if request.matchday is not None:
        matchday_value = str(request.matchday)
        if matchday_value not in jornada_options:
            raise FilterSelectionError(f"La página no ofrece Jornada {request.matchday}")
        page.locator("#jornada").select_option(matchday_value)

    postponed_value = "1" if request.include_postponed else "2"
    if postponed_value not in postponed_options:
        raise FilterSelectionError("El control de aplazados no ofrece el valor solicitado")
    page.locator("#postposat").select_option(postponed_value)

    range_value = {"all": "1", "dates": "2", "rounds": "3"}[request.range_type]
    if range_value not in range_options:
        raise FilterSelectionError("El control no ofrece el tipo de rango solicitado")
    page.locator("#filtre_dates").select_option(range_value)

    if request.range_type == "dates":
        assert request.date_start is not None and request.date_end is not None
        page.locator("#date1").fill(_format_site_date(request.date_start))
        page.locator("#date2").fill(_format_site_date(request.date_end))
    elif request.range_type == "rounds":
        assert request.round_start is not None and request.round_end is not None
        page.locator("#jorn1").fill(str(request.round_start))
        page.locator("#jorn2").fill(str(request.round_end))

    if request.range_type in {"dates", "rounds"}:
        page.evaluate("() => window.recalcula_classificacio()")
        page.wait_for_timeout(100)

    selected_matchday = int(page.locator("#jornada").input_value())
    selected_label = jornada_options.get(str(selected_matchday), "")
    matchday_date = _date_from_option(selected_label)
    if request.range_type == "rounds" and request.round_end is not None:
        if request.round_end > selected_matchday:
            raise FilterSelectionError(
                "El final del rango no puede superar la Jornada seleccionada"
            )

    return ClassificationContext(
        classification_type=request.classification_type,
        matchday=selected_matchday,
        matchday_date=matchday_date,
        postponed_policy="include" if request.include_postponed else "exclude",
        range_type=request.range_type,
        range_start_date=request.date_start.isoformat() if request.date_start else None,
        range_end_date=request.date_end.isoformat() if request.date_end else None,
        range_start_round=request.round_start,
        range_end_round=request.round_end,
    )
