import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import captureSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/metadata/capture.json";
import classificationSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/normalized/classification.json";
import matchesSource from "../../../../data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json";
import progressSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/normalized/progress.json";
import referenceSource from "../../../../data/exports/bdfutbol/group2_classification/derived-clas01b-20261010T102656Z/validation/bdfutbol_js_reference.json";
import App from "../App";

const publicMatches = matchesSource.matches.map((match) => ({
  match_id: match.match_id,
  matchday: match.matchday,
  matchday_date: match.matchday_date,
  source_match_date: match.source_match_date,
  home_team_id: match.home_team_id,
  away_team_id: match.away_team_id,
  home_goals: match.home_goals,
  away_goals: match.away_goals,
  home_yellow_cards: match.home_yellow_cards,
  away_yellow_cards: match.away_yellow_cards,
  home_red_cards: match.home_red_cards,
  away_red_cards: match.away_red_cards,
  status: match.status,
  unplayed_state: match.unplayed_state,
  postponed_by_source_rule: match.postponed_by_source_rule,
  source_match_url: match.source_match_url,
  stadium_id: match.stadium_id,
  stadium_name: match.stadium_name,
  stadium_url: match.stadium_url,
  referee_id: match.referee_id,
  referee_name: match.referee_name,
  referee_url: match.referee_url,
}));

const apiBootstrap = {
  metadata: {
    schema_version: 1,
    source: captureSource.source,
    url: captureSource.url,
    competition: captureSource.competition,
    season: captureSource.season,
    group: captureSource.group,
    team_count: matchesSource.teams.length,
    scheduled_matchdays: Array.from({ length: 38 }, (_, index) => index + 1),
    last_matchday_with_results: matchesSource.metadata.played_matchdays_in_source,
    captured_at: captureSource.captured_at_utc,
    capture_id: captureSource.capture_id,
    dataset_version: `${captureSource.capture_id}-test-fixture`,
    availability: {
      teams: matchesSource.teams.length,
      matches: matchesSource.matches.length,
      played_matches: matchesSource.counts.played,
      unplayed_matches: matchesSource.counts.unplayed,
      incomplete_matches: matchesSource.counts.incomplete,
      matchdays_with_fixtures: Array.from({ length: 38 }, (_, index) => index + 1),
      last_matchday_with_results: matchesSource.metadata.played_matchdays_in_source,
      progress_records: progressSource.records.length,
      progress_through_matchday: progressSource.series_context.available_through_matchday,
      published_standings_available: true,
    },
    progress_context: progressSource.series_context,
    warnings: [
      "1 encuentro no tenía resultado en la captura; no se interpreta como 0-0.",
      "La captura no contiene un partido que active la regla de aplazamiento de BDFutbol.",
    ],
  },
  teams: matchesSource.teams,
  matches: publicMatches,
  progress: progressSource.records,
  published_standings: {
    source: classificationSource.metadata.source,
    source_capture_id: classificationSource.metadata.capture_id,
    context: {
      classification_type: classificationSource.context.classification_type,
      matchday: classificationSource.context.matchday,
      matchday_date: classificationSource.context.matchday_date,
      postponed_policy: classificationSource.context.postponed_policy,
      range_type: classificationSource.context.range_type,
    },
    rows: classificationSource.standings.map((row) => ({
      team_id: row.team_id,
      team_name: row.team_name,
      team_url: row.team_url,
      crest_url: row.crest_url,
      position: row.position,
      points: row.points,
      matches_played: row.matches_played,
      wins: row.wins,
      draws: row.draws,
      losses: row.losses,
      goals_for: row.goals_for,
      goals_against: row.goals_against,
      yellow_cards: row.yellow_cards,
      red_cards: row.red_cards,
      position_change: row.position_change,
      sports_zone: row.sports_zone,
    })),
  },
};

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const fetchMock = vi.fn();

function bootstrapForGeneralJ5() {
  const scenario = referenceSource.scenarios.find((item) => item.name === "general_r5");
  if (!scenario) throw new Error("Falta la referencia real General J5.");
  const expectedById = new Map(scenario.rows.map((row) => [row.team_id, row]));
  const published = apiBootstrap.published_standings;

  return {
    ...apiBootstrap,
    metadata: {
      ...apiBootstrap.metadata,
      last_matchday_with_results: 5,
      availability: {
        ...apiBootstrap.metadata.availability,
        last_matchday_with_results: 5,
      },
    },
    published_standings: {
      ...published,
      context: { ...published.context, matchday: 5, matchday_date: "2026-09-27" },
      rows: published.rows.map((row) => {
        const expected = expectedById.get(row.team_id);
        if (!expected) throw new Error(`Falta el equipo ${row.team_id} en General J5.`);
        return {
          ...row,
          position: expected.position,
          points: expected.points,
          matches_played: expected.matches_played,
          wins: expected.wins,
          draws: expected.draws,
          losses: expected.losses,
          goals_for: expected.goals_for,
          goals_against: expected.goals_against,
          yellow_cards: expected.yellow_cards,
          red_cards: expected.red_cards,
          position_change: null,
          sports_zone: null,
        };
      }),
    },
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(response(200, apiBootstrap));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("dashboard de clasificación", () => {
  it("carga el bootstrap, muestra la competición y destaca discretamente al Real Jaén", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Clasificación" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByText("Primera Federación")).toBeInTheDocument();
    expect(screen.getByText("Grupo II")).toBeInTheDocument();
    expect(screen.getByText("2026/27")).toBeInTheDocument();
    expect(screen.getByText("Jornada 6 disponible")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Jaén/ })).toHaveClass("is-jaen");
    expect(screen.getByText("59 partidos")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(21);
    expect(screen.getByLabelText("Zonas deportivas publicadas")).toBeInTheDocument();
    expect(screen.queryByText("Calculada localmente")).not.toBeInTheDocument();
    expect(screen.queryByText(/Cada punto cuenta/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Al cambiar un filtro no se consulta/)).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(captureSource.capture_id))).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("usa la jornada de metadatos para el resumen compacto", async () => {
    fetchMock.mockResolvedValueOnce(response(200, bootstrapForGeneralJ5()));
    render(<App />);

    expect(await screen.findByText("Jornada 5 disponible")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("recalcula filtros localmente y limita el rango de jornadas al tope", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });

    fireEvent.click(screen.getByRole("button", { name: "Local" }));
    expect(screen.getByRole("heading", { name: "Como local" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Excluir" }));
    expect(screen.getByRole("button", { name: "Excluir" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByLabelText("Tipo de rango"), { target: { value: "dates" } });
    fireEvent.change(screen.getByLabelText("Fecha inicial"), { target: { value: "2026-08-29" } });
    fireEvent.change(screen.getByLabelText("Fecha final"), { target: { value: "2026-09-27" } });
    expect(screen.getByLabelText("Fecha inicial")).toHaveValue("2026-08-29");

    fireEvent.change(screen.getByLabelText("Tipo de rango"), { target: { value: "rounds" } });
    fireEvent.change(screen.getByLabelText("Jornada inicial"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Jornada final"), { target: { value: "4" } });
    await waitFor(() => expect(screen.getByText("30 partidos")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("conserva rangos válidos al recorrer todas las transiciones de modo", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    const rangeType = screen.getByLabelText("Tipo de rango");

    fireEvent.change(rangeType, { target: { value: "dates" } });
    fireEvent.change(screen.getByLabelText("Fecha inicial"), { target: { value: "2026-09-05" } });
    fireEvent.change(screen.getByLabelText("Fecha final"), { target: { value: "2026-09-27" } });
    fireEvent.change(rangeType, { target: { value: "rounds" } });
    fireEvent.change(screen.getByLabelText("Jornada inicial"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Jornada final"), { target: { value: "4" } });

    fireEvent.change(rangeType, { target: { value: "all" } });
    fireEvent.change(rangeType, { target: { value: "dates" } });
    expect(screen.getByLabelText("Fecha inicial")).toHaveValue("2026-09-05");
    expect(screen.getByLabelText("Fecha final")).toHaveValue("2026-09-27");

    fireEvent.change(rangeType, { target: { value: "all" } });
    fireEvent.change(rangeType, { target: { value: "rounds" } });
    expect(screen.getByLabelText("Jornada inicial")).toHaveValue("2");
    expect(screen.getByLabelText("Jornada final")).toHaveValue("4");
    fireEvent.change(rangeType, { target: { value: "dates" } });
    expect(screen.getByLabelText("Fecha inicial")).toHaveValue("2026-09-05");

    fireEvent.change(rangeType, { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Jornada límite"), { target: { value: "3" } });
    fireEvent.change(rangeType, { target: { value: "rounds" } });
    expect(screen.getByLabelText("Jornada inicial")).toHaveValue("2");
    expect(screen.getByLabelText("Jornada final")).toHaveValue("3");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("oculta movimientos cuando el filtro de aplazados difiere del contexto publicado", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    expect(container.querySelectorAll(".movement-cell [title]").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Excluir" }));
    expect(container.querySelectorAll(".movement-cell [title]")).toHaveLength(0);
    expect(container.querySelector(".movement-column span")).toHaveAttribute(
      "title",
      "Movimiento no disponible para este filtro.",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("mantiene las bandas visuales ligadas a la posición deportiva y marca las zonas calculadas como referencia", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });

    const rowAtPosition = (position: number) => container.querySelector(`tr[data-position="${position}"]`);
    expect(rowAtPosition(1)).toHaveAttribute("data-visual-zone", "direct");
    expect(rowAtPosition(1)).toHaveAttribute("data-official-zone", "direct_promotion");
    for (const position of [2, 3, 4, 5]) {
      expect(rowAtPosition(position)).toHaveAttribute("data-visual-zone", "promotion");
      expect(rowAtPosition(position)).toHaveAttribute("data-official-zone", "promotion");
    }
    for (const position of [6, 15]) {
      expect(rowAtPosition(position)).toHaveAttribute("data-visual-zone", "stay");
    }
    for (const position of [16, 20]) {
      expect(rowAtPosition(position)).toHaveAttribute("data-visual-zone", "relegation");
      expect(rowAtPosition(position)).toHaveAttribute("data-official-zone", "relegation");
    }

    const jaenRow = screen.getByRole("row", { name: /Jaén/ });
    expect(jaenRow).toHaveAttribute("data-position", "5");
    expect(jaenRow).toHaveAttribute("data-visual-zone", "promotion");
    fireEvent.click(screen.getByRole("button", { name: /Equipo/ }));
    expect(container.querySelector(".standings-table tbody tr")).not.toHaveAttribute("data-team-id", "39");
    expect(jaenRow).toHaveAttribute("data-position", "5");
    expect(jaenRow).toHaveAttribute("data-visual-zone", "promotion");

    fireEvent.click(screen.getByRole("button", { name: "Local" }));
    expect(container.querySelectorAll(".standings-table tbody tr")).toHaveLength(20);
    expect(screen.getByLabelText("Zonas de referencia por posición")).toBeInTheDocument();
    expect(screen.getByText("Ascenso directo · ref.")).toBeInTheDocument();
    expect(container.querySelectorAll("tr[data-official-zone]")).toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ordena la visualización sin cambiar la posición deportiva", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });

    const jaenRow = screen.getByRole("row", { name: /Jaén/ });
    expect(jaenRow.querySelector(".position-cell")).toHaveTextContent("5");
    fireEvent.click(screen.getByRole("button", { name: /Equipo/ }));

    const firstTeam = container.querySelector(".standings-table tbody tr");
    expect(firstTeam).not.toHaveAttribute("data-team-id", "39");
    expect(jaenRow.querySelector(".position-cell")).toHaveTextContent("5");
    expect(jaenRow).toHaveAttribute("data-visual-zone", "promotion");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("mantiene la métrica y la selección de equipos independientes de los filtros", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });

    const pointsMetric = screen.getByRole("button", { name: "Puntos" });
    fireEvent.click(pointsMetric);
    expect(pointsMetric).toHaveAttribute("aria-pressed", "true");

    const jaenSeries = screen.getByRole("button", { name: "Ocultar Jaén en el gráfico" });
    expect(jaenSeries).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(jaenSeries);
    expect(screen.getByRole("button", { name: "Mostrar Jaén en el gráfico" })).toHaveAttribute("aria-pressed", "false");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("muestra diez fixtures de la última jornada con resultados y sus datos enriquecidos", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));

    expect(await screen.findByRole("heading", { name: "Resultados" })).toBeInTheDocument();
    expect(screen.getByLabelText("Jornada de resultados")).toHaveValue("6");
    expect(container.querySelectorAll(".results-match-row")).toHaveLength(10);
    expect(screen.getByRole("columnheader", { name: "Estadio" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Árbitro" })).toBeInTheDocument();
    expect(screen.getByText("Nuevo Mirador")).toBeInTheDocument();
    expect(screen.getByText("Caro Mogío")).toBeInTheDocument();
    expect(container.querySelectorAll('.results-match-row.is-jaen-match')).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("cambia jornadas, permite Todas y conserva resultados y matriz sin nuevas peticiones", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    const selector = screen.getByLabelText("Jornada de resultados");

    fireEvent.change(selector, { target: { value: "1" } });
    expect(container.querySelectorAll(".results-match-row")).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Jornada anterior" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Jornada siguiente" }));
    expect(selector).toHaveValue("2");

    fireEvent.change(selector, { target: { value: "38" } });
    expect(screen.getByRole("button", { name: "Jornada siguiente" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Jornada anterior" }));
    expect(selector).toHaveValue("37");

    fireEvent.change(selector, { target: { value: "all" } });
    expect(container.querySelectorAll(".results-match-row")).toHaveLength(380);
    expect(container.querySelectorAll(".results-round-divider")).toHaveLength(38);
    expect(container.querySelectorAll(".result-pending")).toHaveLength(321);
    const pending = container.querySelector(".results-match-row:has(.result-pending)");
    expect(pending?.querySelector(".result-score")).toBeNull();

    const matrixRows = [...container.querySelectorAll(".results-matrix tbody tr")];
    expect(matrixRows).toHaveLength(20);
    expect(matrixRows.every((row) => row.querySelectorAll("td").length === 20)).toBe(true);
    expect(container.querySelectorAll(".results-matrix .matrix-result-cell")).toHaveLength(380);
    expect(container.querySelectorAll(".results-matrix .matrix-diagonal")).toHaveLength(20);
    expect(container.querySelectorAll(".results-matrix .is-pending")).toHaveLength(321);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("conserva los filtros de Clasificación al cambiar de sección", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.change(screen.getByLabelText("Tipo de rango"), { target: { value: "dates" } });
    fireEvent.change(screen.getByLabelText("Fecha inicial"), { target: { value: "2026-09-05" } });
    fireEvent.change(screen.getByLabelText("Fecha final"), { target: { value: "2026-09-20" } });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    expect(await screen.findByRole("heading", { name: "Resultados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Clasificación" }));
    expect(await screen.findByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByLabelText("Tipo de rango")).toHaveValue("dates");
    expect(screen.getByLabelText("Fecha inicial")).toHaveValue("2026-09-05");
    expect(screen.getByLabelText("Fecha final")).toHaveValue("2026-09-20");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("muestra un estado de error útil si la API todavía no está preparada", async () => {
    fetchMock.mockResolvedValueOnce(response(503, { detail: "not ready" }));
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("La API todavía no tiene un dataset preparado.");
    expect(screen.getByRole("button", { name: "Reintentar conexión" })).toBeInTheDocument();
  });
});
