import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MatchGenerationRecord, Team } from "../api/contracts";
import { ResultsSection } from "../components/ResultsSection";

afterEach(cleanup);

const teams: Team[] = [
  { team_id: 1, name: "Local", team_url: null, crest_url: null },
  { team_id: 2, name: "Visitante", team_url: null, crest_url: null },
];

function match(kickoffTime: string | null): MatchGenerationRecord {
  return {
    internal_id: "pf-2026-27-group-i-bdfutbol-272525",
    source_match_id: "272525",
    matchday: 1,
    matchday_date: "2026-08-29",
    source_match_date: "2026-08-29",
    kickoff_time_local: kickoffTime,
    home_team_id: 1,
    away_team_id: 2,
    home_goals: 1,
    away_goals: 0,
    home_yellow_cards: null,
    away_yellow_cards: null,
    home_red_cards: null,
    away_red_cards: null,
    status: "played",
    unplayed_state: null,
    postponed_by_source_rule: null,
    source_match_url: "https://www.bdfutbol.com/es/p/p.php?id=272525",
    stadium_id: null,
    stadium_name: null,
    stadium_url: null,
    referee_id: null,
    referee_name: null,
    referee_url: null,
  };
}

function renderResults(kickoffTime: string | null) {
  return render(<ResultsSection
    data={{
      metadata: {
        group: "I", captured_at: "2026-10-14T10:00:00Z", scheduled_matchdays: [1],
        counts: { teams: 2, matches: 1, played: 1, unplayed: 0, incomplete: 0 },
      },
      teams,
      matches: [match(kickoffTime)],
    }}
    matchday={"all"}
    onMatchdayChange={vi.fn()}
    onNavigate={vi.fn()}
  />);
}

describe("ResultsSection match date and kickoff", () => {
  it("shows an observed local time with a machine-readable date-time", () => {
    const { container } = renderResults("19:15");
    const time = container.querySelector(".result-date time");
    expect(time).toHaveAttribute("datetime", "2026-08-29T19:15");
    expect(time).toHaveTextContent("19:15");
  });

  it("does not add a time when the fixture has no verified value", () => {
    renderResults(null);
    expect(screen.queryByText(/19:15/)).not.toBeInTheDocument();
  });
});
