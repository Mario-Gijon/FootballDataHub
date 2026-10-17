import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PlayerDetail } from "../api/contracts";
import { PlayerClubHistory, PlayerIdentityPanel } from "../components/PlayerIdentityPanel";
import { playerIdentityHighlights } from "../components/playerIdentityPresentation";

const detail = {
  identity: {
    display_name: "Manu Pedreño",
    full_name: "Antonio Manuel Moñino Pedreño",
    birth_date: "2000-10-09",
    age_years: 26,
    birth_place: "Los Garres",
    birth_place_raw: "Los Garres ( Murcia )",
    birthplace_province: "Murcia",
    country_of_birth: "España",
    nationality: null,
    position_name: "Central",
    height_cm: 190,
    height_raw: "190 cm",
    weight_kg: 81,
    weight_raw: "81 kg",
    field_sources: {
      position_name: "individual_profile",
      height_cm: "individual_profile",
      weight_kg: "individual_profile",
      country_of_birth: "individual_profile",
      nationality: "unavailable",
    },
    inventory_sha256: "a".repeat(64),
    individual_profile_source_url: "https://www.bdfutbol.com/es/j/j23751.html",
    individual_profile_captured_at: "2026-10-14T13:39:25.641724+00:00",
    individual_profile_sha256: "b".repeat(64),
    conflicts: [],
  },
  club_reference: {
    status: "not_confirmed",
    team_id: null,
    team_name: null,
    group: null,
    observed_at: null,
    reason: "later_or_simultaneous_outgoing_movement",
  },
  last_observed_movement: {
    from_team_id: 414,
    from_team_name: "UD Ibiza",
    from_group: "II",
    to_team_id: 178,
    to_team_name: "UD Logroñés",
    to_group: "I",
    season: "2026-27",
    transfer_date: null,
    observed_at: "2026-10-13T16:48:36.725160+00:00",
    evidence_count: 2,
    evidence: [
      { capture_id: "ibiza", captured_at: "2026-10-13T16:48:36.725160+00:00", source_sha256: "c".repeat(64), source_record_index: 42, team_id: 414, group: "II", direction: "outgoing" },
      { capture_id: "logrones", captured_at: "2026-10-12T16:03:01.180645+00:00", source_sha256: "d".repeat(64), source_record_index: 12, team_id: 178, group: "I", direction: "incoming" },
    ],
  },
  movement_resolution: "identified",
  associations: [
    { team_id: 178, team_name: "UD Logroñés", group: "I", evidence_types: ["membership", "transfer_reference"] },
    { team_id: 414, team_name: "UD Ibiza", group: "II", evidence_types: ["membership", "transfer_reference"] },
  ],
  membership_history: [
    { team_id: 178, team_name: "UD Logroñés", group: "I", season: "2026-27", captured_at: "2026-10-12T16:03:01.180645+00:00", capture_id: "logrones", jersey_number: 15, squad_group_label: "Suplentes", source_views: ["squad"] },
    { team_id: 414, team_name: "UD Ibiza", group: "II", season: "2026-27", captured_at: "2026-10-13T16:48:36.725160+00:00", capture_id: "ibiza", jersey_number: 4, squad_group_label: "Suplentes", source_views: ["squad"] },
  ],
} as unknown as PlayerDetail;

describe("PlayerIdentityPanel", () => {
  it("shows verified personal fields without treating birthplace as nationality", () => {
    render(<PlayerIdentityPanel detail={detail} />);
    const panel = screen.getByText("Datos personales").closest("article");
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getByText("09/10/2000")).toBeTruthy();
    expect(within(panel as HTMLElement).getByText("Los Garres · Murcia")).toBeTruthy();
    expect(within(panel as HTMLElement).getByText("España")).toBeTruthy();
    expect(within(panel as HTMLElement).getByText("No observada")).toBeTruthy();
    expect(playerIdentityHighlights(detail)).toEqual(["Central", "190 cm", "81 kg"]);
    fireEvent.click(within(panel as HTMLElement).getByText("Ver procedencia de identidad"));
    expect(within(panel as HTMLElement).getByText(/Lugar de nacimiento tal como aparece en la fuente: Los Garres \( Murcia \)/)).toBeTruthy();
  });

  it("keeps the latest movement and both club relationships without claiming a current club", () => {
    render(<PlayerClubHistory detail={detail} />);
    expect(screen.getByText("Club actual no confirmado")).toBeTruthy();
    expect(screen.getByText((_content, element) =>
      element?.tagName === "STRONG" && element.textContent?.includes("UD Ibiza · Grupo II") === true
      && element.textContent.includes("UD Logroñés · Grupo I"),
    )).toBeTruthy();
    expect(screen.getAllByText("UD Ibiza · Grupo II").length).toBeGreaterThan(0);
    expect(screen.getAllByText("UD Logroñés · Grupo I").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Club de referencia observado/i)).toBeNull();
    expect(screen.getByText(/fecha de traspaso no publicada/)).toBeTruthy();
  });

  it("surfaces conflicting identity values in a human-readable warning", () => {
    const conflicted = {
      ...detail,
      identity: {
        ...detail.identity,
        conflicts: [{ field: "display_name", inventory_value: "Nombre A", individual_profile_value: "Nombre B", selected_source: "inventory" }],
      },
    } as PlayerDetail;
    render(<PlayerIdentityPanel detail={conflicted} />);
    expect(screen.getByText("Hay diferencias entre fuentes")).toBeTruthy();
    expect(screen.getByText(/Nombre A.*Nombre B.*inventario como valor preferente/)).toBeTruthy();
  });
});
