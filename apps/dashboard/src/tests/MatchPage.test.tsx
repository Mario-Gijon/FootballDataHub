import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { MatchPage as MatchPageData, TeamRoster } from "../api/contracts";

const globalStyles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

const { loadMatchPage, loadLocalMatchPreview, loadTeamRoster } = vi.hoisted(() => ({
  loadMatchPage: vi.fn(),
  loadLocalMatchPreview: vi.fn(),
  loadTeamRoster: vi.fn(),
}));

vi.mock("../api/client", () => ({
  loadMatchPage,
  loadLocalMatchPreview,
  loadTeamRoster,
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

function pendingPage(group: "I" | "II", homeTeamId: number, awayTeamId: number, sourceMatchId: string): MatchPageData {
  const pending = page("approved");
  const internalId = `pf-2026-27-group-${group.toLocaleLowerCase("en-US")}-bdfutbol-${sourceMatchId}`;
  pending.metadata.group = group;
  pending.match.internal_id = internalId;
  pending.match.source_match_id = sourceMatchId;
  pending.match.home_team = { team_id: homeTeamId, name: `Local ${homeTeamId}`, team_url: null, crest_url: null };
  pending.match.away_team = { team_id: awayTeamId, name: `Visitante ${awayTeamId}`, team_url: null, crest_url: null };
  pending.match.home_goals = null;
  pending.match.away_goals = null;
  pending.match.status = "unplayed";
  pending.match.unplayed_state = "scheduled";
  pending.details = null;
  pending.detail_status = "not_available";
  return pending;
}

function expectedRoster(teamId: number, group: "I" | "II" = "II"): TeamRoster {
  const starterId = teamId * 100 + 1;
  const substituteId = teamId * 100 + 2;
  return {
    status: "available",
    metadata: {
      contract_version: 2, validation_status: "valid", source: "BDFutbol",
      url: `https://www.bdfutbol.com/es/t/t2026-271rf${group === "I" ? "1" : "2"}.html`,
      competition: "Primera Federación", season: "2026-27", group, team_id: teamId,
      capture_id: `team-${teamId}`, captured_at: "2026-10-14T10:00:00Z",
      extractor_version: "test", content_sha256: "a".repeat(64),
    },
    team: { team_id: teamId, name: `Equipo ${teamId}`, team_url: `https://www.bdfutbol.com/es/t/t2026-271rf${group === "I" ? "1" : "2"}.html`, crest_url: null },
    coaches: [],
    players: [
      {
        player_id: starterId, display_name: `Titular ${teamId}`, full_name: null,
        profile_url: `https://www.bdfutbol.com/es/j/j${starterId}.html`,
        photo_url: `https://www.bdfutbol.com/i/m/${starterId}.jpg`, age_years: null,
        birth_date: null, birthplace: null, birthplace_province: null,
        nationality_flag_url: null, source_position_code: null, verified_indicators: [], source_views: [],
      },
      {
        player_id: substituteId, display_name: `Suplente ${teamId}`, full_name: null,
        profile_url: null, photo_url: null, age_years: null, birth_date: null,
        birthplace: null, birthplace_province: null, nationality_flag_url: null,
        source_position_code: null, verified_indicators: [], source_views: [],
      },
    ],
    memberships: [
      { player_id: starterId, team_id: teamId, season: "2026-27", competition: "Primera Federación", group, jersey_number: 7, squad_group_label: "Titulares", source_views: [] },
      { player_id: substituteId, team_id: teamId, season: "2026-27", competition: "Primera Federación", group, jersey_number: 18, squad_group_label: "Suplentes", source_views: [] },
    ],
    statistics: [],
    squad_groups: [
      { label: "Titulares", player_ids: [starterId] },
      { label: "Suplentes", player_ids: [substituteId] },
    ],
    tactical_visualization: null,
    source_views: [],
    warnings: [],
  } as TeamRoster;
}

type MatchEvent = NonNullable<NonNullable<MatchPageData["details"]>["events"]>[number];

function event(kind: MatchEvent["event_kind"], minute: string | null, teamId: number, playerId: number | null = null, playerName: string | null = null): MatchEvent {
  return {
    event_kind: kind, minute, team_id: teamId, player_id: playerId, player_name: playerName,
    related_player_id: null, related_player_name: null, is_penalty: null, is_own_goal: null,
    score_after_home: null, score_after_away: null, player_profile_available: false,
    related_player_profile_available: false,
  };
}

describe("MatchPage details", () => {
  beforeEach(() => {
    loadMatchPage.mockReset();
    loadLocalMatchPreview.mockReset();
    loadTeamRoster.mockReset();
    loadMatchPage.mockResolvedValue(page("approved"));
    loadLocalMatchPreview.mockResolvedValue(page("preview_only"));
    loadTeamRoster.mockResolvedValue({ status: "not_captured" });
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
    expect(loadTeamRoster).not.toHaveBeenCalled();
    expect(screen.getAllByRole("link", { name: "Siverio" })[0]).toHaveAttribute("href", "/players/1001");
    const lineupRows = Array.from(container.querySelectorAll(".match-lineup-side li"));
    const enteredRow = lineupRows.find((row) => row.textContent?.includes("Suplente")) as HTMLElement;
    expect(within(enteredRow).getByLabelText("Entró, 90+1 minuto")).toBeInTheDocument();
    expect(enteredRow.querySelector(".match-event-glyph")).toHaveClass("is-substitution_in");
    const exitedRow = lineupRows.find((row) => row.textContent?.includes("Siverio")) as HTMLElement;
    expect(exitedRow.querySelector(".match-event-glyph.is-substitution_out")).toBeInTheDocument();
    const noEntryRow = lineupRows.find((row) => row.textContent?.includes("Sin entrada")) as HTMLElement;
    expect(noEntryRow).not.toHaveTextContent("Sin entrada registrada");
    expect(noEntryRow.querySelector(".match-participation-note")).not.toBeInTheDocument();
    expect(container.querySelector('img[src="https://www.bdfutbol.com/i/m/1001.jpg"]')).toBeInTheDocument();

    const timeline = container.querySelector(".match-events");
    expect(timeline).not.toBeNull();
    expect(container.querySelector(".match-highlights")).not.toBeInTheDocument();
    expect(screen.queryByText("Momentos del partido")).not.toBeInTheDocument();
    const events = within(timeline).getAllByRole("listitem");
    expect(events[0]).toHaveTextContent("15");
    expect(events[0]).toHaveTextContent("Gol de penalti");
    expect(events[0]).toHaveTextContent("1–1");
    expect(within(timeline).getByText("Gol")).toBeInTheDocument();
    expect(within(timeline).getByText("Gol de penalti")).toBeInTheDocument();
    const substitution = events.find((item) => item.classList.contains("match-substitution-row"));
    expect(substitution).toHaveTextContent("90+1");
    expect(substitution).toHaveTextContent("Entraron");
    expect(substitution).toHaveTextContent("Salieron");
    expect(substitution).toHaveTextContent("Suplente");
    expect(substitution).toHaveTextContent("Siverio");
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
    published.details!.home.team_id = 204;
    published.details!.away.team_id = 61;
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
    published.details!.home.starters[10]!.display_name = "Belevonis";
    published.details!.away.starters[0]!.display_name = "Rachad";
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
      ...Array.from({ length: 4 }, (_, index) => ({
        ...makeEvent("yellow_card", `${60 + index}`, 61), player_id: 3100 + index,
        player_name: `Castilla jugador ${index + 1}`, player_profile_available: true,
      })),
      { ...makeEvent("red_card", "90", 204), player_id: 3010, player_name: "Belevonis" },
      { ...makeEvent("missed_penalty", "43", 61), player_id: 3100, player_name: "Rachad" },
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
    expect(loadTeamRoster).not.toHaveBeenCalled();
    expect(screen.queryByText(/Vista previa local/)).not.toBeInTheDocument();
    expect(screen.getByText("Entrenador Teruel")).toBeInTheDocument();
    expect(screen.getByText("Entrenador Castilla")).toBeInTheDocument();
    expect(container.querySelector(".match-highlights")).not.toBeInTheDocument();
    expect(screen.queryByText("Momentos del partido")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".match-lineup-side")[1]?.querySelector(".match-player-row .match-event-yellow_card")).toBeInTheDocument();
    expect(container.querySelectorAll(".match-lineup-side")[0]?.querySelector(".match-player-row .match-event-red_card")).toBeInTheDocument();
    expect(container.querySelectorAll(".match-lineup-side ul li")).toHaveLength(39);
    expect(container.querySelector(".match-lineup-side .match-player-marker.match-event-missed_penalty .missed-penalty-cross")).toBeInTheDocument();
    expect(container.querySelectorAll(".match-events > li")).toHaveLength(15);
    expect(container.querySelector(".match-events .match-event-missed_penalty .match-event-glyph.is-missed_penalty .missed-penalty-cross")).toBeInTheDocument();
    expect(within(container.querySelector(".match-events") as HTMLElement).getByText("Penalti fallado")).toBeInTheDocument();
    expect(within(container.querySelector(".match-events") as HTMLElement).getByText("Expulsión")).toBeInTheDocument();
    expect(within(container.querySelector(".match-events") as HTMLElement).getAllByText("Tarjeta amarilla")).toHaveLength(4);
    expect(screen.getByText("24 acontecimientos")).toBeInTheDocument();
    expect(screen.queryByText("Los detalles de este encuentro todavía no están disponibles.")).not.toBeInTheDocument();
  });

  it("keeps match context, linked officials and provenance in the compact hero", async () => {
    const match = page("approved");
    match.match.matchday_date = "2026-10-10";
    match.match.source_match_date = "2026-10-12";
    match.match.stadium_name = "La Victoria";
    match.match.stadium_url = "https://www.bdfutbol.com/es/s/s49.html";
    match.match.referee_name = "Campos Salinas";
    match.match.referee_url = "https://www.bdfutbol.com/es/r/r123.html";
    loadMatchPage.mockResolvedValue(match);

    const { container } = render(<MatchPage internalId={match.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    await screen.findByRole("heading", { name: "Alineaciones" });

    const hero = container.querySelector(".match-page-hero") as HTMLElement;
    const scoreColumn = hero.querySelector(".match-page-score-column") as HTMLElement;
    expect(container.querySelector(".match-info-panel")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Información del partido" })).not.toBeInTheDocument();
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent("PRIMERA FEDERACIÓN · GRUPO II · TEMPORADA 2026/27");
    expect(hero).toHaveTextContent("PRIMERA FEDERACIÓN · GRUPO II · TEMPORADA 2026/27");
    expect(hero).toHaveTextContent("Jornada 7 · fecha 12 de octubre de 2026");
    expect(scoreColumn.children[0]).toHaveClass("match-finished-label");
    expect(scoreColumn.children[0]).toHaveTextContent("Finalizado");
    expect(scoreColumn.children[1]).toHaveClass("match-page-score");
    expect(hero.querySelector(".match-page-subtitle")).not.toHaveTextContent("Finalizado");
    expect(within(hero).getByText("Estadio")).toBeInTheDocument();
    expect(within(hero).getByText("Árbitro")).toBeInTheDocument();
    expect(within(hero).getByRole("link", { name: "La Victoria" })).toHaveAttribute("href", match.match.stadium_url);
    expect(within(hero).getByRole("link", { name: "Campos Salinas" })).toHaveAttribute("href", match.match.referee_url);
    expect(hero).not.toHaveTextContent("Datos actualizados");
    const sourceLink = within(hero).getByRole("link", { name: "Ficha en BDFutbol ↗" });
    expect(sourceLink).toHaveAttribute("href", match.match.source_match_url);
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink).toHaveAttribute("rel", "noreferrer");
    expect(hero.querySelectorAll(".match-page-context")).toHaveLength(1);
  });

  it("shows non-official reference lineups for an unplayed Group I match using only roster IDs", async () => {
    const pending = pendingPage("I", 48, 49, "270001");
    loadMatchPage.mockResolvedValue(pending);
    loadTeamRoster.mockImplementation(async (teamId: number) => ({
      status: "available",
      roster: expectedRoster(teamId, "I"),
    }));

    const { container } = render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Titular 48")).toBeInTheDocument();
    expect(screen.getByText("Suplente 49")).toBeInTheDocument();
    expect(screen.getByText("Alineación esperada")).toBeInTheDocument();
    expect(screen.getByText("Basada en las plantillas publicadas de los equipos. No es una alineación oficial ni una convocatoria confirmada para este encuentro.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Titular 48" })).toHaveAttribute("href", "/players/4801");
    expect(container.querySelector('img[src="https://www.bdfutbol.com/i/m/4801.jpg"]')).toBeInTheDocument();
    expect(container.querySelectorAll(".match-expected-side")).toHaveLength(2);
    expect(container.querySelectorAll(".match-expected-side .match-player-row")).toHaveLength(4);
    expect(container.querySelector(".match-timeline")).not.toBeInTheDocument();
    expect(container.querySelector(".match-events")).not.toBeInTheDocument();
    expect(screen.queryByText("Cronología")).not.toBeInTheDocument();
    expect(screen.queryByText("Finalizado")).not.toBeInTheDocument();
    expect(loadTeamRoster).toHaveBeenCalledTimes(2);
    expect(loadTeamRoster).toHaveBeenCalledWith(48, "2026-27");
    expect(loadTeamRoster).toHaveBeenCalledWith(49, "2026-27");
  });

  it("keeps the available team when the opponent roster was not captured", async () => {
    const pending = pendingPage("II", 49, 94, "270002");
    loadMatchPage.mockResolvedValue(pending);
    loadTeamRoster.mockImplementation(async (teamId: number) => teamId === 49
      ? { status: "available", roster: expectedRoster(teamId) }
      : { status: "not_captured" });

    render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Titular 49")).toBeInTheDocument();
    expect(screen.getByLabelText("Alineación esperada de Visitante 94")).toBeInTheDocument();
    expect(screen.getByText("No hay plantilla de referencia disponible para este equipo.")).toBeInTheDocument();
  });

  it("shows one availability notice when neither reference roster exists", async () => {
    const pending = pendingPage("II", 49, 94, "270003");
    loadMatchPage.mockResolvedValue(pending);

    const { container } = render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("No hay alineaciones orientativas disponibles para este encuentro.")).toBeInTheDocument();
    expect(container.querySelectorAll(".match-expected-empty")).toHaveLength(1);
    expect(container.querySelectorAll(".match-expected-side")).toHaveLength(0);
    expect(screen.getByLabelText("Partido pendiente")).toBeInTheDocument();
  });

  it("never renders match events for an unplayed fixture even if details are present in the payload", async () => {
    const pending = pendingPage("II", 49, 94, "270008");
    pending.details = page("approved").details;
    pending.detail_status = "available";
    loadMatchPage.mockResolvedValue(pending);

    const { container } = render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("No hay alineaciones orientativas disponibles para este encuentro.")).toBeInTheDocument();
    expect(container.querySelector(".match-timeline, .match-events, .match-lineups")).not.toBeInTheDocument();
    expect(screen.queryByText("Entrenador Teruel")).not.toBeInTheDocument();
    expect(loadTeamRoster).toHaveBeenCalledTimes(2);
  });

  it("isolates one roster request error without hiding the other team or the match", async () => {
    const pending = pendingPage("II", 49, 94, "270004");
    loadMatchPage.mockResolvedValue(pending);
    loadTeamRoster.mockImplementation(async (teamId: number) => {
      if (teamId === 94) throw new Error("offline request failure");
      return { status: "available", roster: expectedRoster(teamId) };
    });

    render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Titular 49")).toBeInTheDocument();
    expect(screen.getByText("No se pudo cargar la plantilla de referencia.")).toBeInTheDocument();
    expect(screen.getByLabelText("Partido pendiente")).toBeInTheDocument();
    expect(screen.queryByText("offline request failure")).not.toBeInTheDocument();
  });

  it("preserves sparse roster groups, absent photos and jerseys without inventing players", async () => {
    const pending = pendingPage("II", 49, 94, "270005");
    const sparse = expectedRoster(49);
    const onlyPlayer = sparse.players[0]!;
    onlyPlayer.photo_url = null;
    onlyPlayer.profile_url = null;
    sparse.players = [onlyPlayer];
    sparse.memberships = [{ ...sparse.memberships[0]!, jersey_number: null }];
    sparse.squad_groups = [{ label: "Titulares", player_ids: [onlyPlayer.player_id] }];
    loadMatchPage.mockResolvedValue(pending);
    loadTeamRoster.mockImplementation(async (teamId: number) => teamId === 49
      ? { status: "available", roster: sparse }
      : { status: "not_captured" });

    const { container } = render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Titular 49")).toBeInTheDocument();
    const homeSide = container.querySelector(".match-expected-side") as HTMLElement;
    expect(homeSide.querySelectorAll(".match-player-row")).toHaveLength(1);
    expect(within(homeSide).getByLabelText("Sin fotografía para Titular 49")).toBeInTheDocument();
    expect(within(homeSide).queryByRole("link", { name: "Titular 49" })).not.toBeInTheDocument();
    expect(homeSide).not.toHaveTextContent("7");
    expect(within(homeSide).getByText("La captura no publica esta agrupación.")).toBeInTheDocument();
  });

  it("does not carry expected rosters across match navigation", async () => {
    const first = pendingPage("I", 48, 49, "270006");
    const second = pendingPage("II", 204, 61, "270007");
    loadMatchPage.mockImplementation(async (internalId: string) => internalId === first.match.internal_id ? first : second);
    loadTeamRoster.mockImplementation(async (teamId: number) => ({ status: "available", roster: expectedRoster(teamId, teamId === 48 ? "I" : "II") }));
    const { rerender } = render(<MatchPage internalId={first.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Titular 48")).toBeInTheDocument();

    rerender(<MatchPage internalId={second.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Titular 204")).toBeInTheDocument();
    expect(screen.queryByText("Titular 48")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Local 204" })).toBeInTheDocument();
  });

  it("omits absent officials and labels the matchday date when the real date is unavailable", async () => {
    const match = page("approved");
    match.match.source_match_date = null;
    match.match.stadium_name = null;
    match.match.stadium_url = null;
    match.match.referee_name = null;
    match.match.referee_url = null;
    match.match.source_match_url = null;
    loadMatchPage.mockResolvedValue(match);

    const { container } = render(<MatchPage internalId={match.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    await screen.findByRole("heading", { name: "Alineaciones" });

    const hero = container.querySelector(".match-page-hero") as HTMLElement;
    expect(hero).toHaveTextContent("Jornada 7 · fecha de jornada 10 de octubre de 2026");
    expect(hero.querySelector(".match-page-officials")).not.toBeInTheDocument();
    expect(within(hero).queryByRole("link", { name: "La Victoria" })).not.toBeInTheDocument();
    expect(within(hero).queryByRole("link", { name: "Campos Salinas" })).not.toBeInTheDocument();
    expect(hero).not.toHaveTextContent("Datos actualizados");
    expect(hero).not.toHaveTextContent("Fuente: BDFutbol");
    expect(hero.querySelector(".match-page-provenance")).not.toBeInTheDocument();
    expect(within(hero).queryByRole("link", { name: /Ficha en BDFutbol/ })).not.toBeInTheDocument();
  });

  it("keeps an entered substitute without a verifiable minute and leaves no-entry substitutes unmarked", async () => {
    const preview = page("preview_only");
    preview.details!.events = preview.details!.events!.filter((item) => item.event_kind !== "substitution_in");
    loadLocalMatchPreview.mockResolvedValue(preview);

    const { container } = render(<MatchPage
      internalId={preview.match.internal_id}
      localPreview
      onNavigate={vi.fn()}
      onReturnToResults={vi.fn()}
    />);
    await screen.findByRole("heading", { name: "Alineaciones" });

    const rows = Array.from(container.querySelectorAll(".match-lineup-side li"));
    const entered = rows.find((row) => row.textContent?.includes("Suplente")) as HTMLElement;
    const noEntry = rows.find((row) => row.textContent?.includes("Sin entrada")) as HTMLElement;
    expect(entered).toHaveTextContent("Entrada registrada");
    expect(entered.querySelector(".match-player-marker.match-event-substitution_in")).not.toBeInTheDocument();
    expect(noEntry).not.toHaveTextContent("Sin entrada registrada");
    expect(noEntry.querySelector(".match-participation-note")).not.toBeInTheDocument();
  });

  it("applies the subtle green timeline border only to goal events", () => {
    expect(globalStyles).toMatch(/\.match-event-row\.match-event-goal,\s*\.match-event-row\.match-event-penalty,\s*\.match-event-row\.match-event-own_goal\s*\{\s*border-color:\s*rgb\(102 186 133 \/ 16%\)/);
    expect(globalStyles).not.toMatch(/\.match-event-row\.match-event-(?:missed_penalty|yellow_card|red_card|second_yellow)[^{]*\{[^}]*border-color:/);
    expect(globalStyles).not.toMatch(/\.match-event-row\.match-substitution-row[^}]*border-color:/);
    expect(globalStyles).toMatch(/\.match-event-row\s*\{[^}]*border:\s*1px solid transparent/);
  });

  it("uses distinct accessible SVGs for goals, scored penalties, missed penalties and own goals", async () => {
    const match = page("approved");
    match.details!.events = [
      { ...event("goal", "10", 49, 1001, "Siverio"), is_penalty: false, is_own_goal: false },
      { ...event("penalty", "20", 49, 1001, "Siverio"), is_penalty: true, is_own_goal: false },
      { ...event("missed_penalty", "30", 49, 1001, "Siverio"), is_penalty: true, is_own_goal: false },
      { ...event("own_goal", "40", 94, 2001, "Ayman"), is_penalty: false, is_own_goal: true },
    ];
    loadMatchPage.mockResolvedValue(match);

    const { container } = render(<MatchPage internalId={match.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    await screen.findByRole("heading", { name: "Cronología" });

    const glyph = (kind: string) => container.querySelector(`.match-events .match-event-${kind} .match-event-glyph`) as SVGSVGElement;
    const goal = glyph("goal");
    const penalty = glyph("penalty");
    const missedPenalty = glyph("missed_penalty");
    const ownGoal = glyph("own_goal");
    expect(goal.tagName.toLowerCase()).toBe("svg");
    expect(goal.querySelector("circle")).toBeInTheDocument();
    expect(goal.querySelector(".penalty-goal-frame")).not.toBeInTheDocument();
    expect(penalty).toHaveClass("is-penalty");
    expect(penalty.querySelector(".penalty-goal-frame")).toBeInTheDocument();
    expect(penalty.querySelector(".penalty-ball")).toBeInTheDocument();
    expect(missedPenalty).toHaveClass("is-missed_penalty");
    expect(missedPenalty.querySelector(".penalty-goal-frame")?.getAttribute("d"))
      .toBe(penalty.querySelector(".penalty-goal-frame")?.getAttribute("d"));
    expect(missedPenalty.querySelector(".penalty-ball")?.getAttribute("r"))
      .toBe(penalty.querySelector(".penalty-ball")?.getAttribute("r"));
    expect(missedPenalty.querySelector(".missed-penalty-cross")).toBeInTheDocument();
    expect(missedPenalty.textContent).not.toContain("!");
    expect(ownGoal).toHaveClass("is-own_goal");
    expect(ownGoal.querySelector(".own-goal-direction")).toBeInTheDocument();
    expect(screen.getAllByText("Gol en propia puerta").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Gol de penalti, 20 minuto")).toBeInTheDocument();
    expect(screen.getByLabelText("Penalti fallado, 30 minuto")).toBeInTheDocument();
    expect(container.querySelector(".match-player-marker.match-event-penalty")).toHaveAttribute("title", "Gol de penalti, 20 minuto");
    expect(container.querySelector(".match-player-marker.match-event-missed_penalty")).toHaveAttribute("title", "Penalti fallado, 30 minuto");
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
    expect(screen.getAllByText("Penalti fallado").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Rachad")).toHaveLength(1);
  });

  it("orders added-time events stably and preserves every source event", async () => {
    const match = page("approved");
    match.details!.events = [
      event("yellow_card", "45+2", 49, 1001, "Siverio"),
      event("goal", "45", 94, null, "Gol sin ID"),
      event("second_yellow", "45+2", 94, null, "Expulsado"),
      event("own_goal", "90+6", 49, null, "Autogol"),
      event("missed_penalty", null, 94, null, "Sin minuto"),
    ];
    loadMatchPage.mockResolvedValue(match);
    const { container } = render(<MatchPage internalId={match.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    await screen.findByRole("heading", { name: "Cronología" });
    const rows = Array.from(container.querySelectorAll(".match-events > li"));
    expect(rows).toHaveLength(5);
    expect(rows.map((row) => row.querySelector("time")?.textContent)).toEqual(["45", "45+2", "45+2", "90+6", "—"]);
    expect(rows[1]).toHaveTextContent("Tarjeta amarilla");
    expect(rows[2]).toHaveTextContent("Segunda amarilla · expulsión");
    expect(rows[3]).toHaveTextContent("Gol en propia puerta");
    expect(rows[4]).toHaveTextContent("Penalti fallado");
  });

  it("annotates lineup players only when both team ID and verified player ID match", async () => {
    const match = page("approved");
    match.details!.events = [
      { ...event("goal", "24", 49, 1001, "Siverio"), player_profile_available: false },
      { ...event("yellow_card", "55", 94, 1001, "Nombre coincidente"), player_profile_available: true },
      event("substitution_in", "60", 49, null, "Sin ID"),
    ];
    loadMatchPage.mockResolvedValue(match);
    const { container } = render(<MatchPage internalId={match.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    await screen.findByRole("heading", { name: "Alineaciones" });
    const homeRow = Array.from(container.querySelectorAll(".match-lineup-side")[0]!.querySelectorAll(".match-player-row"))
      .find((row) => row.textContent?.includes("Siverio"));
    expect(homeRow).toBeDefined();
    expect(within(homeRow as HTMLElement).getAllByLabelText("Gol, 24 minuto")).toHaveLength(1);
    expect(within(homeRow as HTMLElement).queryByLabelText("Tarjeta amarilla, 55 minuto")).not.toBeInTheDocument();
    expect(homeRow).not.toHaveTextContent("60");
  });

  it("groups multiple same-minute substitutions by team without pairing players", async () => {
    const match = page("approved");
    match.details!.events = [
      event("substitution_out", "60", 49, 4001, "Sale uno"),
      event("substitution_out", "60", 49, 4002, "Sale dos"),
      event("substitution_in", "60", 49, 4003, "Entra uno"),
      event("substitution_in", "60", 49, 4004, "Entra dos"),
      event("substitution_in", "60", 94, 5001, "Visitante entra"),
      event("substitution_out", "60", 94, 5002, "Visitante sale"),
    ];
    loadMatchPage.mockResolvedValue(match);
    const { container } = render(<MatchPage internalId={match.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    await screen.findByRole("heading", { name: "Cronología" });
    const rows = Array.from(container.querySelectorAll(".match-events > .match-substitution-row"));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Real Jaén");
    expect(rows[0]).toHaveTextContent("Sale uno");
    expect(rows[0]).toHaveTextContent("Sale dos");
    expect(rows[0]).toHaveTextContent("Entra uno");
    expect(rows[0]).toHaveTextContent("Entra dos");
    expect(rows[1]).toHaveTextContent("Villarreal B");
    expect(rows[1]).toHaveTextContent("Visitante sale");
    expect(rows[1]).toHaveTextContent("Visitante entra");
    expect(container.textContent).not.toContain("→");
    expect(rows[0]?.querySelectorAll(".match-substitution-list")).toHaveLength(2);
    expect(rows[0]?.querySelector(".match-event-glyph")).toHaveClass("is-substitution");
    expect(rows[0]?.querySelector(".match-substitution-list.is-outgoing > span")).toHaveTextContent("Salieron");
    expect(rows[0]?.querySelector(".match-substitution-list.is-incoming > span")).toHaveTextContent("Entraron");
    expect(rows.every((row) => !row.classList.contains("is-home") && !row.classList.contains("is-away"))).toBe(true);
  });

  it("does not claim a pending match is finished and shows one reference-lineup empty state", async () => {
    const pending = page("approved");
    pending.match.status = "unplayed";
    pending.match.home_goals = null;
    pending.match.away_goals = null;
    pending.match.unplayed_state = "scheduled";
    pending.details = null;
    pending.detail_status = "not_available";
    loadMatchPage.mockResolvedValue(pending);
    const { container } = render(<MatchPage internalId={pending.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Pendiente")).toBeInTheDocument();
    expect(screen.queryByText("Finalizado")).not.toBeInTheDocument();
    expect(container.querySelector(".match-page-score-column .match-finished-label")).not.toBeInTheDocument();
    expect(await screen.findByText("No hay alineaciones orientativas disponibles para este encuentro.")).toBeInTheDocument();
    expect(screen.queryByText("Los detalles de este encuentro todavía no están disponibles.")).not.toBeInTheDocument();
    expect(container.querySelector(".match-timeline, .match-events")).not.toBeInTheDocument();
  });

  it("keeps a played match without published details in its existing unavailable state", async () => {
    const played = page("approved");
    played.details = null;
    played.detail_status = "not_available";
    loadMatchPage.mockResolvedValue(played);

    const { container } = render(<MatchPage internalId={played.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Los detalles de este encuentro todavía no están disponibles.")).toBeInTheDocument();
    expect(screen.queryByText("Alineación esperada")).not.toBeInTheDocument();
    expect(container.querySelector(".match-details-panel, .match-timeline, .match-events")).not.toBeInTheDocument();
    expect(loadTeamRoster).not.toHaveBeenCalled();
  });

  it("does not replace the published played status with an expected lineup when its score is incomplete", async () => {
    const incompletePlayed = page("approved");
    incompletePlayed.match.status = "played";
    incompletePlayed.match.home_goals = null;
    incompletePlayed.match.away_goals = null;
    incompletePlayed.details = null;
    incompletePlayed.detail_status = "not_available";
    loadMatchPage.mockResolvedValue(incompletePlayed);

    const { container } = render(<MatchPage internalId={incompletePlayed.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Datos incompletos")).toBeInTheDocument();
    expect(screen.getByText("Finalizado")).toBeInTheDocument();
    expect(screen.queryByText("Alineación esperada")).not.toBeInTheDocument();
    expect(container.querySelector(".match-page-score-column .match-finished-label")).toBeInTheDocument();
    expect(loadTeamRoster).not.toHaveBeenCalled();
  });

  it("keeps incomplete matches incomplete and never requests expected rosters", async () => {
    const incomplete = page("approved");
    incomplete.match.status = "incomplete";
    incomplete.match.home_goals = null;
    incomplete.match.away_goals = null;
    incomplete.match.unplayed_state = null;
    incomplete.details = null;
    incomplete.detail_status = "not_available";
    loadMatchPage.mockResolvedValue(incomplete);
    const { container } = render(<MatchPage internalId={incomplete.match.internal_id} onNavigate={vi.fn()} onReturnToResults={vi.fn()} />);
    expect(await screen.findByText("Datos incompletos")).toBeInTheDocument();
    expect(screen.queryByText("Finalizado")).not.toBeInTheDocument();
    expect(screen.queryByText("Alineación esperada")).not.toBeInTheDocument();
    expect(container.querySelector(".match-page-score-column .match-finished-label")).not.toBeInTheDocument();
    expect(loadTeamRoster).not.toHaveBeenCalled();
  });
});
