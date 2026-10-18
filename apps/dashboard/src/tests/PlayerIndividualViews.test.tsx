import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { PlayerDetail } from "../api/contracts";
import type { CatalogTeam } from "../domain/teams";
import { PlayerIndividualViews } from "../components/PlayerIndividualViews";

type PlayerView = PlayerDetail["verified_individual_views"][number];

function viewFixture(view: PlayerView["view"], patch: Partial<PlayerView> = {}): PlayerView {
  return {
    view,
    source_url: "https://www.bdfutbol.com/es/j/j28577.html?view=" + view,
    captured_at: "2026-10-16T12:00:00+00:00",
    source_sha256: "a".repeat(64),
    scope_note: "CAPTURED_ROWS",
    tables: [],
    profile: null,
    coverage: { data_scope: "CAPTURED_ROWS" },
    historical_matches: [],
    summoned_without_participation: [],
    other_match_records: [],
    record_counts: {},
    individual_matches_source: null,
    window_p_parse_status: null,
    window_p_record_count: null,
    detail_coverage: null,
    exhaustiveness_status: null,
    filter_parameters: {},
    filtered_view: null,
    ...patch,
  };
}

function tableFixture(role: string, columns: PlayerView["tables"][number]["columns"], rows: PlayerView["tables"][number]["rows"][number][]): PlayerView["tables"] {
  return [{ table_role: role, source_table_index: 0, table_id: role, schema_id: "schema-1", columns, rows }];
}

function column(label: string, sourceIndex: number, groupHeader: string | null = null) {
  return { label, source_header: label, title: null, hidden_in_source: false, source_index: sourceIndex, group_header: groupHeader, data_colid: null };
}

function row(values: Array<string | number | null>, sourceFields: Record<string, unknown> = {}, context: Record<string, string | number | boolean | null> = {}) {
  return {
    context,
    cells: values.map((rawValue) => ({ raw_value: rawValue, normalized_integer: typeof rawValue === "number" ? rawValue : null, value_status: null })),
    source_fields: sourceFields,
    internal_player_id: null,
  };
}

function matchFixture(patch: Partial<PlayerView["historical_matches"][number]> = {}): PlayerView["historical_matches"][number] {
  return {
    match_id: "m-1", match_url: "https://www.bdfutbol.com/es/p/p.php?id=1", date: "2026-09-01", date_raw: null,
    season: "2026-27", competition: "Primera Federación", round_label: "Jornada 1",
    player_team: "Real Jaén", opponent_team: "Rival", side: "home", home_goals: 2, away_goals: 1,
    home_team_id: null, away_team_id: null,
    minutes: 90, match_state: "played", appearance_status: "APPEARED_PER_SOURCE_FLAGS", participation: "Titular",
    match_statistics: [
      { label: "Partidos titular", raw_value: 1, normalized_integer: 1 },
      { label: "Minutos", raw_value: 90, normalized_integer: 90 },
      { label: "Tarjetas amarillas", raw_value: "'75", normalized_integer: null },
      { label: "Goles", raw_value: "", normalized_integer: null },
    ],
    source_fields: { source_record_index: 0, home_team_raw: "Real Jaén", away_team_raw: "Rival" },
    ...patch,
  };
}

describe("PlayerIndividualViews", () => {
  afterEach(cleanup);

  it("muestra cuatro apartados deportivos, estadística agrupada y logros semánticos", () => {
    const career = tableFixture("career_trajectory", [
      column("Temporada", 0), column("Equipo", 1), column("Ascenso o descenso", 2), column("Otras competiciones", 3),
    ], [row(["2025-26", "Real Jaén", "", ""], {
      team_achievements_raw: ["Ascenso"], competition_participations_raw: ["Copa del Rey"],
    })]);
    const stats = tableFixture("statistics_by_competition", [column("Estadística", 0), column("Primera Federación", 1)], [row(["Goles", 9])]);
    const byTeam = tableFixture("statistics_by_team", [column("Estadística", 0), column("Real Jaén", 1)], [row(["Partidos", 12])]);
    const milestones = [
      ...tableFixture("milestone_matches", [column("Temporada", 0), column("Partido", 1)], [row(["2025-26", "Real Jaén – Rival"], {}, { table_caption_raw: "Participaciones" })]),
      ...tableFixture("milestone_matches", [column("Temporada", 0), column("Partido", 1)], [row(["2025-26", "Real Jaén – Rival"], {}, { table_caption_raw: "Gol" })]),
    ];
    const rivals = tableFixture("opponent_player_statistics", [
      column("Nombre", 0), column("Jugador · Goles", 1, "Jugador"), column("Rival · Goles", 2, "Rival"),
    ], [row(["Erik Ruiz", 1, 2])]);
    const views = [
      viewFixture("profile", { tables: career }),
      viewFixture("statistics", { tables: [...stats, ...byTeam, ...milestones] }),
      viewFixture("matches", {
        tables: tableFixture("match_summary_by_season", [column("Temporada", 0), column("Partidos", 1)], [row(["2026-27", 3])]),
        historical_matches: [matchFixture(), matchFixture({
          match_id: "m-2", season: "2025-26", competition: "Copa del Rey",
          home_goals: 1, away_goals: 0, date: "2025-01-10", round_label: "Ronda 1",
          match_statistics: [], source_fields: { source_record_index: 1, home_team_raw: "Real Jaén", away_team_raw: "Rival" },
        })],
      }),
      viewFixture("rivals", { tables: rivals }),
    ];
    render(<PlayerIndividualViews views={views} />);

    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.getByRole("heading", { name: "Trayectoria por temporada" })).toBeTruthy();
    expect(screen.getByText("Ascenso")).toBeTruthy();
    expect(screen.getByText("Copa del Rey")).toBeTruthy();
    expect(screen.queryByText(/SHA-256|captura|procedencia|Sin encabezado|Datos de origen/i)).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    expect(screen.getByRole("heading", { name: "Estadísticas por competición" })).toBeTruthy();
    expect(screen.getByText("Primera Federación")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Equipos" }));
    expect(screen.getByRole("heading", { name: "Estadísticas por equipo" })).toBeTruthy();
    expect(screen.getByText("Real Jaén")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Hitos estadísticos" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Participaciones" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Gol" })).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Partidos" }));
    const matchPanel = screen.getByRole("tabpanel", { name: "Partidos" });
    expect(within(matchPanel).getByText("Partidos de la trayectoria")).toBeTruthy();
    expect(within(matchPanel).getByText("2–1")).toBeTruthy();
    expect(within(matchPanel).getByText("1–0")).toBeTruthy();
    expect(within(matchPanel).getByText("'75")).toBeTruthy();
    expect(within(matchPanel).queryByText(/APPEARED_PER_SOURCE_FLAGS|Otros campos|Ver campos/)).toBeNull();
    expect(within(matchPanel).getAllByRole("link", { name: "Ver partido ↗" })[0].getAttribute("href")).toContain("id=1");
    fireEvent.change(within(matchPanel).getByLabelText("Temporada"), { target: { value: "2025-26" } });
    expect(within(matchPanel).queryByText("2–1")).toBeNull();
    expect(within(matchPanel).getByText("1–0")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Rivales" }));
    expect(screen.getByRole("heading", { name: "Rendimiento ante jugadores" })).toBeTruthy();
    expect(screen.getByText("Jugador · Goles")).toBeTruthy();
    expect(screen.getByText("Rival · Goles")).toBeTruthy();
  });

  it("no inventa nombres para columnas que carecen de semántica", () => {
    const unknown = tableFixture("unknown", [], [row(["Dato privado"]) ]);
    render(<PlayerIndividualViews views={[viewFixture("profile", { tables: unknown })]} />);
    expect(screen.queryByText("Sin encabezado")).toBeNull();
    expect(screen.queryByText("Dato privado")).toBeNull();
    expect(screen.queryByText("unknown")).toBeNull();
  });

  it("muestra un movimiento identificado dentro de Trayectoria sin declararlo club actual", () => {
    const movement = {
      from_team_id: 414, from_team_name: "UD Ibiza", from_group: "II",
      to_team_id: 178, to_team_name: "UD Logroñés", to_group: "I",
      season: "2026-27", transfer_date: null, observed_at: null, evidence_count: 2, evidence: [],
    } as unknown as PlayerDetail["last_observed_movement"];
    render(<PlayerIndividualViews views={[viewFixture("profile")]} movement={movement} />);

    expect(screen.getByText("Movimiento registrado · 2026-27:")).toBeTruthy();
    expect(screen.getByText("UD Ibiza → UD Logroñés")).toBeTruthy();
    expect(screen.queryByText(/club actual/i)).toBeNull();
  });

  it("muestra solo métricas acumuladas y conserva las estadísticas de la fila original de BDFutbol", () => {
    const labels = [
      "Temporada", "Equipo", "País", "Ascenso o descenso", "División", "Edad",
      "Partidos Jugados", "Partidos titular", "Partidos completos", "Partidos suplente",
      "Partidos sustituido", "Partidos incompletos", "Partidos convocado", "Total convocado",
      "Ganados", "Empatados", "Perdidos", "Minutos", "Tarjetas amarillas", "Tarjetas rojas",
      "Goles", "Goles penalty", "Goles propia puerta", "Goles encajados", "Dorsal", "Otras competiciones",
    ];
    const values: Array<string | number | null> = [
      "", "", "", "", "Total", "", 170, 117, 34, 53, 81, 134, 14, 184,
      66, 46, 58, 10084, 25, 2, 29, 2, 0, 0, "", "",
    ];
    const totals = tableFixture("career_totals", labels.map((label, index) => column(label, index)), [row(values, {
      row_role: "total", summary_label_raw: "Total", summary_label_span: 6,
    })]);
    const { container } = render(<PlayerIndividualViews views={[viewFixture("profile", { tables: totals })]} />);

    expect(screen.getByRole("heading", { name: "Totales de trayectoria" })).toBeTruthy();
    expect(container.querySelector(".player-career-total-primary")).toBeTruthy();
    expect(screen.getByText("170")).toBeTruthy();
    expect(screen.getByText("117")).toBeTruthy();
    expect(screen.getByText("10084")).toBeTruthy();
    expect(screen.getByText("29")).toBeTruthy();
    expect(screen.getByText("Tarjetas amarillas")).toBeTruthy();
    expect(screen.getByText("25")).toBeTruthy();
    expect(screen.getByText("Goles propia puerta")).toBeTruthy();
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
    for (const descriptive of ["Temporada", "Equipo", "País", "Ascenso o descenso", "División", "Edad", "Dorsal", "Otras competiciones", "Total"]) {
      expect(screen.queryByText(descriptive, { exact: true })).toBeNull();
    }
    expect(container.querySelector(".player-career-totals table")).toBeNull();
  });

  it("alinea los compactos anteriores cuyo Total aparece en una columna descriptiva", () => {
    const legacyTotals = tableFixture("career_totals", [
      column("Temporada", 0), column("Equipo", 1), column("División", 2),
      column("Partidos Jugados", 3), column("Minutos", 4),
    ], [row(["", "", "Total", 51, 2850])]);
    const { container } = render(<PlayerIndividualViews views={[viewFixture("profile", { tables: legacyTotals })]} />);

    expect(screen.getByText("51")).toBeTruthy();
    expect(screen.getByText("2850")).toBeTruthy();
    expect(screen.getByText("Partidos Jugados")).toBeTruthy();
    expect(screen.queryByText("División", { exact: true })).toBeNull();
    expect(container.querySelector(".player-career-totals table")).toBeNull();
  });

  it("respeta estructuras con otro colspan, conserva métricas nuevas y oculta marcadores ausentes", () => {
    const totals = tableFixture("career_totals", [
      column("Temporada", 0), column("Equipo", 1), column("División", 2), column("Edad", 3),
      column("Partidos", 4), column("Asistencias", 5), column("Duelos ganados", 6), column("Dorsal", 7), column("Remates", 8),
    ], [row(["", "", "", "", 22, 7, 8, 11, "-"], {
      row_role: "total", summary_label_raw: "Totales", summary_label_span: 4,
    })]);
    render(<PlayerIndividualViews views={[viewFixture("profile", { tables: totals })]} />);

    expect(screen.getByText("22")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("Asistencias")).toBeTruthy();
    expect(screen.getByText("Duelos ganados")).toBeTruthy();
    expect(screen.queryByText("Dorsal", { exact: true })).toBeNull();
    expect(screen.queryByText("11", { exact: true })).toBeNull();
    expect(screen.queryByText("Remates", { exact: true })).toBeNull();
    expect(screen.queryByText("-", { exact: true })).toBeNull();
    expect(screen.queryByText("Edad", { exact: true })).toBeNull();
  });

  it("enlaza clubes y jugadores solo con IDs presentes y coherentes en los catálogos", () => {
    const catalogTeam = {
      team_id: 49, name: "Real Jaén", crest_url: null,
      team_url: "https://www.bdfutbol.com/es/t/t2026-2749.html",
      group: "2", season: "2026-27", captureId: "capture",
    } as unknown as CatalogTeam;
    const career = tableFixture("career_trajectory", [column("Temporada", 0), column("Equipo", 1)], [row(["2026-27", "Real Jaén"], {
      team_season_reference: "t2026-2749",
      team_season_url: "https://www.bdfutbol.com/es/t/t2026-2749.html",
    })]);
    const rivals = tableFixture("opponent_player_statistics", [column("Nombre", 0), column("Goles", 1)], [
      { ...row(["Iván Rival", 2], { rival_name_raw: "Iván Rival" }), internal_player_id: 23751 },
      row(["Jugador sin inventario", 1], { rival_name_raw: "Jugador sin inventario" }),
    ]);
    const views = [
      viewFixture("profile", { tables: career }),
      viewFixture("matches", { historical_matches: [matchFixture({
        home_team_id: 49,
        away_team_id: 90001,
        source_fields: { source_record_index: 0, home_team_raw: "Real Jaén", away_team_raw: "Club histórico" },
      })] }),
      viewFixture("rivals", { tables: rivals }),
    ];
    const paths: string[] = [];
    render(<PlayerIndividualViews views={views} teams={[catalogTeam]} onNavigate={(path) => paths.push(path)} />);

    const careerTeam = screen.getByRole("link", { name: "Real Jaén" });
    expect(careerTeam).toHaveAttribute("href", "/teams/49");
    fireEvent.click(careerTeam);
    expect(paths).toEqual(["/teams/49"]);

    fireEvent.click(screen.getByRole("tab", { name: "Partidos" }));
    const matchPanel = screen.getByRole("tabpanel", { name: "Partidos" });
    expect(within(matchPanel).getByRole("link", { name: "Real Jaén" })).toHaveAttribute("href", "/teams/49");
    expect(within(matchPanel).getByText("Club histórico").closest("a")).toBeNull();
    expect(within(matchPanel).getByRole("link", { name: "Ver partido ↗" })).toHaveAttribute("target", "_blank");

    fireEvent.click(screen.getByRole("tab", { name: "Rivales" }));
    expect(screen.getByRole("link", { name: "Iván Rival" })).toHaveAttribute("href", "/players/23751");
    expect(screen.getByText("Jugador sin inventario").closest("a")).toBeNull();
  });
});
