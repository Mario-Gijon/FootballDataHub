import { useState } from "react";
import type { PlayerDetail } from "../api/contracts";
import type { CatalogTeam } from "../domain/teams";
import { InternalPlayerLink } from "./InternalPlayerLink";
import { InternalTeamLink } from "./InternalTeamLink";

type PlayerView = PlayerDetail["verified_individual_views"][number];
type PlayerTable = PlayerView["tables"][number];
type PlayerMatch = PlayerView["historical_matches"][number];

const viewOrder = ["profile", "statistics", "matches", "rivals"] as const;
const viewTitle: Record<(typeof viewOrder)[number], string> = {
  profile: "Trayectoria",
  statistics: "Estadísticas",
  matches: "Partidos",
  rivals: "Rivales",
};

const roleLabels: Record<string, string> = {
  career_trajectory: "Trayectoria por temporada",
  career_totals: "Totales de trayectoria",
  match_summary_by_season: "Partidos por temporada",
  match_summary_by_team: "Partidos por equipo",
  match_summary_by_competition: "Partidos por competición",
  match_summary_by_opponent: "Partidos por rival",
  statistics_by_team: "Estadísticas por equipo",
  statistics_by_competition: "Estadísticas por competición",
  opponent_player_statistics: "Rendimiento ante jugadores",
  opponent_coach_statistics: "Rendimiento ante entrenadores",
  opponent_team_statistics: "Rendimiento ante equipos",
  milestone_matches: "Hitos estadísticos",
  additional_sports_table: "Otros registros deportivos",
};

export function PlayerIndividualViews({
  playerId = null,
  views,
  movement = null,
  teams = [],
  onNavigate = () => undefined,
}: {
  views: PlayerView[];
  playerId?: number | null;
  movement?: PlayerDetail["last_observed_movement"];
  teams?: readonly CatalogTeam[];
  onNavigate?: (path: string) => void;
}) {
  const [selected, setSelected] = useState<(typeof viewOrder)[number]>(() => readSelectedView(playerId));
  const byName = new Map(views.map((view) => [view.view, view]));
  const view = byName.get(selected);
  if (!view) return null;

  return <section className="player-individual-views" aria-label="Trayectoria y rendimiento">
    <header className="player-view-heading">
      <h2>Trayectoria y rendimiento</h2>
      <nav className="player-view-tabs" aria-label="Apartados del jugador" role="tablist">
        {viewOrder.map((name) => <button
          key={name}
          id={`player-tab-${name}`}
          type="button"
          role="tab"
          aria-controls="player-view-panel"
          aria-selected={selected === name}
          className={selected === name ? "is-active" : ""}
          onClick={() => {
            setSelected(name);
            storePlayerState(playerId, "view", name);
          }}
        >{viewTitle[name]}</button>)}
      </nav>
    </header>
    <div id="player-view-panel" className="player-view-content" role="tabpanel" aria-labelledby={`player-tab-${selected}`}>
      {selected === "profile" && <CareerView view={view} movement={movement} teams={teams} onNavigate={onNavigate} />}
      {selected === "statistics" && <StatisticsView view={view} />}
      {selected === "matches" && <MatchesView view={view} playerId={playerId} teams={teams} onNavigate={onNavigate} />}
      {selected === "rivals" && <RivalsView view={view} teams={teams} onNavigate={onNavigate} />}
    </div>
  </section>;
}

function CareerView({ view, movement, teams, onNavigate }: {
  view: PlayerView;
  movement: PlayerDetail["last_observed_movement"];
  teams: readonly CatalogTeam[];
  onNavigate: (path: string) => void;
}) {
  const teamsById = new Map(teams.map((team) => [team.team_id, team]));
  return <>
    <DataTables tables={view.tables} empty="No hay temporadas de trayectoria disponibles." teams={teams} onNavigate={onNavigate} />
    {movement && <p className="player-movement-line"><strong>Movimiento registrado · {movement.season}:</strong>{" "}
      {teamReference(movement.from_team_id, movement.from_team_name, teamsById, onNavigate)}{" → "}
      {teamReference(movement.to_team_id, movement.to_team_name, teamsById, onNavigate)}
    </p>}
  </>;
}

function StatisticsView({ view }: { view: PlayerView }) {
  const [dimension, setDimension] = useState<"competition" | "team">("competition");
  const tables = view.tables.filter((table) => table.table_role === `statistics_by_${dimension}`);
  const milestones = view.tables.filter((table) => table.table_role === "milestone_matches");
  const other = view.tables.filter((table) => ![
    "statistics_by_competition", "statistics_by_team", "milestone_matches",
  ].includes(table.table_role));
  return <>
    <nav className="player-stat-dimensions" aria-label="Agrupar estadísticas">
      <button type="button" aria-pressed={dimension === "competition"} className={dimension === "competition" ? "is-active" : ""} onClick={() => setDimension("competition")}>Competiciones</button>
      <button type="button" aria-pressed={dimension === "team"} className={dimension === "team" ? "is-active" : ""} onClick={() => setDimension("team")}>Equipos</button>
    </nav>
    <DataTables tables={tables} empty="No hay estadísticas para esta vista." />
    {milestones.length > 0 && <section className="player-sports-subsection" aria-label="Hitos estadísticos">
      <h3>Hitos estadísticos</h3>
      <DataTables tables={milestones} empty="No hay hitos estadísticos disponibles." />
    </section>}
    {other.length > 0 && <DataTables tables={other} empty="No hay otros registros deportivos disponibles." />}
  </>;
}

function MatchesView({ view, playerId, teams, onNavigate }: { view: PlayerView; playerId: number | null; teams: readonly CatalogTeam[]; onNavigate: (path: string) => void }) {
  const [season, setSeason] = useState(() => readPlayerState(playerId, "season"));
  const [competition, setCompetition] = useState(() => readPlayerState(playerId, "competition"));
  const records = [
    ...view.historical_matches,
    ...view.summoned_without_participation,
    ...view.other_match_records,
  ].sort((left, right) => matchOrder(left) - matchOrder(right));
  const seasons = [...new Set(records.map((record) => record.season).filter((value): value is string => Boolean(value)))].sort((a, b) => b.localeCompare(a));
  const competitions = [...new Set(records.map((record) => record.competition).filter((value): value is string => Boolean(value)))].sort((a, b) => a.localeCompare(b, "es"));
  const filtered = records.filter((record) =>
    (season === "all" || record.season === season)
    && (competition === "all" || record.competition === competition),
  );
  return <>
    <DataTables tables={view.tables} empty="No hay resúmenes de partidos disponibles." teams={teams} onNavigate={onNavigate} />
    <div className="player-match-filters" aria-label="Filtrar partidos">
      <label>Temporada<select aria-label="Temporada" value={season} onChange={(event) => {
        setSeason(event.currentTarget.value);
        storePlayerState(playerId, "season", event.currentTarget.value);
      }}>
        <option value="all">Todas</option>{seasons.map((value) => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <label>Competición<select aria-label="Competición" value={competition} onChange={(event) => {
        setCompetition(event.currentTarget.value);
        storePlayerState(playerId, "competition", event.currentTarget.value);
      }}>
        <option value="all">Todas</option>{competitions.map((value) => <option key={value} value={value}>{value}</option>)}
      </select></label>
    </div>
    <MatchRecords records={filtered} teams={teams} onNavigate={onNavigate} />
  </>;
}

function RivalsView({ view, teams, onNavigate }: { view: PlayerView; teams: readonly CatalogTeam[]; onNavigate: (path: string) => void }) {
  return <DataTables tables={view.tables} empty="No hay estadísticas de rivales disponibles." teams={teams} onNavigate={onNavigate} />;
}

function DataTables({ tables, empty, teams = [], onNavigate = () => undefined }: {
  tables: PlayerTable[];
  empty: string;
  teams?: readonly CatalogTeam[];
  onNavigate?: (path: string) => void;
}) {
  const publishable = tables.filter((table) => table.columns.length > 0);
  if (publishable.length === 0) return <p className="player-data-empty">{empty}</p>;
  return <div className="player-source-tables">
    {publishable.map((table, index) => <SourceTable key={`${table.table_id ?? table.table_role}-${table.source_table_index ?? table.schema_id ?? "table"}-${index}`} table={table} teams={teams} onNavigate={onNavigate} />)}
  </div>;
}

function SourceTable({ table, teams, onNavigate }: { table: PlayerTable; teams: readonly CatalogTeam[]; onNavigate: (path: string) => void }) {
  const caption = tableCaption(table);
  if (!caption) return null;
  if (table.table_role === "career_totals") {
    return <CareerTotalsTable table={table} caption={caption} />;
  }
  return <section className="player-source-table">
    <h3>{caption}</h3>
    {table.rows.length === 0 ? <p className="player-data-empty">No hay datos en esta tabla.</p> : <div className="player-table-scroll">
      <table className="player-data-table">
        <thead><tr>{table.columns.map((column, index) => <th key={`${column.source_index ?? index}-${column.label}`}>{column.label}</th>)}</tr></thead>
        <tbody>{table.rows.map((row, rowIndex) => {
          const isCareerTotal = table.table_role === "career_totals" && row.source_fields.row_role === "total";
          const summaryCellIndex = row.cells.findIndex((cell) =>
            typeof cell.raw_value === "string" && /^total(?:es)?(?:\s|$)/iu.test(cell.raw_value.trim()),
          );
          const summaryLabel = row.source_fields.summary_label_raw
            ?? (summaryCellIndex >= 0 ? row.cells[summaryCellIndex].raw_value : null);
          const declaredSpan = row.source_fields.summary_label_span;
          const summarySpan = typeof declaredSpan === "number" ? declaredSpan : summaryCellIndex + 1;
          if (isCareerTotal && typeof summaryLabel === "string" && summarySpan > 0) {
            return <tr key={rowIndex} className="player-total-row">
              <td colSpan={Math.min(summarySpan, table.columns.length)}>{summaryLabel.trim() || "Total"}</td>
              {table.columns.map((column, columnIndex) => {
                const sourceIndex = column.source_index ?? columnIndex;
                if (sourceIndex < summarySpan) return null;
                return <td key={`${sourceIndex}-${column.label}`}>{tableCellValue(row, column, columnIndex, table, teams, onNavigate)}</td>;
              })}
            </tr>;
          }
          return <tr key={rowIndex}>
            {table.columns.map((column, columnIndex) => <td key={`${column.source_index ?? columnIndex}-${column.label}`}>
              {tableCellValue(row, column, columnIndex, table, teams, onNavigate)}
            </td>)}
          </tr>;
        })}</tbody>
      </table>
    </div>}
  </section>;
}

function CareerTotalsTable({ table, caption }: { table: PlayerTable; caption: string }) {
  const totalRows = table.rows.filter(isCareerTotalRow);
  return <section className="player-source-table player-career-totals">
    <h3>{caption}</h3>
    {totalRows.length === 0 ? <p className="player-data-empty">No hay métricas acumuladas disponibles.</p> : totalRows.map((row, rowIndex) => {
      const metrics = careerTotalMetrics(table, row);
      const primary = metrics.filter((metric) => metric.primary);
      const secondary = metrics.filter((metric) => !metric.primary);
      if (metrics.length === 0) {
        return <p className="player-data-empty" key={rowIndex}>La captura no contiene métricas acumuladas disponibles.</p>;
      }
      return <div className="player-career-total" key={rowIndex}>
        {primary.length > 0 && <dl className="player-career-total-primary" aria-label="Métricas principales">
          {primary.map((metric) => <div key={metric.sourceIndex}>
            <dt>{metric.label}</dt><dd>{metric.value}</dd>
          </div>)}
        </dl>}
        {secondary.length > 0 && <dl className="player-career-total-secondary" aria-label="Otras estadísticas acumuladas">
          {secondary.map((metric) => <div key={metric.sourceIndex}>
            <dt>{metric.label}</dt><dd>{metric.value}</dd>
          </div>)}
        </dl>}
      </div>;
    })}
  </section>;
}

function careerTotalMetrics(table: PlayerTable, row: PlayerTable["rows"][number]) {
  const labelCellIndex = row.cells.findIndex((cell) =>
    typeof cell.raw_value === "string" && /^total(?:es)?$/iu.test(cell.raw_value.trim()),
  );
  const declaredSpan = row.source_fields.summary_label_span;
  const knownSpan = typeof declaredSpan === "number" && Number.isInteger(declaredSpan) && declaredSpan >= 0
    ? declaredSpan : 0;
  const summarySpan = Math.max(knownSpan, labelCellIndex >= 0 ? labelCellIndex + 1 : 0);
  return table.columns.flatMap((column, columnIndex) => {
    const sourceIndex = column.source_index ?? columnIndex;
    if (sourceIndex < summarySpan || isDescriptiveCareerColumn(column)) return [];
    const cell = row.cells[sourceIndex];
    if (!cell || cell.value_status === "MISSING_OR_PLACEHOLDER") return [];
    const raw = cell.raw_value;
    if (raw === null || raw === undefined || raw === "") return [];
    if (typeof raw === "string" && ["-", "–", "—"].includes(raw.trim())) return [];
    const label = column.title?.trim() || column.label.trim();
    if (!label) return [];
    const value = cell.normalized_integer ?? raw;
    const normalizedLabel = normalizeCareerLabel(label);
    return [{
      sourceIndex,
      label,
      value: display(value),
      primary: isPrimaryCareerMetric(normalizedLabel),
    }];
  });
}

function isCareerTotalRow(row: PlayerTable["rows"][number]): boolean {
  if (row.source_fields.row_role === "total") return true;
  const summary = row.source_fields.summary_label_raw;
  if (typeof summary === "string" && /^total(?:es)?$/iu.test(summary.trim())) return true;
  return row.cells.some((cell) => typeof cell.raw_value === "string" && /^total(?:es)?$/iu.test(cell.raw_value.trim()));
}

function isDescriptiveCareerColumn(column: PlayerTable["columns"][number]): boolean {
  const labels = [column.title, column.label, column.source_header]
    .filter((value): value is string => typeof value === "string")
    .map(normalizeCareerLabel);
  const descriptive = new Set([
    "temp", "temporada", "season", "equipo", "team", "pais", "country",
    "ascenso o descenso", "division", "div", "edad", "age", "dorsal", "nr", "numero", "n.º", "nº", "#",
    "numero dorsal", "otras competiciones", "other competitions",
  ]);
  return labels.some((label) => descriptive.has(label));
}

function normalizeCareerLabel(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/gu, "").trim().toLocaleLowerCase("es");
}

function isPrimaryCareerMetric(label: string): boolean {
  return new Set([
    "partidos jugados", "partidos", "pj", "partidos titular", "titularidades", "pt",
    "minutos", "min", "goles", "g",
  ]).has(label);
}

function tableCellValue(
  row: PlayerTable["rows"][number],
  column: PlayerTable["columns"][number],
  columnIndex: number,
  table: PlayerTable,
  teams: readonly CatalogTeam[],
  onNavigate: (path: string) => void,
) {
  const sourceIndex = column.source_index ?? columnIndex;
  const cell = row.cells[sourceIndex];
  const value = cell?.normalized_integer ?? cell?.raw_value;
  const text = display(value) || careerMarker(row, column.label);
  const playerId = table.table_role === "opponent_player_statistics" ? row.internal_player_id : null;
  if (playerId !== null && typeof playerId === "number"
    && text === row.source_fields.rival_name_raw) {
    return <InternalPlayerLink playerId={playerId} onNavigate={onNavigate}>{text}</InternalPlayerLink>;
  }
  if (table.table_role === "career_trajectory" && column.label.toLocaleLowerCase("es") === "equipo") {
    const teamId = verifiedCareerTeamId(row);
    if (teamId !== null && teams.some((team) => team.team_id === teamId)) {
      return <InternalTeamLink teamId={teamId} onNavigate={onNavigate}>{text}</InternalTeamLink>;
    }
  }
  return text;
}

function MatchRecords({ records, teams, onNavigate }: { records: PlayerMatch[]; teams: readonly CatalogTeam[]; onNavigate: (path: string) => void }) {
  if (records.length === 0) return <p className="player-data-empty">No hay partidos disponibles.</p>;
  const teamsById = new Map(teams.map((team) => [team.team_id, team]));
  const statisticLabels = [...new Set(records.flatMap((record) => record.match_statistics.map((item) => item.label)))];
  return <section className="player-source-table player-match-table-section">
    <h3>Partidos de la trayectoria</h3>
    <div className="player-table-scroll">
      <table className="player-data-table">
        <thead><tr>
          <th>Fecha</th><th>Temporada</th><th>Competición</th><th>Jornada</th>
          <th>Local</th><th>Marcador</th><th>Visitante</th><th>Participación</th>
          {statisticLabels.map((label) => <th key={label}>{label}</th>)}
          <th>Partido</th>
        </tr></thead>
        <tbody>{records.map((record, index) => <tr key={`${record.match_id ?? "match"}-${index}`}>
          <td>{record.date ?? record.date_raw ?? "—"}</td>
          <td>{record.season ?? "—"}</td><td>{record.competition ?? "—"}</td><td>{record.round_label ?? "—"}</td>
          <td>{teamReference(record.home_team_id, record.player_team && record.side === "home" ? record.player_team : teamName(record, "home"), teamsById, onNavigate)}</td>
          <td>{score(record.home_goals, record.away_goals)}</td>
          <td>{teamReference(record.away_team_id, record.player_team && record.side === "away" ? record.player_team : teamName(record, "away"), teamsById, onNavigate)}</td>
          <td>{record.participation}</td>
          {statisticLabels.map((label) => <td key={label}>{display(record.match_statistics.find((item) => item.label === label)?.normalized_integer ?? record.match_statistics.find((item) => item.label === label)?.raw_value)}</td>)}
          <td>{record.match_url && <a href={record.match_url} target="_blank" rel="noreferrer">Ver partido ↗</a>}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}

function tableCaption(table: PlayerTable): string | null {
  const sourceCaption = table.rows.find((row) => typeof row.context.table_caption_raw === "string")?.context.table_caption_raw;
  if (typeof sourceCaption === "string" && sourceCaption.trim()) return sourceCaption.trim();
  return roleLabels[table.table_role] ?? null;
}

function careerMarker(row: PlayerTable["rows"][number], label: string): string {
  const key = label === "Ascenso o descenso" ? "team_achievements_raw"
    : label === "Otras competiciones" ? "competition_participations_raw" : null;
  if (!key) return "—";
  const value = row.source_fields[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join(" · ") || "—" : "—";
}

function matchOrder(record: PlayerMatch): number {
  const index = record.source_fields.source_record_index;
  return typeof index === "number" ? index : Number.MAX_SAFE_INTEGER;
}

function teamName(record: PlayerMatch, side: "home" | "away"): string {
  const value = record.source_fields[side === "home" ? "home_team_raw" : "away_team_raw"];
  return typeof value === "string" && value ? value : "—";
}

function verifiedCareerTeamId(row: PlayerTable["rows"][number]): number | null {
  const reference = row.source_fields.team_season_reference;
  const url = row.source_fields.team_season_url;
  if (typeof reference !== "string" || typeof url !== "string") return null;
  let path: string;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || !["bdfutbol.com", "www.bdfutbol.com"].includes(parsed.hostname)) return null;
    path = parsed.pathname;
  } catch { return null; }
  const match = /^\/es\/t\/t\d{4}-\d{2}([1-9]\d*)\.html$/u.exec(path);
  if (!match || reference !== path.split("/").pop()?.replace(/\.html$/u, "")) return null;
  const teamId = Number(match[1]);
  return Number.isSafeInteger(teamId) && teamId > 0 ? teamId : null;
}

function teamReference(
  teamId: number | null,
  name: string,
  teamsById: Map<number, CatalogTeam>,
  onNavigate: (path: string) => void,
) {
  const team = teamId === null ? undefined : teamsById.get(teamId);
  return team ? <InternalTeamLink teamId={team.team_id} onNavigate={onNavigate}>{name}</InternalTeamLink> : name;
}

function score(home: number | null, away: number | null): string {
  return home === null || away === null ? "—" : `${home}–${away}`;
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "object") return "";
  return String(value);
}

type StoredPlayerStateKey = "view" | "season" | "competition";
const playerViews = new Set<string>(viewOrder);

function readSelectedView(playerId: number | null): (typeof viewOrder)[number] {
  const value = readPlayerState(playerId, "view");
  return playerViews.has(value) ? value as (typeof viewOrder)[number] : "profile";
}

function readPlayerState(playerId: number | null, key: StoredPlayerStateKey): string {
  if (playerId === null) return key === "view" ? "profile" : "all";
  try { return window.sessionStorage.getItem(`football-data-hub:player:${playerId}:${key}`) ?? (key === "view" ? "profile" : "all"); }
  catch { return key === "view" ? "profile" : "all"; }
}

function storePlayerState(playerId: number | null, key: StoredPlayerStateKey, value: string): void {
  if (playerId === null) return;
  try { window.sessionStorage.setItem(`football-data-hub:player:${playerId}:${key}`, value); }
  catch { /* The selected view remains usable without session storage. */ }
}
