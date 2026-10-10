import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import captureSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/metadata/capture.json";
import classificationSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/normalized/classification.json";
import matchesSource from "../../../../data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json";
import progressSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/normalized/progress.json";
import referenceSource from "../../../../data/exports/bdfutbol/group2_classification/derived-clas01b-20261010T102656Z/validation/bdfutbol_js_reference.json";
import topCapture from "../../../../data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/metadata/capture.json";
import topPlayers from "../../../../data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/normalized/players.json";
import topRankings from "../../../../data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/normalized/rankings.json";
import topProgress from "../../../../data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/normalized/progress.json";
import topForeigners from "../../../../data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/normalized/foreigners.json";
import refereeCapture from "../../../../data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc/metadata/capture.json";
import refereeCatalog from "../../../../data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc/normalized/referees.json";
import refereeStatistics from "../../../../data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc/normalized/statistics.json";
import refereeMatchReference from "../../../../data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc/validation/match_reference.json";
import statisticsCapture from "../../../../data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/metadata/capture.json";
import statisticsDerived from "../../../../data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/normalized/derived_statistics.json";
import statisticsExclusive from "../../../../data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/normalized/exclusive_statistics.json";
import statisticsReconciliation from "../../../../data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/validation/reconciliation.json";
import group1Capture from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/metadata/capture.json";
import group1Matches from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json";
import group1Classification from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/classification.json";
import group1Progress from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/progress.json";
import group1RefereeReference from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/validation/referee_reference.json";
import group1TopCapture from "../../../../data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/metadata/capture.json";
import group1TopPlayers from "../../../../data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/normalized/players.json";
import group1TopRankings from "../../../../data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/normalized/rankings.json";
import group1TopProgress from "../../../../data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/normalized/progress.json";
import group1TopForeigners from "../../../../data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/normalized/foreigners.json";
import group1TopValidation from "../../../../data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/validation/results.json";
import group1StatisticsCapture from "../../../../data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9/metadata/capture.json";
import group1StatisticsDerived from "../../../../data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9/normalized/derived_statistics.json";
import group1StatisticsExclusive from "../../../../data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9/normalized/exclusive_statistics.json";
import group1StatisticsReconciliation from "../../../../data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9/validation/reconciliation.json";
import { buildTopProgressData, TopSection } from "../components/TopSection";
import type { RefereeBootstrap, StatisticsBootstrap, TopBootstrap } from "../api/contracts";
import { RefereeBootstrapSchema, StatisticsBootstrapSchema } from "../api/contracts";
import App from "../App";

function toPublicMatches(source: typeof matchesSource) {
  return source.matches.map((match) => ({
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
}

const publicMatches = toPublicMatches(matchesSource);

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

const categoryBySourceValue: Record<string, string> = {
  "1": "goals", "2": "minutes", "3": "yellow_cards", "4": "red_cards", "8": "youngest", "9": "oldest",
};

const group1Bootstrap = {
  ...apiBootstrap,
  metadata: {
    ...apiBootstrap.metadata,
    url: group1Capture.url,
    group: "I",
    capture_id: group1Capture.capture_id,
    captured_at: group1Capture.captured_at_utc,
    dataset_version: `${group1Capture.capture_id}-test-fixture`,
    team_count: group1Matches.teams.length,
    last_matchday_with_results: group1Matches.metadata.played_matchdays_in_source,
    availability: {
      ...apiBootstrap.metadata.availability,
      teams: group1Matches.teams.length,
      matches: group1Matches.matches.length,
      played_matches: group1Matches.counts.played,
      unplayed_matches: group1Matches.counts.unplayed,
      incomplete_matches: group1Matches.counts.incomplete,
      last_matchday_with_results: group1Matches.metadata.played_matchdays_in_source,
      progress_records: group1Progress.records.length,
      progress_through_matchday: group1Progress.series_context.available_through_matchday,
    },
  },
  teams: group1Matches.teams,
  matches: toPublicMatches(group1Matches),
  progress: group1Progress.records,
  published_standings: {
    source: group1Classification.metadata.source,
    source_capture_id: group1Classification.metadata.capture_id,
    context: {
      classification_type: group1Classification.context.classification_type,
      matchday: group1Classification.context.matchday,
      matchday_date: group1Classification.context.matchday_date,
      postponed_policy: group1Classification.context.postponed_policy,
      range_type: group1Classification.context.range_type,
    },
    rows: group1Classification.standings.map((row) => ({
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
const topBootstrap = {
  metadata: {
    source: topCapture.source,
    url: topCapture.url,
    competition: topCapture.competition,
    season: topCapture.season,
    group: topCapture.group,
    section: "top",
    capture_id: topCapture.capture_id,
    captured_at: topCapture.captured_at_utc,
    extractor_version: topCapture.extractor_version,
    source_snapshot_sha256: topCapture.source_snapshot_sha256,
    related_team_capture_id: topCapture.related_team_catalog.source_capture_id,
    related_team_catalog_sha256: topCapture.related_team_catalog.sha256,
    active_team_capture_id: apiBootstrap.metadata.capture_id,
    dataset_version: `${topCapture.capture_id}-test-fixture`,
  },
  availability: {
    players: topPlayers.records.length,
    ranking_records: topRankings.records.length,
    progress_series: topProgress.records.length,
    progress_points: topProgress.records.reduce((count, series) => count + series.points.length, 0),
    foreign_players: topForeigners.records.length,
    categories: topRankings.category_source_counts,
    matchdays: topProgress.matchdays,
  },
  categories: topCapture.category_options.map((option) => ({
    source_value: option.value,
    category: categoryBySourceValue[option.value],
    label: option.label,
    available_count: topRankings.category_source_counts[categoryBySourceValue[option.value]],
    graph_available: ["goals", "minutes", "yellow_cards", "red_cards"].includes(categoryBySourceValue[option.value]),
    see_all_available: option.value === "1" && topCapture.see_all_available_for_goals,
  })),
  players: topPlayers.records,
  rankings: topRankings.records,
  progress: topProgress.records,
  foreigners: topForeigners.records.map((player, index) => ({
    player_id: player.player_id,
    statistics: {
      ...player.statistics,
      // Isolated UI fixture to distinguish a genuine zero from missing data.
      ...(index === 0 ? { matches_played: null } : {}),
    },
  })),
  foreigners_summary: {
    source_count: topForeigners.summary.source_count,
    source_percentage: topForeigners.summary.source_percentage,
    denominator_count: topForeigners.summary.denominator_count,
    country_options: topForeigners.summary.country_options.map(([code, label]) => ({ code, label })),
  },
  coverage_note: topRankings.coverage_note,
  warnings: [],
  affiliation_conflicts: [],
};

const group1TopBootstrap = {
  ...topBootstrap,
  metadata: {
    ...topBootstrap.metadata,
    url: group1TopCapture.url,
    group: "I",
    capture_id: group1TopCapture.capture_id,
    captured_at: group1TopCapture.captured_at_utc,
    source_snapshot_sha256: group1TopCapture.source_snapshot_sha256,
    related_team_capture_id: group1TopCapture.related_team_catalog.source_capture_id,
    related_team_catalog_sha256: group1TopCapture.related_team_catalog.sha256,
    active_team_capture_id: group1Bootstrap.metadata.capture_id,
    dataset_version: `${group1TopCapture.capture_id}-test-fixture`,
  },
  availability: {
    players: group1TopPlayers.records.length,
    ranking_records: group1TopRankings.records.length,
    progress_series: group1TopProgress.records.length,
    progress_points: group1TopProgress.records.reduce((count, series) => count + series.points.length, 0),
    foreign_players: group1TopForeigners.records.length,
    categories: group1TopRankings.category_source_counts,
    matchdays: group1TopProgress.matchdays,
  },
  categories: group1TopCapture.category_options.map((option) => ({
    source_value: option.value,
    category: categoryBySourceValue[option.value],
    label: option.label,
    available_count: group1TopRankings.category_source_counts[categoryBySourceValue[option.value]],
    graph_available: ["goals", "minutes", "yellow_cards", "red_cards"].includes(categoryBySourceValue[option.value]),
    see_all_available: option.value === "1" && group1TopCapture.see_all_available_for_goals,
  })),
  players: group1TopPlayers.records,
  rankings: group1TopRankings.records,
  progress: group1TopProgress.records,
  foreigners: group1TopForeigners.records.map((player) => ({
    player_id: player.player_id,
    statistics: player.statistics,
  })),
  foreigners_summary: {
    source_count: group1TopForeigners.summary.source_count,
    source_percentage: group1TopForeigners.summary.source_percentage,
    denominator_count: group1TopForeigners.summary.denominator_count,
    country_options: group1TopForeigners.summary.country_options.map(([code, label]) => ({ code, label })),
  },
  warnings: group1TopValidation.warnings,
  affiliation_conflicts: group1TopCapture.affiliation_conflicts,
};

const refereeScopeLabels = { all: "Todos", group1: "Grupo I", group2: "Grupo II" } as const;
const refereeScopeSummaries = Object.fromEntries(
  (["all", "group1", "group2"] as const).map((scope) => {
    const rows = refereeStatistics.records.filter((row) => row.group_scope === scope);
    const total = (field: "matches_officiated" | "yellow_cards" | "red_cards") =>
      rows.some((row) => row[field] === null)
        ? null
        : rows.reduce((sum, row) => sum + (row[field] ?? 0), 0);
    return [scope, {
      group_scope: scope,
      label: refereeScopeLabels[scope],
      referee_count: rows.length,
      matches_officiated: total("matches_officiated"),
      yellow_cards: total("yellow_cards"),
      red_cards: total("red_cards"),
    }];
  }),
);
const refereeBootstrap = {
  metadata: {
    source: refereeCapture.source,
    url: refereeCapture.url,
    competition: refereeCapture.competition,
    season: refereeCapture.season,
    group: "I/II",
    section: "referees",
    capture_id: refereeCapture.capture_id,
    captured_at: refereeCapture.captured_at_utc,
    extractor_version: refereeCapture.extractor_version,
    dataset_version: `${refereeCapture.capture_id}-test-fixture`,
    source_snapshot_sha256: Object.fromEntries(
      Object.entries(refereeCapture.scope_captures).map(([scope, capture]) => [scope, capture.source_snapshot_sha256]),
    ),
    related_matches_path: refereeCapture.related_match_dataset.path,
    related_matches_sha256: refereeCapture.related_match_dataset.sha256,
    related_matches_capture_id: refereeCapture.related_match_dataset.source_capture_id,
    related_matches_captured_at: refereeCapture.related_match_dataset.source_captured_at_utc,
    match_reference_status: refereeMatchReference.status,
    related_match_datasets: {
      I: {
        capture_id: group1RefereeReference.reference_dataset.source_capture_id,
        captured_at: group1RefereeReference.reference_dataset.source_captured_at_utc,
        sha256: group1RefereeReference.reference_dataset.sha256,
        reference_status: group1RefereeReference.status,
      },
      II: {
        capture_id: refereeCapture.related_match_dataset.source_capture_id,
        captured_at: refereeCapture.related_match_dataset.source_captured_at_utc,
        sha256: refereeCapture.related_match_dataset.sha256,
        reference_status: refereeMatchReference.status,
      },
    },
  },
  availability: {
    catalog_referee_count: refereeCatalog.records.length,
    statistics_record_count: refereeStatistics.records.length,
    scope_counts: refereeScopeSummaries,
  },
  seasons: [{ season: refereeCapture.season, label: "2026/27", available: true }],
  groups: (["all", "group1", "group2"] as const).map((scope) => ({
    group_scope: scope,
    label: refereeScopeLabels[scope],
    referee_count: refereeScopeSummaries[scope].referee_count,
  })),
  referees: refereeCatalog.records,
  statistics: refereeStatistics.records,
  coverage_note: "Las tarjetas son las mostradas en los partidos dirigidos. La nacionalidad no está verificada en esta captura.",
  compatibility_warnings: [],
} as RefereeBootstrap;

const statisticsBootstrap = {
  metadata: {
    source: statisticsCapture.source,
    url: statisticsCapture.final_url,
    competition: statisticsCapture.competition,
    season: statisticsCapture.season,
    group: statisticsCapture.group,
    section: "statistics",
    capture_id: statisticsCapture.capture_id,
    captured_at: statisticsCapture.captured_at_utc,
    extractor_version: statisticsCapture.extractor_version,
    dataset_version: `${statisticsCapture.capture_id}-test-fixture`,
    source_snapshot_sha256: statisticsCapture.source_html_sha256,
    chart_data_provider_sha256: statisticsCapture.chart_data_provider_sha256,
    match_dataset_path: statisticsCapture.match_dataset.path,
    match_dataset_sha256: statisticsCapture.match_dataset.sha256,
    match_dataset_capture_id: statisticsCapture.match_dataset.source_capture_id,
    match_dataset_captured_at: statisticsCapture.match_dataset.source_captured_at_utc,
    active_match_capture_id: apiBootstrap.metadata.capture_id,
  },
  statistics: {
    ...statisticsDerived.statistics.context,
    ...Object.fromEntries(Object.entries(statisticsDerived.statistics).filter(([key]) => key !== "context")),
  },
  penalties: {
    ...statisticsExclusive.items.penalties,
  },
  records: statisticsDerived.records,
  reconciliation: Object.fromEntries(Object.entries(statisticsReconciliation).filter(([key]) => key !== "schema_version")),
  methodology: statisticsDerived.methodology,
  limitations: [
    "La continuidad de rachas ante aplazamientos no está verificada.",
    "Las tarjetas rojas coinciden numéricamente con «Expulsiones»; la equivalencia conceptual queda pendiente.",
    "La serie publicada presenta diferencias con los valores derivados desde Resultados.",
  ],
} as StatisticsBootstrap;

const group1StatisticsBootstrap = {
  ...statisticsBootstrap,
  metadata: {
    ...statisticsBootstrap.metadata,
    url: group1StatisticsCapture.final_url,
    group: "I",
    capture_id: group1StatisticsCapture.capture_id,
    captured_at: group1StatisticsCapture.captured_at_utc,
    source_snapshot_sha256: group1StatisticsCapture.source_html_sha256,
    chart_data_provider_sha256: group1StatisticsCapture.chart_data_provider_sha256,
    match_dataset_path: group1StatisticsCapture.match_dataset.path,
    match_dataset_sha256: group1StatisticsCapture.match_dataset.sha256,
    match_dataset_capture_id: group1StatisticsCapture.match_dataset.source_capture_id,
    match_dataset_captured_at: group1StatisticsCapture.match_dataset.source_captured_at_utc,
    active_match_capture_id: group1Bootstrap.metadata.capture_id,
  },
  statistics: {
    ...group1StatisticsDerived.statistics.context,
    ...Object.fromEntries(Object.entries(group1StatisticsDerived.statistics).filter(([key]) => key !== "context")),
  },
  penalties: { ...group1StatisticsExclusive.items.penalties, source_url: group1StatisticsCapture.requested_url },
  records: group1StatisticsDerived.records,
  reconciliation: Object.fromEntries(Object.entries(group1StatisticsReconciliation).filter(([key]) => key !== "schema_version")),
  methodology: group1StatisticsDerived.methodology,
  limitations: ["Las tarjetas rojas coinciden numéricamente con «Expulsiones»; la equivalencia conceptual queda pendiente."],
} as StatisticsBootstrap;

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const fetchMock = vi.fn();

function payloadFor(input: RequestInfo | URL): unknown {
  const url = String(input);
  const group = url.includes("/groups/1/") ? "1" : "2";
  if (url.includes("/referees/bootstrap")) return refereeBootstrap;
  if (url.includes("/top/bootstrap")) return group === "1" ? group1TopBootstrap : topBootstrap;
  if (url.includes("/statistics/bootstrap")) return group === "1" ? group1StatisticsBootstrap : statisticsBootstrap;
  return group === "1" ? group1Bootstrap : apiBootstrap;
}

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
  fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(response(200, payloadFor(input))));
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
    expect(screen.getByRole("combobox", { name: "Seleccionar grupo" })).toHaveValue("2");
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

  it("cambia entre grupos con cinco secciones, caché y filtros independientes", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.change(screen.getByLabelText("Tipo de rango"), { target: { value: "dates" } });
    fireEvent.change(screen.getByLabelText("Fecha inicial"), { target: { value: "2026-09-05" } });
    const groupPicker = screen.getByRole("combobox", { name: "Seleccionar grupo" });
    fireEvent.change(groupPicker, { target: { value: "1" } });

    expect(await screen.findByRole("row", { name: /Pontevedra/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Jaén/ })).not.toBeInTheDocument();
    const group1View = document.querySelector("#group-dashboard-1") as HTMLElement;
    expect(within(group1View).getByLabelText("Tipo de rango")).toHaveValue("all");
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.change(within(group1View).getByLabelText("Tipo de rango"), { target: { value: "rounds" } });
    fireEvent.change(within(group1View).getByLabelText("Jornada inicial"), { target: { value: "2" } });
    fireEvent.change(within(group1View).getByLabelText("Jornada final"), { target: { value: "4" } });
    fireEvent.click(within(group1View).getByRole("tab", { name: "Resultados" }));
    expect(await screen.findByRole("heading", { name: "Resultados" })).toBeInTheDocument();
    fireEvent.change(within(group1View).getByLabelText("Jornada de resultados"), { target: { value: "all" } });
    expect(group1View.querySelectorAll(".results-match-row")).toHaveLength(380);
    expect(group1View.querySelectorAll(".results-match-row .result-score")).toHaveLength(60);
    expect(group1View.querySelectorAll(".results-match-row .result-pending")).toHaveLength(320);
    fireEvent.click(within(group1View).getByRole("tab", { name: "Destacados" }));
    expect(await screen.findByRole("heading", { name: /Extranjeros — 59 disponibles · 60 publicados/ })).toBeInTheDocument();
    const foreignersTable = screen.getByRole("region", { name: "Estadísticas de jugadores extranjeros" });
    const ambiguousPlayer = within(foreignersTable).getByRole("row", { name: /Luisao/ });
    expect(ambiguousPlayer.lastElementChild).toHaveTextContent("—");
    expect(ambiguousPlayer.lastElementChild?.querySelector("[aria-label='Equipo no determinado']")).toBeInTheDocument();

    fireEvent.click(within(group1View).getByRole("tab", { name: "Árbitros" }));
    expect(await screen.findByText("43 árbitros · Grupo I")).toBeInTheDocument();
    expect(within(group1View).getByLabelText("Grupo")).toHaveValue("group1");

    fireEvent.click(within(group1View).getByRole("tab", { name: "Estadísticas" }));
    expect(await screen.findByText("PRIMERA FEDERACIÓN · GRUPO I")).toBeInTheDocument();
    expect(screen.getByText("Partidos disputados").parentElement).toHaveTextContent("60");

    fireEvent.change(groupPicker, { target: { value: "2" } });
    expect(await screen.findByText("PRIMERA FEDERACIÓN · GRUPO II")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(6);
    fireEvent.change(groupPicker, { target: { value: "1" } });
    expect(await screen.findByText("PRIMERA FEDERACIÓN · GRUPO I")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(6);

    fireEvent.click(within(group1View).getByRole("tab", { name: "Clasificación" }));
    expect(within(group1View).getByLabelText("Tipo de rango")).toHaveValue("rounds");
    expect(within(group1View).getByLabelText("Jornada inicial")).toHaveValue("2");
    expect(within(group1View).getByLabelText("Jornada final")).toHaveValue("4");
    expect(fetchMock).toHaveBeenCalledTimes(6);
  }, 15000);

  it("aísla un fallo de Árbitros de Grupo I y carga el ámbito válido de Grupo II", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/groups/1/referees/bootstrap")) {
        return Promise.resolve(response(503, { detail: "invalid group one reference" }));
      }
      if (url.endsWith("/api/v1/groups/2/referees/bootstrap")) {
        return Promise.resolve(response(200, refereeBootstrap));
      }
      return Promise.resolve(response(200, url.includes("/groups/1/") ? group1Bootstrap : apiBootstrap));
    });
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    const picker = screen.getByRole("combobox", { name: "Seleccionar grupo" });
    fireEvent.change(picker, { target: { value: "1" } });
    await screen.findByRole("row", { name: /Pontevedra/ });
    const group1View = document.querySelector("#group-dashboard-1") as HTMLElement;
    fireEvent.click(within(group1View).getByRole("tab", { name: "Árbitros" }));
    expect(await within(group1View).findByRole("alert")).toHaveTextContent("Árbitros no está disponible");

    fireEvent.change(picker, { target: { value: "2" } });
    expect(await screen.findByText("42 árbitros · Grupo II")).toBeInTheDocument();
    expect(group1View.querySelector('[role="alert"]')).toHaveTextContent("Árbitros no está disponible");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/groups/2/referees/bootstrap",
      expect.objectContaining({ signal: undefined }),
    );
  }, 12000);

  it("descarta del grupo visible el efecto de una respuesta tardía del otro grupo", async () => {
    let finishGroupOne!: (value: Response) => void;
    const groupOnePending = new Promise<Response>((resolve) => { finishGroupOne = resolve; });
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/groups/1/bootstrap")) return groupOnePending;
      return Promise.resolve(response(200, apiBootstrap));
    });
    render(<App />);
    await screen.findByRole("row", { name: /Jaén/ });
    const picker = screen.getByRole("combobox", { name: "Seleccionar grupo" });
    fireEvent.change(picker, { target: { value: "1" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/groups/1/bootstrap",
      expect.objectContaining({ signal: undefined }),
    ));

    fireEvent.change(picker, { target: { value: "2" } });
    expect(screen.getByRole("row", { name: /Jaén/ })).toBeInTheDocument();
    finishGroupOne(response(200, group1Bootstrap));
    await waitFor(() => expect(document.querySelector("#group-dashboard-1")).not.toBeNull());
    expect(picker).toHaveValue("2");
    expect(screen.getByRole("row", { name: /Jaén/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Pontevedra/ })).not.toBeInTheDocument();

    fireEvent.change(picker, { target: { value: "1" } });
    expect(await screen.findByRole("row", { name: /Pontevedra/ })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/groups/1/bootstrap"))).toHaveLength(1);
  }, 12000);

  it("muestra un estado de error útil si la API todavía no está preparada", async () => {
    fetchMock.mockResolvedValueOnce(response(503, { detail: "not ready" }));
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("La API todavía no tiene un dataset preparado para este grupo.");
    expect(screen.getByRole("button", { name: "Reintentar conexión" })).toBeInTheDocument();
  });

  it("carga Árbitros al entrar una vez y cambia de ámbito con filas y totales locales", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/referees/bootstrap")
        ? response(200, refereeBootstrap)
        : response(200, apiBootstrap),
    ));
    expect(RefereeBootstrapSchema.safeParse(refereeBootstrap).success).toBe(true);
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("tab", { name: "Árbitros" }));
    expect(await screen.findByText("42 árbitros · Grupo II")).toBeInTheDocument();
    expect(screen.getByLabelText("Temporada")).toHaveValue("2026-27");
    expect(screen.getByLabelText("Temporada")).toBeDisabled();
    expect(screen.getByLabelText("Grupo")).toHaveValue("group2");
    const tableRegion = screen.getByRole("region", { name: "Árbitros y estadísticas por grupo" });
    expect(within(tableRegion).getAllByRole("row")).toHaveLength(43);
    expect(within(screen.getByRole("region", { name: "Resumen estadístico: Grupo II" })).getByText("59")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Grupo"), { target: { value: "all" } });
    expect(within(tableRegion).getAllByRole("row")).toHaveLength(61);
    expect(screen.getByText("60 árbitros · Todos")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Grupo"), { target: { value: "group1" } });
    expect(within(tableRegion).getAllByRole("row")).toHaveLength(44);
    expect(screen.getByText("43 árbitros · Grupo I")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    expect(await screen.findByRole("heading", { name: "Resultados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Árbitros" }));
    expect(screen.getByLabelText("Grupo")).toHaveValue("group1");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("presenta datos nulos y ceros reales, enlaza la ficha y deja nulos al final en ambos órdenes", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/referees/bootstrap")
        ? response(200, refereeBootstrap)
        : response(200, apiBootstrap),
    ));
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Árbitros" }));
    await screen.findByText("42 árbitros · Grupo II");

    const refereeRegion = screen.getByRole("region", { name: "Árbitros y estadísticas por grupo" });
    const bejar = within(refereeRegion).getByText("Béjar Caballero").closest("tr");
    expect(bejar?.children[2]).toHaveTextContent("—");
    const profileLink = within(bejar as HTMLElement).getByRole("link");
    expect(profileLink).toHaveAttribute("href", "https://www.bdfutbol.com/es/r/r602675.html");
    expect(profileLink).toHaveAttribute("target", "_blank");
    const photo = bejar?.querySelector("img.referee-photo");
    expect(photo).not.toBeNull();
    fireEvent.error(photo as HTMLImageElement);
    expect(bejar?.querySelector(".referee-photo-fallback")).toBeInTheDocument();
    expect(container.querySelector(".referees-table tbody td:nth-child(9)")).toHaveTextContent("0");

    fireEvent.click(screen.getByRole("button", { name: /^Edad/ }));
    let rows = Array.from(container.querySelectorAll(".referees-table tbody tr"));
    expect(rows.at(-1)?.children[2]).toHaveTextContent("—");
    fireEvent.click(screen.getByRole("button", { name: /^Edad/ }));
    rows = Array.from(container.querySelectorAll(".referees-table tbody tr"));
    expect(rows.at(-1)?.children[2]).toHaveTextContent("—");
    expect(screen.getByText("21/01/1999")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reintenta Árbitros sin afectar las secciones existentes y conserva el bootstrap en memoria", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/groups/2/referees/bootstrap")) {
        const attempts = fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/api/v1/groups/2/referees/bootstrap")).length;
        return Promise.resolve(attempts === 1 ? response(503, { detail: "invalid capture" }) : response(200, refereeBootstrap));
      }
      return Promise.resolve(response(200, apiBootstrap));
    });
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Árbitros" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Árbitros no está disponible");
    fireEvent.click(screen.getByRole("tab", { name: "Clasificación" }));
    expect(await screen.findByRole("heading", { name: "General" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Árbitros" }));
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("42 árbitros · Grupo II")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    fireEvent.click(screen.getByRole("tab", { name: "Árbitros" }));
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/api/v1/groups/2/referees/bootstrap"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/api/v1/groups/2/bootstrap"))).toHaveLength(1);
  });

  it("carga Destacados solo al entrar, mantiene selecciones locales y presenta rankings reales", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/top/bootstrap")
        ? response(200, topBootstrap)
        : response(200, apiBootstrap),
    ));
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    expect(await screen.findByRole("heading", { name: "Destacados" })).toBeInTheDocument();
    expect(screen.getByText("217 jugadores identificados")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Extranjeros — 101 \(19,65 %\)/ })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/v1/groups/2/top/bootstrap");

    const goalTable = container.querySelector(".top-ranking-table");
    expect(goalTable?.querySelectorAll("tbody tr")).toHaveLength(10);
    const firstCheckbox = screen.getAllByRole("checkbox", { name: /Incluir a/ })[0]!;
    const originalSelection = (firstCheckbox as HTMLInputElement).checked;
    fireEvent.click(firstCheckbox);
    fireEvent.click(screen.getByRole("button", { name: "Ver todos (107)" }));
    expect(goalTable?.querySelectorAll("tbody tr")).toHaveLength(107);

    fireEvent.click(screen.getByRole("button", { name: "Más joven" }));
    expect(screen.getByRole("heading", { name: "Más joven" })).toBeInTheDocument();
    expect(container.querySelector(".top-chart-panel")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /Incluir a/ })).toBeNull();
    fireEvent.click(within(screen.getByRole("group", { name: "Categoría de destacados" })).getByRole("button", { name: "Goles" }));
    expect((screen.getAllByRole("checkbox", { name: /Incluir a/ })[0] as HTMLInputElement).checked).toBe(!originalSelection);

    fireEvent.change(screen.getByLabelText("Filtrar extranjeros por país"), { target: { value: "argentina" } });
    const filteredRows = container.querySelectorAll(".foreigners-table tbody tr");
    expect(filteredRows.length).toBeGreaterThan(0);
    expect(filteredRows.length).toBeLessThan(101);
    const gazzaniga = screen.getByText("Gianfranco Gazzaniga Farías").closest("tr");
    expect(gazzaniga?.children[4]).toHaveTextContent("—");
    expect(gazzaniga?.children[6]).toHaveTextContent("0");
    fireEvent.click(within(container.querySelector(".foreigners-table") as HTMLElement).getByRole("button", { name: /Goles/ }));
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    fireEvent.change(screen.getByLabelText("Jornada de resultados"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    expect(await screen.findByRole("heading", { name: "Destacados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    expect(screen.getByLabelText("Jornada de resultados")).toHaveValue("all");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reintenta solo la carga de Destacados y no recarga sus datos al volver a entrar", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/v1/groups/2/top/bootstrap")) {
        const topCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/top/bootstrap")).length;
        return Promise.resolve(topCalls === 1 ? response(503, { detail: "invalid capture" }) : response(200, topBootstrap));
      }
      return Promise.resolve(response(200, apiBootstrap));
    });
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Destacados no está disponible");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar Destacados" }));
    expect(await screen.findByRole("heading", { name: "Destacados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Clasificación" }));
    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/top/bootstrap"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/bootstrap"))).toHaveLength(1);
  });

  it("muestra el porcentaje de extranjeros desconocido como guion y conserva el cero real", () => {
    const unknownPercentage = {
      ...topBootstrap,
      foreigners_summary: { ...topBootstrap.foreigners_summary, source_percentage: null },
} as TopBootstrap;

    const { rerender } = render(
      <TopSection data={unknownPercentage} loadState="ready" errorMessage="" onRetry={() => undefined} />,
    );
    expect(screen.getByRole("heading", { name: "Extranjeros — 101 (—)" })).toBeInTheDocument();

    const zeroPercentage = {
      ...topBootstrap,
      foreigners_summary: { ...topBootstrap.foreigners_summary, source_percentage: 0 },
    } as TopBootstrap;
    rerender(<TopSection data={zeroPercentage} loadState="ready" errorMessage="" onRetry={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Extranjeros — 101 (0,00 %)" })).toBeInTheDocument();
  });

  it("mantiene los valores nulos al final en ambos sentidos de ordenación", () => {
    const goals = [5, 3, 2, 0, null, null];
    const sortableFixture = {
      ...topBootstrap,
      foreigners_summary: { ...topBootstrap.foreigners_summary, source_count: goals.length },
      foreigners: topBootstrap.foreigners.slice(0, goals.length).map((foreign, index) => ({
        ...foreign,
        statistics: { ...foreign.statistics, goals: goals[index]! },
      })),
    } as TopBootstrap;
    const { container } = render(
      <TopSection data={sortableFixture} loadState="ready" errorMessage="" onRetry={() => undefined} />,
    );
    const table = container.querySelector(".foreigners-table") as HTMLElement;
    const goalsButton = within(table).getByRole("button", { name: /Goles/ });
    const values = () => Array.from(table.querySelectorAll("tbody tr"))
      .map((row) => row.children[6]?.textContent?.trim());
    const lastTwoPlayerIds = () => Array.from(table.querySelectorAll("tbody tr"))
      .slice(-2)
      .map((row) => Number(row.querySelector("a")?.getAttribute("href")?.match(/j(\d+)\.html$/)?.[1]));
    const expectedNullPlayerIds = sortableFixture.foreigners.slice(-2)
      .map(({ player_id }) => player_id)
      .sort((left, right) => left - right);

    fireEvent.click(goalsButton);
    expect(values()).toEqual(["0", "2", "3", "5", "—", "—"]);
    expect(lastTwoPlayerIds()).toEqual(expectedNullPlayerIds);
    fireEvent.click(goalsButton);
    expect(values()).toEqual(["5", "3", "2", "0", "—", "—"]);
    expect(lastTwoPlayerIds()).toEqual(expectedNullPlayerIds);
  });

  it("conserva los valores numéricos reales de las series de progreso", () => {
    const sourceSeries = topProgress.records[0]!;
    const data = buildTopProgressData([1, 2], [sourceSeries], [sourceSeries.player_id]);
    expect(data[0]?.matchday).toBe(1);
    expect(data[0]?.[`player_${sourceSeries.player_id}`]).toBe(sourceSeries.points[0]?.value);
    expect(data[1]?.[`player_${sourceSeries.player_id}`]).toBe(sourceSeries.points[1]?.value);
  });

  it("valida el contrato de Estadísticas y la carga diferida no repite solicitudes", async () => {
    expect(StatisticsBootstrapSchema.safeParse(statisticsBootstrap).success).toBe(true);
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/statistics/bootstrap")
        ? response(200, statisticsBootstrap)
        : response(200, apiBootstrap),
    ));
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    expect(await screen.findByRole("heading", { name: "Estadísticas" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/v1/groups/2/statistics/bootstrap");

    fireEvent.click(within(screen.getByRole("group", { name: "Series del gráfico" })).getByRole("button", { name: "Tarjetas rojas" }));
    fireEvent.click(screen.getByRole("tab", { name: "Clasificación" }));
    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("presenta totales y medias, conserva empates y señala dinámicamente la diferencia de J5", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/statistics/bootstrap")
        ? response(200, statisticsBootstrap)
        : response(200, apiBootstrap),
    ));
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    await screen.findByRole("heading", { name: "Estadísticas" });

    expect(within(screen.getByLabelText("Resultados generales")).getByText("59")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Goles y tarjetas")).getByText("155")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Goles y tarjetas")).getByText("2,63")).toBeInTheDocument();
    const penalties = screen.getByRole("heading", { name: "Penaltis" }).closest("section");
    expect(penalties).not.toBeNull();
    expect(within(penalties as HTMLElement).getByText("24")).toBeInTheDocument();
    expect(within(penalties as HTMLElement).getByText("21")).toBeInTheDocument();
    expect(within(penalties as HTMLElement).getByText("3")).toBeInTheDocument();
    expect(screen.getAllByText("0 – 3")).toHaveLength(2);
    const winlessCard = container.querySelectorAll(".streak-card")[3] as HTMLElement;
    expect(within(winlessCard).getAllByText("6 partidos")).toHaveLength(2);
    expect(container.querySelector(".statistics-discrepancies p")?.textContent).toMatch(/J5 \(9 de 10 partidos\).*19 goles.*21/);
    expect(screen.getByText(/Resultados.*2026/)).toBeInTheDocument();
    expect(screen.getByText(/Datos exclusivos.*2026/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("permite reintentar Estadísticas de forma independiente", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/v1/groups/2/statistics/bootstrap")) {
        const attempts = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/statistics/bootstrap")).length;
        return Promise.resolve(attempts === 1 ? response(503, { detail: "capture mismatch" }) : response(200, statisticsBootstrap));
      }
      return Promise.resolve(response(200, apiBootstrap));
    });
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Estadísticas no está disponible");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar Estadísticas" }));
    expect(await screen.findByRole("heading", { name: "Estadísticas" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/statistics/bootstrap"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/bootstrap"))).toHaveLength(1);
  });
});
