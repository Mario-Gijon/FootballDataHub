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
import jaenTeamCapture from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/metadata/capture.json";
import jaenTeamIdentity from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/normalized/team_identity.json";
import jaenTeamSeason from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/normalized/team_season.json";
import jaenPlayers from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/normalized/players.json";
import jaenMemberships from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/normalized/memberships.json";
import jaenPlayerStatistics from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/normalized/player_statistics.json";
import jaenPlayerMatchMinutes from "../../../../data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/normalized/player_match_minutes.json";
import jaenFollowCapture from "../../../../data/exports/bdfutbol/teams/2026-27/49/20261012T120720.895650Z-8c75b830/metadata/capture.json";
import jaenFollowMinutes from "../../../../data/exports/bdfutbol/teams/2026-27/49/20261012T120720.895650Z-8c75b830/normalized/player_match_minutes.json";
import jaenFollowMetrics from "../../../../data/exports/bdfutbol/teams/2026-27/49/20261012T120720.895650Z-8c75b830/normalized/player_match_metrics.json";
import racingTeamCapture from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/metadata/capture.json";
import racingTeamIdentity from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/team_identity.json";
import racingTeamSeason from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/team_season.json";
import racingPlayers from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/players.json";
import racingMemberships from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/memberships.json";
import racingPlayerStatistics from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/player_statistics.json";
import racingPlayerMatchMinutes from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/player_match_minutes.json";
import racingPlayerMatchMetrics from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/normalized/player_match_metrics.json";
import jaenTransfersCapture from "../../../../data/exports/bdfutbol/teams/2026-27/49/20261012T131457.209360Z-602005d8/metadata/capture.json";
import jaenTransfersDocument from "../../../../data/exports/bdfutbol/teams/2026-27/49/20261012T131457.209360Z-602005d8/normalized/transfers.json";
import racingTransfersCapture from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261012T131518.543469Z-43ff1122/metadata/capture.json";
import racingTransfersDocument from "../../../../data/exports/bdfutbol/teams/2026-27/48/20261012T131518.543469Z-43ff1122/normalized/transfers.json";
import { buildTopProgressData, TopSection } from "../components/TopSection";
import { TeamRosterSection } from "../components/TeamRoster";
import { ProfileImage } from "../components/TeamRosterShared";
import { clearMatchPageCache, clearTeamProfileCache } from "../api/client";
import type { MatchPage, MatchResultsBootstrap, RefereeBootstrap, StatisticsBootstrap, TeamFollow, TeamRoster, TeamTransfers, TopBootstrap } from "../api/contracts";
import { RefereeBootstrapSchema, StatisticsBootstrapSchema, TeamFollowSchema, TeamRosterSchema, TeamTransfersSchema, TopBootstrapSchema } from "../api/contracts";
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

function resultGroup(group: "I" | "II", bootstrap: Bootstrap, captured: { capture_id: string; captured_at_utc: string }) {
  return {
    group,
    source_capture_id: captured.capture_id,
    source_captured_at: captured.captured_at_utc,
    teams: bootstrap.teams,
    matches: bootstrap.matches.map((match) => ({
      internal_id: `pf-2026-27-group-${group.toLowerCase()}-bdfutbol-${match.match_id}`,
      source_match_id: match.match_id,
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
    })),
    scheduled_matchdays: bootstrap.metadata.scheduled_matchdays,
    counts: {
      teams: bootstrap.teams.length,
      matches: bootstrap.matches.length,
      played: bootstrap.matches.filter((match) => match.status === "played").length,
      unplayed: bootstrap.matches.filter((match) => match.status === "unplayed").length,
      incomplete: bootstrap.matches.filter((match) => match.status === "incomplete").length,
    },
  };
}

const playerMetadata = {
  season: "2026-27",
  inventory_generated_at: "2026-10-14T12:31:48.863106+00:00",
  inventory_player_count: 2,
  complete_individual_profile_count: 1,
  partial_individual_profile_count: 0,
  inventory_only_count: 1,
  roster_membership_count: 1,
  transfer_only_count: 1,
  compact_generation_id: "ui-01-player-fixture",
  compact_generated_at: "2026-10-17T12:00:00+00:00",
  inventory_sha256: "b".repeat(64),
};
const playerDirectoryFixture = {
  metadata: playerMetadata,
  available_teams: [{ team_id: 49, team_name: "Real Jaén", group: "II" }],
  query: "",
  group: null,
  team_id: null,
  page: 1,
  page_size: 25,
  total: 2,
  players: [
    { player_id: 28577, display_name: "Nacho Castillo", full_name: "Nacho Castillo", profile_url: "https://www.bdfutbol.com/es/j/j28577.html", photo_url: "https://www.bdfutbol.com/i/m/28577.png", birth_date: null, age_years: null, nationality: "España", position_name: "Delantero", groups: ["II"], association_status: "roster_membership_observed", team_associations: [{ team_id: 49, team_name: "Real Jaén", group: "II", evidence_types: ["membership"] }], profile_status: "four_views_verified" },
    { player_id: 70001, display_name: "Jugador Referenciado", full_name: null, profile_url: "https://www.bdfutbol.com/es/j/j70001.html", photo_url: null, birth_date: null, age_years: null, nationality: null, position_name: null, groups: ["II"], association_status: "transfer_reference_only", team_associations: [{ team_id: 49, team_name: "Real Jaén", group: "II", evidence_types: ["transfer_reference"] }], profile_status: "inventory_only" },
  ],
};
const playerDetailFixture = {
  metadata: playerMetadata,
  player: playerDirectoryFixture.players[0],
  identity: {
    display_name: "Nacho Castillo", full_name: "Nacho Castillo", birth_date: null, age_years: null,
    birth_place: null, birth_place_raw: null, birthplace_province: null, country_of_birth: null, nationality: "España",
    position_name: "Delantero", height_cm: null, height_raw: null, weight_kg: null, weight_raw: null,
    field_sources: { display_name: "inventory", position_name: "inventory", nationality: "inventory" },
    inventory_sha256: "a".repeat(64), individual_profile_source_url: null,
    individual_profile_captured_at: null, individual_profile_sha256: null, conflicts: [],
  },
  club_reference: { status: "observed", team_id: 49, team_name: "Real Jaén", group: "II", observed_at: "2026-10-14T12:00:00+00:00", reason: "latest_unique_membership_observation" },
  last_observed_movement: null,
  movement_resolution: "none",
  birth_place: null,
  birthplace_province: null,
  nationality_flag_url: null,
  verified_indicators: [],
  associations: playerDirectoryFixture.players[0].team_associations,
  membership_history: [{ team_id: 49, team_name: "Real Jaén", group: "II", season: "2026-27", captured_at: "2026-10-14T12:00:00+00:00", capture_id: "capture", jersey_number: null, squad_group_label: null, source_views: ["squad"] }],
  transfer_references: [],
  season_statistics: [],
  match_minutes: [],
  match_metrics: [],
  verified_individual_views: (["profile", "statistics", "matches", "rivals"] as const).map((view) => ({
    view,
    source_url: view === "profile" || view === "statistics"
      ? "https://www.bdfutbol.com/es/j/j28577.html"
      : "https://www.bdfutbol.com/es/p/j28577.html",
    captured_at: "2026-10-16T12:00:00+00:00",
    source_sha256: "c".repeat(64),
    scope_note: "Fixture de prueba; no representa un snapshot real.",
    tables: [],
    profile: null,
    coverage: null,
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
  })),
  warnings: ["La pertenencia se observó en capturas de la temporada; no certifica que siga vigente hoy."],
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

const matchResultsBootstrap: MatchResultsBootstrap = {
  metadata: {
    schema_version: 1,
    source: "BDFutbol",
    competition: "Primera Federación",
    season: "2026-27",
    generation_id: "ui-01-test-generation",
    generation_sha256: "a".repeat(64),
    captured_at: captureSource.captured_at_utc,
    team_count: 40,
    match_count: 760,
    played_count: group1Matches.counts.played + matchesSource.counts.played,
    unplayed_count: group1Matches.counts.unplayed + matchesSource.counts.unplayed,
    incomplete_count: group1Matches.counts.incomplete + matchesSource.counts.incomplete,
  },
  groups: {
    I: resultGroup("I", group1Bootstrap, group1Capture),
    II: resultGroup("II", apiBootstrap, captureSource),
  },
};

function matchPageFixture(internalId: string): MatchPage | null {
  for (const groupCode of ["I", "II"] as const) {
    const group = matchResultsBootstrap.groups[groupCode];
    const match = group.matches.find((item) => item.internal_id === internalId);
    if (!match) continue;
    const teams = new Map(group.teams.map((team) => [team.team_id, team]));
    const homeTeam = teams.get(match.home_team_id);
    const awayTeam = teams.get(match.away_team_id);
    if (!homeTeam || !awayTeam) return null;
    return {
      metadata: {
        contract_version: 2,
        source: "BDFutbol",
        competition: "Primera Federación",
        season: "2026-27",
        group: groupCode,
        generation_id: matchResultsBootstrap.metadata.generation_id,
        generation_sha256: matchResultsBootstrap.metadata.generation_sha256,
        source_capture_id: group.source_capture_id,
        source_captured_at: group.source_captured_at,
      },
      match: {
        internal_id: match.internal_id,
        source_match_id: match.source_match_id,
        matchday: match.matchday,
        matchday_date: match.matchday_date,
        source_match_date: match.source_match_date,
        home_team: homeTeam,
        away_team: awayTeam,
        home_goals: match.home_goals,
        away_goals: match.away_goals,
        status: match.status,
        unplayed_state: match.unplayed_state,
        stadium_name: match.stadium_name,
        stadium_url: match.stadium_url,
        referee_name: match.referee_name,
        referee_url: match.referee_url,
        source_match_url: match.source_match_url,
      },
      detail_status: "not_available",
      details: null,
    };
  }
  return null;
}
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
  players: topPlayers.records.map((player) => ({ ...player, internal_player_id: player.player_id })),
  rankings: topRankings.records,
  progress: topProgress.records,
  foreigners: topForeigners.records.map((player, index) => ({
    player_id: player.player_id,
    internal_player_id: player.player_id,
    statistics: {
      ...player.statistics,
      // Isolated UI fixture to distinguish a genuine zero from missing data.
      ...(index === 0 ? { matches_played: null } : {}),
    },
  })),
  foreigners_summary: {
    source_count: topForeigners.summary.source_count,
    available_count: topForeigners.records.length,
    missing_count: topForeigners.summary.source_count - topForeigners.records.length,
    coverage_status: topForeigners.summary.source_count === topForeigners.records.length ? "complete" : "documented_discrepancy",
    source_percentage: topForeigners.summary.source_percentage,
    denominator_count: topForeigners.summary.denominator_count,
    country_options: topForeigners.summary.country_options.map(([code, label]) => ({ code, label })),
  },
  coverage_note: topRankings.coverage_note,
  warnings: [],
  affiliation_conflicts: [],
  affiliation_absences: [],
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
    available_count: group1TopForeigners.records.length,
    missing_count: group1TopForeigners.summary.source_count - group1TopForeigners.records.length,
    coverage_status: group1TopForeigners.summary.source_count === group1TopForeigners.records.length ? "complete" : "documented_discrepancy",
    source_percentage: group1TopForeigners.summary.source_percentage,
    denominator_count: group1TopForeigners.summary.denominator_count,
    country_options: group1TopForeigners.summary.country_options.map(([code, label]) => ({ code, label })),
  },
  warnings: group1TopValidation.warnings,
  affiliation_conflicts: group1TopCapture.affiliation_conflicts,
  affiliation_absences: [],
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
  if (url.endsWith("/api/v1/matches/bootstrap")) return matchResultsBootstrap;
  const matchPagePath = url.match(/^\/api\/v1\/matches\/(pf-2026-27-group-(?:i|ii)-bdfutbol-\d+)$/);
  if (matchPagePath) return matchPageFixture(matchPagePath[1]);
  if (/^\/api\/v1\/players\/\d+$/.test(url)) return playerDetailFixture;
  if (url.startsWith("/api/v1/players")) {
    const params = new URL(url, window.location.origin).searchParams;
    const query = params.get("q")?.toLocaleLowerCase("es-ES") ?? "";
    const group = params.get("group");
    const teamId = Number(params.get("team_id")) || null;
    const page = Number(params.get("page")) || 1;
    const pageSize = Number(params.get("page_size")) || 25;
    const players = playerDirectoryFixture.players.filter((player) =>
      (!query || `${player.display_name ?? ""} ${player.full_name ?? ""}`.toLocaleLowerCase("es-ES").includes(query))
      && (!group || player.groups.includes(group as "I" | "II"))
      && (!teamId || player.team_associations.some((team) => team.team_id === teamId)),
    );
    return { ...playerDirectoryFixture, query: params.get("q") ?? "", group, team_id: teamId, page, page_size: pageSize, total: players.length, players: players.slice((page - 1) * pageSize, page * pageSize) };
  }
  const group = url.includes("/groups/1/") ? "1" : "2";
  const transfersPath = url.match(/\/api\/v1\/teams\/(\d+)\/seasons\/2026-27\/transfers$/);
  if (transfersPath) return teamTransfersPayload(Number(transfersPath[1]));
  const followPath = url.match(/\/api\/v1\/teams\/(\d+)\/seasons\/2026-27\/follow$/);
  if (followPath) return teamFollowPayload(Number(followPath[1]));
  const rosterPath = url.match(/\/api\/v1\/teams\/(\d+)\/seasons\/2026-27\/roster$/);
  if (rosterPath) return teamRosterPayload(Number(rosterPath[1]));
  if (url.includes("/referees/bootstrap")) return refereeBootstrap;
  if (url.includes("/top/bootstrap")) return group === "1" ? group1TopBootstrap : topBootstrap;
  if (url.includes("/statistics/bootstrap")) return group === "1" ? group1StatisticsBootstrap : statisticsBootstrap;
  return group === "1" ? group1Bootstrap : apiBootstrap;
}

type JsonObject = Record<string, unknown>;

const tacticalSourcePlayers: Record<number, Array<[string, number]>> = {
  49: [
    ["d_por", 209629], ["d_def13", 400021], ["d_def23", 210600], ["d_def33", 304042],
    ["d_mig14", 403736], ["d_mig24", 24012], ["d_mig34", 401038], ["d_mig44", 28577],
    ["d_dav13", 20231], ["d_dav23", 209777], ["d_dav33", 401419],
  ],
  48: [
    ["d_por", 102284], ["d_def14", 21932], ["d_def24", 26664], ["d_def34", 15141], ["d_def44", 103110],
    ["d_mig12", 21519], ["d_mig22", 20263], ["d_dav14", 200661], ["d_dav24", 1080822], ["d_dav34", 20236], ["d_dav44", 20934],
  ],
};

function tacticalFixture(teamId: number, alignmentView: JsonObject) {
  const horizontalByLine = { por: 0.14, def: 0.38, mig: 0.62, dav: 0.86 } as const;
  const lineName = { por: "goalkeeper", def: "defense", mig: "midfield", dav: "attack" } as const;
  return {
    source: "BDFutbol" as const,
    source_view: "alignment" as const,
    source_url: alignmentView.url,
    source_sha256: alignmentView.sha256,
    coordinate_method: "source_line_and_slot_normalized" as const,
    layout_convention: "goalkeeper_to_attack_left_to_right" as const,
    approximate: true as const,
    positions: tacticalSourcePlayers[teamId]!.map(([source_dom_id, player_id]) => {
      const match = /^d_(por|def|mig|dav)(?:(\d+)(\d+))?$/.exec(source_dom_id)!;
      const line = match[1] as keyof typeof horizontalByLine;
      const slot = match[2] ? Number(match[2]) : 1;
      const line_size = match[3] ? Number(match[3]) : 1;
      return {
        player_id,
        horizontal: horizontalByLine[line],
        vertical: 0.1 + 0.8 * slot / (line_size + 1),
        line: lineName[line],
        slot,
        line_size,
        source_dom_id,
      };
    }),
  };
}

function asJsonObject(value: unknown): JsonObject {
  return value as JsonObject;
}

function teamRosterPayload(teamId: number): TeamRoster {
  const source = teamId === 49
    ? { capture: jaenTeamCapture, identity: jaenTeamIdentity, season: jaenTeamSeason, players: jaenPlayers, memberships: jaenMemberships, statistics: jaenPlayerStatistics }
    : teamId === 48
      ? { capture: racingTeamCapture, identity: racingTeamIdentity, season: racingTeamSeason, players: racingPlayers, memberships: racingMemberships, statistics: racingPlayerStatistics }
      : null;
  if (!source) throw new Error(`No hay una captura de Plantilla de prueba para ${teamId}.`);
  const capture = asJsonObject(source.capture);
  const identity = asJsonObject(asJsonObject(source.identity).record);
  const season = asJsonObject(asJsonObject(source.season).record);
  const players = asJsonObject(source.players).records as JsonObject[];
  const memberships = asJsonObject(source.memberships).records as JsonObject[];
  const statistics = asJsonObject(source.statistics).records as JsonObject[];
  const snapshots = asJsonObject(capture.source_snapshots);
  const views = (["alignment", "squad", "statistics"] as const).map((view) => {
    const evidence = asJsonObject(snapshots[view]);
    return {
      view,
      url: evidence.url,
      title: evidence.title,
      status: "VALID",
      http_status: evidence.http_status,
      sha256: evidence.sha256,
      captured_at: evidence.captured_at_utc,
    };
  });
  const alignmentView = views.find((view) => view.view === "alignment")!;
  const groupMemberships = new Map<string, number[]>();
  for (const membership of memberships) {
    const label = membership.squad_group_label;
    if (typeof label !== "string") continue;
    const playerIds = groupMemberships.get(label) ?? [];
    playerIds.push(membership.player_id as number);
    groupMemberships.set(label, playerIds);
  }
  return TeamRosterSchema.parse({
    status: "available",
    metadata: {
      contract_version: 2,
      validation_status: "valid",
      source: "BDFutbol",
      url: identity.team_url,
      competition: "Primera Federación",
      season: "2026-27",
      group: capture.group,
      team_id: teamId,
      capture_id: capture.capture_id,
      captured_at: capture.captured_at_utc,
      extractor_version: capture.extractor_version,
      content_sha256: "a".repeat(64),
    },
    team: identity,
    coaches: season.coaches,
    players,
    memberships,
    statistics,
    squad_groups: [...groupMemberships].map(([label, player_ids]) => ({ label, player_ids })),
    tactical_visualization: tacticalFixture(teamId, alignmentView),
    source_views: views,
    warnings: teamId === 49
      ? ["La captura no contiene estados enriquecidos de Seguimiento; no son necesarios para Plantilla."]
      : [],
  });
}

function teamFollowPayload(teamId: number): TeamFollow {
  if (teamId !== 48 && teamId !== 49) throw new Error(`No hay una captura de Seguimiento de prueba para ${teamId}.`);
  const isRacing = teamId === 48;
  const capture = asJsonObject(isRacing ? racingTeamCapture : jaenFollowCapture);
  const roster = teamRosterPayload(teamId);
  const minuteRecords = asJsonObject(isRacing ? racingPlayerMatchMinutes : jaenFollowMinutes).records as JsonObject[];
  const metricDocument = asJsonObject(isRacing ? racingPlayerMatchMetrics : jaenFollowMetrics);
  const metricRecords = metricDocument.records as JsonObject[];
  const groupBootstrap = isRacing ? group1Bootstrap : apiBootstrap;
  const matchById = new Map(groupBootstrap.matches.map((match) => [match.match_id, match]));
  const teamById = new Map(groupBootstrap.teams.map((team) => [team.team_id, team]));
  const matchIds = new Set([...minuteRecords, ...metricRecords].map((item) => String(item.match_id)));
  const matches = [...matchIds].map((matchId) => {
    const match = matchById.get(matchId);
    if (!match) throw new Error(`No existe el partido ${matchId} en el grupo de fixture.`);
    return {
      match_id: match.match_id,
      matchday: match.matchday,
      matchday_date: match.matchday_date,
      source_match_date: match.source_match_date,
      home_team_id: match.home_team_id,
      home_team_name: teamById.get(match.home_team_id)!.name,
      away_team_id: match.away_team_id,
      away_team_name: teamById.get(match.away_team_id)!.name,
      home_goals: match.home_goals,
      away_goals: match.away_goals,
      status: match.status,
    };
  }).sort((left, right) => left.matchday - right.matchday);
  const capturedStates = new Set(["p", "t", "go", "tot"]);
  const matchdays = [...new Set(matches.map((match) => match.matchday))].sort((left, right) => left - right);
  const metricSum = (metric: string) => metricRecords.filter((item) => item.metric === metric)
    .reduce((sum, item) => sum + Number(item.value), 0);
  const followSnapshot = asJsonObject(asJsonObject(capture.source_snapshots).follow);
  return TeamFollowSchema.parse({
    status: "available",
    metadata: {
      contract_version: 2,
      source: "BDFutbol",
      url: followSnapshot.url,
      competition: "Primera Federación",
      competition_scope: "Liga",
      season: "2026-27",
      group: isRacing ? "I" : "II",
      team_id: teamId,
      capture_id: capture.capture_id,
      captured_at: capture.captured_at_utc,
      extractor_version: capture.extractor_version,
      content_sha256: "c".repeat(64),
      match_capture_id: groupBootstrap.metadata.capture_id,
      match_catalog_sha256: "d".repeat(64),
      derived_states: isRacing ? [] : ["t", "go", "tot"],
      derived_at: isRacing ? null : "2026-10-12T12:07:20.895591+00:00",
    },
    team: roster.team,
    players: roster.players.map((player) => ({
      player_id: player.player_id,
      display_name: player.display_name,
      profile_url: player.profile_url,
      photo_url: player.photo_url,
      jersey_number: roster.memberships.find((item) => item.player_id === player.player_id)?.jersey_number ?? null,
    })),
    matches,
    matchdays,
    minutes: minuteRecords.map((item) => ({
      player_id: item.player_id,
      match_id: String(item.match_id),
      matchday: item.matchday,
      minutes_played: item.value,
      source_value: item.raw_value,
      source_view: item.source_view,
      source_state: item.source_state,
    })),
    metrics: metricRecords.map((item) => ({
      player_id: item.player_id,
      match_id: String(item.match_id),
      matchday: item.matchday,
      metric: item.metric,
      value: item.value,
      source_value: item.raw_value,
      source_view: item.source_view,
      source_state: item.source_state,
    })),
    coverage: [
      { state: "p", available: true, record_count: minuteRecords.length, value_total: null, matchdays },
      { state: "t", available: capturedStates.has("t"), record_count: metricRecords.filter((item) => item.metric === "yellow_cards" || item.metric === "red_cards").length, value_total: capturedStates.has("t") ? metricSum("yellow_cards") + metricSum("red_cards") : null, matchdays: capturedStates.has("t") ? matchdays : [] },
      { state: "go", available: capturedStates.has("go"), record_count: metricRecords.filter((item) => item.metric === "goals").length, value_total: capturedStates.has("go") ? metricSum("goals") : null, matchdays: capturedStates.has("go") ? matchdays : [] },
      { state: "tot", available: capturedStates.has("tot"), record_count: 0, value_total: null, matchdays: capturedStates.has("tot") ? matchdays : [] },
    ],
    warnings: [],
  });
}

function teamTransfersPayload(teamId: number): TeamTransfers {
  if (teamId !== 48 && teamId !== 49) throw new Error(`No hay una captura de Traspasos de prueba para ${teamId}.`);
  const isRacing = teamId === 48;
  const capture = asJsonObject(isRacing ? racingTransfersCapture : jaenTransfersCapture);
  const document = asJsonObject(isRacing ? racingTransfersDocument : jaenTransfersDocument);
  const transferSnapshot = asJsonObject(asJsonObject(capture.source_snapshots).transfers);
  const records = document.records as JsonObject[];
  return TeamTransfersSchema.parse({
    status: "available",
    metadata: {
      contract_version: 1,
      validation_status: "valid",
      source: "BDFutbol",
      url: transferSnapshot.url,
      competition: "Primera Federación",
      competition_scope: "Liga",
      season: "2026-27",
      group: isRacing ? "I" : "II",
      team_id: teamId,
      capture_id: capture.capture_id,
      captured_at: capture.captured_at_utc,
      derived_at: asJsonObject(capture.derivation).derived_at_utc,
      extractor_version: capture.extractor_version,
      source_sha256: transferSnapshot.sha256,
      content_sha256: "e".repeat(64),
    },
    sections: document.sections,
    incoming: records.filter((record) => record.direction === "incoming"),
    outgoing: records.filter((record) => record.direction === "outgoing"),
    warnings: ["Los enlaces relacionados pueden ser históricos."],
  });
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
  window.history.replaceState({}, "", "/");
  window.sessionStorage.clear();
  clearTeamProfileCache();
  clearMatchPageCache();
  fetchMock.mockReset();
  fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(response(200, payloadFor(input))));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("dashboard de clasificación", () => {
  it("abre Jugadores, busca por nombre y navega a una ficha individual interna", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("link", { name: "Jugadores" }));

    expect(await screen.findByRole("heading", { name: "Jugadores" })).toBeInTheDocument();
    expect(screen.queryByText(/vistas publicadas|inventario generado|referencia de traspaso|pertenencia observada/i)).not.toBeInTheDocument();
    const search = screen.getByRole("searchbox", { name: "Buscar jugador" });
    fireEvent.change(search, { target: { value: "Nacho" } });
    const playerLink = await screen.findByRole("link", { name: /Nacho Castillo/ });
    expect(playerLink).toHaveAttribute("href", "/players/28577");
    expect(screen.queryByText("Jugador Referenciado")).not.toBeInTheDocument();

    fireEvent.click(playerLink);
    expect(window.location.pathname).toBe("/players/28577");
    expect(await screen.findByRole("heading", { name: "Nacho Castillo" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BDFutbol ↗" })).toHaveAttribute("target", "_blank");
    expect(await screen.findByRole("link", { name: "Jaén · Grupo II" })).toHaveAttribute("href", "/teams/49");
    expect(screen.getByRole("heading", { name: "Trayectoria y rendimiento" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(document.body.textContent).not.toMatch(/SHA-256|captura|procedencia|inventario|fuente.*discrepa|no certifica|four_views_verified|roster_membership_observed/i);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/v1/players/28577"))).toBe(true);
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("bdfutbol.com"))).toBe(true);
  });

  it("permite abrir directamente una ficha de jugador por URL", async () => {
    window.history.replaceState({}, "", "/players/28577");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Nacho Castillo" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/v1/players/28577"))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/v1/groups/2/bootstrap"))).toBe(true);
  });

  it("construye el directorio con ambos bootstraps y filtra sin nuevas solicitudes", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Clasificación" });
    fireEvent.click(screen.getByRole("link", { name: "Equipos" }));

    expect(await screen.findByText(/40 equipos disponibles/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Abrir ficha de/ })).toHaveLength(40);
    expect(screen.getByRole("button", { name: /Todos/ })).toHaveTextContent("40");
    expect(screen.getByRole("button", { name: /^Grupo I 20$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Grupo II 20$/ })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar equipo" }), { target: { value: "jaen" } });
    expect(screen.getAllByRole("link", { name: /Abrir ficha de/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Abrir ficha de Jaén, Grupo II" })).toHaveAttribute("href", "/teams/49");
    fireEvent.click(screen.getByRole("button", { name: /^Grupo I 20$/ }));
    expect(screen.getByText("No hay equipos que coincidan con la búsqueda.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("abre fichas por team_id y muestra solo sus datos deportivos del grupo correspondiente", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Clasificación" });
    fireEvent.click(screen.getByRole("link", { name: "Equipos" }));
    await screen.findByText(/40 equipos disponibles/);
    fireEvent.click(screen.getByRole("link", { name: "Abrir ficha de Racing de Ferrol, Grupo I" }));

    expect(await screen.findByRole("heading", { name: "Racing de Ferrol" })).toBeInTheDocument();
    expect(screen.getByText("GRUPO I · TEMPORADA 2026/27")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Últimos partidos" })).toBeInTheDocument();
    expect(document.querySelectorAll(".team-recent-list li")).toHaveLength(5);
    expect(screen.getByRole("link", { name: "BDFutbol ↗" })).toHaveAttribute("target", "_blank");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("abre directamente la ficha del Real Jaén y maneja IDs que no existen", async () => {
    window.history.replaceState({}, "", "/teams/49");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Jaén" })).toBeInTheDocument();
    expect(screen.getByText("GRUPO II · TEMPORADA 2026/27")).toBeInTheDocument();
    expect(document.querySelectorAll(".team-recent-list li")).toHaveLength(5);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    cleanup();
    window.history.replaceState({}, "", "/teams/99999");
    render(<App />);
    expect(await screen.findByText(/No hay un equipo con el identificador 99999/)).toBeInTheDocument();
  });

  it("abre el club de Clasificación dentro de la aplicación y conserva el enlace de fuente", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    const row = screen.getByRole("row", { name: /Jaén/ });
    const link = row.querySelector<HTMLAnchorElement>(".club-team-link");
    expect(link).toHaveAttribute("href", "/teams/49");
    expect(link?.querySelector("img.team-crest, .team-crest-fallback")).toBeInTheDocument();

    fireEvent.click(link!);
    expect(window.location.pathname).toBe("/teams/49");
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BDFutbol ↗" })).toHaveAttribute("target", "_blank");
  });

  it("recupera la pestaña y la búsqueda de Plantilla al volver de una ficha de jugador", async () => {
    window.sessionStorage.clear();
    window.history.replaceState({}, "", "/teams/49/roster");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Jaén" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("tab", { name: "Plantilla" }));
    const dorsalSort = screen.getByRole("button", { name: "Ordenar por Dorsal" });
    fireEvent.click(dorsalSort);
    expect(dorsalSort.closest("th")).toHaveAttribute("aria-sort", "ascending");
    const search = screen.getByRole("textbox", { name: "Buscar en la plantilla" });
    fireEvent.change(search, { target: { value: "Nacho" } });
    const playerLink = await screen.findByRole("link", { name: /Nacho Castillo/ });
    fireEvent.click(playerLink);
    expect(await screen.findByRole("heading", { name: "Nacho Castillo" })).toBeInTheDocument();

    window.history.replaceState({}, "", "/teams/49/roster");
    window.dispatchEvent(new PopStateEvent("popstate"));
    const rosterTab = await screen.findByRole("tab", { name: "Plantilla" });
    expect(rosterTab).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("textbox", { name: "Buscar en la plantilla" })).toHaveValue("Nacho");
    expect(document.querySelectorAll(".roster-biography-table tbody tr[data-player-id]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Ordenar por Dorsal" }).closest("th")).toHaveAttribute("aria-sort", "ascending");
  });

  it("enlaza local, visitante y matriz a fichas internas sin convertir marcadores en enlaces de equipo", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    await screen.findByRole("heading", { name: "Resultados" });
    const matchRow = container.querySelector<HTMLElement>(".results-match-row")!;
    const teamLinks = matchRow.querySelectorAll<HTMLAnchorElement>(".result-team-link");
    expect(teamLinks).toHaveLength(2);
    expect(teamLinks[0]?.getAttribute("href")).toMatch(/^\/teams\/\d+$/);
    expect(teamLinks[1]?.getAttribute("href")).toMatch(/^\/teams\/\d+$/);
    expect(matchRow.querySelector(".result-score")?.getAttribute("href")).toMatch(/^\/matches\/pf-2026-27-group-ii-bdfutbol-\d+$/);

    const scoreLink = matchRow.querySelector<HTMLAnchorElement>(".result-score")!;
    fireEvent.click(scoreLink);
    expect(window.location.pathname).toBe(scoreLink.getAttribute("href"));
    expect(await screen.findByRole("heading", { name: "PRIMERA FEDERACIÓN · GRUPO II · TEMPORADA 2026/27" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Información del partido" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Datos actualizados/)).not.toBeInTheDocument();
    expect(screen.getByText("Los detalles de este encuentro todavía no están disponibles.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Alineaciones" })).not.toBeInTheDocument();
    const sourceLink = screen.getByRole("link", { name: "Ficha en BDFutbol ↗" });
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink.getAttribute("href")).toMatch(/^https:\/\/www\.bdfutbol\.com\/es\/p\/p\.php\?id=/);
    const matchTeams = document.querySelectorAll<HTMLAnchorElement>(".match-page-team");
    expect(matchTeams).toHaveLength(2);
    expect(matchTeams[0]?.getAttribute("href")).toMatch(/^\/teams\/\d+$/);
    fireEvent.click(screen.getByRole("link", { name: "← Volver a Resultados" }));
    expect(window.location.pathname).toBe("/");
    expect(await screen.findByLabelText("Jornada de resultados")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Seleccionar grupo" })).toHaveValue("2");

    fireEvent.click(teamLinks[0]!);
    expect(window.location.pathname).toBe(teamLinks[0]?.getAttribute("href"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();

    cleanup();
    window.history.replaceState({}, "", "/");
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    await screen.findByRole("heading", { name: "Resultados" });
    const awayLink = document.querySelectorAll<HTMLAnchorElement>(".results-match-row .result-team-link")[1]!;
    fireEvent.click(awayLink);
    expect(window.location.pathname).toBe(awayLink.getAttribute("href"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();

    cleanup();
    window.history.replaceState({}, "", "/");
    const matrixView = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    await screen.findByRole("heading", { name: "Resultados" });
    const matrixRowLink = matrixView.container.querySelector<HTMLAnchorElement>(".matrix-row-team a[href='/teams/49']");
    const matrixColumnLink = matrixView.container.querySelector<HTMLAnchorElement>(".matrix-column-team a[href='/teams/49']");
    expect(matrixRowLink).toBeInTheDocument();
    expect(matrixColumnLink).toBeInTheDocument();
    fireEvent.click(matrixRowLink!);
    expect(window.location.pathname).toBe("/teams/49");
  });

  it("usa solo afiliaciones verificadas para enlazar equipos en Destacados", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    await screen.findByRole("heading", { name: "Destacados" });
    const teamLink = document.querySelector<HTMLAnchorElement>(".top-team-link[href^='/teams/']");
    expect(teamLink).toBeInTheDocument();
    expect(teamLink?.getAttribute("href")).toMatch(/^\/teams\/\d+$/);
    expect(document.querySelector(".top-player-link[href^='/players/']")).toBeInTheDocument();
    fireEvent.click(teamLink!);
    expect(window.location.pathname).toBe(teamLink?.getAttribute("href"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
  });

  it("mantiene como texto un jugador de Destacados sin ID corroborado en el inventario", async () => {
    const unverifiedTop = structuredClone(topBootstrap);
    const visibleRanking = unverifiedTop.rankings.find((ranking) => ranking.category === "goals")!;
    const firstPlayer = unverifiedTop.players.find((player) => player.player_id === visibleRanking.player_id)!;
    firstPlayer.internal_player_id = null;
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/top/bootstrap") ? response(200, unverifiedTop) : response(200, payloadFor(input)),
    ));
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    await screen.findByRole("heading", { name: "Destacados" });

    const playerName = firstPlayer.full_name ?? firstPlayer.display_name;
    const targetRow = [...document.querySelectorAll(".top-ranking-table tbody tr")]
      .find((row) => row.textContent?.includes(playerName));
    expect(targetRow).toBeDefined();
    expect(targetRow?.querySelector("a[href^='/players/']")).toBeNull();
  });

  it("enlaza clubes de Récords y Rachas y abre las fichas internas de los partidos", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Estadísticas" }));
    await screen.findByRole("heading", { name: "Estadísticas" });
    const recordTeam = document.querySelector<HTMLAnchorElement>(".record-match .statistics-team[href^='/teams/']");
    const streakTeam = document.querySelector<HTMLAnchorElement>(".streak-leader .statistics-team[href^='/teams/']");
    expect(recordTeam).toBeInTheDocument();
    expect(streakTeam).toBeInTheDocument();
    expect(document.querySelector(".record-score[href^='/matches/']")).toBeInTheDocument();
    fireEvent.click(recordTeam!);
    expect(window.location.pathname).toBe(recordTeam?.getAttribute("href"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
  });

  it("enlaza rivales de Últimos partidos al equipo correcto", async () => {
    window.history.replaceState({}, "", "/teams/49");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Últimos partidos" })).toBeInTheDocument();
    const opponent = document.querySelector<HTMLAnchorElement>(".team-recent-opponent-link");
    expect(opponent?.getAttribute("href")).toMatch(/^\/teams\/\d+$/);
    expect(opponent?.querySelector("img.team-recent-crest, .team-card-crest-fallback")).toBeInTheDocument();
    fireEvent.click(opponent!);
    expect(window.location.pathname).toBe(opponent?.getAttribute("href"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
  });

  it("muestra catálogo parcial y permite reintentar solo el grupo que falló", async () => {
    let group1Failed = false;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/groups/1/bootstrap") && !group1Failed) {
        group1Failed = true;
        return Promise.resolve(response(503, { detail: "unavailable" }));
      }
      return Promise.resolve(response(200, payloadFor(input)));
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Clasificación" });
    fireEvent.click(screen.getByRole("link", { name: "Equipos" }));

    expect(await screen.findByText(/20 equipos disponibles/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Abrir ficha de/ })).toHaveLength(20);
    expect(screen.getByText(/Grupo I: La API todavía no tiene/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(await screen.findByText(/40 equipos disponibles/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/groups/1/bootstrap"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/groups/2/bootstrap"))).toHaveLength(1);
  });

  it("muestra rutas inexistentes sin solicitar bootstraps deportivos", async () => {
    window.history.replaceState({}, "", "/no-existe");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "No encontramos esta página" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("mantiene filtros deportivos y grupo activo al alternar Competiciones y Equipos", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.change(screen.getByLabelText("Seleccionar grupo"), { target: { value: "1" } });
    await screen.findByRole("row", { name: /Pontevedra/ });
    const group1View = document.querySelector<HTMLElement>("#group-dashboard-1")!;
    fireEvent.change(group1View.querySelector('select[aria-label="Tipo de rango"]')!, { target: { value: "dates" } });
    fireEvent.change(group1View.querySelector('input[aria-label="Fecha inicial"]')!, { target: { value: "2026-09-05" } });
    fireEvent.click(screen.getByRole("link", { name: "Equipos" }));
    expect(await screen.findByText(/40 equipos disponibles/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Competiciones" }));

    const persistedGroup1View = document.querySelector<HTMLElement>("#group-dashboard-1");
    expect(persistedGroup1View).not.toBeNull();
    expect(persistedGroup1View?.querySelector<HTMLSelectElement>('select[aria-label="Tipo de rango"]')).toHaveValue("dates");
    expect(persistedGroup1View?.querySelector<HTMLInputElement>('input[aria-label="Fecha inicial"]')).toHaveValue("2026-09-05");
    expect(screen.getByRole("combobox", { name: "Seleccionar grupo" })).toHaveValue("1");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("atiende la navegación Atrás/Adelante del navegador mediante popstate", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Clasificación" });
    fireEvent.click(screen.getByRole("link", { name: "Equipos" }));
    expect(await screen.findByRole("heading", { name: "Equipos" })).toBeInTheDocument();
    window.history.replaceState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: "Clasificación" })).toBeInTheDocument();
    window.history.replaceState({}, "", "/teams");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: "Equipos" })).toBeInTheDocument();
  });

  it("valida cobertura y afiliaciones de Destacados por sus datos, sin IDs fijos", () => {
    expect(TopBootstrapSchema.safeParse(group1TopBootstrap).success).toBe(true);

    const resolved = structuredClone(group1TopBootstrap);
    const resolvedPlayer = resolved.players.find((player) => player.player_id === 304291)!;
    const resolvedTeam = group1Bootstrap.teams.find((team) => team.team_id === 58)!;
    Object.assign(resolvedPlayer, {
      team_id: resolvedTeam.team_id,
      team_name: resolvedTeam.name,
      team_url: resolvedTeam.team_url,
      crest_url: resolvedTeam.crest_url,
    });
    resolved.affiliation_conflicts = [];
    resolved.affiliation_absences = [];
    resolved.warnings = resolved.warnings.filter((warning) => !warning.startsWith("Afiliación de equipo ambigua para player_id="));
    expect(TopBootstrapSchema.safeParse(resolved).success).toBe(true);

    const absent = structuredClone(group1TopBootstrap);
    absent.affiliation_conflicts = [];
    absent.affiliation_absences = [{
      player_id: 304291,
      source_records: ["DESTACATS_JS.LG", "table#tab_estran"],
      reason: "not_published",
    }];
    absent.warnings = absent.warnings.filter((warning) => !warning.startsWith("Afiliación de equipo ambigua para player_id="));
    absent.warnings.push(
      "Afiliación de equipo no publicada para player_id=304291; se conserva como null en el catálogo y la ausencia está respaldada por las fuentes indicadas en affiliation_absences.",
    );
    expect(TopBootstrapSchema.safeParse(absent).success).toBe(true);

    const multiple = structuredClone(group1TopBootstrap);
    const extraPlayer = {
      ...multiple.players.find((player) => player.player_id === 304291)!,
      player_id: 999991,
      display_name: "Jugador sintético",
      full_name: "Jugador sintético de prueba",
      profile_url: "https://www.bdfutbol.com/es/j/j999991.html",
      photo_url: "https://www.bdfutbol.com/i/m/999991.png",
    };
    multiple.players.push(extraPlayer);
    multiple.affiliation_conflicts.push({
      player_id: extraPlayer.player_id,
      affiliations: multiple.affiliation_conflicts[0]!.affiliations,
    });
    multiple.warnings.push(
      "Afiliación de equipo ambigua para player_id=999991; se conserva como null en el catálogo y las fuentes/IDs están en affiliation_conflicts.",
    );
    expect(TopBootstrapSchema.safeParse(multiple).success).toBe(true);

    const unexplained = structuredClone(multiple);
    unexplained.affiliation_conflicts = unexplained.affiliation_conflicts.slice(1);
    expect(TopBootstrapSchema.safeParse(unexplained).success).toBe(false);
  });

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
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/matches/bootstrap", expect.anything());
    expect(screen.getByText("Primera Federación · Grupo II")).toBeInTheDocument();
    expect(screen.queryByText(/Generación MATCH-00/)).not.toBeInTheDocument();
  });

  it("mantiene Resultados en su endpoint MATCH-00 separado del bootstrap de Clasificación", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    expect(await screen.findByRole("heading", { name: "Resultados" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/matches/bootstrap"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/groups/2/bootstrap"))).toHaveLength(1);
    expect(screen.queryByText(/Generación MATCH-00/)).not.toBeInTheDocument();
  });

  it("cambia jornadas, permite Todas y conserva resultados y matriz sin nuevas peticiones", async () => {
    const { container } = render(<App />);
    await screen.findByRole("heading", { name: "General" });
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    await screen.findByRole("heading", { name: "Resultados" });
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
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
    const unknownAffiliation = ambiguousPlayer.lastElementChild?.querySelector("[aria-label='Equipo no determinado']");
    expect(unknownAffiliation).toBeInTheDocument();
    expect(unknownAffiliation).toHaveAttribute("title", expect.stringContaining("Afiliación de equipo ambigua"));
    expect(ambiguousPlayer.lastElementChild?.querySelector("a[href^='/teams/']")).toBeNull();

    fireEvent.click(within(group1View).getByRole("tab", { name: "Árbitros" }));
    expect(await screen.findByText("43 árbitros · Grupo I")).toBeInTheDocument();
    expect(within(group1View).getByLabelText("Grupo")).toHaveValue("group1");

    fireEvent.click(within(group1View).getByRole("tab", { name: "Estadísticas" }));
    expect(await screen.findByText("PRIMERA FEDERACIÓN · GRUPO I")).toBeInTheDocument();
    expect(screen.getByText("Partidos disputados").parentElement).toHaveTextContent("60");

    fireEvent.change(groupPicker, { target: { value: "2" } });
    expect(await screen.findByText("PRIMERA FEDERACIÓN · GRUPO II")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(7);
    fireEvent.change(groupPicker, { target: { value: "1" } });
    expect(await screen.findByText("PRIMERA FEDERACIÓN · GRUPO I")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(7);

    fireEvent.click(within(group1View).getByRole("tab", { name: "Clasificación" }));
    expect(within(group1View).getByLabelText("Tipo de rango")).toHaveValue("rounds");
    expect(within(group1View).getByLabelText("Jornada inicial")).toHaveValue("2");
    expect(within(group1View).getByLabelText("Jornada final")).toHaveValue("4");
    expect(fetchMock).toHaveBeenCalledTimes(7);
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
        : String(input).endsWith("/api/v1/matches/bootstrap")
          ? response(200, matchResultsBootstrap)
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
    expect(fetchMock).toHaveBeenCalledTimes(3);
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
        : String(input).endsWith("/api/v1/matches/bootstrap")
          ? response(200, matchResultsBootstrap)
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
    await screen.findByRole("heading", { name: "Resultados" });
    fireEvent.change(screen.getByLabelText("Jornada de resultados"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("tab", { name: "Destacados" }));
    expect(await screen.findByRole("heading", { name: "Destacados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Resultados" }));
    expect(screen.getByLabelText("Jornada de resultados")).toHaveValue("all");
    expect(fetchMock).toHaveBeenCalledTimes(3);
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
      <TopSection data={unknownPercentage} loadState="ready" errorMessage="" onRetry={() => undefined} teams={apiBootstrap.teams} onNavigate={() => undefined} />,
    );
    expect(screen.getByRole("heading", { name: "Extranjeros — 101 (—)" })).toBeInTheDocument();

    const zeroPercentage = {
      ...topBootstrap,
      foreigners_summary: { ...topBootstrap.foreigners_summary, source_percentage: 0 },
    } as TopBootstrap;
    rerender(<TopSection data={zeroPercentage} loadState="ready" errorMessage="" onRetry={() => undefined} teams={apiBootstrap.teams} onNavigate={() => undefined} />);
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
      <TopSection data={sortableFixture} loadState="ready" errorMessage="" onRetry={() => undefined} teams={apiBootstrap.teams} onNavigate={() => undefined} />,
    );
    const table = container.querySelector(".foreigners-table") as HTMLElement;
    const goalsButton = within(table).getByRole("button", { name: /Goles/ });
    const values = () => Array.from(table.querySelectorAll("tbody tr"))
      .map((row) => row.children[6]?.textContent?.trim());
    const lastTwoPlayerIds = () => Array.from(table.querySelectorAll("tbody tr"))
      .slice(-2)
      .map((row) => Number(row.querySelector("a")?.getAttribute("href")?.match(/\/players\/(\d+)$/)?.[1]));
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

  it("muestra la Plantilla unificada de Jaén con tablas, indicadores y táctica enlazados por ID", async () => {
    window.history.replaceState({}, "", "/teams/49/roster");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Jaén" })).toBeInTheDocument();
    expect(await screen.findByText("Entrenadores publicados")).toBeInTheDocument();
    const sectionNavigation = screen.getByRole("navigation", { name: "Secciones de Jaén" });
    expect(within(sectionNavigation).getAllByRole("link").map((link) => link.textContent)).toEqual(["Resumen", "Plantilla", "Seguimiento", "Traspasos", "Partidos"]);
    expect(screen.getByRole("tab", { name: "Alineación" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Plantilla" })).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByRole("heading", { name: "Estadísticas de temporada" })).not.toBeInTheDocument();
    expect(screen.getByText("La captura no contiene estados enriquecidos de Seguimiento; no son necesarios para Plantilla.")).toBeInTheDocument();

    const roster = teamRosterPayload(49);
    const starters = screen.getByRole("region", { name: "Tabla de Titulares" });
    const substitutes = screen.getByRole("region", { name: "Tabla de Suplentes" });
    expect(screen.getByRole("heading", { name: "Titulares" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Suplentes" })).toBeInTheDocument();
    expect(within(starters).getAllByRole("row")).toHaveLength(12);
    expect(within(substitutes).getAllByRole("row")).toHaveLength(15);
    const playerRows = [...starters.querySelectorAll("tbody tr[data-player-id]"), ...substitutes.querySelectorAll("tbody tr[data-player-id]")];
    expect(new Set(playerRows.map((row) => row.getAttribute("data-player-id"))).size).toBe(25);
    expect(new Set(playerRows.map((row) => row.getAttribute("data-player-id")))).toEqual(new Set(roster.players.map((player) => String(player.player_id))));

    const morillas = roster.players.find((player) => player.display_name === "Morillas");
    const morillasStatistics = roster.statistics.find((statistics) => statistics.player_id === morillas?.player_id);
    expect(morillasStatistics?.goals).toBe(0);
    const morillasRow = starters.querySelector(`tr[data-player-id="${morillas?.player_id}"]`);
    expect(morillasRow?.children[11]).toHaveTextContent("0");
    expect(morillasRow).not.toHaveTextContent("-5");

    expect(screen.getByText("Ha jugado en 1ª división")).toBeInTheDocument();
    expect(screen.getByText("Ha jugado en 2ª división")).toBeInTheDocument();
    expect(screen.getByText("Internacional en categorías inferiores")).toBeInTheDocument();
    expect(screen.getByText("Nueva incorporación")).toBeInTheDocument();
    const tactic = screen.getByRole("group", { name: "Representación aproximada de la táctica" });
    const markers = [...tactic.querySelectorAll<HTMLElement>("[data-player-id]")];
    expect(markers).toHaveLength(11);
    expect(new Set(markers.map((marker) => marker.dataset.playerId))).toEqual(new Set(roster.tactical_visualization?.positions.map((position) => String(position.player_id))));
    expect(screen.getByText("Representación aproximada basada en los datos de origen. No corresponde necesariamente al dibujo táctico real.")).toBeInTheDocument();

    const firstPlayer = roster.players[0]!;
    const search = screen.getByRole("textbox", { name: "Buscar jugador en titulares y suplentes" });
    fireEvent.change(search, { target: { value: firstPlayer.display_name.slice(0, 3) } });
    expect(screen.getAllByRole("row").filter((row) => row.hasAttribute("data-player-id"))).toHaveLength(1);
    const filteredRow = screen.getAllByRole("row").find((row) => row.getAttribute("data-player-id") === String(firstPlayer.player_id));
    expect(filteredRow).toBeInTheDocument();
    expect(within(filteredRow!).getByRole("link", { name: firstPlayer.display_name })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "" } });

    fireEvent.click(screen.getByRole("link", { name: "Resumen" }));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Plantilla" }));
    expect(await screen.findByText("Entrenadores publicados")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/roster"))).toHaveLength(1);
    expect(window.location.pathname).toBe("/teams/49/roster");
  });

  it("abre directamente Plantilla de Racing de Ferrol, Grupo I", async () => {
    window.history.replaceState({}, "", "/teams/48/roster");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Racing de Ferrol" })).toBeInTheDocument();
    expect(screen.getByText("GRUPO I · TEMPORADA 2026/27")).toBeInTheDocument();
    expect(await screen.findByText("Entrenadores publicados")).toBeInTheDocument();
    const racing = teamRosterPayload(48);
    expect(racing.players).toHaveLength(25);
    expect(screen.getByRole("heading", { name: "Titulares" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Suplentes" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Representación aproximada de la táctica" }).querySelectorAll("[data-player-id]")).toHaveLength(11);
    const tacticalLink = screen.getByRole("group", { name: "Representación aproximada de la táctica" }).querySelector<HTMLAnchorElement>("a.tactical-player-marker");
    expect(tacticalLink).toHaveAttribute("href", `/players/${tacticalLink?.dataset.playerId}`);
    expect(screen.getByRole("tab", { name: "Alineación" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Plantilla" })).toHaveAttribute("aria-selected", "false");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/48/seasons/2026-27/roster"))).toHaveLength(1);
  });

  it("ofrece biografías y todas las estadísticas locales para los 25 jugadores", async () => {
    const roster = teamRosterPayload(49);
    window.history.replaceState({}, "", "/teams/49/roster");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Entrenadores publicados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Plantilla" }));
    expect(screen.getByRole("heading", { name: "Jugadores" })).toBeInTheDocument();
    const bioTable = screen.getByRole("region", { name: "Tabla biográfica de jugadores" });
    const bioRows = [...bioTable.querySelectorAll<HTMLTableRowElement>("tbody tr[data-player-id]")];
    expect(bioRows).toHaveLength(25);
    expect(bioRows[0]?.dataset.playerId).toBe(String(roster.players[0]?.player_id));
    const firstPlayer = roster.players[0]!;
    expect(bioRows[0]?.querySelector("a[href^='/players/']")).toHaveAttribute("href", `/players/${firstPlayer.player_id}`);
    const birthDate = firstPlayer.birth_date ? `${firstPlayer.birth_date.slice(8, 10)}/${firstPlayer.birth_date.slice(5, 7)}/${firstPlayer.birth_date.slice(0, 4)}` : "—";
    expect(bioRows[0]?.cells[3]).toHaveTextContent(birthDate);
    expect(bioRows[0]?.cells[2]).toHaveTextContent(firstPlayer.full_name ?? "—");
    expect(bioRows[0]?.cells[6]).toHaveTextContent("equivalencia no verificada");
    expect(screen.getByRole("region", { name: "Datos biográficos de entrenadores" })).toBeInTheDocument();
    expect(screen.getByText(roster.coaches[0]!.full_name!)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Buscar en la plantilla" }), { target: { value: firstPlayer.display_name } });
    expect(bioTable.querySelectorAll("tbody tr[data-player-id]")).toHaveLength(1);
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar en la plantilla" }), { target: { value: "" } });
    fireEvent.click(within(bioTable).getByRole("button", { name: "Ordenar por Dorsal" }));
    const jerseyByPlayer = new Map(roster.memberships.map((membership) => [membership.player_id, membership.jersey_number]));
    const expectedJerseyOrder = roster.players.map((player, sourceIndex) => ({ playerId: player.player_id, jersey: jerseyByPlayer.get(player.player_id), sourceIndex }))
      .sort((left, right) => {
        if (left.jersey === null || left.jersey === undefined) return right.jersey === null || right.jersey === undefined ? left.sourceIndex - right.sourceIndex : 1;
        if (right.jersey === null || right.jersey === undefined) return -1;
        return left.jersey - right.jersey || left.sourceIndex - right.sourceIndex;
      })
      .map((item) => String(item.playerId));
    expect([...bioTable.querySelectorAll<HTMLTableRowElement>("tbody tr[data-player-id]")].map((row) => row.dataset.playerId)).toEqual(expectedJerseyOrder);

    fireEvent.click(screen.getByRole("tab", { name: "Análisis" }));
    const analysisTable = screen.getByRole("region", { name: "Tabla de estadísticas de jugadores" });
    const analysisRows = [...analysisTable.querySelectorAll<HTMLTableRowElement>("tbody tr[data-player-id]")];
    expect(screen.getByRole("heading", { name: "Estadísticas de temporada" })).toBeInTheDocument();
    expect(analysisRows).toHaveLength(25);
    expect(within(analysisTable).getAllByRole("columnheader")).toHaveLength(20);
    for (const header of [
      "PJ · Partidos jugados", "PT · Partidos como titular", "PC · Partidos completos",
      "PS · Partidos como suplente", "PX · Partidos en los que fue sustituido", "C · Convocado sin jugar",
      "MIN · Minutos jugados", "TA · Tarjetas amarillas", "TR · Tarjetas rojas", "G · Goles",
      "MIN/G · Minutos por gol", "GP · Goles de penalti", "GPP · Goles en propia puerta",
      "GE · Goles encajados", "PG · Victorias del equipo", "PE · Empates del equipo", "PP · Derrotas del equipo",
    ]) expect(within(analysisTable).getByRole("button", { name: `Ordenar por ${header}` })).toBeInTheDocument();
    const firstStatistics = roster.statistics.find((item) => item.player_id === firstPlayer.player_id)!;
    const firstAnalysisRow = analysisRows.find((row) => row.dataset.playerId === String(firstPlayer.player_id))!;
    expect(firstAnalysisRow.querySelector("a[href^='/players/']")).toHaveAttribute("href", `/players/${firstPlayer.player_id}`);
    expect(firstAnalysisRow.cells[3 + 6]).toHaveTextContent(String(firstStatistics.minutes_played));
    expect(firstAnalysisRow.cells[3 + 11]).toHaveTextContent(String(firstStatistics.penalty_goals));
    expect(firstAnalysisRow.cells[3 + 16]).toHaveTextContent(String(firstStatistics.team_losses));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/roster"))).toHaveLength(1);
  });

  it("deja los valores ausentes al final en ambos sentidos y no arrastra la vista entre equipos", () => {
    const jaen = teamRosterPayload(49);
    const racing = teamRosterPayload(48);
    const nullPlayerId = jaen.players[0]!.player_id;
    const rosterWithNull = TeamRosterSchema.parse({
      ...jaen,
      statistics: jaen.statistics.map((item) => item.player_id === nullPlayerId ? { ...item, goals: null } : item),
    });
    const { rerender } = render(<TeamRosterSection roster={rosterWithNull} />);
    fireEvent.click(screen.getByRole("tab", { name: "Análisis" }));
    const analysisTable = screen.getByRole("region", { name: "Tabla de estadísticas de jugadores" });
    const goalSort = within(analysisTable).getByRole("button", { name: "Ordenar por G · Goles" });
    fireEvent.click(goalSort);
    const rowsAscending = [...analysisTable.querySelectorAll<HTMLTableRowElement>("tbody tr[data-player-id]")];
    expect(rowsAscending.at(-1)?.dataset.playerId).toBe(String(nullPlayerId));
    expect(rowsAscending.at(-1)?.cells[12]).toHaveTextContent("—");
    fireEvent.click(goalSort);
    const rowsDescending = [...analysisTable.querySelectorAll<HTMLTableRowElement>("tbody tr[data-player-id]")];
    expect(rowsDescending.at(-1)?.dataset.playerId).toBe(String(nullPlayerId));

    rerender(<TeamRosterSection roster={racing} />);
    expect(screen.getByRole("tab", { name: "Alineación" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Titulares" })).toBeInTheDocument();
  });

  it("recuerda la vista por equipo al volver desde Resumen sin volver a pedir la Plantilla", async () => {
    window.history.replaceState({}, "", "/teams/49/roster");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Entrenadores publicados" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Plantilla" }));
    fireEvent.click(screen.getByRole("link", { name: "Resumen" }));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Plantilla" }));
    expect(await screen.findByRole("heading", { name: "Jugadores" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/roster"))).toHaveLength(1);
  });

  it("mantiene el resumen disponible si un equipo conocido aún no tiene Plantilla adquirida", async () => {
    const uncapturedTeam = apiBootstrap.teams.find((team) => team.team_id !== 49 && team.team_id !== 48);
    expect(uncapturedTeam).toBeDefined();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).includes("/roster")) {
        return Promise.resolve(response(404, { detail: { code: "profile_not_captured", message: "not captured" } }));
      }
      return Promise.resolve(response(200, payloadFor(input)));
    });
    window.history.replaceState({}, "", `/teams/${uncapturedTeam?.team_id}/roster`);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Plantilla aún no adquirida" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Resumen" })).toHaveAttribute("href", `/teams/${uncapturedTeam?.team_id}`);
    fireEvent.click(screen.getByRole("link", { name: "Resumen" }));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("conserva ceros y representa los valores ausentes con un guion", () => {
    const captured = teamRosterPayload(49);
    const zeroStat = captured.statistics.find((item) => item.goals === 0);
    const zeroPlayer = captured.players.find((player) => player.player_id === zeroStat?.player_id);
    expect(zeroPlayer).toBeDefined();
    const nullPlayer = captured.players.find((player) => player.player_id !== zeroPlayer?.player_id)!;
    const syntheticRoster = TeamRosterSchema.parse({
      ...captured,
      statistics: captured.statistics.map((item) => item.player_id === nullPlayer.player_id ? { ...item, goals: null } : item),
    });
    render(<TeamRosterSection roster={syntheticRoster} />);
    const nullRow = document.querySelector(`tr[data-player-id="${nullPlayer.player_id}"]`);
    const zeroRow = document.querySelector(`tr[data-player-id="${zeroPlayer!.player_id}"]`);
    expect(nullRow?.children[11]).toHaveTextContent("—");
    expect(zeroRow?.children[11]).toHaveTextContent("0");
  });

  it("muestra el Seguimiento completo de Jaén, con fotos y eventos validados, sin nuevas peticiones al cambiar de modo", async () => {
    window.history.replaceState({}, "", "/teams/49/follow");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Seguimiento" })).toBeInTheDocument();
    const matrix = await screen.findByTestId("team-follow-matrix");
    const followPlayerLink = matrix.querySelector<HTMLAnchorElement>("a.follow-player-link");
    expect(followPlayerLink?.getAttribute("href")).toMatch(/^\/players\/\d+$/);
    const sectionNavigation = screen.getByRole("navigation", { name: "Secciones de Jaén" });
    expect(within(sectionNavigation).getAllByRole("link").map((link) => link.textContent)).toEqual(["Resumen", "Plantilla", "Seguimiento", "Traspasos", "Partidos"]);
    expect(screen.getByRole("tab", { name: "Partidos" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("6 jornadas capturadas")).toBeInTheDocument();
    expect(within(matrix).getAllByRole("row")).toHaveLength(26);
    expect(within(matrix).getAllByRole("columnheader")).toHaveLength(7);
    const jaenPhotoPlayer = teamFollowPayload(49).players.find((player) => player.photo_url)!;
    const photoRow = matrix.querySelector(`tbody tr[data-player-id="${jaenPhotoPlayer.player_id}"]`);
    expect(photoRow?.querySelector("img.follow-player-photo")).toHaveAttribute("src", jaenPhotoPlayer.photo_url);
    const minuteRows = jaenPlayerMatchMinutes.records as Array<{ player_id: number; match_id: string; value: number | null }>;
    expect(minuteRows.some((item) => item.value === 0)).toBe(true);
    expect(minuteRows.some((item) => item.value === null)).toBe(true);
    expect(document.querySelector('.team-follow-matrix [aria-label="0 minutos"]')).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Tarjetas" }));
    const yellowCards = await screen.findAllByLabelText(/\d+ tarjetas? amarillas? verificadas?/);
    const redCards = await screen.findAllByLabelText(/\d+ tarjetas? rojas? verificadas?/);
    expect(yellowCards).toHaveLength(13);
    expect(redCards).toHaveLength(2);
    expect(yellowCards.some((item) => item.textContent?.includes("×2"))).toBe(true);
    fireEvent.click(screen.getByRole("tab", { name: "Goles" }));
    const goals = await screen.findAllByLabelText(/\d+ gol(?:es)?/);
    expect(goals.reduce((sum, item) => sum + Number(item.textContent), 0)).toBe(8);
    fireEvent.click(screen.getByRole("tab", { name: "Todo" }));
    expect(await screen.findAllByLabelText(/\d+ tarjetas? amarillas? verificadas?/)).toHaveLength(13);
    expect(screen.getAllByLabelText(/\d+ tarjetas? rojas? verificadas?/)).toHaveLength(2);
    expect(screen.getAllByLabelText(/\d+ gol(?:es)? verificado(?:s)?/).reduce((sum, item) => sum + Number(item.getAttribute("aria-label")?.match(/^\d+/)?.[0] ?? 0), 0)).toBe(8);
    expect(screen.getByText(/Tarjetas, Goles, Todo reconstruidos offline/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/follow"))).toHaveLength(1);

    fireEvent.click(within(sectionNavigation).getByRole("link", { name: "Plantilla" }));
    expect(await screen.findByText("Entrenadores publicados")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("navigation", { name: "Secciones de Jaén" })).getByRole("link", { name: "Seguimiento" }));
    expect(await screen.findByTestId("team-follow-matrix")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/follow"))).toHaveLength(1);
  });

  it("resuelve acceso directo y navegación Atrás/Adelante a Seguimiento en la ruta de equipo", async () => {
    window.history.replaceState({}, "", "/teams/49/follow");
    render(<App />);
    expect(await screen.findByTestId("team-follow-matrix")).toBeInTheDocument();

    window.history.replaceState({}, "", "/teams/49");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();

    window.history.replaceState({}, "", "/teams/49/follow");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByTestId("team-follow-matrix")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/follow"))).toHaveLength(1);
  });

  it("muestra Altas y Bajas reales del Jaén con fotos, enlaces y búsqueda local", async () => {
    window.history.replaceState({}, "", "/teams/49/transfers");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Traspasos" })).toBeInTheDocument();
    const altas = await screen.findByRole("region", { name: "Altas" });
    const bajas = await screen.findByRole("region", { name: "Bajas" });
    expect(within(altas).getAllByRole("row")).toHaveLength(15);
    expect(within(bajas).getAllByRole("row")).toHaveLength(21);
    expect(within(altas).getByRole("link", { name: "Álex Pérez" })).toHaveAttribute("href", "/players/304042");
    expect(within(bajas).getByRole("link", { name: "Rabanillo" })).toHaveAttribute("href", "/players/22537");
    expect(within(bajas).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(bajas).getAllByText("Código por · sin equivalencia validada").length).toBeGreaterThan(0);
    const photo = altas.querySelector('img[src="https://www.bdfutbol.com/i/m/304042.png"]');
    expect(photo).toHaveAttribute("src", "https://www.bdfutbol.com/i/m/304042.png");

    fireEvent.change(screen.getByRole("textbox", { name: "Buscar futbolista o equipo" }), { target: { value: "rabanillo" } });
    expect(within(altas).getByText("No hay resultados para la búsqueda.")).toBeInTheDocument();
    expect(within(bajas).getAllByRole("row")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/49/seasons/2026-27/transfers"))).toHaveLength(1);
    expect(within(screen.getByRole("navigation", { name: "Secciones de Jaén" })).getAllByRole("link").map((link) => link.textContent))
      .toEqual(["Resumen", "Plantilla", "Seguimiento", "Traspasos", "Partidos"]);
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar futbolista o equipo" }), { target: { value: "" } });
    const verifiedRelatedTeam = altas.querySelector<HTMLAnchorElement>("a[href='/teams/488']");
    expect(verifiedRelatedTeam).toHaveTextContent("Juventud de Torremolinos");
    fireEvent.click(verifiedRelatedTeam!);
    expect(window.location.pathname).toBe("/teams/488");
    expect(await screen.findByRole("heading", { name: "Juventud de Torremolinos" })).toBeInTheDocument();
  });

  it("cambia entre Traspasos directos de equipos sin mezclar sus filas y conserva navegación", async () => {
    window.history.replaceState({}, "", "/teams/49/transfers");
    render(<App />);
    expect(await screen.findByRole("link", { name: "Rabanillo" })).toBeInTheDocument();

    window.history.replaceState({}, "", "/teams/48/transfers");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("link", { name: "Parera" })).toHaveAttribute("href", "/players/23024");
    expect(screen.queryByRole("link", { name: "Rabanillo" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/48/seasons/2026-27/transfers"))).toHaveLength(1);

    window.history.replaceState({}, "", "/teams/48");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    window.history.replaceState({}, "", "/teams/48/transfers");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("link", { name: "Parera" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/48/seasons/2026-27/transfers"))).toHaveLength(1);
  });

  it("muestra el estado sin captura de Traspasos sin bloquear Resumen", async () => {
    const uncaptured = apiBootstrap.teams.find((team) => team.team_id !== 48 && team.team_id !== 49)!;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith(`/api/v1/teams/${uncaptured.team_id}/seasons/2026-27/transfers`)) {
        return Promise.resolve(response(404, { detail: { code: "transfers_not_captured", message: "not captured" } }));
      }
      return Promise.resolve(response(200, payloadFor(input)));
    });
    window.history.replaceState({}, "", `/teams/${uncaptured.team_id}/transfers`);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Traspasos aún no adquiridos" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Resumen" }));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("muestra el calendario, progreso y récords reales del Jaén con filtros locales", async () => {
    window.history.replaceState({}, "", "/teams/49/matches");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(screen.getByText("6 disputados · 32 pendientes")).toBeInTheDocument();
    expect(screen.getByText(/Datos capturados el 10 de octubre de 2026/)).toBeInTheDocument();
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(38);
    const firstJaenFixture = document.querySelector('tr[data-match-id="272523"]');
    expect(firstJaenFixture).toHaveTextContent("J1");
    expect(firstJaenFixture?.querySelector("time")).toHaveTextContent("30 ago 2026");
    expect(firstJaenFixture?.querySelector(".team-match-score")).toHaveTextContent("0 : 3");
    expect(firstJaenFixture?.querySelector(".team-match-score")).toHaveClass("is-win");
    expect(firstJaenFixture?.querySelector(".team-match-score")).toHaveAttribute("aria-label", "Victoria: 0 : 3");
    expect(firstJaenFixture?.querySelector('a[href="/teams/89"]')).toBeInTheDocument();
    expect(screen.getByTestId("team-progress-chart")).toHaveAttribute("data-progress-count", "6");
    expect(screen.getByRole("heading", { name: "Mayor victoria en casa" })).toBeInTheDocument();
    expect(screen.getByText("1 gol")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar partidos por estado" }), { target: { value: "played" } });
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(6);
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar partidos por estado" }), { target: { value: "all" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar partidos por condición" }), { target: { value: "home" } });
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(19);
    expect([...screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")].every((row) => {
      const matchId = row.getAttribute("data-match-id");
      return matchesSource.matches.find((match) => match.match_id === matchId)?.home_team_id === 49;
    })).toBe(true);
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar partidos por condición" }), { target: { value: "away" } });
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(19);
    expect([...screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")].every((row) => {
      const matchId = row.getAttribute("data-match-id");
      return matchesSource.matches.find((match) => match.match_id === matchId)?.away_team_id === 49;
    })).toBe(true);
    const drawRecord = screen.getByRole("heading", { name: "Mayor racha de empates" }).closest("article");
    expect(drawRecord?.querySelectorAll("li.is-new-run")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([url]) => /\/api\/v1\/groups\/[12]\/bootstrap$/.test(String(url)))).toBe(true);
  });

  it("abre Partidos del Grupo I y un tercer club sin perfil adquirido desde su bootstrap", async () => {
    window.history.replaceState({}, "", "/teams/48/matches");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(screen.getByText("GRUPO I · TEMPORADA 2026/27")).toBeInTheDocument();
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(38);
    expect(screen.queryByText("Jaén", { selector: ".team-match-team span" })).not.toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([url]) => /\/api\/v1\/teams\/\d+\/seasons\/2026-27\/(roster|follow|transfers)$/.test(String(url)))).toBe(false);
  });

  it("muestra el calendario de un tercer club aunque no tenga captura de perfil", async () => {
    const uncapturedTeam = apiBootstrap.teams.find((team) => team.team_id !== 48 && team.team_id !== 49)!;
    window.history.replaceState({}, "", `/teams/${uncapturedTeam.team_id}/matches`);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: uncapturedTeam.name })).toBeInTheDocument();
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(38);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([url]) => /\/api\/v1\/teams\/\d+\/seasons\/2026-27\/(roster|follow|transfers)$/.test(String(url)))).toBe(false);
  });

  it("distingue una fecha de jornada y una fecha ausente sin inventar valores", async () => {
    const datesBootstrap = {
      ...apiBootstrap,
      matches: apiBootstrap.matches.map((match) => match.match_id === "272523"
        ? { ...match, source_match_date: null }
        : match.match_id === "272532"
          ? { ...match, source_match_date: null, matchday_date: null }
          : match),
    };
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/bootstrap")
        ? response(200, datesBootstrap)
        : response(200, payloadFor(input)),
    ));
    window.history.replaceState({}, "", "/teams/49/matches");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(document.querySelector('tr[data-match-id="272523"] .team-match-date')).toHaveTextContent("30 ago 2026Fecha de jornada");
    expect(document.querySelector('tr[data-match-id="272532"] .team-match-date')).toHaveTextContent("—");
    expect(document.querySelector('tr[data-match-id="272532"] .team-match-date')).not.toHaveTextContent("2026");
  });

  it("no dibuja progreso cuando el bootstrap no contiene la serie del equipo", async () => {
    const progresslessBootstrap = { ...apiBootstrap, progress: [] };
    fetchMock.mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      String(input).endsWith("/api/v1/groups/2/bootstrap")
        ? response(200, progresslessBootstrap)
        : response(200, payloadFor(input)),
    ));
    window.history.replaceState({}, "", "/teams/49/matches");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(screen.queryByTestId("team-progress-chart")).not.toBeInTheDocument();
    expect(screen.getByText("No hay una serie de progreso disponible para este equipo.")).toBeInTheDocument();
  });

  it("navega a la ficha del rival y vuelve por historial sin adquirir partidos ni mezclar grupos", async () => {
    window.history.replaceState({}, "", "/teams/49/matches");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();

    fireEvent.click(document.querySelector('tr[data-match-id="272523"] a[href="/teams/89"]') as HTMLAnchorElement);
    expect(window.location.pathname).toBe("/teams/89");
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("navigation", { name: "Secciones de Europa" })).getByRole("link", { name: "Partidos" }));
    expect(window.location.pathname).toBe("/teams/89/matches");
    expect(await screen.findByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(screen.getByRole("table").querySelectorAll("tbody tr[data-match-id]")).toHaveLength(38);
    expect(screen.queryByText("Racing de Ferrol", { selector: ".team-match-team span" })).not.toBeInTheDocument();

    window.history.replaceState({}, "", "/teams/49/matches");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: "Jaén" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Partidos" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("muestra los eventos verificados de Racing y mantiene las cuatro vistas locales", async () => {
    window.history.replaceState({}, "", "/teams/48/follow");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Seguimiento" })).toBeInTheDocument();
    const table = await screen.findByTestId("team-follow-matrix");
    expect(screen.getByText("GRUPO I · TEMPORADA 2026/27")).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(26);
    const racingPhotoPlayer = teamFollowPayload(48).players.find((player) => player.photo_url)!;
    const racingPhotoRow = table.querySelector(`tbody tr[data-player-id="${racingPhotoPlayer.player_id}"]`);
    expect(racingPhotoRow?.querySelector("img.follow-player-photo")).toHaveAttribute("src", racingPhotoPlayer.photo_url);
    const yellowMetricCount = racingPlayerMatchMetrics.records.filter((item) => item.metric === "yellow_cards").length;
    const goalSum = racingPlayerMatchMetrics.records.filter((item) => item.metric === "goals").reduce((sum, item) => sum + item.value, 0);

    fireEvent.click(screen.getByRole("tab", { name: "Tarjetas" }));
    expect(await screen.findAllByLabelText(/\d+ tarjetas? amarillas? verificadas?/)).toHaveLength(yellowMetricCount);
    fireEvent.click(screen.getByRole("tab", { name: "Goles" }));
    const goalCells = await screen.findAllByLabelText(/\d+ gol(?:es)?/);
    expect(goalCells.reduce((sum, cell) => sum + Number(cell.textContent), 0)).toBe(goalSum);
    fireEvent.click(screen.getByRole("tab", { name: "Todo" }));
    expect(await screen.findAllByLabelText(/\d+ tarjetas? amarillas? verificadas?/)).toHaveLength(yellowMetricCount);
    expect(screen.getAllByLabelText(/\d+ gol(?:es)? verificado(?:s)?/).reduce((sum, cell) => sum + Number(cell.textContent.match(/\d+/)?.[0] ?? 0), 0)).toBe(goalSum);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/teams/48/seasons/2026-27/follow"))).toHaveLength(1);
  });

  it("ProfileImage conserva fallback de iniciales solo si falta o falla la foto", () => {
    const { container, rerender } = render(<ProfileImage src={null} name="Jugador Demo" className="follow-player-photo" />);
    expect(container.querySelector(".profile-image-fallback")).toHaveTextContent("JD");
    rerender(<ProfileImage src="https://www.bdfutbol.com/i/m/demo.png" name="Jugador Demo" className="follow-player-photo" />);
    fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector(".profile-image-fallback")).toHaveTextContent("JD");
  });

  it("declara Seguimiento no adquirido para otros equipos sin afectar Resumen", async () => {
    const uncaptured = apiBootstrap.teams.find((team) => team.team_id !== 48 && team.team_id !== 49)!;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith(`/api/v1/teams/${uncaptured.team_id}/seasons/2026-27/follow`)) {
        return Promise.resolve(response(404, { detail: { code: "follow_not_captured", message: "not captured" } }));
      }
      return Promise.resolve(response(200, payloadFor(input)));
    });
    window.history.replaceState({}, "", `/teams/${uncaptured.team_id}/follow`);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Seguimiento aún no adquirido" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Resumen" }));
    expect(await screen.findByRole("heading", { name: "Resumen deportivo" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
