"""Preview deportiva local de los exports parsed de FootballDataHub."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from football_data_hub.dev_explorer.data import (
    GROUPS,
    DatasetCandidate,
    DatasetValidationError,
    ExplorerDataset,
    PlayerExplorerDataset,
    diagnostic_rows,
    discover_datasets,
    discover_player_exports,
    filter_player_matches,
    filter_matches,
    fixture_status,
    group_quality,
    has_result,
    latest_valid_dataset,
    latest_valid_player_export,
    load_player_export,
    load_dataset,
    player_match_counts,
    player_export_captured_at,
    player_search_label,
    search_records,
    recent_results,
    score_label,
    standings_table_rows,
    team_records,
    upcoming_matches,
)


DATA_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "parsed"
    / "bdfutbol"
    / "primera_federacion_2026_27"
)
PLAYER_DATA_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "parsed"
    / "bdfutbol"
    / "player_2026_27"
    / "compact"
)

STATUS_LABELS = {
    "played": "Disputado",
    "scheduled": "Programado",
    "unresolved": "Resultado pendiente",
    "unconfirmed": "Fecha por confirmar",
    "unknown": "Sin estado disponible",
}
STATUS_ICONS = {
    "played": "●",
    "scheduled": "◷",
    "unresolved": "!",
    "unconfirmed": "…",
    "unknown": "·",
}
STANDING_COLUMN_ORDER = [
    "Posición",
    "Equipo",
    "Puntos",
    "PJ",
    "PG",
    "PE",
    "PP",
    "GF",
    "GC",
    "TA",
    "TR",
]

st.set_page_config(
    page_title="Primera Federación 2026/27",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.6rem; padding-bottom: 3rem; }
        [data-testid="stSidebar"] { border-right: 1px solid rgba(148,163,184,.12); }
        [data-testid="stMetric"] {
            background: rgba(255,255,255,.035);
            border: 1px solid rgba(148,163,184,.14);
            border-radius: 14px;
            padding: .85rem 1rem;
        }
        [data-testid="stMetricLabel"] { color: #a7b4c5; }
        .sport-kicker {
            color: #86efac; font-size: .78rem; font-weight: 700;
            letter-spacing: .12em; text-transform: uppercase; margin-bottom: .3rem;
        }
        .sport-title { font-size: clamp(2rem, 4vw, 3.25rem); font-weight: 750; line-height: 1.05; }
        .sport-subtitle { color: #a7b4c5; margin-top: .35rem; }
        .fixture-line {
            display: grid; grid-template-columns: minmax(0,1fr) auto minmax(0,1fr);
            align-items: center; gap: 1rem; text-align: center; padding: .2rem 0;
        }
        .fixture-team { font-size: 1rem; font-weight: 650; line-height: 1.35; }
        .fixture-home { text-align: right; }
        .fixture-away { text-align: left; }
        .fixture-score { font-size: 1.35rem; font-weight: 800; white-space: nowrap; }
        .fixture-meta { color: #a7b4c5; font-size: .82rem; margin-top: .65rem; }
        .team-name { font-size: 1.25rem; font-weight: 700; }
        div[data-testid="stDataFrame"] { border: 1px solid rgba(148,163,184,.12); border-radius: 12px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _date_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "Fecha por confirmar"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def _capture_date_label(dataset: ExplorerDataset, group: str) -> str:
    captured = dataset.capture_for_group(group).get("captured_at_utc")
    if not isinstance(captured, str):
        return "fecha no disponible"
    return _date_label(captured[:10])


def _capture_label(candidate: DatasetCandidate) -> str:
    captured = candidate.captured_at
    if captured is None:
        return "Export incompleto · sin fecha de captura"
    local_date = captured.astimezone(timezone.utc).strftime("%d/%m/%Y · %H:%M UTC")
    state = "disponible" if candidate.valid else "incompleto"
    return f"Captura {local_date} · {state}"


def _team_options(dataset: ExplorerDataset, group: str) -> list[tuple[str, str]]:
    teams = [team for team in dataset.participants if team.get("group") == group]
    return sorted(
        [
            (str(team.get("team_season_id", "")), str(team.get("team_name", "Equipo sin nombre")))
            for team in teams
        ],
        key=lambda item: item[1].casefold(),
    )


def _team_name(options: list[tuple[str, str]], team_id: str) -> str:
    return next((name for identity, name in options if identity == team_id), team_id)


def _standing_frame(dataset: ExplorerDataset, group: str) -> pd.DataFrame:
    rows = standings_table_rows(dataset, group)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.drop(columns=["ID equipo/temporada"], errors="ignore")
    ordered = [column for column in STANDING_COLUMN_ORDER if column in frame.columns]
    ordered.extend(column for column in frame.columns if column not in ordered)
    return frame[ordered]


def _styled_standings(frame: pd.DataFrame) -> Any:
    def highlight_leader(row: pd.Series) -> list[str]:
        if row.get("Posición") == 1:
            return ["background-color: rgba(134, 239, 172, .12); font-weight: 700"] * len(row)
        return [""] * len(row)

    return frame.style.apply(highlight_leader, axis=1)


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, STATUS_LABELS["unknown"])


def _match_table(dataset: ExplorerDataset, matches: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Fecha": _date_label(match.get("date")),
                "Jornada": match.get("round"),
                "Local": match.get("home_team_name"),
                "Marcador": score_label(match),
                "Visitante": match.get("away_team_name"),
                "Estadio": match.get("stadium_name") or "—",
                "Árbitro": match.get("referee_name") or "—",
                "Estado": _status_label(fixture_status(match, dataset)),
            }
            for match in matches
        ]
    )


def _fixture_card(dataset: ExplorerDataset, match: dict[str, Any]) -> None:
    status = fixture_status(match, dataset)
    home = escape(str(match.get("home_team_name") or "Local por confirmar"))
    away = escape(str(match.get("away_team_name") or "Visitante por confirmar"))
    score = escape(score_label(match))
    line = (
        "<div class='fixture-line'>"
        f"<div class='fixture-team fixture-home'>{home}</div>"
        f"<div class='fixture-score'>{score}</div>"
        f"<div class='fixture-team fixture-away'>{away}</div>"
        "</div>"
    )
    with st.container(border=True):
        st.markdown(line, unsafe_allow_html=True)
        details = [
            _date_label(match.get("date")),
            f"Jornada {match.get('round') or '—'}",
            f"{STATUS_ICONS.get(status, '·')} {_status_label(status)}",
        ]
        if match.get("stadium_name"):
            details.append(str(match["stadium_name"]))
        st.caption(" · ".join(details))


def _dataset_choice() -> ExplorerDataset | None:
    candidates = discover_datasets(DATA_ROOT)
    if not candidates:
        st.warning("Todavía no hay exports disponibles para esta competición.")
        return None
    latest = latest_valid_dataset(candidates)
    selected = st.sidebar.selectbox(
        "Dataset",
        range(len(candidates)),
        index=candidates.index(latest) if latest else 0,
        format_func=lambda index: _capture_label(candidates[index]),
    )
    candidate = candidates[selected]
    if not candidate.valid:
        st.warning("El export elegido está incompleto y no se puede mostrar como preview.")
        return None
    try:
        dataset = load_dataset(candidate.path)
    except DatasetValidationError:
        st.warning("No se pudo leer el export elegido. Prueba con otra captura.")
        return None
    captured = dataset.captured_at_utc
    st.sidebar.caption(
        f"BDFutbol · temporada {dataset.metadata.get('season', '—')}"
        + (f" · actualizado {_date_label(captured[:10])}" if captured else "")
    )
    return dataset


def _hero(dataset: ExplorerDataset, group: str, eyebrow: str = "PREVIEW DE TEMPORADA") -> None:
    competition = next(
        (item.get("name") for item in dataset.competition_groups if item.get("name")),
        "Primera Federación",
    )
    st.markdown(
        f"<div class='sport-kicker'>{escape(eyebrow)} · GRUPO {escape(group)}</div>"
        f"<div class='sport-title'>{escape(str(competition))}</div>"
        f"<div class='sport-subtitle'>Temporada {escape(str(dataset.metadata.get('season', '—')))}</div>",
        unsafe_allow_html=True,
    )


def _dashboard(dataset: ExplorerDataset, group: str) -> None:
    _hero(dataset, group)
    matches = dataset.matches.get(group, [])
    standings = dataset.standings.get(group, [])
    played = sum(fixture_status(match, dataset) == "played" for match in matches)
    results = sum(has_result(match) for match in matches)
    scheduled = sum(fixture_status(match, dataset) == "scheduled" for match in matches)
    round_count = len(
        {match.get("round") for match in matches if isinstance(match.get("round"), int)}
    )
    metrics = st.columns(5)
    metrics[0].metric("Equipos", len(standings))
    metrics[1].metric("Jornadas", round_count)
    metrics[2].metric("Partidos", len(matches))
    metrics[3].metric("Disputados", played)
    metrics[4].metric("Resultados", f"{results} / {len(matches)}")
    st.caption(
        f"Actualizado {_capture_date_label(dataset, group)} · {scheduled} encuentros programados"
    )

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Últimos resultados")
        results_list = recent_results(dataset, group=group, limit=5)
        if results_list:
            for match in results_list:
                _fixture_card(dataset, match)
        else:
            st.info("Aún no hay resultados publicados para este grupo.")
    with right:
        st.subheader("Próximos encuentros")
        fixtures = upcoming_matches(dataset, group=group, limit=5)
        if fixtures:
            for match in fixtures:
                _fixture_card(dataset, match)
        else:
            st.info("No hay próximos encuentros programados en esta captura.")

    st.subheader("Clasificación")
    frame = _standing_frame(dataset, group).head(5)
    if frame.empty:
        st.info("No hay clasificación disponible para este grupo.")
    else:
        st.dataframe(
            _styled_standings(frame),
            hide_index=True,
            width="stretch",
            column_config={"Posición": st.column_config.NumberColumn("Pos.", format="%d")},
        )
        st.caption("Consulta las veinte posiciones en Clasificación.")


def _standings_page(dataset: ExplorerDataset, group: str) -> None:
    _hero(dataset, group, "CLASIFICACIÓN")
    frame = _standing_frame(dataset, group)
    if frame.empty:
        st.info("No hay clasificación disponible para este grupo.")
        return
    st.dataframe(
        _styled_standings(frame),
        hide_index=True,
        width="stretch",
        height=720,
        column_config={"Posición": st.column_config.NumberColumn("Pos.", format="%d")},
    )
    options = _team_options(dataset, group)
    if not options:
        return
    selected_id = st.selectbox(
        "Ver resumen de un equipo",
        [identity for identity, _ in options],
        format_func=lambda value: _team_name(options, value),
        key="standings_team",
    )
    _team_summary(dataset, selected_id)


def _team_summary(dataset: ExplorerDataset, team_id: str) -> None:
    record = team_records(dataset, team_id)
    if record is None:
        st.info("No hay una ficha única para el equipo seleccionado.")
        return
    participant = record["participant"]
    standing = record["standing"]
    st.markdown(f"<div class='team-name'>{escape(str(participant.get('team_name', 'Equipo')))}</div>", unsafe_allow_html=True)
    if not standing:
        st.info("No hay fila de clasificación relacionada.")
        return
    stats = standing.get("stats", {})
    summary = st.columns(5)
    summary[0].metric("Posición", standing.get("position", "—"))
    summary[1].metric("Puntos", stats.get("points", "—"))
    summary[2].metric("PJ", stats.get("played", "—"))
    summary[3].metric("Victorias", stats.get("wins", "—"))
    summary[4].metric("Goles", f"{stats.get('goals_for', '—')} : {stats.get('goals_against', '—')}")
    st.caption(f"Grupo {participant.get('group', '—')} · equipo participante de la temporada")


def _calendar_page(dataset: ExplorerDataset, group: str) -> None:
    _hero(dataset, group, "CALENDARIO Y RESULTADOS")
    rounds = sorted(
        {match.get("round") for match in dataset.matches.get(group, []) if isinstance(match.get("round"), int)}
    )
    round_options: list[int | None] = [None, *rounds]
    selected_round = st.selectbox(
        "Jornada",
        round_options,
        format_func=lambda value: "Todas las jornadas" if value is None else f"Jornada {value}",
    )
    labels = list(STATUS_LABELS)
    selected_statuses = st.multiselect(
        "Estado del partido",
        labels,
        default=labels,
        format_func=_status_label,
    )
    matches = filter_matches(
        dataset,
        group=group,
        round_number=selected_round,
        statuses=set(selected_statuses),
    )
    matches.sort(key=lambda match: (str(match.get("date") or ""), int(match.get("round") or 0)))
    st.caption(f"{len(matches)} encuentros en el calendario del Grupo {group}.")
    if matches:
        st.dataframe(
            _match_table(dataset, matches),
            hide_index=True,
            width="stretch",
            height=650,
        )
        st.subheader("Vista rápida del encuentro")
        labels_by_match = [
            f"J{match.get('round')} · {_date_label(match.get('date'))} · "
            f"{match.get('home_team_name')} {score_label(match)} {match.get('away_team_name')}"
            for match in matches
        ]
        selected_index = st.selectbox("Encuentro", range(len(matches)), format_func=lambda i: labels_by_match[i])
        _match_detail(dataset, matches[selected_index])
    else:
        st.info("No hay partidos que coincidan con esos filtros.")


def _match_detail(dataset: ExplorerDataset, match: dict[str, Any]) -> None:
    group = str(match.get("group", ""))
    _hero(dataset, group, "FICHA DEL PARTIDO")
    status = fixture_status(match, dataset)
    st.caption(
        f"Jornada {match.get('round', '—')} · {_date_label(match.get('date'))} · {_status_label(status)}"
    )
    home, score, away = st.columns([4, 2, 4], vertical_alignment="center")
    home.markdown(f"### {escape(str(match.get('home_team_name') or 'Local por confirmar'))}")
    score.markdown(f"<div class='fixture-score' style='text-align:center'>{escape(score_label(match))}</div>", unsafe_allow_html=True)
    away.markdown(f"### {escape(str(match.get('away_team_name') or 'Visitante por confirmar'))}")
    venue, referee, result_state = st.columns(3)
    venue.metric("Estadio", match.get("stadium_name") or "No publicado")
    referee.metric("Árbitro", match.get("referee_name") or "No publicado")
    result_state.metric("Resultado", _status_label(status))


def _match_page(dataset: ExplorerDataset, group: str) -> None:
    _hero(dataset, group, "PARTIDOS")
    matches = dataset.matches.get(group, [])
    if not matches:
        st.info("No hay partidos disponibles para este grupo.")
        return
    matches = sorted(
        matches,
        key=lambda match: (int(match.get("round") or 0), str(match.get("date") or "")),
    )
    labels = [
        f"J{match.get('round')} · {_date_label(match.get('date'))} · "
        f"{match.get('home_team_name')} {score_label(match)} {match.get('away_team_name')}"
        for match in matches
    ]
    selected = st.selectbox("Encuentro", range(len(matches)), format_func=lambda index: labels[index])
    _match_detail(dataset, matches[selected])


def _team_page(dataset: ExplorerDataset, group: str) -> None:
    _hero(dataset, group, "EQUIPOS")
    options = _team_options(dataset, group)
    if not options:
        st.info("No hay equipos disponibles para este grupo.")
        return
    selected_id = st.selectbox(
        "Equipo",
        [identity for identity, _ in options],
        format_func=lambda value: _team_name(options, value),
        key="team_page_team",
    )
    record = team_records(dataset, selected_id)
    if record is None:
        st.info("No hay una ficha única para el equipo seleccionado.")
        return
    participant = record["participant"]
    standing = record["standing"]
    st.markdown(f"<div class='team-name'>{escape(str(participant.get('team_name', 'Equipo')))}</div>", unsafe_allow_html=True)
    if standing:
        stats = standing.get("stats", {})
        columns = st.columns(6)
        columns[0].metric("Posición", standing.get("position", "—"))
        columns[1].metric("Puntos", stats.get("points", "—"))
        columns[2].metric("PJ", stats.get("played", "—"))
        columns[3].metric("PG", stats.get("wins", "—"))
        columns[4].metric("PE", stats.get("draws", "—"))
        columns[5].metric("PP", stats.get("losses", "—"))
        st.caption(
            f"Goles {stats.get('goals_for', '—')} a favor · "
            f"{stats.get('goals_against', '—')} en contra · Grupo {group}"
        )
    st.subheader("Últimos resultados")
    past = [
        match
        for match in record["matches"]
        if fixture_status(match, dataset) == "played" and has_result(match)
    ]
    past.sort(key=lambda match: str(match.get("date") or ""), reverse=True)
    if past:
        for match in past[:3]:
            _fixture_card(dataset, match)
    else:
        st.info("Aún no hay resultados publicados para este equipo.")
    st.subheader("Próximos partidos")
    next_matches = [
        match for match in record["matches"] if fixture_status(match, dataset) == "scheduled"
    ]
    next_matches.sort(key=lambda match: str(match.get("date") or ""))
    if next_matches:
        for match in next_matches[:3]:
            _fixture_card(dataset, match)
    else:
        st.info("No hay próximos partidos programados para este equipo.")


def _quality_page(dataset: ExplorerDataset) -> None:
    st.title("Calidad y procedencia")
    st.caption(
        f"Temporada {dataset.metadata.get('season', '—')} · "
        f"captura seleccionada: {_date_label((dataset.captured_at_utc or '')[:10])}"
    )
    st.info("Cobertura del calendario, disponibilidad de resultados, consistencia y acceso se evalúan por separado.")
    for group in GROUPS:
        report = group_quality(dataset, group)
        with st.expander(f"Grupo {group}", expanded=True):
            st.markdown("**A · Cobertura estructural**")
            metrics = st.columns(4)
            metrics[0].metric("Equipos", f"{report['teams']} / {report['expected_teams']}")
            metrics[1].metric("Jornadas", f"{report['rounds']} / {report['expected_rounds']}")
            metrics[2].metric("Partidos", f"{report['matches']} / {report['expected_matches']}")
            metrics[3].metric("Calendario estructural", "Completo" if report["structural_complete"] else "Con pendientes")
            st.markdown("**B · Resultados deportivos**")
            result_metrics = st.columns(2)
            result_metrics[0].metric("Resultados disponibles", report["results_available"])
            result_metrics[1].metric("Resultados ausentes", report["results_missing"])
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Estado": _status_label(status), "Encuentros": count}
                        for status, count in sorted(report["states"].items())
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            st.markdown("**C · Calidad y consistencia**")
            consistency = st.columns(5)
            consistency[0].metric("Sin ID publicado", len(report["missing_match_ids"]))
            consistency[1].metric("IDs duplicados", sum(report["duplicate_match_ids"].values()))
            consistency[2].metric("Encuentros duplicados", len(report["duplicate_fixture_keys"]))
            consistency[3].metric("Relaciones de equipo ausentes", len(report["missing_team_relations"]))
            consistency[4].metric(
                "Referencias sin resolver",
                report["reported_unresolved_team_refs"] if report["reported_unresolved_team_refs"] is not None else "—",
            )
            if report["duplicate_match_ids"]:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"ID de partido": match_id, "Repeticiones": count}
                            for match_id, count in report["duplicate_match_ids"].items()
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            if report["duplicate_fixture_keys"]:
                st.dataframe(pd.DataFrame(report["duplicate_fixture_keys"]), hide_index=True, width="stretch")
            if report["missing_match_ids"]:
                rows = [
                    {
                        "Jornada": match.get("round"),
                        "Fecha": _date_label(match.get("date")),
                        "Local": match.get("home_team_name"),
                        "Visitante": match.get("away_team_name"),
                        "Estado": _status_label(fixture_status(match, dataset)),
                    }
                    for match in report["missing_match_ids"]
                ]
                with st.expander(f"Inspeccionar {len(rows)} encuentros sin ID publicado"):
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            checks = report["coverage_checks"]
            if checks:
                st.markdown("**Comprobaciones del parser**")
                st.dataframe(
                    pd.DataFrame(
                        [{"Comprobación": name, "Resultado": "Correcto" if passed else "Revisar"} for name, passed in checks.items()]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            diagnostics = [row for row in diagnostic_rows(dataset) if row.get("group") == group]
            if diagnostics or report["parser_diagnostics"]:
                st.markdown("**Incidencias y advertencias**")
                if diagnostics:
                    st.dataframe(pd.DataFrame(diagnostics), hide_index=True, width="stretch")
                if report["parser_diagnostics"]:
                    st.dataframe(pd.DataFrame(report["parser_diagnostics"]), hide_index=True, width="stretch")
            else:
                st.success("Sin incidencias registradas por las comprobaciones actuales.")
            st.markdown("**D · Validez de adquisición**")
            acquisition = st.columns(3)
            acquisition[0].metric("Acceso", report["access_status"] or "—")
            acquisition[1].metric("Respuesta HTTP", report["http_status"] or "—")
            acquisition[2].metric("Capturado", _date_label((report["captured_at_utc"] or "")[:10]))
            with st.expander("Procedencia detallada del snapshot"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Dato de procedencia": "URL solicitada", "Valor": report["requested_url"]},
                            {"Dato de procedencia": "URL final", "Valor": report["final_url"]},
                            {"Dato de procedencia": "SHA-256", "Valor": report["snapshot_sha256"]},
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )


def _player_export_choice() -> PlayerExplorerDataset | None:
    candidates = discover_player_exports(PLAYER_DATA_ROOT)
    valid = [candidate for candidate in candidates if candidate.valid]
    if not valid:
        st.warning("No hay exports de jugadores compatibles y válidos en el repositorio.")
        invalid = [candidate for candidate in candidates if not candidate.valid]
        if invalid:
            with st.expander(f"Versiones no compatibles ({len(invalid)})"):
                st.dataframe(
                    pd.DataFrame([
                        {"Export": item.path.name, "Motivo": "; ".join(item.errors)}
                        for item in invalid
                    ]),
                    hide_index=True,
                    width="stretch",
                )
        return None
    latest = latest_valid_player_export(valid)
    selected_index = st.sidebar.selectbox(
        "Export de jugadores",
        range(len(valid)),
        index=valid.index(latest) if latest else 0,
        format_func=lambda index: valid[index].label,
        key="player_export_selection",
    )
    candidate = valid[selected_index]
    if len(valid) > 1:
        st.sidebar.caption(f"{len(valid)} exports válidos; se muestran también versiones anteriores.")
    try:
        return load_player_export(candidate.path)
    except DatasetValidationError as exc:
        st.error(f"No se pudo cargar este export de jugadores: {exc}")
        return None


def _player_view_coverage(dataset: PlayerExplorerDataset, player_id: str, view: str) -> dict[str, Any]:
    return dataset.coverage_for(player_id, view) or {}


def _player_view_is_parsed(dataset: PlayerExplorerDataset, player_id: str, view: str) -> bool:
    status = _player_view_coverage(dataset, player_id, view)
    return status.get("coverage_status") == "CAPTURED_AND_PARSED" and status.get("parse_status") == "PARSED"


def _player_view_label(dataset: PlayerExplorerDataset, player_id: str, view: str) -> str:
    labels = {"profile": "Perfil", "statistics": "Estadísticas", "matches": "Partidos", "rivals": "Rivales"}
    return f"✓ {labels[view]}" if _player_view_is_parsed(dataset, player_id, view) else f"◷ {labels[view]}"


def _column_header(column: dict[str, Any], index: int) -> str:
    return str(
        column.get("header_title_raw")
        or column.get("header_original")
        or column.get("data_colid_raw")
        or f"Col. {index + 1}"
    )


def _unique_headers(headers: list[str]) -> list[str]:
    counts: Counter[str] = Counter()
    unique: list[str] = []
    for header in headers:
        counts[header] += 1
        unique.append(header if counts[header] == 1 else f"{header} ({counts[header]})")
    return unique


def _raw_rows_frame(
    rows: list[dict[str, Any]],
    *,
    metadata_fields: list[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    width = max((len(row.get("columns", [])) for row in rows), default=0)
    labels: list[str] = []
    for index in range(width):
        label = next((
            _column_header(columns[index], index)
            for row in rows
            if len(columns := row.get("columns", [])) > index
            and (_column_header(columns[index], index) != f"Col. {index + 1}")
        ), f"Col. {index + 1}")
        labels.append(label)
    labels = _unique_headers(labels)
    prefix = metadata_fields or []
    output: list[dict[str, Any]] = []
    for row in rows:
        item = {label: row.get(key) for label, key in prefix}
        cells = row.get("columns", [])
        for index, label in enumerate(labels):
            item[label] = cells[index].get("raw_value") if index < len(cells) else None
        output.append(item)
    return pd.DataFrame(output)


def _raw_cell_details(columns: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Columna original": _column_header(column, index),
            "Valor raw": column.get("raw_value"),
            "Estado de valor": column.get("value_status"),
            "Oculta en origen": column.get("hidden_by_inline_style"),
            "Opcional responsive": column.get("responsive_optional"),
            "Enlaces raw": json.dumps(column.get("links", []), ensure_ascii=False),
        }
        for index, column in enumerate(columns)
    ])


def _raw_detail_selector(rows: list[dict[str, Any]], *, key: str) -> None:
    if not rows:
        return
    labels = [
        f"{row.get('season_raw') or _raw_cell_value(row, {'temp', 'temporada'}) or row.get('metric_label_raw') or row.get('rival_name_raw') or 'Fila'}"
        f" · fila {row.get('source_row_index', row.get('source_record_index', index))}"
        for index, row in enumerate(rows)
    ]
    selected = st.selectbox(
        "Inspeccionar una fila conservada",
        range(len(rows)),
        format_func=lambda index: labels[index],
        key=key,
    )
    columns = rows[selected].get("columns", [])
    if columns:
        st.dataframe(_raw_cell_details(columns), hide_index=True, width="stretch")
    else:
        st.json(rows[selected])


def _raw_cell_value(row: dict[str, Any], names: set[str]) -> str | None:
    for index, column in enumerate(row.get("columns", [])):
        label = _column_header(column, index).strip().casefold()
        if label in names:
            raw = column.get("raw_value")
            return str(raw) if raw is not None else None
    return None


def _player_membership_frame(player: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Equipo": membership.get("team_name"),
            "Grupo": membership.get("group"),
            "Temporada/equipo ID": membership.get("team_season_id"),
            "Apariciones raw plantilla": membership.get("appearances_raw"),
            "Demarcación raw": membership.get("position_raw"),
            "Dorsal raw": membership.get("shirt_number_raw"),
        }
        for membership in player.get("team_memberships", [])
    ])


def _career_status_label(value: Any) -> str:
    labels = {
        "NOT_CERTIFIED_COMPLETE": "No certificada",
        "NOT_ASSESSED_NO_PLAYER_HISTORY_ACQUISITION": "Sin evaluar",
    }
    return labels.get(str(value), "No evaluada" if not value else str(value))


def _player_coverage_panel(dataset: PlayerExplorerDataset, player_id: str) -> None:
    views = ("profile", "statistics", "matches", "rivals")
    rows = []
    for view in views:
        coverage = _player_view_coverage(dataset, player_id, view)
        snapshot_status = coverage.get("snapshot_status", "NOT_AVAILABLE")
        parsed = _player_view_is_parsed(dataset, player_id, view)
        if parsed:
            state = "Capturada y parseada"
        elif snapshot_status in {"PENDING_CAPTURE", "PENDING_SNAPSHOT", "NOT_CAPTURED"}:
            state = "Pendiente de adquisición"
        else:
            state = str(snapshot_status)
        rows.append({
            "Vista": {"profile": "Perfil", "statistics": "Estadísticas", "matches": "Partidos", "rivals": "Rivales"}[view],
            "Estado": state,
            "Snapshot": coverage.get("snapshot_status", "—"),
            "Parser": coverage.get("parse_status", "—"),
            "Campos normalizados": ", ".join(coverage.get("fields_normalized", [])) or "—",
            "Campos solo raw": ", ".join(
                field for field in coverage.get("fields_preserved_raw", [])
                if field not in coverage.get("fields_normalized", [])
            ) or "—",
            "Campos ausentes en snapshot": ", ".join(coverage.get("fields_not_found_in_snapshot", [])) or "—",
            "Hash": coverage.get("selected_snapshot_sha256") or "—",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _player_profile_tab(dataset: PlayerExplorerDataset, player: dict[str, Any], player_id: str) -> None:
    profile = dataset.profile(player_id)
    if profile is None:
        st.info("La ficha individual está pendiente de adquisición. Aquí solo se muestran datos reales de plantilla.")
    else:
        st.caption(f"Título de origen: {profile.get('page_title_raw') or '—'} · ID {player_id}")
        st.markdown(f"**{profile.get('position_raw') or 'Demarcación no publicada'}**")
        metrics = st.columns(3)
        metrics[0].metric("Edad mostrada", profile.get("age_as_displayed_years") if profile.get("age_as_displayed_years") is not None else "No publicada")
        metrics[1].metric("Altura", profile.get("height_raw") or "No publicada")
        metrics[2].metric("Peso", profile.get("weight_raw") or "No publicado")
        st.caption(f"Nombre completo raw: {profile.get('full_name_raw') or 'No publicado'}")
        coverage = _player_view_coverage(dataset, player_id, "profile")
        normalized = set(coverage.get("fields_normalized", []))
        preserved_raw = set(coverage.get("fields_preserved_raw", []))
        field_status = profile.get("personal_field_status", {})
        field_rows = []
        for field, value in profile.get("personal_fields", {}).items():
            raw_value = value.get("raw_value") if isinstance(value, dict) else None
            parser_state = field_status.get(field, "")
            if "NOT_FOUND" in parser_state or (value is None and not raw_value):
                status = "Campo ausente en snapshot"
            elif field in normalized and field in preserved_raw:
                status = "Raw conservado e interpretado"
            elif field in preserved_raw:
                status = "Solo raw; interpretación pendiente"
            elif raw_value:
                status = "Raw conservado; estado semántico no clasificado"
            else:
                status = "Sin valor raw en el snapshot"
            field_rows.append({"Campo": field, "Valor raw": "" if raw_value is None else raw_value, "Estado": status})
        st.subheader("Datos personales disponibles")
        st.dataframe(pd.DataFrame(field_rows), hide_index=True, width="stretch")
        st.caption(
            f"Completitud histórica: {_career_status_label(profile.get('career_completeness'))}. "
            "La existencia de una ficha no certifica que se hayan adquirido todos los años de carrera."
        )

        photos = profile.get("photo_references", [])
        if photos:
            st.subheader("Referencias de fotografías")
            st.caption("Son referencias encontradas en el export. La aplicación no descarga ni muestra imágenes.")
            st.dataframe(pd.DataFrame([
                {"URL raw": image.get("url"), "Texto alternativo raw": image.get("alt_raw"), "Descargada": image.get("downloaded", False)}
                for image in photos
            ]), hide_index=True, width="stretch")

    st.subheader("Pertenencias de plantilla")
    memberships = _player_membership_frame(player)
    if memberships.empty:
        st.info("No hay pertenencias de plantilla en este export.")
    else:
        st.dataframe(memberships, hide_index=True, width="stretch")


def _player_trajectory_tab(dataset: PlayerExplorerDataset, player_id: str) -> None:
    if not _player_view_is_parsed(dataset, player_id, "profile"):
        st.info("La trayectoria no está disponible porque el perfil está pendiente de adquisición.")
        return
    profile = dataset.profile(player_id) or {}
    rows = profile.get("career_rows", [])
    if not rows:
        st.info("El perfil se capturó, pero no contiene filas de trayectoria interpretadas.")
        return
    extracted = []
    for row in rows:
        extracted.append({
            "Temporada raw": row.get("season_raw") or _raw_cell_value(row, {"temp", "temporada"}),
            "Equipo raw": row.get("team_name_raw") or _raw_cell_value(row, {"equipo", "equip"}),
            "División raw": row.get("division_raw") or _raw_cell_value(row, {"div", "división", "division"}),
            "Edad raw": row.get("age_raw") or _raw_cell_value(row, {"edad"}),
        })
    season_counts = Counter(row.get("Temporada raw") for row in extracted if row.get("Temporada raw"))
    multi_rows = [
        {"Temporada raw": season, "Filas de trayectoria": count}
        for season, count in season_counts.items() if count > 1
    ]
    st.caption(f"{len(rows)} filas del perfil; se conserva la tabla de origen completa. Completitud: {profile.get('career_completeness', 'no evaluada')}.")
    if multi_rows:
        st.info("Hay varias filas fuente para una o más temporadas; no se interpretan automáticamente como traspasos.")
        st.dataframe(pd.DataFrame(multi_rows), hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame(extracted), hide_index=True, width="stretch")
    st.subheader("Columnas originales y valores raw")
    st.dataframe(_raw_rows_frame(rows), hide_index=True, width="stretch", height=460)
    with st.expander("Inspeccionar estado, visibilidad y enlaces de una fila"):
        _raw_detail_selector(rows, key=f"trajectory_raw_{player_id}")
    totals = profile.get("career_totals_raw", [])
    if totals:
        with st.expander("Totales raw de la trayectoria"):
            st.json(totals)


def _player_statistics_tab(dataset: PlayerExplorerDataset, player_id: str) -> None:
    if not _player_view_is_parsed(dataset, player_id, "statistics"):
        st.info("La vista de estadísticas está pendiente de adquisición; no se muestran cifras inferidas.")
        return
    rows = dataset.records_for("statistics", player_id)
    if not rows:
        st.info("La vista se capturó y parseó, pero el export no contiene filas estadísticas.")
        return
    roles = sorted({str(row.get("table_role") or "sin_tipo") for row in rows})
    role_labels = {
        "statistics_by_competition": "Por competición",
        "statistics_by_team": "Por equipo",
        "milestone_matches": "Hitos deportivos",
    }
    role_filter = st.selectbox(
        "Sección estadística",
        ["Todas", *roles],
        format_func=lambda value: "Todas las secciones" if value == "Todas" else role_labels.get(value, value),
        key=f"statistics_role_{player_id}",
    )
    selected_rows = rows if role_filter == "Todas" else [row for row in rows if row.get("table_role") == role_filter]
    st.caption("Se conservan las celdas originales, incluidos ceros, guiones, columnas ocultas y códigos sin interpretar.")
    for role in roles if role_filter == "Todas" else [role_filter]:
        section = [row for row in selected_rows if str(row.get("table_role") or "sin_tipo") == role]
        with st.expander(f"{role_labels.get(role, role)} · {len(section)} filas", expanded=True):
            frame = _raw_rows_frame(
                section,
                metadata_fields=[("Métrica raw", "metric_label_raw"), ("Tabla de origen", "table_id")],
            )
            st.dataframe(frame, hide_index=True, width="stretch", height=min(520, 45 + 34 * min(len(frame), 14)))
            with st.expander("Inspeccionar celdas raw de una fila"):
                _raw_detail_selector(section, key=f"statistics_raw_{player_id}_{role}")


def _player_matches_tab(dataset: PlayerExplorerDataset, player_id: str) -> None:
    if not _player_view_is_parsed(dataset, player_id, "matches"):
        st.info("La vista de partidos está pendiente de adquisición; no se generan encuentros a partir de agregados.")
        return
    source_rows = dataset.records_for("individual_matches", player_id)
    counts = player_match_counts(source_rows)
    metrics = st.columns(4)
    metrics[0].metric("Filas fuente", counts["source_records"])
    metrics[1].metric("IDs de encuentro únicos", counts["unique_match_ids"])
    metrics[2].metric("IDs con flag de participación", counts["unique_match_ids_with_appearance_flag"])
    metrics[3].metric("Filas duplicadas por ID", counts["duplicate_source_rows"])
    st.caption(
        f"Flags en registros fuente: {counts['appearance_flag_records']} filas con participación, "
        f"{counts['non_appearance_flag_records']} sin participación y "
        f"{counts['unknown_appearance_flag_records']} sin flag interpretado. "
        "Los contadores no se suman para inferir apariciones; cada fila conservada aparece abajo."
    )
    repeated = counts["duplicate_match_ids"]
    if repeated:
        st.info("El origen repite algunos IDs. Se conservan todas las filas y solo se cuentan una vez en IDs únicos.")
        st.dataframe(pd.DataFrame([
            {"ID de encuentro": match_id, "Filas fuente": count}
            for match_id, count in sorted(repeated.items())
        ]), hide_index=True, width="stretch")
    if not source_rows:
        st.info("La vista está disponible, pero no hay registros individuales de encuentros en el export.")
        return

    seasons = sorted({str(row.get("season_raw")) for row in source_rows if row.get("season_raw")})
    teams = sorted({str(row.get("player_team_raw")) for row in source_rows if row.get("player_team_raw")})
    competitions = sorted({str(row.get("competition_raw")) for row in source_rows if row.get("competition_raw")})
    season_col, team_col, competition_col = st.columns(3)
    season_filter = season_col.selectbox("Temporada", ["Todas", *seasons], key=f"match_season_{player_id}")
    team_filter = team_col.selectbox("Equipo", ["Todos", *teams], key=f"match_team_{player_id}")
    competition_filter = competition_col.selectbox("Competición (código raw)", ["Todas", *competitions], key=f"match_comp_{player_id}")
    matches = filter_player_matches(
        source_rows,
        season=None if season_filter == "Todas" else season_filter,
        team=None if team_filter == "Todos" else team_filter,
        competition=None if competition_filter == "Todas" else competition_filter,
    )
    duplicate_counts = Counter(
        str(row.get("match_id"))
        for row in source_rows
        if row.get("match_id") not in (None, "")
    )
    frame_rows = []
    for row in matches:
        match_id = str(row.get("match_id") or "")
        status = row.get("player_appearance_status")
        if status == "APPEARED_PER_SOURCE_FLAGS":
            appearance = "Participación según flags de origen"
        elif status == "NO_APPEARANCE_PER_SOURCE_FLAGS":
            appearance = "Sin participación según flags de origen"
        else:
            appearance = f"Sin clasificar · {status or 'sin estado'}"
        metrics_raw = row.get("player_match_metrics_raw")
        frame_rows.append({
            "ID encuentro": match_id or "—",
            "Fecha raw": row.get("date_raw") or row.get("date"),
            "Temporada raw": row.get("season_raw"),
            "Competición raw": row.get("competition_raw"),
            "Jornada raw": row.get("round_title_raw") or row.get("round_raw"),
            "Local raw": row.get("home_team_raw"),
            "Resultado raw": row.get("result_raw"),
            "Visitante raw": row.get("away_team_raw"),
            "Equipo jugador raw": row.get("player_team_raw"),
            "Rival raw": row.get("opponent_team_raw"),
            "Participación fuente": appearance,
            "Minutos raw (código min)": metrics_raw.get("min") if isinstance(metrics_raw, dict) else None,
            "URL de origen": row.get("match_url"),
            "Repeticiones de este ID": duplicate_counts.get(match_id, 0) if match_id else 0,
        })
    st.caption(f"{len(matches)} filas de fuente con estos filtros; no se deduplican en la tabla.")
    st.dataframe(pd.DataFrame(frame_rows), hide_index=True, width="stretch", height=560)
    with st.expander("Estadísticas y tupla raw de una fila"):
        _raw_detail_selector(matches, key=f"matches_raw_{player_id}")
    summaries = dataset.records_for("matches", player_id)
    if summaries:
        with st.expander("Agregados de partidos por dimensión (no son filas de encuentros)"):
            summary_roles = sorted({str(row.get("summary_dimension")) for row in summaries})
            chosen_role = st.selectbox(
                "Dimensión agregada",
                summary_roles,
                key=f"match_summary_role_{player_id}",
            )
            subset = [row for row in summaries if str(row.get("summary_dimension")) == chosen_role]
            st.dataframe(
                _raw_rows_frame(subset, metadata_fields=[("Dimensión", "summary_dimension"), ("Valor raw", "dimension_value_raw")]),
                hide_index=True,
                width="stretch",
            )


def _player_rivals_tab(dataset: PlayerExplorerDataset, player_id: str) -> None:
    if not _player_view_is_parsed(dataset, player_id, "rivals"):
        st.info("La vista de rivales está pendiente de adquisición; no se muestran relaciones inferidas.")
        return
    rows = dataset.records_for("rivals", player_id)
    if not rows:
        st.info("La vista se capturó y parseó, pero no hay registros de rivales en el export.")
        return
    counts = Counter(str(row.get("rival_kind") or "sin_tipo") for row in rows)
    columns = st.columns(max(1, len(counts)))
    for column, (kind, count) in zip(columns, sorted(counts.items())):
        column.metric({"player": "Jugadores", "coach": "Entrenadores", "club": "Clubes/equipos"}.get(kind, kind), count)
    kinds = sorted(counts)
    kind_filter = st.selectbox(
        "Tipo de rival",
        ["Todos", *kinds],
        format_func=lambda value: "Todos" if value == "Todos" else {"player": "Jugador", "coach": "Entrenador", "club": "Club/equipo"}.get(value, value),
        key=f"rival_kind_{player_id}",
    )
    query = st.text_input("Buscar rival", key=f"rival_search_{player_id}").strip().casefold()
    kind_rows = [
        row for row in rows
        if (kind_filter == "Todos" or row.get("rival_kind") == kind_filter)
    ]
    if query:
        indexed_rows = [
            {"row_index": index, "name": row.get("rival_name_raw"), "id": row.get("rival_id")}
            for index, row in enumerate(kind_rows)
        ]
        matching_indices = {
            item["row_index"] for item in search_records(indexed_rows, query=query)
        }
        selected_rows = [row for index, row in enumerate(kind_rows) if index in matching_indices]
    else:
        selected_rows = kind_rows
    page_size = st.number_input("Filas por página", min_value=50, max_value=1000, value=200, step=50, key=f"rival_page_size_{player_id}")
    pages = max(1, (len(selected_rows) + int(page_size) - 1) // int(page_size))
    page_number = st.number_input(
        "Página",
        min_value=1,
        max_value=pages,
        value=1,
        step=1,
        key=f"rival_page_{player_id}_{kind_filter}_{query}_{int(page_size)}",
    )
    offset = (int(page_number) - 1) * int(page_size)
    page_rows = selected_rows[offset : offset + int(page_size)]
    st.caption(f"{len(selected_rows)} relaciones en el filtro · mostrando {offset + 1 if page_rows else 0}–{offset + len(page_rows)}; filas de fuente preservadas.")
    st.dataframe(pd.DataFrame([
        {
            "Tipo": row.get("rival_kind"),
            "Rival raw": row.get("rival_name_raw"),
            "ID de entidad": row.get("rival_id"),
            "Fila fuente": row.get("source_row_index"),
            "ID duplicado de fila": row.get("row_duplicate_of"),
            "URL de origen": row.get("rival_url"),
        }
        for row in page_rows
    ]), hide_index=True, width="stretch", height=560)
    with st.expander("Inspeccionar columnas raw de una relación"):
        _raw_detail_selector(page_rows, key=f"rivals_raw_{player_id}")


def _players_page(dataset: PlayerExplorerDataset) -> None:
    summary = dataset.arrays["summary"][0] if dataset.arrays["summary"] else {}
    st.markdown("<div class='sport-kicker'>FICHAS INDIVIDUALES · SOLO EXPORTS LOCALES</div>", unsafe_allow_html=True)
    st.title("Jugadores")
    st.caption("Inventario de plantilla y vistas individuales capturadas. No se realizan peticiones a BDFutbol.")
    metrics = st.columns(4)
    metrics[0].metric("Plantilla", summary.get("player_count", len(dataset.players)))
    metrics[1].metric("Fichas individuales", summary.get("parsed_player_count", len(dataset.arrays["profiles"])))
    metrics[2].metric("4 vistas completas", summary.get("players_with_all_four_views", "—"))
    metrics[3].metric("Filas de partidos", summary.get("match_fixture_rows_parsed", len(dataset.arrays["individual_matches"])))
    newest_capture = player_export_captured_at(dataset.metadata)
    st.caption(
        f"Parser {dataset.metadata.get('parser_version', '—')} · esquema {dataset.metadata.get('schema_version', '—')} · "
        f"vistas válidas {summary.get('player_views_captured', len(dataset.metadata.get('source_page_snapshots', [])))} · "
        f"actualización de fuentes {newest_capture or 'no disponible'}"
    )

    search = st.text_input("Buscar por nombre raw o ID de BDFutbol", key="player_search").strip()
    profiles = {str(record.get("player_id")): record for record in dataset.arrays["profiles"]}
    players = sorted(
        dataset.players,
        key=lambda item: (
            profiles.get(str(item.get("player_id"))) is None,
            player_search_label(item, profiles.get(str(item.get("player_id")))).casefold(),
        ),
    )
    if search:
        search_labels = [
            {"player_id": player.get("player_id"), "label": player_search_label(
                player, profiles.get(str(player.get("player_id")))
            )}
            for player in players
        ]
        found_ids = {item["player_id"] for item in search_records(search_labels, query=search)}
        players = [
            player for player in players
            if player.get("player_id") in found_ids
            or search.casefold() in str(player.get("player_id", "")).casefold()
        ]
    if not players:
        st.info("No se encontraron jugadores en este export.")
        return
    player_ids = [str(player.get("player_id")) for player in players]
    selected_id = st.selectbox(
        "Seleccionar futbolista",
        player_ids,
        format_func=lambda player_id: (
            f"{player_search_label(dataset.player(player_id) or {}, profiles.get(player_id))} · "
            f"{'ficha individual' if profiles.get(player_id) else 'solo plantilla'}"
        ),
        key="player_selected_id",
    )
    player = dataset.player(selected_id)
    if player is None:
        st.error("El jugador elegido no está en el inventario del export.")
        return
    profile = profiles.get(selected_id)
    captured_views = len(player.get("views_with_snapshot", []))
    memberships = player.get("team_memberships", [])
    st.markdown(f"### {escape(player_search_label(player, profile))}")
    left, middle, right = st.columns(3)
    left.metric("Cobertura de vistas", f"{captured_views} / {len(player.get('views_required', ['profile', 'statistics', 'matches', 'rivals']))}")
    middle.metric("Pertenencias de plantilla", len(memberships))
    right.metric("Carrera histórica", _career_status_label(profile.get("career_completeness")) if profile else "No adquirida")
    with st.expander("Estado de las cuatro vistas y campos", expanded=False):
        _player_coverage_panel(dataset, selected_id)

    tabs = st.tabs([
        _player_view_label(dataset, selected_id, "profile"),
        "Trayectoria",
        _player_view_label(dataset, selected_id, "statistics"),
        _player_view_label(dataset, selected_id, "matches"),
        _player_view_label(dataset, selected_id, "rivals"),
    ])
    with tabs[0]:
        _player_profile_tab(dataset, player, selected_id)
    with tabs[1]:
        _player_trajectory_tab(dataset, selected_id)
    with tabs[2]:
        _player_statistics_tab(dataset, selected_id)
    with tabs[3]:
        _player_matches_tab(dataset, selected_id)
    with tabs[4]:
        _player_rivals_tab(dataset, selected_id)


def main() -> None:
    _inject_styles()
    st.sidebar.markdown("## ⚽ FootballDataHub")
    st.sidebar.caption("PREVIEW DE TEMPORADA · 2026/27")
    page = st.sidebar.radio(
        "Navegación",
        ["Inicio", "Clasificación", "Calendario", "Equipos", "Partidos", "Jugadores"],
    )
    if page == "Jugadores":
        player_dataset = _player_export_choice()
        if player_dataset is not None:
            _players_page(player_dataset)
        return
    dataset = _dataset_choice()
    if dataset is None:
        return
    group = st.sidebar.radio(
        "Grupo",
        GROUPS,
        format_func=lambda value: f"Grupo {value}",
        horizontal=True,
    )
    st.sidebar.divider()
    if st.session_state.get("show_quality", False):
        if st.sidebar.button("← Volver a la preview", width="stretch"):
            st.session_state.show_quality = False
            st.rerun()
        _quality_page(dataset)
        return
    st.sidebar.caption("DATOS Y VALIDACIÓN")
    if st.sidebar.button("Calidad y procedencia", width="stretch"):
        st.session_state.show_quality = True
        st.rerun()
    if page == "Inicio":
        _dashboard(dataset, group)
    elif page == "Clasificación":
        _standings_page(dataset, group)
    elif page == "Calendario":
        _calendar_page(dataset, group)
    elif page == "Equipos":
        _team_page(dataset, group)
    else:
        _match_page(dataset, group)


if __name__ == "__main__":
    main()
