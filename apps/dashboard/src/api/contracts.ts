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

const sourceViewsSchema = z.array(z.string());
const teamRosterCoachSchema = z.object({
  coach_id: positiveInteger,
  display_name: z.string().min(1),
  full_name: z.string().nullable(),
  profile_url: z.string().url().nullable(),
  photo_url: z.string().url().nullable(),
  age_years: nullableInteger,
  birth_date: dateOnly,
  birthplace: z.string().nullable(),
  birthplace_province: z.string().nullable(),
  coached_matchdays_source: z.string().nullable(),
  matches_managed: nullableInteger,
  yellow_cards: nullableInteger,
  red_cards: nullableInteger,
  source_views: sourceViewsSchema,
}).strict();

const teamRosterPlayerSchema = z.object({
  player_id: positiveInteger,
  display_name: z.string().min(1),
  full_name: z.string().nullable(),
  profile_url: z.string().url().nullable(),
  photo_url: z.string().url().nullable(),
  age_years: nullableInteger,
  birth_date: dateOnly,
  birthplace: z.string().nullable(),
  birthplace_province: z.string().nullable(),
  nationality_flag_url: z.string().url().nullable(),
  source_position_code: z.string().nullable(),
  verified_indicators: z.array(z.string()),
  source_views: sourceViewsSchema,
}).strict();

const teamRosterMembershipSchema = z.object({
  player_id: positiveInteger,
  team_id: positiveInteger,
  season: z.string(),
  competition: z.string(),
  group: z.string(),
  jersey_number: nullableInteger,
  squad_group_label: z.string().nullable(),
  source_views: sourceViewsSchema,
}).strict();

const teamRosterStatisticsSchema = z.object({
  player_id: positiveInteger,
  team_id: positiveInteger,
  season: z.string(),
  competition: z.string(),
  group: z.string(),
  matches_played: nullableInteger,
  starts: nullableInteger,
  full_matches: nullableInteger,
  substitute_appearances: nullableInteger,
  matches_substituted: nullableInteger,
  unused_substitute_calls: nullableInteger,
  minutes_played: nullableInteger,
  yellow_cards: nullableInteger,
  red_cards: nullableInteger,
  goals: nullableInteger,
  minutes_per_goal: nullableInteger,
  penalty_goals: nullableInteger,
  own_goals: nullableInteger,
  goals_conceded: nullableInteger,
  team_wins: nullableInteger,
  team_draws: nullableInteger,
  team_losses: nullableInteger,
  source_view: z.string(),
}).strict();

const teamRosterTacticalPositionSchema = z.object({
  player_id: positiveInteger,
  horizontal: z.number().finite().min(0).max(1),
  vertical: z.number().finite().min(0).max(1),
  line: z.enum(["goalkeeper", "defense", "midfield", "attack"]),
  slot: positiveInteger,
  line_size: positiveInteger,
  source_dom_id: z.string().regex(/^d_(por|def\d+\d+|mig\d+\d+|dav\d+\d+)$/),
}).strict().superRefine((position, context) => {
  if (position.slot > position.line_size) {
    context.addIssue({ code: "custom", message: "La posición supera el tamaño de su línea." });
  }
});

const teamRosterTacticalSchema = z.object({
  source: z.literal("BDFutbol"),
  source_view: z.literal("alignment"),
  source_url: z.string().url(),
  source_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  coordinate_method: z.literal("source_line_and_slot_normalized"),
  layout_convention: z.literal("goalkeeper_to_attack_left_to_right"),
  approximate: z.literal(true),
  positions: z.array(teamRosterTacticalPositionSchema).min(1),
}).strict();

export const TeamRosterSchema = z.object({
  status: z.literal("available"),
  metadata: z.object({
    contract_version: z.literal(2),
    validation_status: z.literal("valid"),
    source: z.literal("BDFutbol"),
    url: z.string().url(),
    competition: z.literal("Primera Federación"),
    season: z.literal("2026-27"),
    group: z.enum(["I", "II"]),
    team_id: positiveInteger,
    capture_id: z.string().min(1),
    captured_at: z.string().datetime({ offset: true }),
    extractor_version: z.string(),
    content_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  }).strict(),
  team: TeamSchema,
  coaches: z.array(teamRosterCoachSchema),
  players: z.array(teamRosterPlayerSchema),
  memberships: z.array(teamRosterMembershipSchema),
  statistics: z.array(teamRosterStatisticsSchema),
  squad_groups: z.array(z.object({ label: z.string().min(1), player_ids: z.array(positiveInteger) }).strict()),
  tactical_visualization: teamRosterTacticalSchema.nullable(),
  source_views: z.array(z.object({
    view: z.string(),
    url: z.string().url(),
    title: z.string(),
    status: z.literal("VALID"),
    http_status: z.number().int(),
    sha256: z.string().regex(/^[a-f0-9]{64}$/),
    captured_at: z.string().datetime({ offset: true }).nullable(),
  }).strict()),
  warnings: z.array(z.string()),
}).strict().superRefine((roster, context) => {
  if (roster.metadata.team_id !== roster.team.team_id) {
    context.addIssue({ code: "custom", message: "La Plantilla pertenece a otro equipo." });
  }
  const playerIds = new Set(roster.players.map((player) => player.player_id));
  if (playerIds.size !== roster.players.length) {
    context.addIssue({ code: "custom", message: "La Plantilla repite player_id." });
  }
  for (const entry of [...roster.memberships, ...roster.statistics]) {
    if (!playerIds.has(entry.player_id) || entry.team_id !== roster.team.team_id) {
      context.addIssue({ code: "custom", message: "La pertenencia o estadística no coincide por player_id." });
    }
  }
  const groupedIds = roster.squad_groups.flatMap((group) => group.player_ids);
  if (groupedIds.some((id) => !playerIds.has(id)) || new Set(groupedIds).size !== groupedIds.length) {
    context.addIssue({ code: "custom", message: "Las agrupaciones contienen jugadores ausentes o duplicados." });
  }
  if (roster.tactical_visualization) {
    const positions = roster.tactical_visualization.positions;
    const tacticIds = positions.map((position) => position.player_id);
    if (new Set(tacticIds).size !== tacticIds.length) {
      context.addIssue({ code: "custom", message: "La táctica repite player_id." });
    }
    const starterIds = new Set(roster.squad_groups
      .filter((group) => group.label.toLocaleLowerCase("es-ES") === "titulares")
      .flatMap((group) => group.player_ids));
    if (tacticIds.some((id) => !playerIds.has(id) || !starterIds.has(id))) {
      context.addIssue({ code: "custom", message: "La táctica contiene jugadores ausentes o no titulares." });
    }
    const alignment = roster.source_views.find((view) => view.view === "alignment");
    if (!alignment || alignment.url !== roster.tactical_visualization.source_url || alignment.sha256 !== roster.tactical_visualization.source_sha256) {
      context.addIssue({ code: "custom", message: "La procedencia táctica no coincide con Alineación." });
    }
  }
});

export type TeamRoster = z.infer<typeof TeamRosterSchema>;

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
    available_count: z.number().int().nonnegative(),
    missing_count: z.number().int().nonnegative(),
    coverage_status: z.enum(["complete", "documented_discrepancy"]),
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
  affiliation_absences: z.array(z.object({
    player_id: positiveInteger,
    source_records: z.array(z.string().min(1)).min(1),
    reason: z.literal("not_published"),
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
  const coverage = top.foreigners_summary;
  if (coverage.available_count !== top.foreigners.length
    || coverage.available_count !== top.availability.foreign_players
    || coverage.source_count - coverage.available_count !== coverage.missing_count
    || coverage.missing_count < 0
    || (coverage.missing_count === 0 && coverage.coverage_status !== "complete")
    || (coverage.missing_count > 0 && coverage.coverage_status !== "documented_discrepancy")) {
    context.addIssue({ code: "custom", message: "La cobertura de extranjeros no coincide con los registros disponibles." });
  }
  const nullTeamIds = top.players.filter((player) => player.team_id === null).map((player) => player.player_id);
  const conflictIds = top.affiliation_conflicts.map((conflict) => conflict.player_id);
  const absenceIds = top.affiliation_absences.map((absence) => absence.player_id);
  const documentedNullIds = [...conflictIds, ...absenceIds];
  if (new Set(conflictIds).size !== conflictIds.length
    || new Set(absenceIds).size !== absenceIds.length
    || absenceIds.some((playerId) => conflictIds.includes(playerId))
    || new Set(nullTeamIds).size !== nullTeamIds.length
    || nullTeamIds.length !== documentedNullIds.length
    || nullTeamIds.some((playerId) => !documentedNullIds.includes(playerId))) {
    context.addIssue({ code: "custom", message: "Los jugadores sin equipo no coinciden con las afiliaciones documentadas." });
  }
  const expectedAffiliationWarnings = new Set<string>();
  for (const conflict of top.affiliation_conflicts) {
    const player = top.players.find((item) => item.player_id === conflict.player_id);
    const teamIds = conflict.affiliations.map((item) => item.team_id);
    const warning = `Afiliación de equipo ambigua para player_id=${conflict.player_id}; se conserva como null en el catálogo y las fuentes/IDs están en affiliation_conflicts.`;
    expectedAffiliationWarnings.add(warning);
    if (!player || player.team_id !== null || player.team_name !== null || player.team_url !== null || player.crest_url !== null
      || new Set(teamIds).size !== teamIds.length
      || new Set(teamIds).size < 2) {
      context.addIssue({ code: "custom", message: "Un conflicto de afiliación no coincide con el jugador o sus equipos." });
    }
  }
  for (const absence of top.affiliation_absences) {
    const player = top.players.find((item) => item.player_id === absence.player_id);
    expectedAffiliationWarnings.add(
      `Afiliación de equipo no publicada para player_id=${absence.player_id}; se conserva como null en el catálogo y la ausencia está respaldada por las fuentes indicadas en affiliation_absences.`,
    );
    if (!player || player.team_id !== null || player.team_name !== null || player.team_url !== null || player.crest_url !== null) {
      context.addIssue({ code: "custom", message: "Una ausencia de afiliación no coincide con un jugador sin equipo." });
    }
  }
  const affiliationWarnings = top.warnings.filter((warning) => warning.startsWith("Afiliación de equipo ambigua para player_id="));
  const absenceWarnings = top.warnings.filter((warning) => warning.startsWith("Afiliación de equipo no publicada para player_id="));
  const allAffiliationWarnings = [...affiliationWarnings, ...absenceWarnings];
  if (allAffiliationWarnings.length !== expectedAffiliationWarnings.size
    || allAffiliationWarnings.some((warning) => !expectedAffiliationWarnings.has(warning))) {
    context.addIssue({ code: "custom", message: "Las advertencias de afiliación no coinciden con los conflictos declarados." });
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
