import { useState } from "react";
import type { PlayerDetail } from "../api/contracts";

type PlayerView = PlayerDetail["verified_individual_views"][number];
type PlayerTable = PlayerView["tables"][number];

const viewOrder = ["profile", "statistics", "matches", "rivals"] as const;
const viewTitle: Record<(typeof viewOrder)[number], string> = {
  profile: "Trayectoria",
  statistics: "Estadísticas",
  matches: "Partidos",
  rivals: "Rivales",
};

const roleLabels: Record<string, string> = {
  career_trajectory: "Trayectoria por temporada y club",
  career_totals: "Totales de trayectoria",
  match_summary_by_season: "Resumen de partidos por temporada",
  match_summary_by_team: "Resumen de partidos por equipo",
  match_summary_by_competition: "Resumen de partidos por competición",
  statistics_by_team: "Estadísticas por equipo",
  statistics_by_competition: "Estadísticas por competición",
  opponent_team_statistics: "Estadísticas por rival",
  opponent_competition_statistics: "Estadísticas por competición y rival",
};

const statusLabels: Record<string, string> = {
  CAREER_ROWS_PRESENT_NOT_CERTIFIED_COMPLETE: "Hay filas de trayectoria en la captura; el histórico no está certificado como completo.",
  NOT_CERTIFIED_COMPLETE: "La fuente no certifica que este histórico esté completo.",
  SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE: "Los datos corresponden al alcance de esta captura; no se certifica exhaustividad.",
  CAPTURED_ROWS: "Se muestran las filas observadas en la captura guardada.",
  PARSED: "La captura se pudo interpretar; esto no certifica que incluya todos los datos.",
  CAPTURED_VALID: "Captura validada para la vista individual.",
};

export function PlayerIndividualViews({ views }: { views: PlayerView[] }) {
  const [selected, setSelected] = useState<(typeof viewOrder)[number]>("profile");
  const byName = new Map(views.map((view) => [view.view, view]));
  const view = byName.get(selected);
  if (!view) return <section className="player-individual-views"><h2>Datos individuales</h2><p>No hay compactos individuales verificados para este jugador.</p></section>;

  return <section className="player-individual-views" aria-label="Datos individuales capturados">
    <header className="player-view-heading"><div><span className="section-kicker">CAPTURAS INDIVIDUALES VERIFICADAS</span><h2>Datos deportivos</h2></div>
      <nav className="player-view-tabs" aria-label="Apartados individuales" role="tablist">
        {viewOrder.map((name) => {
          const item = byName.get(name);
          return <button key={name} type="button" role="tab" aria-selected={selected === name} className={selected === name ? "is-active" : ""} onClick={() => setSelected(name)}>
            {viewTitle[name]}{item && <span>{name === "matches" ? item.historical_matches.length : item.tables.length}</span>}
          </button>;
        })}
      </nav>
    </header>
    <div className="player-view-content" role="tabpanel" aria-label={viewTitle[selected]}>
      <p className="player-view-scope">{readableStatus(view.scope_note)}</p>
      {selected === "profile" && <CareerView view={view} />}
      {selected === "statistics" && <StatisticsView view={view} />}
      {selected === "matches" && <MatchesView view={view} />}
      {selected === "rivals" && <RivalsView view={view} />}
      <a className="player-source-link" href={view.source_url} target="_blank" rel="noreferrer">Abrir esta vista en BDFutbol ↗</a>
    </div>
  </section>;
}

function CareerView({ view }: { view: PlayerView }) {
  const profile = view.profile;
  return <>
    {typeof profile?.career_completeness === "string" && <p className="player-data-note">{readableStatus(profile.career_completeness)}</p>}
    <DataTables tables={view.tables} empty="La captura no contiene filas de trayectoria estructuradas." fallbackCaption="Trayectoria observada" />
  </>;
}

function StatisticsView({ view }: { view: PlayerView }) {
  return <DataTables tables={view.tables} empty="La captura no contiene tablas estadísticas estructuradas." fallbackCaption="Estadísticas observadas" />;
}

function MatchesView({ view }: { view: PlayerView }) {
  const played = view.historical_matches;
  const summoned = view.summoned_without_participation;
  const other = view.other_match_records;
  return <>
    <div className="player-match-coverage">
      <span><strong>{played.length}</strong> partidos con participación observada</span>
      <span><strong>{summoned.length}</strong> convocatorias sin participación</span>
      <span><strong>{other.length}</strong> otros registros</span>
      {view.window_p_record_count !== null && <span><strong>{view.window_p_record_count}</strong> filas procesadas en la captura</span>}
    </div>
    {(view.exhaustiveness_status || view.detail_coverage) && <p className="player-data-note">Cobertura: {[view.detail_coverage, view.exhaustiveness_status].filter((value): value is string => Boolean(value)).map(readableStatus).join(" · ")}</p>}
    <DataTables tables={view.tables} empty="La captura no contiene resúmenes de partidos estructurados." fallbackCaption="Resumen de partidos observado" />
    <MatchRecords title="Partidos con participación" records={played} />
    <MatchRecords title="Convocatorias sin participación" records={summoned} />
    <MatchRecords title="Otros registros de partidos" records={other} />
  </>;
}

function RivalsView({ view }: { view: PlayerView }) {
  return <DataTables tables={view.tables} empty="La captura no contiene tablas de rivales estructuradas." fallbackCaption="Rendimiento frente a rivales" />;
}

function DataTables({ tables, empty, fallbackCaption }: { tables: PlayerTable[]; empty: string; fallbackCaption: string }) {
  if (tables.length === 0) return <p className="player-data-empty">{empty}</p>;
  return <div className="player-source-tables">{tables.map((table, index) => <SourceTable key={`${table.table_id ?? table.table_role}-${table.schema_id ?? index}`} table={table} fallbackCaption={fallbackCaption} />)}</div>;
}

function SourceTable({ table, fallbackCaption }: { table: PlayerTable; fallbackCaption: string }) {
  const caption = roleLabels[table.table_role] ?? fallbackCaption;
  return <section className="player-source-table">
    <header><h3>{caption}</h3><span>{table.rows.length} filas
      <details className="player-source-table-details"><summary>Ver procedencia</summary><dl><div><dt>Rol original</dt><dd>{table.table_role}</dd></div>{table.source_table_index !== null && <div><dt>Posición original de la tabla</dt><dd>{table.source_table_index + 1}</dd></div>}{table.table_id && <div><dt>ID de tabla</dt><dd>{table.table_id}</dd></div>}{table.schema_id && <div><dt>Esquema de origen</dt><dd>{table.schema_id}</dd></div>}</dl></details>
    </span></header>
    {table.rows.length === 0 ? <p className="player-data-empty">No hay filas observadas en esta tabla.</p> : <div className="player-table-scroll"><table className="player-data-table"><thead><tr>
      {table.columns.map((column, index) => <th key={`${column.source_index ?? index}-${column.label}`} title={[column.group_header, column.title].filter(Boolean).join(" · ") || undefined}>
        {column.label}{!column.source_header?.trim() && <details className="player-column-provenance"><summary aria-label={`Procedencia de ${column.label}`}>i</summary><span>La fuente no incluye un encabezado interpretable. Columna de origen {column.source_index === null ? index + 1 : column.source_index + 1}.{column.title && ` Título original: ${column.title}.`}{column.group_header && ` Grupo: ${column.group_header}.`}{column.data_colid && ` Identificador original: ${column.data_colid}.`}</span></details>}
      </th>)}
      <th>Datos de origen</th>
    </tr></thead><tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>
      {table.columns.map((column, columnIndex) => {
        const cell = row.cells[column.source_index ?? columnIndex];
        return <td key={`${column.source_index ?? columnIndex}-${column.label}`}>{display(cell?.normalized_integer ?? cell?.raw_value)}</td>;
      })}
      <td><SourceFields fields={row.source_fields} /></td>
    </tr>)}</tbody></table></div>}
  </section>;
}

function MatchRecords({ title, records }: { title: string; records: PlayerView["historical_matches"] }) {
  if (records.length === 0) return null;
  return <section className="player-source-table"><header><h3>{title}</h3><span>{records.length} registros</span></header>
    <div className="player-table-scroll"><table className="player-data-table"><thead><tr><th>Fecha</th><th>Competición / jornada</th><th>Partido</th><th>Minutos</th><th>Estado de participación</th><th>Otros campos</th></tr></thead>
      <tbody>{records.map((match, index) => <tr key={`${match.match_id ?? "record"}-${index}`}>
        <td>{match.date ?? match.date_raw ?? "—"}</td><td>{[match.competition, match.round_label, match.season].filter(Boolean).join(" · ") || "—"}</td>
        <td>{match.match_url ? <a href={match.match_url} target="_blank" rel="noreferrer">{match.player_team ?? "—"} – {match.opponent_team ?? "—"} ↗</a> : `${match.player_team ?? "—"} – ${match.opponent_team ?? "—"}`}</td>
        <td>{display(match.minutes)}</td><td>{match.appearance_status ?? match.match_state ?? "—"}</td><td><SourceFields fields={match.source_fields} /></td>
      </tr>)}</tbody></table></div>
  </section>;
}

function SourceFields({ fields }: { fields: Record<string, unknown> }) {
  const entries = Object.entries(fields).filter(([key]) => key !== "player_id");
  if (entries.length === 0) return <>—</>;
  return <details className="player-row-source-fields"><summary>Ver campos ({entries.length})</summary><dl>{entries.map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{display(value)}</dd></div>)}</dl></details>;
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function readableStatus(value: string): string {
  if (statusLabels[value]) return statusLabels[value];
  if (Object.values(statusLabels).includes(value)) return value;
  if (/^[A-Z0-9_]+$/.test(value)) return "Cobertura o estado de captura no certificado como exhaustivo.";
  return value;
}
