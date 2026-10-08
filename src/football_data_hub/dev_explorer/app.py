"""Interfaz local de solo lectura para explorar exports parsed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from football_data_hub.dev_explorer.data import (
    FIXTURE_STATES,
    GROUPS,
    DatasetValidationError,
    diagnostic_rows,
    discover_datasets,
    filter_matches,
    fixture_status,
    flatten_record,
    group_quality,
    has_result,
    latest_valid_dataset,
    load_dataset,
    null_counts,
    score_label,
    search_records,
    standings_table_rows,
    team_records,
)


DATA_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "parsed"
    / "bdfutbol"
    / "primera_federacion_2026_27"
)

st.set_page_config(page_title="FootballDataHub · Dev Explorer", layout="wide")


def _team_options(dataset: Any, group: str) -> list[tuple[str, str]]:
    teams = [team for team in dataset.participants if team.get("group") == group]
    return sorted(
        [(str(team.get("team_season_id", "")), str(team.get("team_name", "(sin nombre)"))) for team in teams],
        key=lambda item: item[1].casefold(),
    )


def _team_label(options: list[tuple[str, str]], team_id: str) -> str:
    return next((name for identity, name in options if identity == team_id), team_id)


def _competition_for_group(dataset: Any, group: str) -> dict[str, Any]:
    return next(
        (item for item in dataset.competition_groups if item.get("group") == group),
        {},
    )


def _matches_table(matches: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for match in matches:
        rows.append(
            {
                "Grupo": match.get("group"),
                "Jornada": match.get("round"),
                "Fecha": match.get("date"),
                "Local": match.get("home_team_name"),
                "Resultado": match.get("_display_score", score_label(match)),
                "Visitante": match.get("away_team_name"),
                "Estadio": match.get("stadium_name"),
                "Árbitro": match.get("referee_name"),
                "Estado": match.get("_display_fixture_status", fixture_status(match, st.session_state.dataset)),
                "ID partido": match.get("match_id"),
            }
        )
    return pd.DataFrame(rows)


def _show_selected_match(dataset: Any, matches: list[dict[str, Any]]) -> None:
    if not matches:
        st.info("No hay partidos para mostrar.")
        return
    labels = [
        f"G{match.get('group')} · J{match.get('round')} · {match.get('date') or 'sin fecha'} · "
        f"{match.get('home_team_name')} {score_label(match)} {match.get('away_team_name')} · {match.get('match_id') or 'sin ID'}"
        for match in matches
    ]
    index = st.selectbox("Partido", range(len(matches)), format_func=lambda value: labels[value])
    match = matches[index]
    col1, col2, col3 = st.columns(3)
    col1.metric("Estado", fixture_status(match, dataset))
    col2.metric("Resultado", score_label(match))
    col3.metric("ID de partido", match.get("match_id") or "No publicado")
    group = str(match.get("group", ""))
    competition = _competition_for_group(dataset, group)
    st.caption(
        f"{competition.get('name', 'Competición no identificada')} · "
        f"Temporada {dataset.metadata.get('season', 'no indicada')} · Grupo {group} · "
        f"Jornada {match.get('round')} · Fecha {match.get('date') or 'sin fecha'}"
    )
    st.write(
        {
            "result_status": match.get("result_status"),
            "home_team_season_id": match.get("home_team_season_id"),
            "away_team_season_id": match.get("away_team_season_id"),
            "stadium_id": match.get("stadium_id"),
            "referee_id": match.get("referee_id"),
            "date_raw": match.get("date_raw"),
            "result_raw": match.get("result_raw"),
            "match_url": match.get("match_url"),
            "home_team_season_url": match.get("home_team_season_url"),
            "away_team_season_url": match.get("away_team_season_url"),
            "stadium_url": match.get("stadium_url"),
            "referee_url": match.get("referee_url"),
        }
    )
    if match.get("match_url"):
        st.link_button("Abrir fuente BDFutbol", match["match_url"])
    st.json(match, expanded=True)


def _show_dataset_choice() -> Any | None:
    candidates = discover_datasets(DATA_ROOT)
    if not candidates:
        st.error(f"No se encontraron directorios de dataset en `{DATA_ROOT}`.")
        return None
    latest = latest_valid_dataset(candidates)
    options = [candidate.label for candidate in candidates]
    default_index = candidates.index(latest) if latest else 0
    selected_index = st.sidebar.selectbox(
        "Dataset parsed",
        range(len(candidates)),
        index=default_index,
        format_func=lambda value: options[value],
    )
    selected = candidates[selected_index]
    if not selected.valid:
        st.error(f"El dataset `{selected.path.name}` no es legible como export compatible.")
        for error in selected.errors:
            st.write(f"- {error}")
        return None
    try:
        dataset = load_dataset(selected.path)
    except DatasetValidationError as exc:
        st.error(f"No se pudo cargar el dataset: {exc}")
        return None
    st.sidebar.caption(f"Ruta: `{dataset.path}`")
    st.sidebar.caption(f"Parser: {dataset.metadata.get('parser_version')} · esquema: {dataset.metadata.get('schema_version')}")
    return dataset


def _summary(dataset: Any) -> None:
    st.title("FootballDataHub · Dev Explorer")
    competition_names = sorted(
        {str(item.get("name")) for item in dataset.competition_groups if item.get("name")}
    )
    available_groups = sorted(
        {str(item.get("group")) for item in dataset.competition_groups if item.get("group")}
    )
    competition_label = ", ".join(competition_names) or "Competición no identificada"
    season = dataset.metadata.get("season", "temporada no indicada")
    st.caption(
        f"{competition_label} · Temporada {season} · Grupos {', '.join(available_groups) or 'no identificados'} · "
        "exploración local y de solo lectura"
    )
    totals = {
        state: sum(
            fixture_status(match, dataset) == state
            for group in GROUPS
            for match in dataset.matches.get(group, [])
        )
        for state in FIXTURE_STATES
    }
    results = sum(has_result(match) for group in GROUPS for match in dataset.matches.get(group, []))
    rounds_by_group = {
        group: len(
            {
                match.get("round")
                for match in dataset.matches.get(group, [])
                if isinstance(match.get("round"), int)
            }
        )
        for group in GROUPS
    }
    columns = st.columns(5)
    columns[0].metric("Equipos", len(dataset.participants))
    columns[1].metric("Grupos", ", ".join(available_groups) or "—")
    columns[2].metric(
        "Jornadas",
        f"I: {rounds_by_group['I']} · II: {rounds_by_group['II']}",
    )
    columns[3].metric("Partidos", sum(len(dataset.matches[group]) for group in GROUPS))
    columns[4].metric("Captura más reciente (UTC)", dataset.captured_at_utc or "No indicada")
    status_columns = st.columns(6)
    status_columns[0].metric("Disputados", totals["played"])
    status_columns[1].metric("Programados", totals["scheduled"])
    status_columns[2].metric("Sin resolver", totals["unresolved"])
    status_columns[3].metric("Sin confirmar / estado desconocido", totals["unconfirmed"] + totals["unknown"])
    status_columns[4].metric("Resultados disponibles", results)
    status_columns[5].metric("Resultados ausentes", sum(len(dataset.matches[group]) for group in GROUPS) - results)
    st.info(
        "La cobertura estructural (equipos, jornadas y filas de calendario) y la disponibilidad de resultados "
        "son medidas distintas. Una temporada en curso puede tener el calendario completo con muchos resultados aún ausentes."
    )
    st.subheader("Procedencia del dataset")
    st.write(
        {
            "extracción": dataset.metadata.get("extraction_key"),
            "parser": dataset.metadata.get("parser_version"),
            "esquema": dataset.metadata.get("schema_version"),
            "temporada": dataset.metadata.get("season"),
            "captura más reciente (UTC)": dataset.captured_at_utc,
            "directorio": dataset.path.name,
        }
    )
    cols = st.columns(2)
    for column, group in zip(cols, GROUPS, strict=True):
        source = dataset.capture_for_group(group)
        with column:
            st.markdown(f"**Grupo {group} · captura de origen**")
            st.write(
                {
                    "estado de acceso": source.get("access_status"),
                    "HTTP": source.get("http_status"),
                    "captura": source.get("captured_at_utc"),
                    "URL solicitada": source.get("requested_url"),
                    "SHA-256 raw": source.get("snapshot_sha256"),
                }
            )


def _standings(dataset: Any) -> None:
    st.title("Clasificaciones y equipos")
    group = st.selectbox("Grupo", GROUPS, key="standings_group")
    rows = standings_table_rows(dataset, group)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    options = _team_options(dataset, group)
    if not options:
        st.warning("No hay participantes para este grupo.")
        return
    chosen_id = st.selectbox(
        "Inspeccionar equipo",
        [item[0] for item in options],
        format_func=lambda value: _team_label(options, value),
        key="standing_team",
    )
    records = team_records(dataset, chosen_id)
    if not records:
        st.warning("No se encontró un participante único para ese ID.")
        return
    st.subheader(records["participant"].get("team_name", "Equipo"))
    st.write(records["participant"])
    if records["standing"]:
        st.markdown("**Fila de clasificación**")
        st.json(records["standing"])
    elif records["standing_ambiguous"]:
        st.warning("Hay más de una fila de clasificación para este equipo.")
    st.markdown("**Partidos del equipo**")
    st.dataframe(_matches_table(records["matches"]), hide_index=True, width="stretch")


def _calendar(dataset: Any) -> None:
    st.title("Calendario y resultados")
    group_col, round_col, team_col, state_col = st.columns(4)
    group = group_col.selectbox("Grupo", GROUPS, key="calendar_group")
    rounds = sorted(
        {match.get("round") for match in dataset.matches[group] if isinstance(match.get("round"), int)}
    )
    selected_round = round_col.selectbox("Jornada", [None, *rounds], format_func=lambda value: "Todas" if value is None else str(value))
    options = _team_options(dataset, group)
    teams = {"": "Todos los equipos", **{identity: name for identity, name in options}}
    selected_team = team_col.selectbox("Equipo", list(teams), format_func=lambda value: teams[value])
    state_options = ["played", "scheduled", "unresolved", "unconfirmed", "unknown"]
    selected_states = state_col.multiselect("Estado", state_options, default=state_options)
    query = st.text_input("Buscar en los campos del partido", placeholder="Equipo, estadio, árbitro o ID")
    filtered = filter_matches(
        dataset,
        group=group,
        round_number=selected_round,
        team_season_id=selected_team or None,
        statuses=set(selected_states),
        search=query,
    )
    st.caption(f"{len(filtered)} partidos coinciden con los filtros.")
    st.dataframe(_matches_table(filtered), hide_index=True, width="stretch")
    with st.expander("Inspeccionar partido"):
        _show_selected_match(dataset, filtered)


def _match_viewer(dataset: Any) -> None:
    st.title("Visor de partidos")
    group = st.selectbox("Grupo", GROUPS, key="match_view_group")
    candidates = dataset.matches[group]
    if not candidates:
        st.info("El grupo no tiene partidos en el dataset.")
        return
    _show_selected_match(dataset, candidates)


def _teams(dataset: Any) -> None:
    st.title("Equipos")
    group = st.selectbox("Grupo", GROUPS, key="teams_group")
    options = _team_options(dataset, group)
    if not options:
        st.info("No hay equipos en este grupo.")
        return
    team_id = st.selectbox(
        "Equipo", [item[0] for item in options],
        format_func=lambda value: _team_label(options, value), key="teams_team",
    )
    record = team_records(dataset, team_id)
    if record is None:
        st.warning("No se encontró un participante único para ese ID.")
        return
    participant = record["participant"]
    st.subheader(participant.get("team_name", "Equipo"))
    st.link_button("Ficha de temporada en BDFutbol", participant["team_season_url"])
    st.write({key: value for key, value in participant.items() if not key.startswith("_")})
    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Clasificación**")
        if record["standing"]:
            st.json(record["standing"])
        elif record["standing_ambiguous"]:
            st.warning("Hay varias filas de clasificación enlazadas.")
        else:
            st.info("No hay fila de clasificación enlazada.")
    with right:
        st.markdown("**Partidos**")
        st.dataframe(_matches_table(record["matches"]), hide_index=True, width="stretch")


def _quality(dataset: Any) -> None:
    st.title("Calidad y cobertura")
    st.caption("No se calcula una puntuación total: la integridad estructural no implica que los resultados ya estén publicados.")
    for group in GROUPS:
        report = group_quality(dataset, group)
        with st.expander(f"Grupo {group}", expanded=True):
            st.markdown("**Cobertura estructural observada**")
            st.write(
                {
                    "equipos": f"{report['teams']} / {report['expected_teams']}",
                    "jornadas": f"{report['rounds']} / {report['expected_rounds']}",
                    "filas de partidos": f"{report['matches']} / {report['expected_matches']}",
                    "comprobación estructural del parser": report["structural_complete"],
                }
            )
            st.markdown("**Disponibilidad deportiva**")
            st.write({"con resultado": report["results_available"], "sin resultado": report["results_missing"], "estados": dict(report["states"])})
            st.markdown("**Integridad de relaciones e IDs**")
            st.write(
                {
                    "partidos sin ID": len(report["missing_match_ids"]),
                    "IDs de partido duplicados": report["duplicate_match_ids"],
                    "claves de partido duplicadas": report["duplicate_fixture_keys"],
                    "referencias de equipo ausentes": len(report["missing_team_relations"]),
                    "referencias sin resolver informadas por parser": report["reported_unresolved_team_refs"],
                }
            )
            if report["missing_match_ids"]:
                missing_rows = [
                    {
                        "Jornada": match.get("round"),
                        "Fecha": match.get("date"),
                        "Local": match.get("home_team_name"),
                        "Visitante": match.get("away_team_name"),
                        "Estado": fixture_status(match, dataset),
                        "Resultado": score_label(match),
                    }
                    for match in report["missing_match_ids"]
                ]
                with st.expander(f"Inspeccionar {len(missing_rows)} partidos sin ID publicado"):
                    st.dataframe(pd.DataFrame(missing_rows), hide_index=True, width="stretch")
            st.markdown("**Comprobaciones registradas por el parser**")
            checks = report["coverage_checks"]
            if checks:
                st.dataframe(
                    pd.DataFrame([{"Comprobación": key, "Resultado": value} for key, value in checks.items()]),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("Este export no incluye comprobaciones de cobertura con este formato.")
            st.markdown("**Acceso y procedencia**")
            st.write({key: report[key] for key in ("access_status", "http_status", "requested_url", "final_url", "captured_at_utc", "snapshot_sha256")})
            if report["parser_diagnostics"]:
                st.markdown("**Diagnósticos del parser**")
                st.json(report["parser_diagnostics"])
    st.subheader("Diagnósticos derivados para inspección")
    rows = diagnostic_rows(dataset)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.success("No hay fallos de checks del parser ni duplicados/referencias ausentes detectados por estas reglas locales.")


def _explorer(dataset: Any) -> None:
    st.title("Explorador JSON")
    filenames = sorted(dataset.json_files)
    filename = st.selectbox("Archivo JSON", filenames)
    document = dataset.json_files[filename]
    items = document.get("items") if isinstance(document, dict) else None
    if isinstance(items, list):
        records = [item for item in items if isinstance(item, dict)]
        flattened_keys = sorted({key for item in records for key in flatten_record(item)})
        field_options = ["(todos los campos)", *flattened_keys]
        selected_field = st.selectbox("Campo", field_options)
        query = st.text_input("Filtro de texto", placeholder="Subcadena; vacío muestra todos")
        filtered = search_records(records, None if selected_field == field_options[0] else selected_field, query)
        st.caption(f"{len(filtered)} de {len(records)} registros.")
        if filtered:
            st.dataframe(pd.DataFrame([flatten_record(row) for row in filtered]), hide_index=True, width="stretch")
        else:
            st.info("Ningún registro coincide con el filtro.")
        st.subheader("Campos null")
        counts = null_counts(records)
        st.dataframe(
            pd.DataFrame([{"Ruta de campo": field, "Valores null": count} for field, count in sorted(counts.items())]),
            hide_index=True,
            width="stretch",
        )
        if filtered:
            record_index = st.selectbox("Registro JSON completo", range(len(filtered)))
            st.json(filtered[record_index], expanded=True)
    else:
        st.json(document, expanded=True)


def main() -> None:
    st.sidebar.title("FootballDataHub")
    dataset = _show_dataset_choice()
    if dataset is None:
        return
    st.session_state.dataset = dataset
    section = st.sidebar.radio(
        "Sección",
        ["Resumen", "Clasificaciones", "Calendario", "Visor de partidos", "Equipos", "Calidad y cobertura", "Explorador de datos"],
    )
    if section == "Resumen":
        _summary(dataset)
    elif section == "Clasificaciones":
        _standings(dataset)
    elif section == "Calendario":
        _calendar(dataset)
    elif section == "Visor de partidos":
        _match_viewer(dataset)
    elif section == "Equipos":
        _teams(dataset)
    elif section == "Calidad y cobertura":
        _quality(dataset)
    else:
        _explorer(dataset)


if __name__ == "__main__":
    main()
