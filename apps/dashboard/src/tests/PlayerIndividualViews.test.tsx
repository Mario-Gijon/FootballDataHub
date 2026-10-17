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
    scope_note: "Datos observados en la captura local.",
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

function tableFixture(role: string, rawValue: string | number) {
  return [{
    table_role: role,
    source_table_index: 0,
    table_id: role,
    schema_id: "schema-1",
    columns: [{
      label: "Valor", title: null, hidden_in_source: false, source_index: 0, group_header: null, data_colid: "val",
    }],
    rows: [{
      context: { season_raw: "2025-26" },
      cells: [{ raw_value: rawValue, normalized_integer: typeof rawValue === "number" ? rawValue : null, value_status: null }],
      source_fields: { season_raw: "2025-26", team_name_raw: "Real Jaén", zero_preserved: 0 },
    }],
  }];
}

describe("PlayerIndividualViews", () => {
  it("presenta la trayectoria, estadísticas, resúmenes, convocatorias y datos de rivales por apartados", () => {
    const views: PlayerView[] = [
      viewFixture("profile", {
        profile: { display_name_raw: "Nacho Castillo", position_raw: "Centrocampista", height_raw: "183 cm" },
        tables: tableFixture("career_trajectory", 12),
      }),
      viewFixture("statistics", { tables: tableFixture("statistics_by_team", 0) }),
      viewFixture("matches", {
        tables: tableFixture("match_summary_by_season", 4),
        historical_matches: [{
          match_id: "m-1", match_url: null, date: "2026-09-01", date_raw: null, season: "2026-26",
          competition: "Primera Federación", round_label: "J1", player_team: "Real Jaén", opponent_team: "Rival",
          side: "home", minutes: 90, match_state: "played", appearance_status: "APPEARED",
          source_fields: { match_id: "m-1", result_raw: "1-0" },
        }],
        summoned_without_participation: [{
          match_id: "m-2", match_url: null, date: null, date_raw: "08/09/2026", season: "2026-27",
          competition: "Primera Federación", round_label: "J2", player_team: "Real Jaén", opponent_team: "Otro",
          side: "away", minutes: null, match_state: "played", appearance_status: "SUMMONED_WITHOUT_APPEARANCE",
          source_fields: { player_summoned_status: "SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG" },
        }],
        record_counts: { individual_matches: 1, summoned_without_participation: 1 },
        exhaustiveness_status: "SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE",
      }),
      viewFixture("rivals", { tables: tableFixture("opponent_team_statistics", 3) }),
    ];
    render(<PlayerIndividualViews views={views} />);

    expect(screen.getByText("Nacho Castillo")).toBeTruthy();
    expect(screen.getByText("Centrocampista")).toBeTruthy();
    expect(screen.getByText("183 cm")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Estadísticas/ }));
    expect(screen.getByText("statistics by team")).toBeTruthy();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Ver campos (3)"));
    expect(screen.getAllByText("Real Jaén").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: /Partidos/ }));
    expect(screen.getByText(/Exhaustividad: SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE/)).toBeTruthy();
    expect(screen.getByText("1-0")).toBeTruthy();
    expect(screen.getByText("Convocatorias sin participación")).toBeTruthy();
    expect(screen.getByText(/SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG/)).toBeTruthy();
    expect(screen.getByText("match summary by season")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Rivales/ }));
    const panel = screen.getByRole("tabpanel", { name: "Rivales" });
    expect(within(panel).getByText("opponent team statistics")).toBeTruthy();
  });
});
