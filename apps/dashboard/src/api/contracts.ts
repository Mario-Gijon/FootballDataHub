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

const TopForeignPlayerSchema = z.object({
  player_id: positiveInteger,
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
    active_team_capture_id: z.string().min(1).nullable(),
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
  warnings: z.array(z.string()),
  affiliation_conflicts: z.array(z.object({
    player_id: positiveInteger,
    affiliations: z.array(z.object({
      team_id: positiveInteger,
      team_name: z.string().min(1),
      source_records: z.array(z.string().min(1)).min(1),
    }).strict()).min(2),
  }).strict()),
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
  if (top.availability.foreign_players !== top.foreigners.length) {
    context.addIssue({ code: "custom", message: "El recuento disponible de extranjeros no coincide con las filas." });
  }
  const hasVerifiedGroupOneGap = top.metadata.group === "I"
    && top.foreigners_summary.source_count === 60
    && top.foreigners.length === 59
    && top.warnings.some((warning) => warning.includes("#tab_estran expone 59 registros"));
  if (top.foreigners_summary.source_count !== top.foreigners.length && !hasVerifiedGroupOneGap) {
    context.addIssue({ code: "custom", message: "El recuento de la fuente no coincide con filas ni con la discrepancia documentada." });
  }
  const nullTeamIds = top.players.filter((player) => player.team_id === null).map((player) => player.player_id);
  const conflictIds = top.affiliation_conflicts.map((conflict) => conflict.player_id);
  if (top.metadata.group === "I") {
    const conflict = top.affiliation_conflicts.find((item) => item.player_id === 304291);
    const affiliations = new Map(conflict?.affiliations.map((item) => [item.team_id, item.team_name]));
    if (nullTeamIds.length !== 1 || nullTeamIds[0] !== 304291
      || conflictIds.length !== 1
      || affiliations.get(58) !== "Pontevedra"
      || affiliations.get(104) !== "Deportivo Fabril"
      || !top.rankings.some((item) => item.player_id === 304291)
      || !top.progress.some((item) => item.player_id === 304291)
      || !top.foreigners.some((item) => item.player_id === 304291)) {
      context.addIssue({ code: "custom", message: "La afiliación ambigua de Grupo I no conserva su evidencia o sus filas relacionadas." });
    }
  } else if (nullTeamIds.length > 0 || conflictIds.length > 0) {
    context.addIssue({ code: "custom", message: "La captura contiene una afiliación ambigua no documentada para el grupo." });
  }
});

export const RefereeScopeSchema = z.enum(["all", "group1", "group2"]);
const RefereeSchema = z.object({
  referee_id: z.string().regex(/^r\d+$/),
  display_name: z.string().min(1),
  full_name: z.string().nullable(),
  profile_url: z.string().url(),
  photo_url: z.string().url().nullable(),
  flag_url: z.string().url().nullable(),
  nationality: z.string().nullable(),
  nationality_code: z.string().nullable(),
  age_years: nullableInteger,
  birth_date: dateOnly,
  birthplace: z.string().nullable(),
  province: z.string().nullable(),
}).strict();

const RefereeStatisticsSchema = z.object({
  referee_id: z.string().regex(/^r\d+$/),
  season: z.string(),
  group_scope: RefereeScopeSchema,
  published_order: z.number().int().positive(),
  matches_officiated: nullableInteger,
  yellow_cards: nullableInteger,
  red_cards: nullableInteger,
  statistics_url: z.string().url().nullable(),
  source_page_url: z.string().url(),
}).strict();

const RefereeScopeSummarySchema = z.object({
  group_scope: RefereeScopeSchema,
  label: z.string(),
  referee_count: z.number().int().nonnegative(),
  matches_officiated: nullableInteger,
  yellow_cards: nullableInteger,
  red_cards: nullableInteger,
}).strict();

export const RefereeBootstrapSchema = z.object({
  metadata: z.object({
    source: z.string(),
    url: z.string().url(),
    competition: z.string(),
    season: z.string(),
    group: z.string(),
    section: z.literal("referees"),
    capture_id: z.string().min(1),
    captured_at: z.string().datetime({ offset: true }),
    extractor_version: z.string(),
    dataset_version: z.string().min(1),
    source_snapshot_sha256: z.record(RefereeScopeSchema, z.string().regex(/^[a-f0-9]{64}$/)),
    related_matches_path: z.string().min(1),
    related_matches_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    related_matches_capture_id: z.string().min(1),
    related_matches_captured_at: z.string().datetime({ offset: true }),
    match_reference_status: z.enum(["consistent", "discrepancies"]),
    related_match_datasets: z.object({
      I: z.object({
        capture_id: z.string().min(1),
        captured_at: z.string().datetime({ offset: true }),
        sha256: z.string().regex(/^[a-f0-9]{64}$/),
        reference_status: z.enum(["consistent", "discrepancies"]),
      }).strict().optional(),
      II: z.object({
        capture_id: z.string().min(1),
        captured_at: z.string().datetime({ offset: true }),
        sha256: z.string().regex(/^[a-f0-9]{64}$/),
        reference_status: z.enum(["consistent", "discrepancies"]),
      }).strict().optional(),
    }).strict(),
  }).strict(),
  availability: z.object({
    catalog_referee_count: z.number().int().nonnegative(),
    statistics_record_count: z.number().int().nonnegative(),
    scope_counts: z.record(RefereeScopeSchema, RefereeScopeSummarySchema),
  }).strict(),
  seasons: z.array(z.object({
    season: z.string(),
    label: z.string(),
    available: z.boolean(),
  }).strict()),
  groups: z.array(z.object({
    group_scope: RefereeScopeSchema,
    label: z.string(),
    referee_count: z.number().int().nonnegative(),
  }).strict()),
  referees: z.array(RefereeSchema),
  statistics: z.array(RefereeStatisticsSchema),
  coverage_note: z.string(),
  compatibility_warnings: z.array(z.string()),
}).strict().superRefine((payload, context) => {
  const refereeIds = new Set(payload.referees.map((referee) => referee.referee_id));
  if (refereeIds.size !== payload.referees.length) {
    context.addIssue({ code: "custom", message: "El catálogo de árbitros repite IDs." });
  }
  for (const referee of payload.referees) {
    if (!new URL(referee.profile_url).pathname.endsWith(`/r/${referee.referee_id}.html`)) {
      context.addIssue({ code: "custom", message: `El perfil no coincide con ${referee.referee_id}.` });
    }
  }
  const keys = new Set<string>();
  const byScope = new Map<string, typeof payload.statistics>();
  for (const row of payload.statistics) {
    const key = `${row.referee_id}|${row.season}|${row.group_scope}`;
    if (keys.has(key)) context.addIssue({ code: "custom", message: "Hay estadísticas de árbitro duplicadas." });
    keys.add(key);
    if (!refereeIds.has(row.referee_id)) {
      context.addIssue({ code: "custom", message: `Estadísticas sin árbitro ${row.referee_id}.` });
    }
    if (row.season !== payload.metadata.season) {
      context.addIssue({ code: "custom", message: "Una estadística pertenece a otra temporada." });
    }
    byScope.set(row.group_scope, [...(byScope.get(row.group_scope) ?? []), row]);
  }
  const expectedScopes = ["all", "group1", "group2"] as const;
  if (payload.seasons.length !== 1 || payload.seasons[0]?.season !== payload.metadata.season || !payload.seasons[0]?.available) {
    context.addIssue({ code: "custom", message: "La temporada disponible no coincide con la captura." });
  }
  if (payload.groups.length !== expectedScopes.length || new Set(payload.groups.map((group) => group.group_scope)).size !== expectedScopes.length) {
    context.addIssue({ code: "custom", message: "Las opciones de grupo están incompletas o duplicadas." });
  }
  if (payload.availability.catalog_referee_count !== payload.referees.length || payload.availability.statistics_record_count !== payload.statistics.length) {
    context.addIssue({ code: "custom", message: "Los recuentos de Árbitros no coinciden con los registros." });
  }
  for (const scope of expectedScopes) {
    const rows = byScope.get(scope) ?? [];
    const summary = payload.availability.scope_counts[scope];
    const option = payload.groups.find((group) => group.group_scope === scope);
    if (!summary || !option || summary.referee_count !== rows.length || option.referee_count !== rows.length || summary.group_scope !== scope) {
      context.addIssue({ code: "custom", message: `El resumen de ${scope} no coincide con sus registros.` });
      continue;
    }
    for (const field of ["matches_officiated", "yellow_cards", "red_cards"] as const) {
      const values = rows.map((row) => row[field]);
      const expected = values.length === 0 || values.some((value) => value === null)
        ? null
        : values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
      if (summary[field] !== expected) {
        context.addIssue({ code: "custom", message: `El total ${field} de ${scope} no coincide.` });
      }
    }
    const orders = rows.map((row) => row.published_order);
    if (new Set(orders).size !== orders.length) {
      context.addIssue({ code: "custom", message: `published_order se repite en ${scope}.` });
    }
  }
});

const StatisticsCoverageSchema = z.object({
  matches_played: z.number().int().nonnegative(),
  matches_with_value: z.number().int().nonnegative(),
  missing_match_ids: z.array(z.string()),
}).strict();

const StatisticsRoundSchema = z.object({
  matchday: z.number().int().min(1).max(38),
  scheduled_matches: z.number().int().nonnegative(),
  played_matches: z.number().int().nonnegative(),
  unplayed_matches: z.number().int().nonnegative(),
  incomplete_matches: z.number().int().nonnegative(),
  coverage: z.enum(["complete", "partial", "not_started", "incomplete"]),
  goals: nullableInteger,
  yellow_cards: nullableInteger,
  red_cards: nullableInteger,
  yellow_card_coverage: StatisticsCoverageSchema,
  red_card_coverage: StatisticsCoverageSchema,
}).strict();

const StatisticsRecordMatchSchema = z.object({
  match_id: z.string().min(1),
  matchday: z.number().int().min(1).max(38),
  home_team_id: positiveInteger,
  away_team_id: positiveInteger,
  home_goals: z.number().int().nonnegative(),
  away_goals: z.number().int().nonnegative(),
}).strict();

const StatisticsReconciliationMetricSchema = z.object({
  statistic: z.string(),
  calculated: z.number().nullable(),
  published: z.number().nullable(),
  difference_published_minus_calculated: z.number().nullable(),
  comparison_basis: z.string(),
  status: z.string(),
  cause: z.string().nullable(),
}).strict();

const StatisticsRoundCheckSchema = z.object({
  matchday: z.number().int().min(1).max(38),
  statistic: z.enum(["goals", "yellow_cards", "red_cards"]),
  calculated: z.number().nullable(),
  published: z.number().nullable(),
  difference_published_minus_calculated: z.number().nullable(),
  played_matches: z.number().int().nonnegative(),
  scheduled_matches: z.number().int().nonnegative(),
  coverage: z.enum(["complete", "partial", "not_started", "incomplete"]),
  status: z.string(),
  cause: z.string().nullable(),
}).strict();

export const StatisticsBootstrapSchema = z.object({
  metadata: z.object({
    source: z.string(),
    url: z.string().url(),
    competition: z.string(),
    season: z.string(),
    group: z.string(),
    section: z.literal("statistics"),
    capture_id: z.string().min(1),
    captured_at: z.string().datetime({ offset: true }),
    extractor_version: z.string(),
    dataset_version: z.string().min(1),
    source_snapshot_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    chart_data_provider_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    match_dataset_path: z.string(),
    match_dataset_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    match_dataset_capture_id: z.string(),
    match_dataset_captured_at: z.string().datetime({ offset: true }),
    active_match_capture_id: z.string(),
  }).strict(),
  statistics: z.object({
    competition: z.string(),
    season: z.string(),
    group: z.string(),
    team_count: z.number().int().nonnegative(),
    scheduled_matches: z.number().int().nonnegative(),
    played_matches: z.number().int().nonnegative(),
    unplayed_matches: z.number().int().nonnegative(),
    incomplete_matches: z.number().int().nonnegative(),
    home_wins: z.number().int().nonnegative(),
    away_wins: z.number().int().nonnegative(),
    draws: z.number().int().nonnegative(),
    goals: nullableInteger,
    goals_per_match: z.number().nullable(),
    yellow_cards: nullableInteger,
    yellow_cards_per_match: z.number().nullable(),
    red_cards: nullableInteger,
    red_cards_per_match: z.number().nullable(),
    yellow_card_coverage: StatisticsCoverageSchema,
    red_card_coverage: StatisticsCoverageSchema,
    rounds: z.array(StatisticsRoundSchema),
  }).strict(),
  penalties: z.object({
    penalties_awarded: z.number().int().nonnegative(),
    penalties_scored: z.number().int().nonnegative(),
    penalties_missed: z.number().int().nonnegative(),
    source_labels: z.array(z.string()),
    unit: z.literal("penalties"),
    scope: z.literal("competition_total"),
    source_url: z.string().url(),
  }).strict(),
  records: z.object({
    match_records: z.array(z.object({
      kind: z.enum(["largest_home_win", "largest_away_win", "most_goals"]),
      measure: z.number().int().nonnegative(),
      matches: z.array(StatisticsRecordMatchSchema).min(1),
    }).strict()),
    streaks: z.array(z.object({
      team_id: positiveInteger,
      kind: z.enum(["winning", "losing", "unbeaten", "winless"]),
      match_count: z.number().int().positive(),
      matchday_start: z.number().int().min(1).max(38),
      matchday_end: z.number().int().min(1).max(38),
      match_ids: z.array(z.string().min(1)).min(1),
    }).strict()),
  }).strict(),
  reconciliation: z.object({
    statistics_capture_id: z.string(),
    statistics_captured_at_utc: z.string().datetime({ offset: true }),
    match_dataset_capture_id: z.string(),
    match_dataset_captured_at_utc: z.string().datetime({ offset: true }),
    capture_windows_differ: z.boolean(),
    temporal_comparison_status: z.string(),
    match_data_alignment: z.record(z.string(), z.unknown()),
    metrics: z.array(StatisticsReconciliationMetricSchema),
    exclusive_penalties: z.object({
      source: z.object({
        penalties_awarded: z.number().int(),
        penalties_scored: z.number().int(),
        penalties_missed: z.number().int(),
        source_labels: z.array(z.string()),
      }).strict(),
      status: z.string(),
      equation_valid: z.boolean(),
    }).strict(),
    published_match_records: z.array(z.object({
      kind: z.enum(["largest_home_win", "largest_away_win", "most_goals"]),
      measure: z.number().int(),
      match_id: z.string(),
      home_goals: z.number().int(),
      away_goals: z.number().int(),
      source_url: z.string().url(),
      home_team_id: positiveInteger,
      away_team_id: positiveInteger,
      calculated_measure: z.number().int(),
      calculated_match_ids: z.array(z.string()),
      status: z.string(),
    }).strict()),
    published_streaks: z.array(z.object({
      kind: z.enum(["winning", "losing", "unbeaten", "winless"]),
      published_team_name: z.string(),
      resolved_team_id: positiveInteger,
      published_match_count: z.number().int(),
      published_matchday_start: z.number().int(),
      published_matchday_end: z.number().int(),
      calculated_max_match_count: z.number().int(),
      calculated_tied_team_ids: z.array(positiveInteger),
      calculated_match_ids: z.array(z.array(z.string())),
      status: z.string(),
    }).strict()),
    round_series: z.array(StatisticsRoundCheckSchema),
    summary: z.object({
      metric_count: z.number().int(),
      metric_matches: z.number().int(),
      metric_differences: z.number().int(),
      metric_semantics_unverified: z.number().int(),
      record_statuses: z.record(z.string(), z.string()),
      round_series_differences: z.number().int(),
    }).strict(),
  }).strict(),
  methodology: z.record(z.string(), z.string()),
  limitations: z.array(z.string()),
}).strict();

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
export type RefereeScope = z.infer<typeof RefereeScopeSchema>;
export type Referee = z.infer<typeof RefereeSchema>;
export type RefereeStatistics = z.infer<typeof RefereeStatisticsSchema>;
export type RefereeBootstrap = z.infer<typeof RefereeBootstrapSchema>;
export type StatisticsBootstrap = z.infer<typeof StatisticsBootstrapSchema>;
