import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import type { MatchPage as MatchPageData } from "../api/contracts";

const { loadMatchPage, loadLocalMatchPreview } = vi.hoisted(() => ({
  loadMatchPage: vi.fn(),
  loadLocalMatchPreview: vi.fn(),
}));

vi.mock("../api/client", () => ({
  loadMatchPage,
  loadLocalMatchPreview,
  MatchPageApiError: class MatchPageApiError extends Error {},
}));

import { MatchPage } from "../components/MatchPage";

afterEach(cleanup);

function page(publicationStatus: "approved" | "preview_only"): MatchPageData {
  const details: NonNullable<MatchPageData["details"]> = {
    publication_status: publicationStatus,
    validation_status: "valid",
    source: "BDFutbol",
    internal_id: "pf-2026-27-group-ii-bdfutbol-272582",
    source_match_id: "272582",
    source_generation_id: "match-00-test",
    source_capture_id: "capture-II",
    source_html_sha256: "a".repeat(64),
    match_date: "2026-10-10",
    home_team_id: 49,
    away_team_id: 94,
    home_goals: 3,
    away_goals: 3,
    home: {
      team_id: 49,
      coach: { coach_id: 1, display_name: "Manolo Herrero", profile_url: null, photo_url: null },
      starters: [{
        player_id: 1001, display_name: "Siverio", profile_url: "https://www.bdfutbol.com/es/j/j1001.html",
        photo_url: "https://www.bdfutbol.com/i/m/1001.jpg", shirt_number: 9, position: null,
        role: "starter", participation_status: "not_applicable", player_profile_available: true,
      }],
      substitutes: [{
        player_id: 1002, display_name: "Suplente", profile_url: null, photo_url: null, shirt_number: 18,
        position: null, role: "substitute", participation_status: "entered", player_profile_available: false,
      }, {
        player_id: 1003, display_name: "Sin entrada", profile_url: null, photo_url: null, shirt_number: 19,
        position: null, role: "substitute", participation_status: "no_entry_marker", player_profile_available: true,
      }],
    },
    away: { team_id: 94, coach: null, starters: null, substitutes: null },
    events: [
      { event_kind: "goal", minute: "83", team_id: 94, player_id: 2001, player_name: "Ayman", related_player_id: null, related_player_name: null, is_penalty: false, is_own_goal: false, score_after_home: 2, score_after_away: 3, player_profile_available: true, related_player_profile_available: false },
      { event_kind: "penalty", minute: "15", team_id: 49, player_id: 1001, player_name: "Siverio", related_player_id: null, related_player_name: null, is_penalty: true, is_own_goal: false, score_after_home: 1, score_after_away: 1, player_profile_available: true, related_player_profile_available: false },
      { event_kind: "substitution_in", minute: "90+1", team_id: 49, player_id: 1002, player_name: "Suplente", related_player_id: null, related_player_name: null, is_penalty: null, is_own_goal: null, score_after_home: null, score_after_away: null, player_profile_available: false, related_player_profile_available: false },
      { event_kind: "substitution_out", minute: "90+1", team_id: 49, player_id: 1001, player_name: "Siverio", related_player_id: null, related_player_name: null, is_penalty: null, is_own_goal: null, score_after_home: null, score_after_away: null, player_profile_available: true, related_player_profile_available: false },
    ],
  };
  return {
    metadata: {
      contract_version: 2, source: "BDFutbol", competition: "Primera Federación", season: "2026-27",
      group: "II", generation_id: "match-00-test", generation_sha256: "b".repeat(64),
      source_capture_id: "capture-II", source_captured_at: "2026-10-14T10:00:00Z",
    },
    match: {
      internal_id: "pf-2026-27-group-ii-bdfutbol-272582", source_match_id: "272582", matchday: 7,
      matchday_date: "2026-10-10", source_match_date: "2026-10-10",
      home_team: { team_id: 49, name: "Real Jaén", team_url: null, crest_url: null },
      away_team: { team_id: 94, name: "Villarreal B", team_url: null, crest_url: null },
      home_goals: 3, away_goals: 3, status: "played", unplayed_state: null,
      stadium_name: "La Victoria", stadium_url: null, referee_name: "Campos Salinas", referee_url: null,
      source_match_url: "https://www.bdfutbol.com/es/p/p.php?id=272582",
    },
    detail_status: publicationStatus === "approved" ? "available" : "preview_only",
    details,
  };
}

describe("MatchPage details", () => {
  beforeEach(() => {
    loadMatchPage.mockReset();
    loadLocalMatchPreview.mockReset();
    loadMatchPage.mockResolvedValue(page("approved"));
    loadLocalMatchPreview.mockResolvedValue(page("preview_only"));
  });

  it("renders a clearly local preview, photos, verified internal links and separate substitutions", async () => {
    const onNavigate = vi.fn();
    const { container } = render(<MatchPage
      internalId="pf-2026-27-group-ii-bdfutbol-272582"
      localPreview
      onNavigate={onNavigate}
      onReturnToResults={vi.fn()}
    />);

    expect(await screen.findByText("Vista previa local · datos exploratorios, no publicados")).toBeInTheDocument();
    expect(loadLocalMatchPreview).toHaveBeenCalledWith("pf-2026-27-group-ii-bdfutbol-272582");
    expect(screen.getAllByRole("link", { name: "Siverio" })[0]).toHaveAttribute("href", "/players/1001");
    const lineupRows = Array.from(container.querySelectorAll(".match-lineup-side li"));
    expect(lineupRows.find((row) => row.textContent?.includes("Suplente"))).toHaveTextContent("Entró");
    expect(lineupRows.find((row) => row.textContent?.includes("Sin entrada"))).toHaveTextContent("Sin entrada registrada");
    expect(container.querySelector('img[src="https://www.bdfutbol.com/i/m/1001.jpg"]')).toBeInTheDocument();

    const timeline = container.querySelector(".match-events");
    expect(timeline).not.toBeNull();
    const events = within(timeline).getAllByRole("listitem");
    expect(events[0]).toHaveTextContent("15");
    expect(events[0]).toHaveTextContent("Gol de penalti");
    expect(events[0]).toHaveTextContent("1–1");
    expect(events[2]).toHaveTextContent("90+1");
    expect(events[2]).toHaveTextContent("Entró");
    expect(events[3]).toHaveTextContent("90+1");
    expect(events[3]).toHaveTextContent("Salió");
    expect(screen.queryByText(/↔/)).not.toBeInTheDocument();
  });

  it("uses the public endpoint by default", async () => {
    render(<MatchPage
      internalId="pf-2026-27-group-ii-bdfutbol-272582"
      onNavigate={vi.fn()}
      onReturnToResults={vi.fn()}
    />);
    await waitFor(() => expect(loadMatchPage).toHaveBeenCalledWith("pf-2026-27-group-ii-bdfutbol-272582"));
    expect(loadLocalMatchPreview).not.toHaveBeenCalled();
  });

  it("renders an approved 272525 publication through the normal public page", async () => {
    const published = page("approved");
    const internalId = "pf-2026-27-group-ii-bdfutbol-272525";
    published.match.internal_id = internalId;
    published.match.source_match_id = "272525";
    published.match.home_team = { team_id: 204, name: "Teruel", team_url: null, crest_url: null };
    published.match.away_team = { team_id: 61, name: "Real Madrid Castilla", team_url: null, crest_url: null };
    published.match.home_goals = 0;
    published.match.away_goals = 0;
    published.match.status = "played";
    published.details!.internal_id = internalId;
    published.details!.source_match_id = "272525";
    published.details!.home_team_id = 204;
    published.details!.away_team_id = 61;
    published.details!.home_goals = 0;
    published.details!.away_goals = 0;

    const makePlayer = (playerId: number, role: "starter" | "substitute", team: string) => ({
      player_id: playerId,
      display_name: `${team} ${role} ${playerId}`,
      profile_url: null,
      photo_url: null,
      shirt_number: playerId % 30,
      position: null,
      role,
      participation_status: role === "starter" ? "not_applicable" as const : "no_entry_marker" as const,
      player_profile_available: false,
    });
    published.details!.home.coach = {
      coach_id: 5001, display_name: "Entrenador Teruel", profile_url: null, photo_url: null,
    };
    published.details!.away.coach = {
      coach_id: 5002, display_name: "Entrenador Castilla", profile_url: null, photo_url: null,
    };
    published.details!.home.starters = Array.from({ length: 11 }, (_, index) => makePlayer(3000 + index, "starter", "Teruel"));
    published.details!.away.starters = Array.from({ length: 11 }, (_, index) => makePlayer(3100 + index, "starter", "Castilla"));
    published.details!.home.substitutes = Array.from({ length: 7 }, (_, index) => makePlayer(3200 + index, "substitute", "Teruel"));
    published.details!.away.substitutes = Array.from({ length: 10 }, (_, index) => makePlayer(3300 + index, "substitute", "Castilla"));

    type Event = NonNullable<NonNullable<MatchPageData["details"]>["events"]>[number];
    const makeEvent = (event_kind: Event["event_kind"], minute: string, team_id: number): Event => ({
      event_kind, minute, team_id, player_id: null, player_name: null,
      related_player_id: null, related_player_name: null, is_penalty: null,
      is_own_goal: null, score_after_home: null, score_after_away: null,
      player_profile_available: false, related_player_profile_available: false,
    });
    published.details!.events = [
      ...Array.from({ length: 9 }, (_, index) => makeEvent("substitution_in", `${10 + index}`, 204)),
      ...Array.from({ length: 9 }, (_, index) => makeEvent("substitution_out", `${10 + index}`, 204)),
      ...Array.from({ length: 4 }, (_, index) => makeEvent("yellow_card", `${60 + index}`, 61)),
      makeEvent("red_card", "80", 61),
      makeEvent("missed_penalty", "43", 204),
    ];
    loadMatchPage.mockResolvedValue(published);

    const { container } = render(<MatchPage
      internalId={internalId}
      onNavigate={vi.fn()}
      onReturnToResults={vi.fn()}
    />);

    expect(await screen.findByLabelText("Resultado 0 a 0")).toBeInTheDocument();
    expect(loadMatchPage).toHaveBeenCalledWith(internalId);
    expect(loadLocalMatchPreview).not.toHaveBeenCalled();
    expect(screen.queryByText(/Vista previa local/)).not.toBeInTheDocument();
    expect(screen.getByText("Entrenador Teruel")).toBeInTheDocument();
    expect(screen.getByText("Entrenador Castilla")).toBeInTheDocument();
    expect(screen.getByText("Penalti fallado")).toBeInTheDocument();
    expect(container.querySelectorAll(".match-lineup-side ul li")).toHaveLength(39);
    expect(container.querySelectorAll(".match-events li")).toHaveLength(24);
    expect(screen.queryByText("Los detalles de este encuentro todavía no están disponibles.")).not.toBeInTheDocument();
  });

  it("renders a local 0–0 preview and a missed-penalty event", async () => {
    const zeroScorePreview = page("preview_only");
    zeroScorePreview.match.home_goals = 0;
    zeroScorePreview.match.away_goals = 0;
    zeroScorePreview.details!.home_goals = 0;
    zeroScorePreview.details!.away_goals = 0;
    zeroScorePreview.details!.events = [{
      event_kind: "missed_penalty",
      minute: "43",
      team_id: 94,
      player_id: 2001,
      player_name: "Rachad",
      related_player_id: null,
      related_player_name: null,
      is_penalty: true,
      is_own_goal: false,
      score_after_home: null,
      score_after_away: null,
      player_profile_available: true,
      related_player_profile_available: false,
    }];
    loadLocalMatchPreview.mockResolvedValue(zeroScorePreview);

    render(<MatchPage
      internalId="pf-2026-27-group-ii-bdfutbol-272525"
      localPreview
      onNavigate={vi.fn()}
      onReturnToResults={vi.fn()}
    />);

    expect(await screen.findByLabelText("Resultado 0 a 0")).toBeInTheDocument();
    expect(screen.getByText("Penalti fallado")).toBeInTheDocument();
    expect(screen.getByText("Rachad")).toBeInTheDocument();
  });
});
