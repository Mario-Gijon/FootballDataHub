import { useState } from "react";
import type { PlayerDetail } from "../api/contracts";

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

export function PlayerIndividualViews({ views, movement = null }: { views: PlayerView[]; movement?: PlayerDetail["last_observed_movement"] }) {
  const [selected, setSelected] = useState<(typeof viewOrder)[number]>("profile");
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
          onClick={() => setSelected(name)}
        >{viewTitle[name]}</button>)}
      </nav>
    </header>
    <div id="player-view-panel" className="player-view-content" role="tabpanel" aria-labelledby={`player-tab-${selected}`}>
      {selected === "profile" && <CareerView view={view} movement={movement} />}
      {selected === "statistics" && <StatisticsView view={view} />}
      {selected === "matches" && <MatchesView view={view} />}
      {selected === "rivals" && <RivalsView view={view} />}
    </div>
  </section>;
}

function CareerView({ view, movement }: { view: PlayerView; movement: PlayerDetail["last_observed_movement"] }) {
  return <>
    <DataTables tables={view.tables} empty="No hay temporadas de trayectoria disponibles." />
    {movement && <p className="player-movement-line"><strong>Movimiento registrado · {movement.season}:</strong> {movement.from_team_name} → {movement.to_team_name}</p>}
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

function MatchesView({ view }: { view: PlayerView }) {
  const [season, setSeason] = useState("all");
  const [competition, setCompetition] = useState("all");
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
    <DataTables tables={view.tables} empty="No hay resúmenes de partidos disponibles." />
    <div className="player-match-filters" aria-label="Filtrar partidos">
      <label>Temporada<select aria-label="Temporada" value={season} onChange={(event) => setSeason(event.currentTarget.value)}>
        <option value="all">Todas</option>{seasons.map((value) => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <label>Competición<select aria-label="Competición" value={competition} onChange={(event) => setCompetition(event.currentTarget.value)}>
        <option value="all">Todas</option>{competitions.map((value) => <option key={value} value={value}>{value}</option>)}
      </select></label>
    </div>
    <MatchRecords records={filtered} />
  </>;
}

function RivalsView({ view }: { view: PlayerView }) {
  return <DataTables tables={view.tables} empty="No hay estadísticas de rivales disponibles." />;
}

function DataTables({ tables, empty }: { tables: PlayerTable[]; empty: string }) {
  const publishable = tables.filter((table) => table.columns.length > 0);
  if (publishable.length === 0) return <p className="player-data-empty">{empty}</p>;
  return <div className="player-source-tables">
    {publishable.map((table, index) => <SourceTable key={`${table.table_id ?? table.table_role}-${table.source_table_index ?? table.schema_id ?? "table"}-${index}`} table={table} />)}
  </div>;
}

function SourceTable({ table }: { table: PlayerTable }) {
  const caption = tableCaption(table);
  if (!caption) return null;
  return <section className="player-source-table">
    <h3>{caption}</h3>
    {table.rows.length === 0 ? <p className="player-data-empty">No hay datos en esta tabla.</p> : <div className="player-table-scroll">
      <table className="player-data-table">
        <thead><tr>{table.columns.map((column, index) => <th key={`${column.source_index ?? index}-${column.label}`}>{column.label}</th>)}</tr></thead>
        <tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>
          {table.columns.map((column, columnIndex) => {
            const sourceIndex = column.source_index ?? columnIndex;
            const cell = row.cells[sourceIndex];
            const value = cell?.normalized_integer ?? cell?.raw_value;
            return <td key={`${sourceIndex}-${column.label}`}>{display(value) || careerMarker(row, column.label)}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}

function MatchRecords({ records }: { records: PlayerMatch[] }) {
  if (records.length === 0) return <p className="player-data-empty">No hay partidos disponibles.</p>;
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
          <td>{record.player_team && record.side === "home" ? record.player_team : teamName(record, "home")}</td>
          <td>{score(record.home_goals, record.away_goals)}</td>
          <td>{record.player_team && record.side === "away" ? record.player_team : teamName(record, "away")}</td>
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

function score(home: number | null, away: number | null): string {
  return home === null || away === null ? "—" : `${home}–${away}`;
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "object") return "";
  return String(value);
}
