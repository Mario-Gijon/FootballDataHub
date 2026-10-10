import { z } from "zod";

const nullableInteger = z.number().int().nullable();
const positiveInteger = z.number().int().positive();
const dateOnly = z.string().regex(/^\d{4}-\d{2}-\d{2}$/).nullable();

export const TeamSchema = z.object({
  team_id: positiveInteger,
  name: z.string().min(1),
  team_url: z.string().url().nullable(),
  crest_url: z.string().url().nullable(),
}).strict();

export const MatchSchema = z.object({
  match_id: z.string().min(1),
  matchday: z.number().int().min(1).max(38),
  matchday_date: dateOnly,
  source_match_date: dateOnly,
  home_team_id: positiveInteger,
  away_team_id: positiveInteger,
  home_goals: nullableInteger,
  away_goals: nullableInteger,
  home_yellow_cards: nullableInteger,
  away_yellow_cards: nullableInteger,
  home_red_cards: nullableInteger,
  away_red_cards: nullableInteger,
  status: z.enum(["played", "unplayed", "incomplete"]),
  unplayed_state: z.enum(["scheduled", "result_unavailable_at_capture", "unknown"]).nullable(),
  postponed_by_source_rule: z.boolean().nullable(),
  source_match_url: z.string().url().nullable(),
  stadium_id: z.string().nullable(),
  stadium_name: z.string().nullable(),
  stadium_url: z.string().url().nullable(),
  referee_id: z.string().nullable(),
  referee_name: z.string().nullable(),
  referee_url: z.string().url().nullable(),
}).strict().superRefine((match, context) => {
  if (match.home_team_id === match.away_team_id) {
    context.addIssue({ code: "custom", message: "El partido no puede enfrentar al mismo equipo." });
  }
  if (match.status === "played" && (match.home_goals === null || match.away_goals === null)) {
    context.addIssue({ code: "custom", message: "El partido disputado requiere ambos marcadores." });
  }
  if (match.status === "unplayed" && (match.home_goals !== null || match.away_goals !== null)) {
    context.addIssue({ code: "custom", message: "Un partido pendiente debe conservar marcadores null." });
  }
  if (match.status === "unplayed" && match.unplayed_state === null) {
    context.addIssue({ code: "custom", message: "El estado del partido pendiente es obligatorio." });
  }
});

export const ProgressSchema = z.object({
  team_id: positiveInteger,
  matchday: z.number().int().min(1).max(38),
  matchday_date: dateOnly,
  position: nullableInteger,
  points: nullableInteger,
  goals_for: nullableInteger,
  goals_against: nullableInteger,
}).strict();

export const PublishedStandingSchema = z.object({
  team_id: positiveInteger,
  team_name: z.string(),
  team_url: z.string().url().nullable(),
  crest_url: z.string().url().nullable(),
  position: nullableInteger,
  points: nullableInteger,
  matches_played: nullableInteger,
  wins: nullableInteger,
  draws: nullableInteger,
  losses: nullableInteger,
  goals_for: nullableInteger,
  goals_against: nullableInteger,
  yellow_cards: nullableInteger,
  red_cards: nullableInteger,
  position_change: z.enum(["up", "down", "same"]).nullable(),
  sports_zone: z.enum(["direct_promotion", "promotion", "stay", "relegation"]).nullable(),
}).strict();

export const BootstrapSchema = z.object({
  metadata: z.object({
    schema_version: z.number().int(),
    source: z.string(),
    url: z.string().url(),
    competition: z.string(),
    season: z.string(),
    group: z.string(),
    team_count: z.number().int(),
    scheduled_matchdays: z.array(z.number().int()),
    last_matchday_with_results: z.number().int().nullable(),
    captured_at: z.string().datetime({ offset: true }),
    capture_id: z.string(),
    dataset_version: z.string(),
    availability: z.object({
      teams: z.number().int(),
      matches: z.number().int(),
      played_matches: z.number().int(),
      unplayed_matches: z.number().int(),
      incomplete_matches: z.number().int(),
      matchdays_with_fixtures: z.array(z.number().int()),
      last_matchday_with_results: z.number().int().nullable(),
      progress_records: z.number().int(),
      progress_through_matchday: z.number().int(),
      published_standings_available: z.boolean(),
    }).strict(),
    progress_context: z.object({
      classification_type: z.literal("general"),
      postponed_policy: z.literal("source_defined_unknown"),
      range_type: z.literal("all"),
      source_independent_of_standings_filters: z.boolean(),
      available_through_matchday: z.number().int(),
    }).strict(),
    warnings: z.array(z.string()),
  }).strict(),
  teams: z.array(TeamSchema),
  matches: z.array(MatchSchema),
  progress: z.array(ProgressSchema),
  published_standings: z.object({
    source: z.string(),
    source_capture_id: z.string(),
    context: z.object({
      classification_type: z.enum(["general", "local", "visitor"]),
      matchday: z.number().int(),
      matchday_date: dateOnly,
      postponed_policy: z.enum(["include", "exclude"]),
      range_type: z.enum(["all", "dates", "rounds"]),
    }).strict(),
    rows: z.array(PublishedStandingSchema),
  }).strict().nullable(),
}).strict().superRefine((bootstrap, context) => {
  const teamIds = new Set(bootstrap.teams.map((team) => team.team_id));
  if (teamIds.size !== bootstrap.teams.length) {
    context.addIssue({ code: "custom", message: "El catálogo contiene IDs de equipo repetidos." });
  }
  for (const match of bootstrap.matches) {
    if (!teamIds.has(match.home_team_id) || !teamIds.has(match.away_team_id)) {
      context.addIssue({ code: "custom", message: `El partido ${match.match_id} referencia un equipo ausente.` });
    }
  }
  for (const row of bootstrap.progress) {
    if (!teamIds.has(row.team_id)) {
      context.addIssue({ code: "custom", message: `El progreso referencia un equipo ausente (${row.team_id}).` });
    }
  }
  if (bootstrap.published_standings && bootstrap.published_standings.source_capture_id !== bootstrap.metadata.capture_id) {
    context.addIssue({ code: "custom", message: "La tabla publicada pertenece a otra captura." });
  }
});

export const TopCategorySchema = z.enum([
  "goals", "minutes", "yellow_cards", "red_cards", "youngest", "oldest",
]);

const TopPlayerSchema = z.object({
  player_id: positiveInteger,
  display_name: z.string().min(1),
  full_name: z.string().nullable(),
  profile_url: z.string().url().nullable(),
  photo_url: z.string().url().nullable(),
  nationality_code: z.string().nullable(),
  nationality: z.string().nullable(),
  position_code: z.string().nullable(),
  position_name: z.string().nullable(),
  age_years: nullableInteger,
  team_id: positiveInteger.nullable(),
  team_name: z.string().nullable(),
  team_url: z.string().url().nullable(),
  crest_url: z.string().url().nullable(),
}).strict();

const TopRankingSchema = z.object({
  category: TopCategorySchema,
  rank: z.number().int().positive(),
  player_id: positiveInteger,
  metric: z.enum(["goals", "minutes_played", "yellow_cards", "red_cards", "age_years"]),
  metric_value: z.number().int().nonnegative(),
  unit: z.enum(["goals", "minutes", "cards", "years"]),
  matches_played: nullableInteger,
  source_record: z.enum(["html_table", "destacats_js_lg"]),
  graph_selected_by_default: z.boolean().nullable(),
}).strict();

const TopProgressSchema = z.object({
  category: z.enum(["goals", "minutes", "yellow_cards", "red_cards"]),
  player_id: positiveInteger,
  metric: z.enum(["goals", "minutes_played", "yellow_cards", "red_cards"]),
  unit: z.enum(["goals", "minutes", "cards"]),
  points: z.array(z.object({
    matchday: z.number().int().min(1).max(38),
    value: nullableInteger,
  }).strict()),
  graph_selected_by_default: z.boolean(),
}).strict();

const TopForeignPlayerSchema = TopPlayerSchema.extend({
  statistics: z.object({
    matches_played: nullableInteger,
    minutes_played: nullableInteger,
    goals: nullableInteger,
    yellow_cards: nullableInteger,
    red_cards: nullableInteger,
  }).strict(),
}).strict();

export const TopBootstrapSchema = z.object({
  metadata: z.object({
    source: z.string(),
    url: z.string().url(),
    competition: z.string(),
    season: z.string(),
    group: z.string(),
    section: z.literal("top"),
    capture_id: z.string().min(1),
    captured_at: z.string().datetime({ offset: true }),
    extractor_version: z.string(),
    source_snapshot_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    related_team_capture_id: z.string().min(1),
    related_team_catalog_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    dataset_version: z.string().min(1),
  }).strict(),
  availability: z.object({
    players: z.number().int().nonnegative(),
    ranking_records: z.number().int().nonnegative(),
    progress_series: z.number().int().nonnegative(),
    progress_points: z.number().int().nonnegative(),
    foreign_players: z.number().int().nonnegative(),
    categories: z.record(TopCategorySchema, z.number().int().nonnegative()),
    matchdays: z.array(z.number().int().min(1).max(38)),
  }).strict(),
  categories: z.array(z.object({
    source_value: z.string(),
    category: TopCategorySchema,
    label: z.string(),
    available_count: z.number().int().nonnegative(),
    graph_available: z.boolean(),
    see_all_available: z.boolean(),
  }).strict()),
  players: z.array(TopPlayerSchema),
  rankings: z.array(TopRankingSchema),
  progress: z.array(TopProgressSchema),
  foreigners: z.array(TopForeignPlayerSchema),
  foreigners_summary: z.object({
    source_count: z.number().int().nonnegative(),
    source_percentage: z.number().nullable(),
    denominator_count: nullableInteger,
    country_options: z.array(z.object({ code: z.string(), label: z.string() }).strict()),
  }).strict(),
  coverage_note: z.string(),
}).strict().superRefine((top, context) => {
  const playerIds = new Set(top.players.map((player) => player.player_id));
  if (playerIds.size !== top.players.length) {
    context.addIssue({ code: "custom", message: "La captura TOP contiene IDs de jugador repetidos." });
  }
  if (top.rankings.some((ranking) => !playerIds.has(ranking.player_id))) {
    context.addIssue({ code: "custom", message: "Un ranking TOP referencia un jugador inexistente." });
  }
  if (top.progress.some((series) => !playerIds.has(series.player_id))) {
    context.addIssue({ code: "custom", message: "Una serie TOP referencia un jugador inexistente." });
  }
  if (top.foreigners.some((player) => !playerIds.has(player.player_id))) {
    context.addIssue({ code: "custom", message: "La tabla de extranjeros referencia un jugador inexistente." });
  }
});

export type Team = z.infer<typeof TeamSchema>;
export type Match = z.infer<typeof MatchSchema>;
export type ProgressRecord = z.infer<typeof ProgressSchema>;
export type PublishedStanding = z.infer<typeof PublishedStandingSchema>;
export type Bootstrap = z.infer<typeof BootstrapSchema>;
export type TopCategory = z.infer<typeof TopCategorySchema>;
export type TopPlayer = z.infer<typeof TopPlayerSchema>;
export type TopRanking = z.infer<typeof TopRankingSchema>;
export type TopProgressSeries = z.infer<typeof TopProgressSchema>;
export type TopForeignPlayer = z.infer<typeof TopForeignPlayerSchema>;
export type TopBootstrap = z.infer<typeof TopBootstrapSchema>;
