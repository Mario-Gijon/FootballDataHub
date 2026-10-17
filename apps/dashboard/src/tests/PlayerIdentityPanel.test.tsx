import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { PlayerDetail } from "../api/contracts";
import { PlayerIdentityPanel } from "../components/PlayerIdentityPanel";

const team = { team_id: 49, name: "Jaén", crest_url: null, team_url: "https://www.bdfutbol.com/es/t/t2026-2749.html", group: "2", season: "2026-27", captureId: "capture" } as const;

const detail = {
  player: {
    player_id: 23751,
    display_name: "Manu Pedreño",
    full_name: "Antonio Manuel Moñino Pedreño",
    profile_url: "https://www.bdfutbol.com/es/j/j23751.html",
    photo_url: "https://www.bdfutbol.com/i/players/23751.jpg",
  },
  club_reference: { status: "not_confirmed", team_id: null, team_name: null, group: null, observed_at: null, reason: "ambiguous" },
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
    field_sources: {}, inventory_sha256: "a".repeat(64),
    individual_profile_source_url: "https://www.bdfutbol.com/es/j/j23751.html",
    individual_profile_captured_at: "2026-10-14T13:39:25.641724+00:00",
    individual_profile_sha256: "b".repeat(64),
    conflicts: [{ field: "display_name", inventory_value: "Nombre A", individual_profile_value: "Nombre B", selected_source: "individual_profile" }],
  },
} as unknown as PlayerDetail;

describe("PlayerIdentityPanel", () => {
  afterEach(cleanup);

  it("presenta primero la identidad individual y mantiene país de nacimiento separado de nacionalidad", () => {
    render(<PlayerIdentityPanel detail={detail} teams={[team]} onNavigate={() => undefined} />);

    expect(screen.getByRole("heading", { name: "Manu Pedreño" })).toBeTruthy();
    expect(screen.getByText("Antonio Manuel Moñino Pedreño")).toBeTruthy();
    expect(screen.getByText("09/10/2000")).toBeTruthy();
    expect(screen.getByText("Los Garres (Murcia)")).toBeTruthy();
    expect(screen.getByText("España")).toBeTruthy();
    expect(screen.getByText("190 cm")).toBeTruthy();
    expect(screen.getByText("81 kg")).toBeTruthy();
    expect(screen.queryByText("Nacionalidad")).toBeNull();
    expect(screen.getByRole("link", { name: "BDFutbol ↗" }).getAttribute("href")).toBe(detail.player.profile_url);
  });

  it("no muestra conflictos ni datos internos de procedencia en la ficha pública", () => {
    render(<PlayerIdentityPanel detail={detail} teams={[team]} onNavigate={() => undefined} />);
    expect(screen.queryByText(/diferencias entre fuentes/i)).toBeNull();
    expect(screen.queryByText(/inventario «/i)).toBeNull();
    expect(screen.queryByText(/SHA-256|captura individual|procedencia/i)).toBeNull();
  });

  it("enlaza el equipo de referencia cuando la identidad del club está confirmada", () => {
    const paths: string[] = [];
    const confirmed = {
      ...detail,
      club_reference: { status: "observed", team_id: 49, team_name: "Jaén", group: "II", observed_at: null, reason: "latest_unique_membership_observation" },
    } as unknown as PlayerDetail;
    render(<PlayerIdentityPanel detail={confirmed} teams={[team]} onNavigate={(path) => paths.push(path)} />);

    const teamLink = screen.getByRole("link", { name: "Jaén · Grupo II" });
    expect(teamLink.getAttribute("href")).toBe("/teams/49");
    fireEvent.click(teamLink);
    expect(paths).toEqual(["/teams/49"]);
  });

  it("mantiene como texto una referencia confirmada que no está en el catálogo de temporada", () => {
    const confirmed = {
      ...detail,
      club_reference: { status: "observed", team_id: 209, team_name: "Jaén", group: "II", observed_at: null, reason: "historic" },
    } as unknown as PlayerDetail;
    render(<PlayerIdentityPanel detail={confirmed} teams={[team]} onNavigate={() => undefined} />);

    expect(screen.getByText("Jaén · Grupo II").tagName).toBe("SPAN");
    expect(screen.queryByRole("link", { name: "Jaén · Grupo II" })).toBeNull();
  });
});
