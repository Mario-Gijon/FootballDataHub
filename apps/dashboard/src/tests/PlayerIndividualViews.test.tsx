import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PlayerDetail } from "../api/contracts";
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
  };
}

function matchFixture(patch: Partial<PlayerView["historical_matches"][number]> = {}): PlayerView["historical_matches"][number] {
  return {
    match_id: "m-1", match_url: "https://www.bdfutbol.com/es/p/p.php?id=1", date: "2026-09-01", date_raw: null,
    season: "2026-27", competition: "Primera Federación", round_label: "Jornada 1",
    player_team: "Real Jaén", opponent_team: "Rival", side: "home", home_goals: 2, away_goals: 1,
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

  it("presenta la fila Total como resumen y mantiene las métricas bajo sus columnas", () => {
    const totals = tableFixture("career_totals", [
      column("Temporada", 0), column("Equipo", 1), column("País", 2),
      column("Ascenso o descenso", 3), column("División", 4), column("Edad", 5),
      column("Partidos Jugados", 6), column("Minutos", 7),
    ], [row(["", "", "", "", "", "", 100, 7846], {
      row_role: "total", summary_label_raw: "Total", summary_label_span: 6,
    })]);
    render(<PlayerIndividualViews views={[viewFixture("profile", { tables: totals })]} />);

    const summary = screen.getByRole("heading", { name: "Totales de trayectoria" }).parentElement;
    const totalRow = summary?.querySelector("tbody tr");
    expect(totalRow?.querySelector("td[colspan='6']")?.textContent).toBe("Total");
    expect(within(totalRow as HTMLElement).getByText("100")).toBeTruthy();
    expect(within(totalRow as HTMLElement).getByText("7846")).toBeTruthy();
    expect(totalRow?.children).toHaveLength(3);
  });

  it("corrige también la alineación dispersa de los compactos ya publicados", () => {
    const legacyTotals = tableFixture("career_totals", [
      column("Temporada", 0), column("Equipo", 1), column("División", 2),
      column("Partidos Jugados", 3), column("Minutos", 4),
    ], [row(["", "", "Total", 51, 2850], { row_role: "total" })]);
    const { container } = render(<PlayerIndividualViews views={[viewFixture("profile", { tables: legacyTotals })]} />);

    const table = container.querySelector(".player-source-table table");
    const totalRow = table?.querySelector("tbody tr");
    expect(totalRow?.querySelector("td[colspan='3']")?.textContent).toBe("Total");
    expect(within(totalRow as HTMLElement).getByText("51")).toBeTruthy();
    expect(within(totalRow as HTMLElement).getByText("2850")).toBeTruthy();
  });
});
