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
      <p className="player-view-scope">{view.scope_note}{view.coverage && typeof view.coverage.data_scope === "string" ? ` · ${view.coverage.data_scope}` : ""}</p>
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
  const availableFields: Array<[string, unknown]> = profile ? [
    ["Nombre", profile.display_name_raw], ["Nombre completo", profile.full_name_raw],
    ["Nacimiento", profile.birth_date_raw], ["Lugar de nacimiento", profile.birth_place_raw],
    ["País de nacimiento", profile.country_of_birth_raw], ["Demarcación", profile.position_raw],
    ["Altura", profile.height_raw], ["Peso", profile.weight_raw],
  ] : [];
  const fields = availableFields.filter(([, value]) => value !== null && value !== undefined && value !== "");
  return <>
    {fields.length > 0 && <dl className="player-personal-facts">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl>}
    {typeof profile?.career_completeness === "string" && <p className="player-data-note">Cobertura de trayectoria: {profile.career_completeness}. La fuente no certifica que el histórico sea exhaustivo.</p>}
    <DataTables tables={view.tables} empty="La captura no contiene filas de trayectoria estructuradas." />
  </>;
}

function StatisticsView({ view }: { view: PlayerView }) {
  return <DataTables tables={view.tables} empty="La captura no contiene tablas estadísticas estructuradas." />;
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
    {(view.exhaustiveness_status || view.detail_coverage) && <p className="player-data-note">{[view.detail_coverage, `Exhaustividad: ${view.exhaustiveness_status ?? "no determinada"}`].filter(Boolean).join(" · ")}</p>}
    <DataTables tables={view.tables} empty="La captura no contiene resúmenes de partidos estructurados." />
    <MatchRecords title="Partidos con participación" records={played} />
    <MatchRecords title="Convocatorias sin participación" records={summoned} />
    <MatchRecords title="Otros registros de partidos" records={other} />
  </>;
}

function RivalsView({ view }: { view: PlayerView }) {
  return <DataTables tables={view.tables} empty="La captura no contiene tablas de rivales estructuradas." />;
}

function DataTables({ tables, empty }: { tables: PlayerTable[]; empty: string }) {
  if (tables.length === 0) return <p className="player-data-empty">{empty}</p>;
  return <div className="player-source-tables">{tables.map((table, index) => <SourceTable key={`${table.table_id ?? table.table_role}-${table.schema_id ?? index}`} table={table} />)}</div>;
}

function SourceTable({ table }: { table: PlayerTable }) {
  const caption = table.table_role.replaceAll("_", " ");
  return <section className="player-source-table">
    <header><h3>{caption}</h3><span>{table.rows.length} filas{table.source_table_index !== null ? ` · tabla ${table.source_table_index + 1} de origen` : ""}</span></header>
    {table.rows.length === 0 ? <p className="player-data-empty">No hay filas observadas en esta tabla.</p> : <div className="player-table-scroll"><table className="player-data-table"><thead><tr>
      {table.columns.map((column, index) => <th key={`${column.source_index ?? index}-${column.label}`} title={[column.group_header, column.title].filter(Boolean).join(" · ") || undefined}>{column.label}</th>)}
      <th>Otros campos de origen</th>
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
