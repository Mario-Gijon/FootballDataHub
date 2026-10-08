"""Preview deportiva local de los exports parsed de FootballDataHub."""

from __future__ import annotations

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
    diagnostic_rows,
    discover_datasets,
    filter_matches,
    fixture_status,
    group_quality,
    has_result,
    latest_valid_dataset,
    load_dataset,
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


def main() -> None:
    _inject_styles()
    st.sidebar.markdown("## ⚽ FootballDataHub")
    st.sidebar.caption("PREVIEW DE TEMPORADA · 2026/27")
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
    page = st.sidebar.radio(
        "Navegación",
        ["Inicio", "Clasificación", "Calendario", "Equipos", "Partidos"],
    )
    st.sidebar.divider()
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
