"""Parser semántico de los agregados, récords y serie AmCharts de BDFutbol."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

from .models import (
    ParsedBDFutbolStatistics,
    PublishedChart,
    PublishedCompetitionSummary,
    PublishedMatchRecord,
    PublishedPenaltyStatistics,
    PublishedRoundPoint,
    PublishedStreak,
)

STATISTICS_URL = "https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=stats"
_TARGET_TITLE_MARKERS = ("grupo ii", "2026-27")
_SUMMARY_LABELS = (
    "Equipos",
    "Partidos",
    "Victorias locales",
    "Victorias visitantes",
    "Empates",
    "Goles marcados",
    "Promedio goleador",
    "Tarjetas amarillas",
    "Tarjetas amarillas por partido",
    "Expulsiones",
    "Expulsiones por partido",
)
_RECORD_PREFIXES = {
    "Máxima victoria local:": ("match", "largest_home_win"),
    "Máxima victoria visitante:": ("match", "largest_away_win"),
    "Mejor racha ganadora:": ("streak", "winning"),
    "Peor racha perdedora:": ("streak", "losing"),
    "Mejor racha no perdiendo:": ("streak", "unbeaten"),
    "Peor racha no ganando:": ("streak", "winless"),
    "Partido con más goles:": ("match", "most_goals"),
}
_CHART_FIELDS = {
    "VG": ("Goles", "goals"),
    "VTG": ("Tarjetas amarillas", "yellow_cards"),
    "VTV": ("Tarjetas rojas", "red_cards"),
}
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class StatisticsParseError(ValueError):
    """El documento o gráfico no expone una estructura semántica validable."""


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str | None]
    parts: list[str | _Node] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        return " ".join(
            part.text() if isinstance(part, _Node) else part
            for part in self.parts
        )

    def descendants(self, tag: str | None = None):
        for part in self.parts:
            if not isinstance(part, _Node):
                continue
            if tag is None or part.tag == tag:
                yield part
            yield from part.descendants(tag)


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, dict(attrs))
        self.stack[-1].parts.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].parts.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].parts.append(data.strip())


def validate_statistics_page_html(source_html: str) -> tuple[str, ...]:
    """Valida contenido y estructura antes de aceptar una captura como válida."""
    try:
        root = _parse_tree(source_html)
    except (RecursionError, ValueError) as exc:
        return (f"HTML no interpretable: {type(exc).__name__}",)
    errors: list[str] = []
    stats = _statistics_container(root)
    if stats is None:
        return ("No se encontró el panel semántico de Estadísticas",)
    text = stats.text()
    for label in (*_SUMMARY_LABELS, "Penaltis pitados", "Penaltis marcados", "Penaltis fallados"):
        if label.casefold() not in text.casefold():
            errors.append(f"Falta el dato publicado {label!r}")
    if not any(node.attrs.get("id") == "grf_stats" for node in stats.descendants()):
        errors.append("No se encontró el contenedor #grf_stats")
    record_table = _record_table(stats)
    if record_table is None:
        errors.append("No se encontró la tabla de récords y rachas")
    else:
        table_text = record_table.text()
        for prefix in _RECORD_PREFIXES:
            if prefix.casefold() not in table_text.casefold():
                errors.append(f"Falta el récord o racha {prefix!r}")
    if "Grupo II" not in root.text() or "2026-27" not in root.text():
        errors.append("El documento no identifica Grupo II 2026-27")
    return tuple(errors)


def parse_statistics_page(
    source_html: str,
    chart_runtime: dict[str, object],
    *,
    source_url: str = STATISTICS_URL,
) -> ParsedBDFutbolStatistics:
    parts = urlsplit(source_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.bdfutbol.com"
        or parts.path != "/es/t/t2026-271rf2.html"
        or parse_qs(parts.query).get("tab") != ["stats"]
    ):
        raise StatisticsParseError("La URL no corresponde a Estadísticas Grupo II 2026-27")
    missing = validate_statistics_page_html(source_html)
    if missing:
        raise StatisticsParseError("; ".join(missing))
    root = _parse_tree(source_html)
    title = _page_title(root).casefold()
    if any(marker not in title for marker in _TARGET_TITLE_MARKERS):
        raise StatisticsParseError("El título no confirma Grupo II 2026-27")
    stats = _statistics_container(root)
    assert stats is not None
    text = _normalized_text(stats.text())
    published = _parse_summary(text)
    penalties = _parse_penalties(text)
    records, streaks = _parse_records(stats)
    chart = _parse_chart(stats, chart_runtime)
    return ParsedBDFutbolStatistics(
        source_url=source_url,
        competition="Primera Federación",
        season="2026-27",
        group="II",
        source_summary=published,
        exclusive_penalties=penalties,
        match_records=records,
        streaks=streaks,
        chart=chart,
    )


def _parse_tree(source_html: str) -> _Node:
    parser = _TreeParser()
    parser.feed(source_html)
    parser.close()
    return parser.root


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _page_title(root: _Node) -> str:
    for node in root.descendants("title"):
        return _normalized_text(node.text())
    return ""


def _statistics_container(root: _Node) -> _Node | None:
    candidates = [
        node
        for node in root.descendants("div")
        if "tab-divs" in node.classes()
        and "pt-3" in node.classes()
        and "penaltis pitados" in node.text().casefold()
    ]
    return min(candidates, key=lambda node: len(node.text())) if candidates else None


def _record_table(stats: _Node) -> _Node | None:
    candidates = [
        node
        for node in stats.descendants("table")
        if all(prefix.casefold() in node.text().casefold() for prefix in _RECORD_PREFIXES)
    ]
    return min(candidates, key=lambda node: len(node.text())) if candidates else None


def _integer_after(text: str, label: str) -> int:
    match = re.search(rf"(?<![\w]){re.escape(label)}\s+(\d+)(?![\d,.])", text, re.I)
    if match is None:
        raise StatisticsParseError(f"No se pudo leer el valor de {label!r}")
    return int(match.group(1))


def _integer_before(text: str, label: str) -> int:
    match = re.search(rf"(?<![\d])([\d]+)\s+{re.escape(label)}(?!\s+por partido)", text, re.I)
    if match is None:
        raise StatisticsParseError(f"No se pudo leer el total de {label!r}")
    return int(match.group(1))


def _average_before(text: str, label: str) -> float:
    match = re.search(rf"(?<![\d])([\d]+(?:[,.][\d]+)?)\s+{re.escape(label)}", text, re.I)
    if match is None:
        raise StatisticsParseError(f"No se pudo leer el promedio de {label!r}")
    return float(match.group(1).replace(",", "."))


def _parse_summary(text: str) -> PublishedCompetitionSummary:
    return PublishedCompetitionSummary(
        teams=_integer_after(text, "Equipos"),
        matches=_integer_after(text, "Partidos"),
        home_wins=_integer_after(text, "Victorias locales"),
        away_wins=_integer_after(text, "Victorias visitantes"),
        draws=_integer_after(text, "Empates"),
        goals=_integer_before(text, "Goles marcados"),
        goals_per_match=_average_before(text, "Promedio goleador"),
        yellow_cards=_integer_before(text, "Tarjetas amarillas"),
        yellow_cards_per_match=_average_before(text, "Tarjetas amarillas por partido"),
        expulsions=_integer_before(text, "Expulsiones"),
        expulsions_per_match=_average_before(text, "Expulsiones por partido"),
    )


def _parse_penalties(text: str) -> PublishedPenaltyStatistics:
    return PublishedPenaltyStatistics(
        penalties_awarded=_integer_after(text, "Penaltis pitados"),
        penalties_scored=_integer_after(text, "Penaltis marcados"),
        penalties_missed=_integer_after(text, "Penaltis fallados"),
    )


def _parse_records(
    stats: _Node,
) -> tuple[tuple[PublishedMatchRecord, ...], tuple[PublishedStreak, ...]]:
    table = _record_table(stats)
    if table is None:
        raise StatisticsParseError("No se encontró la tabla de récords y rachas")
    match_records: list[PublishedMatchRecord] = []
    streaks: list[PublishedStreak] = []
    for row in table.descendants("tr"):
        row_text = _normalized_text(row.text())
        if not row_text:
            continue
        prefix = next(
            (item for item in _RECORD_PREFIXES if row_text.casefold().startswith(item.casefold())),
            None,
        )
        if prefix is None:
            continue
        record_type, kind = _RECORD_PREFIXES[prefix]
        if record_type == "match":
            match = _parse_match_record(row, prefix, kind)
            match_records.append(match)
        else:
            streaks.append(_parse_streak(row_text, prefix, kind))
    expected_matches = {"largest_home_win", "largest_away_win", "most_goals"}
    expected_streaks = {"winning", "losing", "unbeaten", "winless"}
    if {item.kind for item in match_records} != expected_matches:
        raise StatisticsParseError("La tabla no contiene los tres récords de partido esperados")
    if {item.kind for item in streaks} != expected_streaks:
        raise StatisticsParseError("La tabla no contiene las cuatro rachas esperadas")
    return tuple(match_records), tuple(streaks)


def _parse_match_record(row: _Node, prefix: str, kind: str) -> PublishedMatchRecord:
    link = next(
        (
            node
            for node in row.descendants("a")
            if "/p/p.php" in (node.attrs.get("href") or "")
        ),
        None,
    )
    if link is None:
        raise StatisticsParseError(f"El récord {prefix!r} no incluye enlace de partido")
    href = link.attrs.get("href") or ""
    match_id = parse_qs(urlsplit(urljoin("https://www.bdfutbol.com/es/t/", href)).query).get("id", [""])[0]
    if not match_id.isdecimal():
        raise StatisticsParseError(f"El récord {prefix!r} no incluye ID de partido válido")
    link_text = _normalized_text(link.text())
    score = re.match(r"(\d+)\s*[-–]\s*(\d+)", link_text)
    if score is None:
        raise StatisticsParseError(f"No se pudo leer el marcador del récord {prefix!r}")
    home_goals, away_goals = int(score.group(1)), int(score.group(2))
    measure = (
        home_goals - away_goals
        if kind == "largest_home_win"
        else away_goals - home_goals
        if kind == "largest_away_win"
        else home_goals + away_goals
    )
    if measure <= 0:
        raise StatisticsParseError(f"El marcador no respalda el récord {prefix!r}")
    source_url = urljoin("https://www.bdfutbol.com/es/t/", href)
    return PublishedMatchRecord(
        kind=kind,  # type: ignore[arg-type]
        measure=measure,
        match_id=match_id,
        home_goals=home_goals,
        away_goals=away_goals,
        source_url=source_url,
    )


def _parse_streak(row_text: str, prefix: str, kind: str) -> PublishedStreak:
    pattern = rf"^{re.escape(prefix)}\s*(.+?):\s*(\d+)\s+Partidos\s*\(Jornadas\s+(\d+)\s*[-–]\s*(\d+)\)\s*$"
    match = re.match(pattern, row_text, re.I)
    if match is None:
        raise StatisticsParseError(f"No se pudo leer la racha publicada {prefix!r}")
    team_name, count, start, end = match.groups()
    return PublishedStreak(
        kind=kind,  # type: ignore[arg-type]
        team_name=team_name.strip(),
        match_count=int(count),
        matchday_start=int(start),
        matchday_end=int(end),
    )


def _parse_chart(stats: _Node, payload: dict[str, object]) -> PublishedChart:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise StatisticsParseError("Falta el objeto del gráfico capturado desde AmCharts")
    if chart.get("category_field") != "jornada":
        raise StatisticsParseError("El gráfico no utiliza jornada como categoría")
    data_provider = chart.get("data_provider")
    graphs = chart.get("graph_fields")
    if not isinstance(data_provider, list) or not isinstance(graphs, list):
        raise StatisticsParseError("El gráfico no conserva dataProvider o graph_fields")
    labels_by_field: dict[str, str] = {}
    for graph in graphs:
        if not isinstance(graph, dict):
            raise StatisticsParseError("Metadato de serie de gráfico inválido")
        field_name = graph.get("value_field")
        title = graph.get("title")
        if field_name in labels_by_field or field_name not in _CHART_FIELDS:
            raise StatisticsParseError(f"Campo de serie no reconocido o repetido: {field_name!r}")
        expected_title, _ = _CHART_FIELDS[field_name]
        if title != expected_title:
            raise StatisticsParseError(f"Título inesperado para la serie {field_name!r}: {title!r}")
        labels_by_field[str(field_name)] = str(title)
    if set(labels_by_field) != set(_CHART_FIELDS):
        raise StatisticsParseError("El gráfico debe contener Goles, amarillas y rojas")

    points: list[PublishedRoundPoint] = []
    seen_rounds: set[int] = set()
    for item in data_provider:
        if not isinstance(item, dict):
            raise StatisticsParseError("Punto de gráfico inválido")
        matchday = item.get("jornada")
        if isinstance(matchday, bool) or not isinstance(matchday, int) or matchday < 1:
            raise StatisticsParseError("El gráfico contiene una jornada inválida")
        if matchday in seen_rounds:
            raise StatisticsParseError(f"Jornada duplicada en dataProvider: {matchday}")
        seen_rounds.add(matchday)
        values = {
            _CHART_FIELDS[field_name][1]: _chart_value(item, field_name)
            for field_name in _CHART_FIELDS
        }
        points.append(
            PublishedRoundPoint(
                matchday=matchday,
                goals=values["goals"],
                yellow_cards=values["yellow_cards"],
                red_cards=values["red_cards"],
            )
        )
    points.sort(key=lambda item: item.matchday)
    version_match = re.search(r"amCharts\s+([\d.]+)", stats.text(), re.I)
    library = "amCharts" + (f" {version_match.group(1)}" if version_match else "")
    fields = tuple(
        (labels_by_field[field_name], field_name)
        for field_name in ("VG", "VTG", "VTV")
    )
    return PublishedChart(
        library=library,
        category_field="jornada",
        graph_fields=fields,
        points=tuple(points),
    )


def _chart_value(point: dict[str, object], field_name: str) -> int | None:
    value = point.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StatisticsParseError(f"Valor de gráfico inválido en {field_name}: {value!r}")
    return value
