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
  kickoff_time_local: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/).nullable().optional(),
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

export const TeamFollowSchema = z.object({
  status: z.literal("available"),
  metadata: z.object({
    contract_version: z.literal(2),
    source: z.literal("BDFutbol"),
    url: z.string().url(),
    competition: z.literal("Primera Federación"),
    competition_scope: z.literal("Liga"),
    season: z.literal("2026-27"),
    group: z.enum(["I", "II"]),
    team_id: positiveInteger,
    capture_id: z.string().min(1),
    captured_at: z.string().datetime({ offset: true }),
    extractor_version: z.string(),
    content_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    match_capture_id: z.string().min(1),
    match_catalog_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    derived_states: z.array(z.enum(["p", "t", "go", "tot"])),
    derived_at: z.string().datetime({ offset: true }).nullable(),
  }).strict(),
  team: TeamSchema,
  players: z.array(z.object({
    player_id: positiveInteger,
    display_name: z.string().min(1),
    profile_url: z.string().url().nullable(),
    photo_url: z.string().url().nullable(),
    jersey_number: nullableInteger,
  }).strict()).min(1),
  matches: z.array(z.object({
    match_id: z.string().min(1),
    matchday: z.number().int().min(1).max(38),
    matchday_date: dateOnly,
    source_match_date: dateOnly,
    home_team_id: positiveInteger,
    home_team_name: z.string().min(1),
    away_team_id: positiveInteger,
    away_team_name: z.string().min(1),
    home_goals: nullableInteger,
    away_goals: nullableInteger,
    status: z.enum(["played", "unplayed", "incomplete"]),
  }).strict()),
  matchdays: z.array(z.number().int().min(1).max(38)),
  minutes: z.array(z.object({
    player_id: positiveInteger,
    match_id: z.string().min(1),
    matchday: z.number().int().min(1).max(38),
    minutes_played: z.number().int().nonnegative().nullable(),
    source_value: z.string(),
    source_view: z.literal("follow"),
    source_state: z.literal("p"),
  }).strict()),
  metrics: z.array(z.object({
    player_id: positiveInteger,
    match_id: z.string().min(1),
    matchday: z.number().int().min(1).max(38),
    metric: z.enum(["yellow_cards", "red_cards", "goals"]),
    value: z.number().int().positive(),
    source_value: z.string(),
    source_view: z.literal("follow"),
    source_state: z.enum(["t", "go"]),
  }).strict()),
  coverage: z.array(z.object({
    state: z.enum(["p", "t", "go", "tot"]),
    available: z.boolean(),
    record_count: z.number().int().nonnegative(),
    value_total: z.number().int().nonnegative().nullable(),
    matchdays: z.array(z.number().int().min(1).max(38)),
  }).strict()).length(4),
  warnings: z.array(z.string()),
}).strict().superRefine((follow, context) => {
  const playerIds = new Set(follow.players.map((player) => player.player_id));
  const matches = new Map(follow.matches.map((match) => [match.match_id, match]));
  if (playerIds.size !== follow.players.length || matches.size !== follow.matches.length) {
    context.addIssue({ code: "custom", message: "Seguimiento repite IDs de jugador o partido." });
  }
  if (follow.metadata.team_id !== follow.team.team_id) {
    context.addIssue({ code: "custom", message: "Seguimiento pertenece a otro equipo." });
  }
  const records = [...follow.minutes, ...follow.metrics];
  for (const record of records) {
    const match = matches.get(record.match_id);
    if (!playerIds.has(record.player_id) || !match || match.matchday !== record.matchday) {
      context.addIssue({ code: "custom", message: "Una celda no enlaza jugador y partido correctamente." });
    }
  }
  const minuteKeys = follow.minutes.map((item) => `${item.player_id}:${item.match_id}`);
  const metricKeys = follow.metrics.map((item) => `${item.player_id}:${item.match_id}:${item.metric}`);
  if (new Set(minuteKeys).size !== minuteKeys.length || new Set(metricKeys).size !== metricKeys.length) {
    context.addIssue({ code: "custom", message: "La matriz repite una celda de minutos o métrica." });
  }
  if (follow.metrics.some((item) => (item.metric === "goals" ? "go" : "t") !== item.source_state)) {
    context.addIssue({ code: "custom", message: "La métrica no coincide con el estado fuente." });
  }
  if (follow.matchdays.some((day, index) => index > 0 && day <= follow.matchdays[index - 1]!)) {
    context.addIssue({ code: "custom", message: "Las jornadas deben ser únicas y estar ordenadas." });
  }
  if (new Set(follow.matches.map((item) => item.matchday)).size !== follow.matches.length
    || new Set(follow.matchdays).size !== new Set(follow.matches.map((item) => item.matchday)).size) {
    context.addIssue({ code: "custom", message: "La matriz tiene jornadas repetidas o incompletas." });
  }
  if (new Set(follow.coverage.map((entry) => entry.state)).size !== 4) {
    context.addIssue({ code: "custom", message: "La cobertura debe declarar una vez cada modo." });
  }
});

export type TeamFollow = z.infer<typeof TeamFollowSchema>;

const TeamTransferSectionSchema = z.object({
  direction: z.enum(["incoming", "outgoing"]),
  source_heading: z.enum(["Altas", "Bajas"]),
  status: z.enum(["verified_with_rows", "verified_empty"]),
  row_count: z.number().int().nonnegative(),
  source_team_column: z.enum(["Equipo origen", "Equipo destino"]),
}).strict().superRefine((section, context) => {
  const expected = section.direction === "incoming"
    ? { heading: "Altas", column: "Equipo origen" }
    : { heading: "Bajas", column: "Equipo destino" };
  if (section.source_heading !== expected.heading || section.source_team_column !== expected.column) {
    context.addIssue({ code: "custom", message: "La sección no coincide con su dirección." });
  }
  if ((section.status === "verified_empty") !== (section.row_count === 0)) {
    context.addIssue({ code: "custom", message: "El estado vacío no coincide con el recuento." });
  }
});

const TeamTransferRecordSchema = z.object({
  player_id: positiveInteger,
  player_display_name: z.string().min(1),
  player_full_name: z.string().nullable(),
  player_profile_url: z.string().url(),
  player_photo_url: z.string().url().nullable(),
  team_id: positiveInteger,
  season: z.literal("2026-27"),
  competition: z.literal("Primera Federación"),
  group: z.enum(["I", "II"]),
  direction: z.enum(["incoming", "outgoing"]),
  other_team_name: z.string().nullable(),
  other_team_id: positiveInteger.nullable(),
  other_team_url: z.string().url().nullable(),
  age_years: nullableInteger,
  source_position_code: z.string().nullable(),
  transfer_date: z.string().nullable(),
  fee: z.string().nullable(),
  source_view: z.literal("transfers"),
  source_heading: z.enum(["Altas", "Bajas"]),
}).strict().superRefine((record, context) => {
  const expected = record.direction === "incoming" ? "Altas" : "Bajas";
  const playerId = /\/j\/j(\d+)\.html$/.exec(new URL(record.player_profile_url).pathname)?.[1];
  if (record.source_heading !== expected || Number(playerId) !== record.player_id) {
    context.addIssue({ code: "custom", message: "La dirección o identidad del jugador no coincide con la fuente." });
  }
  if ((record.other_team_id === null) !== (record.other_team_url === null)) {
    context.addIssue({ code: "custom", message: "El ID y la URL del otro equipo deben conservarse juntos." });
  }
  if (record.other_team_url) {
    const otherId = /\/t\d{4}-\d{2}(\d+)\.html$/.exec(new URL(record.other_team_url).pathname)?.[1];
    if (Number(otherId) !== record.other_team_id) {
      context.addIssue({ code: "custom", message: "La URL del otro equipo no coincide con su ID." });
    }
  }
});

export const TeamTransfersSchema = z.object({
  status: z.literal("available"),
  metadata: z.object({
    contract_version: z.literal(1),
    validation_status: z.literal("valid"),
    source: z.literal("BDFutbol"),
    url: z.string().url(),
    competition: z.literal("Primera Federación"),
    competition_scope: z.literal("Liga"),
    season: z.literal("2026-27"),
    group: z.enum(["I", "II"]),
    team_id: positiveInteger,
    capture_id: z.string().min(1),
    captured_at: z.string().datetime({ offset: true }),
    derived_at: z.string().datetime({ offset: true }).nullable(),
    extractor_version: z.string(),
    source_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    content_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  }).strict(),
  sections: z.array(TeamTransferSectionSchema).length(2),
  incoming: z.array(TeamTransferRecordSchema),
  outgoing: z.array(TeamTransferRecordSchema),
  warnings: z.array(z.string()),
}).strict().superRefine((transfers, context) => {
  if (transfers.metadata.team_id <= 0) {
    context.addIssue({ code: "custom", message: "team_id inválido." });
  }
  const sectionMap = new Map(transfers.sections.map((section) => [section.direction, section]));
  if (sectionMap.size !== 2 || !sectionMap.has("incoming") || !sectionMap.has("outgoing")) {
    context.addIssue({ code: "custom", message: "La respuesta debe demostrar Altas y Bajas." });
  }
  for (const [direction, records] of [["incoming", transfers.incoming], ["outgoing", transfers.outgoing]] as const) {
    if (sectionMap.get(direction)?.row_count !== records.length) {
      context.addIssue({ code: "custom", message: `El recuento de ${direction} no coincide.` });
    }
    if (records.some((record) => record.direction !== direction
      || record.team_id !== transfers.metadata.team_id
      || record.group !== transfers.metadata.group)) {
      context.addIssue({ code: "custom", message: `Los registros ${direction} pertenecen a otro contexto.` });
    }
  }
  const keys = [...transfers.incoming, ...transfers.outgoing].map((record) => `${record.direction}:${record.player_id}`);
  if (new Set(keys).size !== keys.length) {
    context.addIssue({ code: "custom", message: "Se repite un jugador dentro de la misma dirección." });
  }
});

export type TeamTransferRecord = z.infer<typeof TeamTransferRecordSchema>;
export type TeamTransfers = z.infer<typeof TeamTransfersSchema>;

export const TopCategorySchema = z.enum([
  "goals", "minutes", "yellow_cards", "red_cards", "youngest", "oldest",
]);

const TopPlayerSchema = z.object({
  player_id: positiveInteger,
  internal_player_id: positiveInteger.nullable().optional(),
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
  internal_player_id: positiveInteger.nullable().optional(),
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
    active_match_captured_at: z.string().datetime({ offset: true }),
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

const MatchGenerationRecordSchema = z.object({
  internal_id: z.string().min(1),
  source_match_id: z.string().min(1),
  matchday: z.number().int().min(1).max(38),
  matchday_date: dateOnly,
  source_match_date: dateOnly,
  kickoff_time_local: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/).nullable().optional(),
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
  if (match.status === "played" && (match.home_goals === null || match.away_goals === null || match.unplayed_state !== null)) {
    context.addIssue({ code: "custom", message: "El resultado disputado requiere marcador completo." });
  }
  if (match.status === "unplayed" && (match.home_goals !== null || match.away_goals !== null || match.unplayed_state === null)) {
    context.addIssue({ code: "custom", message: "El partido pendiente debe conservar el marcador null y su estado." });
  }
});

const MatchGenerationGroupSchema = z.object({
  group: z.enum(["I", "II"]),
  source_capture_id: z.string().min(1),
  source_captured_at: z.string().datetime({ offset: true }),
  teams: z.array(TeamSchema),
  matches: z.array(MatchGenerationRecordSchema),
  scheduled_matchdays: z.array(z.number().int().min(1).max(38)),
  counts: z.object({
    teams: z.number().int().nonnegative(),
    matches: z.number().int().nonnegative(),
    played: z.number().int().nonnegative(),
    unplayed: z.number().int().nonnegative(),
    incomplete: z.number().int().nonnegative(),
  }).strict(),
}).strict().superRefine((group, context) => {
  if (group.group === "I" || group.group === "II") {
    if (group.counts.teams !== group.teams.length || group.counts.matches !== group.matches.length) {
      context.addIssue({ code: "custom", message: "Los recuentos del grupo no coinciden." });
    }
    const ids = new Set(group.teams.map((team) => team.team_id));
    const matchIds = new Set(group.matches.map((match) => match.internal_id));
    if (ids.size !== group.teams.length || matchIds.size !== group.matches.length) {
      context.addIssue({ code: "custom", message: "El grupo contiene IDs duplicados." });
    }
    if (group.matches.some((match) => !ids.has(match.home_team_id) || !ids.has(match.away_team_id))) {
      context.addIssue({ code: "custom", message: "Un partido referencia un equipo ausente." });
    }
    const groupSlug = group.group.toLowerCase();
    if (group.matches.some((match) => match.internal_id !== `pf-2026-27-group-${groupSlug}-bdfutbol-${match.source_match_id}`)) {
      context.addIssue({ code: "custom", message: "Un ID interno de partido no coincide con grupo e identidad de fuente." });
    }
    const actual = {
      played: group.matches.filter((match) => match.status === "played").length,
      unplayed: group.matches.filter((match) => match.status === "unplayed").length,
      incomplete: group.matches.filter((match) => match.status === "incomplete").length,
    };
    if (Object.keys(actual).some((key) => actual[key as keyof typeof actual] !== group.counts[key as keyof typeof group.counts])) {
      context.addIssue({ code: "custom", message: "Los recuentos por estado no coinciden." });
    }
  }
});

export const MatchResultsBootstrapSchema = z.object({
  metadata: z.object({
    schema_version: z.literal(1),
    source: z.literal("BDFutbol"),
    competition: z.literal("Primera Federación"),
    season: z.literal("2026-27"),
    generation_id: z.string().min(1),
    generation_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    captured_at: z.string().datetime({ offset: true }),
    team_count: z.number().int().nonnegative(),
    match_count: z.number().int().nonnegative(),
    played_count: z.number().int().nonnegative(),
    unplayed_count: z.number().int().nonnegative(),
    incomplete_count: z.number().int().nonnegative(),
  }).strict(),
  groups: z.object({ I: MatchGenerationGroupSchema, II: MatchGenerationGroupSchema }).strict(),
}).strict().superRefine((payload, context) => {
  const teams = payload.groups.I.counts.teams + payload.groups.II.counts.teams;
  const matches = payload.groups.I.counts.matches + payload.groups.II.counts.matches;
  const played = payload.groups.I.counts.played + payload.groups.II.counts.played;
  const unplayed = payload.groups.I.counts.unplayed + payload.groups.II.counts.unplayed;
  const incomplete = payload.groups.I.counts.incomplete + payload.groups.II.counts.incomplete;
  if (payload.metadata.team_count !== teams || payload.metadata.match_count !== matches
    || payload.metadata.played_count !== played || payload.metadata.unplayed_count !== unplayed
    || payload.metadata.incomplete_count !== incomplete) {
    context.addIssue({ code: "custom", message: "Los totales de la generación no coinciden con sus grupos." });
  }
});

const MatchPageTeamSchema = z.object({
  team_id: positiveInteger,
  name: z.string().min(1),
  team_url: z.string().url().nullable(),
  crest_url: z.string().url().nullable(),
}).strict();

const MatchPublishedPlayerSchema = z.object({
  player_id: nullableInteger,
  display_name: z.string().min(1),
  profile_url: z.string().url().nullable(),
  photo_url: z.string().url().nullable(),
  shirt_number: nullableInteger,
  position: z.string().nullable(),
  role: z.enum(["starter", "substitute"]),
  participation_status: z.enum(["entered", "no_entry_marker", "not_applicable"]).nullable(),
  player_profile_available: z.boolean(),
}).strict();

const MatchPublishedCoachSchema = z.object({
  coach_id: nullableInteger,
  display_name: z.string().min(1),
  profile_url: z.string().url().nullable(),
  photo_url: z.string().url().nullable(),
}).strict();

const MatchPublishedSideSchema = z.object({
  team_id: positiveInteger,
  coach: MatchPublishedCoachSchema.nullable(),
  starters: z.array(MatchPublishedPlayerSchema).nullable(),
  substitutes: z.array(MatchPublishedPlayerSchema).nullable(),
}).strict();

const MatchPublishedEventSchema = z.object({
  event_kind: z.enum(["goal", "penalty", "missed_penalty", "own_goal", "yellow_card", "red_card", "second_yellow", "substitution", "substitution_in", "substitution_out", "other"]),
  minute: z.string().nullable(),
  team_id: positiveInteger,
  player_id: nullableInteger,
  player_name: z.string().nullable(),
  related_player_id: nullableInteger,
  related_player_name: z.string().nullable(),
  is_penalty: z.boolean().nullable(),
  is_own_goal: z.boolean().nullable(),
  source_description: z.string().nullable().optional(),
  score_after_home: nullableInteger,
  score_after_away: nullableInteger,
  player_profile_available: z.boolean(),
  related_player_profile_available: z.boolean(),
}).strict();

const MatchPublishedDetailsSchema = z.object({
  publication_status: z.enum(["approved", "preview_only"]),
  validation_status: z.literal("valid"),
  source: z.literal("BDFutbol"),
  internal_id: z.string().min(1),
  source_match_id: z.string().min(1),
  source_generation_id: z.string().min(1),
  source_capture_id: z.string().min(1),
  source_html_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  match_date: dateOnly,
  kickoff_time_local: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/).nullable().optional(),
  kickoff_state: z.enum(["observed", "explicitly_absent", "not_observed", "unresolved"]).nullable().optional(),
  kickoff_timezone: z.string().nullable().optional(),
  kickoff_source_text: z.string().nullable().optional(),
  kickoff_source_reference: z.string().nullable().optional(),
  kickoff_parser_version: z.string().nullable().optional(),
  kickoff_source_html_sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable().optional(),
  home_team_id: positiveInteger,
  away_team_id: positiveInteger,
  home_goals: z.number().int().nonnegative(),
  away_goals: z.number().int().nonnegative(),
  home: MatchPublishedSideSchema,
  away: MatchPublishedSideSchema,
  events: z.array(MatchPublishedEventSchema).nullable(),
}).strict();

export const MatchPageSchema = z.object({
  metadata: z.object({
    contract_version: z.literal(2),
    source: z.literal("BDFutbol"),
    competition: z.literal("Primera Federación"),
    season: z.literal("2026-27"),
    group: z.enum(["I", "II"]),
    generation_id: z.string().min(1),
    generation_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    source_capture_id: z.string().min(1),
    source_captured_at: z.string().datetime({ offset: true }),
  }).strict(),
  match: z.object({
    internal_id: z.string().min(1),
    source_match_id: z.string().min(1),
    matchday: z.number().int().min(1).max(38),
    matchday_date: dateOnly,
    source_match_date: dateOnly,
    kickoff_time_local: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/).nullable().optional(),
    home_team: MatchPageTeamSchema,
    away_team: MatchPageTeamSchema,
    home_goals: nullableInteger,
    away_goals: nullableInteger,
    status: z.enum(["played", "unplayed", "incomplete"]),
    unplayed_state: z.enum(["scheduled", "result_unavailable_at_capture", "unknown"]).nullable(),
    stadium_name: z.string().nullable(),
    stadium_url: z.string().url().nullable(),
    referee_name: z.string().nullable(),
    referee_url: z.string().url().nullable(),
    source_match_url: z.string().url().nullable(),
  }).strict(),
  detail_status: z.enum(["not_available", "available", "preview_only"]),
  details: MatchPublishedDetailsSchema.nullable(),
}).strict().superRefine((page, context) => {
  const expectedId = `pf-${page.metadata.season}-group-${page.metadata.group.toLowerCase()}-bdfutbol-${page.match.source_match_id}`;
  if (page.match.internal_id !== expectedId) {
    context.addIssue({ code: "custom", message: "El identificador no coincide con la competición y partido." });
  }
  if (page.match.home_team.team_id === page.match.away_team.team_id) {
    context.addIssue({ code: "custom", message: "El partido no puede enfrentar al mismo equipo." });
  }
  if (page.match.status === "played" && (page.match.home_goals === null || page.match.away_goals === null)) {
    context.addIssue({ code: "custom", message: "El partido disputado necesita un marcador, incluso 0–0." });
  }
  if (page.match.status === "unplayed" && (page.match.home_goals !== null || page.match.away_goals !== null || page.match.unplayed_state === null)) {
    context.addIssue({ code: "custom", message: "El partido pendiente debe conservar marcador nulo." });
  }
  if (page.match.status === "incomplete" && (page.match.home_goals !== null || page.match.away_goals !== null)) {
    context.addIssue({ code: "custom", message: "Un partido incompleto no puede mostrar un marcador parcial." });
  }
  if ((page.detail_status === "not_available") !== (page.details === null)) {
    context.addIssue({ code: "custom", message: "El estado y el contenido de los detalles no coinciden." });
  }
  if (page.details && (
    (page.detail_status === "available" && page.details.publication_status !== "approved") ||
    (page.detail_status === "preview_only" && page.details.publication_status !== "preview_only")
  )) {
    context.addIssue({ code: "custom", message: "El estado y la aprobación de los detalles no coinciden." });
  }
  if (page.details && (page.details.internal_id !== page.match.internal_id
    || page.details.source_match_id !== page.match.source_match_id
    || page.details.home_team_id !== page.match.home_team.team_id
    || page.details.away_team_id !== page.match.away_team.team_id
    || page.details.home.team_id !== page.match.home_team.team_id
    || page.details.away.team_id !== page.match.away_team.team_id
    || page.details.home_goals !== page.match.home_goals
    || page.details.away_goals !== page.match.away_goals
    || (page.match.source_match_date !== null && page.details.match_date !== page.match.source_match_date))) {
    context.addIssue({ code: "custom", message: "Los detalles no pertenecen al partido y generación solicitados." });
  }
  if (page.details?.events?.some((event) => event.team_id !== page.match.home_team.team_id && event.team_id !== page.match.away_team.team_id)) {
    context.addIssue({ code: "custom", message: "Un evento de partido referencia otro equipo." });
  }
});

const PlayerAssociationSchema = z.object({
  team_id: positiveInteger,
  team_name: z.string().min(1),
  group: z.enum(["I", "II"]),
  evidence_types: z.array(z.enum(["membership", "transfer_reference"])),
}).strict();

const PlayerIndexRecordSchema = z.object({
  player_id: positiveInteger,
  display_name: z.string().min(1).nullable(),
  full_name: z.string().nullable(),
  profile_url: z.string().url().nullable(),
  photo_url: z.string().url().nullable(),
  birth_date: dateOnly,
  age_years: nullableInteger,
  nationality: z.string().nullable(),
  position_name: z.string().nullable(),
  groups: z.array(z.enum(["I", "II"])),
  association_status: z.enum(["roster_membership_observed", "transfer_reference_only"]),
  team_associations: z.array(PlayerAssociationSchema),
  profile_status: z.enum(["four_views_verified", "partial_individual_views", "inventory_only"]),
}).strict();

const PlayerDirectoryMetadataSchema = z.object({
  season: z.literal("2026-27"),
  inventory_generated_at: z.string().datetime({ offset: true }),
  inventory_player_count: z.number().int().nonnegative(),
  complete_individual_profile_count: z.number().int().nonnegative(),
  partial_individual_profile_count: z.number().int().nonnegative(),
  inventory_only_count: z.number().int().nonnegative(),
  roster_membership_count: z.number().int().nonnegative(),
  transfer_only_count: z.number().int().nonnegative(),
  compact_generation_id: z.string().nullable(),
  compact_generated_at: z.string().datetime({ offset: true }).nullable(),
  inventory_sha256: z.string().regex(/^[a-f0-9]{64}$/),
}).strict();

const PlayerIdentitySchema = z.object({
  display_name: z.string().nullable(),
  full_name: z.string().nullable(),
  birth_date: dateOnly,
  age_years: nullableInteger,
  birth_place: z.string().nullable(),
  birth_place_raw: z.string().nullable(),
  birthplace_province: z.string().nullable(),
  country_of_birth: z.string().nullable(),
  nationality: z.string().nullable(),
  position_name: z.string().nullable(),
  height_cm: z.number().positive().nullable(),
  height_raw: z.string().nullable(),
  weight_kg: z.number().positive().nullable(),
  weight_raw: z.string().nullable(),
  field_sources: z.record(z.string(), z.enum(["inventory", "individual_profile", "unavailable"])),
  inventory_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  individual_profile_source_url: z.string().url().nullable(),
  individual_profile_captured_at: z.string().datetime({ offset: true }).nullable(),
  individual_profile_sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
  conflicts: z.array(z.object({
    field: z.string().min(1),
    inventory_value: z.string(),
    individual_profile_value: z.string(),
    selected_source: z.literal("individual_profile"),
  }).strict()),
}).strict();

const PlayerClubReferenceSchema = z.object({
  status: z.enum(["observed", "not_confirmed"]),
  team_id: positiveInteger.nullable(),
  team_name: z.string().nullable(),
  group: z.enum(["I", "II"]).nullable(),
  observed_at: z.string().datetime({ offset: true }).nullable(),
  reason: z.string().min(1),
}).strict();

const PlayerTransferEvidenceSchema = z.object({
  capture_id: z.string().nullable(),
  captured_at: z.string().datetime({ offset: true }).nullable(),
  source_sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
  source_record_index: nullableInteger,
  team_id: positiveInteger,
  group: z.enum(["I", "II"]).nullable(),
  direction: z.enum(["incoming", "outgoing"]),
}).strict();

const PlayerClubMovementSchema = z.object({
  from_team_id: positiveInteger,
  from_team_name: z.string().min(1),
  from_group: z.enum(["I", "II"]).nullable(),
  to_team_id: positiveInteger,
  to_team_name: z.string().min(1),
  to_group: z.enum(["I", "II"]).nullable(),
  season: z.literal("2026-27"),
  transfer_date: dateOnly,
  observed_at: z.string().datetime({ offset: true }).nullable(),
  evidence_count: z.number().int().min(1),
  evidence: z.array(PlayerTransferEvidenceSchema).min(1),
}).strict();

const PlayerMembershipHistorySchema = z.object({
  team_id: positiveInteger,
  team_name: z.string().min(1),
  group: z.enum(["I", "II"]),
  season: z.literal("2026-27"),
  captured_at: z.string().datetime({ offset: true }).nullable(),
  capture_id: z.string().nullable(),
  jersey_number: nullableInteger,
  squad_group_label: z.string().nullable(),
  source_views: z.array(z.string()),
}).strict();

export const PlayerDirectorySchema = z.object({
  metadata: PlayerDirectoryMetadataSchema,
  available_teams: z.array(z.object({ team_id: positiveInteger, team_name: z.string(), group: z.enum(["I", "II"]) }).strict()),
  query: z.string(),
  group: z.enum(["I", "II"]).nullable(),
  team_id: positiveInteger.nullable(),
  page: z.number().int().min(1),
  page_size: z.number().int().min(1).max(100),
  total: z.number().int().nonnegative(),
  players: z.array(PlayerIndexRecordSchema),
}).strict();

const PlayerCellScalarSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);
const PlayerSourceFieldsSchema = z.record(z.string(), z.unknown());
const PlayerViewSchema = z.object({
  view: z.enum(["profile", "statistics", "matches", "rivals"]),
  source_url: z.string().url(),
  captured_at: z.string().datetime({ offset: true }).nullable(),
  source_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  scope_note: z.string(),
  tables: z.array(z.object({
    table_role: z.string(),
    source_table_index: z.number().int().nullable(),
    table_id: z.string().nullable(),
    schema_id: z.string().nullable(),
    columns: z.array(z.object({
      label: z.string(), source_header: z.string().nullable(), title: z.string().nullable(), hidden_in_source: z.boolean(),
      source_index: z.number().int().nullable(), group_header: z.string().nullable(), data_colid: z.string().nullable(),
    }).strict()),
    rows: z.array(z.object({
      context: z.record(z.string(), PlayerCellScalarSchema),
      cells: z.array(z.object({ raw_value: PlayerCellScalarSchema, normalized_integer: nullableInteger, value_status: z.string().nullable() }).strict()),
      source_fields: PlayerSourceFieldsSchema,
      internal_player_id: positiveInteger.nullable(),
    }).strict()),
  }).strict()),
  profile: PlayerSourceFieldsSchema.nullable(),
  coverage: PlayerSourceFieldsSchema.nullable(),
  historical_matches: z.array(z.object({
    match_id: z.string().nullable(), match_url: z.string().url().nullable(), date: dateOnly, date_raw: z.string().nullable(),
    season: z.string().nullable(), competition: z.string().nullable(), round_label: z.string().nullable(),
    player_team: z.string().nullable(), opponent_team: z.string().nullable(), side: z.string().nullable(),
    home_goals: nullableInteger, away_goals: nullableInteger, home_team_id: positiveInteger.nullable(), away_team_id: positiveInteger.nullable(),
    minutes: nullableInteger, match_state: z.string().nullable(), appearance_status: z.string().nullable(),
    participation: z.string(),
    match_statistics: z.array(z.object({ label: z.string().min(1), raw_value: PlayerCellScalarSchema, normalized_integer: nullableInteger }).strict()),
    source_fields: PlayerSourceFieldsSchema,
  }).strict()),
  summoned_without_participation: z.array(z.object({
    match_id: z.string().nullable(), match_url: z.string().url().nullable(), date: dateOnly, date_raw: z.string().nullable(),
    season: z.string().nullable(), competition: z.string().nullable(), round_label: z.string().nullable(),
    player_team: z.string().nullable(), opponent_team: z.string().nullable(), side: z.string().nullable(),
    home_goals: nullableInteger, away_goals: nullableInteger, home_team_id: positiveInteger.nullable(), away_team_id: positiveInteger.nullable(),
    minutes: nullableInteger, match_state: z.string().nullable(), appearance_status: z.string().nullable(),
    participation: z.string(),
    match_statistics: z.array(z.object({ label: z.string().min(1), raw_value: PlayerCellScalarSchema, normalized_integer: nullableInteger }).strict()),
    source_fields: PlayerSourceFieldsSchema,
  }).strict()),
  other_match_records: z.array(z.object({
    match_id: z.string().nullable(), match_url: z.string().url().nullable(), date: dateOnly, date_raw: z.string().nullable(),
    season: z.string().nullable(), competition: z.string().nullable(), round_label: z.string().nullable(),
    player_team: z.string().nullable(), opponent_team: z.string().nullable(), side: z.string().nullable(),
    home_goals: nullableInteger, away_goals: nullableInteger, home_team_id: positiveInteger.nullable(), away_team_id: positiveInteger.nullable(),
    minutes: nullableInteger, match_state: z.string().nullable(), appearance_status: z.string().nullable(),
    participation: z.string(),
    match_statistics: z.array(z.object({ label: z.string().min(1), raw_value: PlayerCellScalarSchema, normalized_integer: nullableInteger }).strict()),
    source_fields: PlayerSourceFieldsSchema,
  }).strict()),
  record_counts: PlayerSourceFieldsSchema,
  individual_matches_source: z.string().nullable(),
  window_p_parse_status: z.string().nullable(),
  window_p_record_count: nullableInteger,
  detail_coverage: z.string().nullable(),
  exhaustiveness_status: z.string().nullable(),
  filter_parameters: PlayerSourceFieldsSchema,
  filtered_view: z.boolean().nullable(),
}).strict();

export const PlayerDetailSchema = z.object({
  metadata: PlayerDirectoryMetadataSchema,
  player: PlayerIndexRecordSchema,
  identity: PlayerIdentitySchema,
  club_reference: PlayerClubReferenceSchema,
  last_observed_movement: PlayerClubMovementSchema.nullable(),
  movement_resolution: z.enum(["identified", "ambiguous", "none"]),
  birth_place: z.string().nullable(),
  birthplace_province: z.string().nullable(),
  nationality_flag_url: z.string().url().nullable(),
  verified_indicators: z.array(z.string()),
  associations: z.array(PlayerAssociationSchema),
  membership_history: z.array(PlayerMembershipHistorySchema),
  transfer_references: z.array(z.object({
    team_id: positiveInteger, team_name: z.string().nullable(), group: z.enum(["I", "II"]),
    direction: z.enum(["incoming", "outgoing"]), other_team_name: z.string().nullable(), other_team_id: positiveInteger.nullable(),
    source_position_code: z.string().nullable(), age_years: nullableInteger, transfer_date: dateOnly,
    capture_id: z.string().nullable(), captured_at: z.string().datetime({ offset: true }).nullable(),
    source_sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(), source_record_index: nullableInteger,
  }).strict()),
  season_statistics: z.array(z.object({
    team_id: positiveInteger, team_name: z.string().nullable(), group: z.enum(["I", "II"]),
    matches_played: nullableInteger, starts: nullableInteger, minutes_played: nullableInteger, goals: nullableInteger,
    assists: nullableInteger, yellow_cards: nullableInteger, red_cards: nullableInteger, source_view: z.string().nullable(),
  }).strict()),
  match_minutes: z.array(z.object({
    team_id: positiveInteger, team_name: z.string().nullable(), group: z.enum(["I", "II"]), match_id: z.string().nullable(),
    matchday: z.number().int().min(1).max(38), metric: z.string().nullable(), value: z.number().int().nonnegative(),
    raw_value: z.string().nullable(), source_state: z.string().nullable(), captured_at: z.string().datetime({ offset: true }).nullable(),
  }).strict()),
  match_metrics: z.array(z.object({
    team_id: positiveInteger, team_name: z.string().nullable(), group: z.enum(["I", "II"]), match_id: z.string().nullable(),
    matchday: z.number().int().min(1).max(38), metric: z.string().nullable(), value: z.number().int().nonnegative(),
    raw_value: z.string().nullable(), source_state: z.string().nullable(), captured_at: z.string().datetime({ offset: true }).nullable(),
  }).strict()),
  verified_individual_views: z.array(PlayerViewSchema),
  warnings: z.array(z.string()),
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
export type MatchResultsBootstrap = z.infer<typeof MatchResultsBootstrapSchema>;
export type MatchResultsGroup = MatchResultsBootstrap["groups"]["I"];
export type MatchGenerationRecord = z.infer<typeof MatchGenerationRecordSchema>;
export type MatchPage = z.infer<typeof MatchPageSchema>;
export type PlayerDirectory = z.infer<typeof PlayerDirectorySchema>;
export type PlayerIndexRecord = z.infer<typeof PlayerIndexRecordSchema>;
export type PlayerDetail = z.infer<typeof PlayerDetailSchema>;
