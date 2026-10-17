import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PlayerDirectory } from "../api/contracts";
import { PlayersPage } from "../components/PlayersPage";

const api = vi.hoisted(() => ({
  loadPlayerDirectory: vi.fn(),
  loadPlayerDetail: vi.fn(),
}));

vi.mock("../api/client", () => api);

describe("PlayersPage directory presentation", () => {
  beforeEach(() => vi.clearAllMocks());

  it("does not show acquisition, inventory, or membership diagnostics in public player listings", async () => {
    api.loadPlayerDirectory.mockResolvedValue({
      metadata: {
        season: "2026-27", inventory_generated_at: "2026-10-17T00:00:00Z",
        inventory_player_count: 1709, complete_individual_profile_count: 1708,
        partial_individual_profile_count: 0, inventory_only_count: 1,
        roster_membership_count: 1200, transfer_only_count: 509,
        compact_generation_id: "generation-internal", compact_generated_at: "2026-10-17T00:00:00Z",
        inventory_sha256: "a".repeat(64),
      },
      available_teams: [{ team_id: 49, team_name: "Jaén", group: "II" }],
      query: "", group: null, team_id: null, page: 1, page_size: 25, total: 1,
      players: [{
        player_id: 23751, display_name: "Manu Pedreño", full_name: "Antonio Manuel Moñino Pedreño",
        profile_url: null, photo_url: null, birth_date: null, age_years: null,
        nationality: null, position_name: "Central", groups: ["I", "II"],
        association_status: "roster_membership_observed", profile_status: "four_views_verified",
        team_associations: [{ team_id: 49, team_name: "Jaén", group: "II", evidence_types: ["membership"] }],
      }],
    } satisfies PlayerDirectory);

    render(<PlayersPage playerId={null} onNavigate={() => undefined} />);

    expect(await screen.findByRole("link", { name: /Manu Pedreño/ })).toBeTruthy();
    expect(document.body.textContent).toContain("Jaén · II");
    expect(document.body.textContent).not.toMatch(/vistas publicadas|perfil compacto|inventario generado|IDs inventariados|pertenencia observada|transferencia/iu);
    expect(document.body.textContent).not.toMatch(/captura|SHA-256|generación-internal|acquisition|procedencia/iu);
  });
});
