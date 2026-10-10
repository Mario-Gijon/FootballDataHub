import { useMemo, useState } from "react";
import type {
  Referee,
  RefereeBootstrap,
  RefereeScope,
  RefereeStatistics,
} from "../api/contracts";

type LoadState = "idle" | "loading" | "error" | "ready";
type SortField =
  | "name"
  | "age"
  | "birthDate"
  | "birthplace"
  | "province"
  | "matches"
  | "yellow"
  | "red";
type SortState = { field: SortField; direction: "asc" | "desc" } | null;

interface Props {
  data: RefereeBootstrap | null;
  loadState: LoadState;
  errorMessage: string;
  onRetry: () => void;
}

interface JoinedRow {
  referee: Referee;
  statistics: RefereeStatistics;
}

const DEFAULT_SCOPE: RefereeScope = "group2";

export function RefereesSection({ data, loadState, errorMessage, onRetry }: Props) {
  const [scope, setScope] = useState<RefereeScope>(DEFAULT_SCOPE);
  const [sort, setSort] = useState<SortState>(null);

  const rows = useMemo<JoinedRow[]>(() => {
    if (!data) return [];
    const refereesById = new Map(data.referees.map((referee) => [referee.referee_id, referee]));
    const selected = data.statistics
      .filter((item) => item.season === data.metadata.season && item.group_scope === scope)
      .flatMap((statistics) => {
        const referee = refereesById.get(statistics.referee_id);
        return referee ? [{ referee, statistics }] : [];
      });
    if (!sort) return selected.sort((left, right) => left.statistics.published_order - right.statistics.published_order);
    return selected.sort((left, right) => compareRows(left, right, sort));
  }, [data, scope, sort]);

  if (loadState === "idle" || loadState === "loading") {
    return (
      <section className="referees-section" role="tabpanel" id="referees-panel" aria-labelledby="referees-tab">
        <section className="competition-hero referees-hero"><h1>Árbitros</h1></section>
        <div className="referees-state" role="status">{loadState === "loading" ? "Cargando árbitros…" : "Preparando datos de árbitros…"}</div>
      </section>
    );
  }
  if (loadState === "error" || !data) {
    return (
      <section className="referees-section" role="tabpanel" id="referees-panel" aria-labelledby="referees-tab">
        <section className="competition-hero referees-hero"><h1>Árbitros</h1></section>
        <div className="state-card error-card referees-error" role="alert">
          <span className="section-kicker">DATOS NO DISPONIBLES</span>
          <p>{errorMessage || "No se pudieron cargar los datos de Árbitros."}</p>
          <button className="primary-button" onClick={onRetry} type="button">Reintentar</button>
        </div>
      </section>
    );
  }

  const summary = data.availability.scope_counts[scope];
  const season = data.seasons[0];

  return (
    <section className="referees-section" role="tabpanel" id="referees-panel" aria-labelledby="referees-tab">
      <section className="competition-hero referees-hero">
        <h1>Árbitros</h1>
        <div className="dataset-meta" aria-label="Actualización de los datos de árbitros">
          <span>{summary.referee_count} árbitros · {summary.label}</span>
          <time dateTime={data.metadata.captured_at}>Actualizado {formatCaptureDate(data.metadata.captured_at)}</time>
        </div>
      </section>

      <section className="referees-controls" aria-label="Filtros de árbitros">
        <label className="referees-select">
          <span>Temporada</span>
          <select aria-label="Temporada" value={season.season} disabled={data.seasons.length === 1} onChange={() => undefined}>
            {data.seasons.map((option) => <option key={option.season} value={option.season}>{option.label}</option>)}
          </select>
        </label>
        <label className="referees-select">
          <span>Grupo</span>
          <select
            aria-label="Grupo"
            value={scope}
            onChange={(event) => {
              setScope(event.currentTarget.value as RefereeScope);
              setSort(null);
            }}
          >
            {data.groups.map((option) => (
              <option key={option.group_scope} value={option.group_scope}>{option.label}</option>
            ))}
          </select>
        </label>
        <span className="referees-result-count">{rows.length} árbitros</span>
      </section>

      <section className="referee-summary" aria-label={`Resumen estadístico: ${summary.label}`}>
        <SummaryItem label="Árbitros" value={summary.referee_count} />
        <SummaryItem label="Partidos arbitrados" value={summary.matches_officiated} />
        <SummaryItem label="Tarjetas amarillas" value={summary.yellow_cards} />
        <SummaryItem label="Tarjetas rojas" value={summary.red_cards} />
      </section>

      <section className="referees-table-card" aria-label="Tabla de árbitros">
        <div className="referees-scroll" role="region" aria-label="Árbitros y estadísticas por grupo" tabIndex={0}>
          <table className="referees-table">
            <thead>
              <tr>
                <th scope="col" className="referee-order-column">#</th>
                <SortableHeader label="Árbitro" field="name" sort={sort} onSort={setSort} />
                <SortableHeader label="Edad" field="age" sort={sort} onSort={setSort} />
                <SortableHeader label="Fecha de nacimiento" field="birthDate" sort={sort} onSort={setSort} />
                <SortableHeader label="Lugar de nacimiento" field="birthplace" sort={sort} onSort={setSort} />
                <SortableHeader label="Provincia" field="province" sort={sort} onSort={setSort} />
                <SortableHeader label="P" field="matches" title="Partidos arbitrados" sort={sort} onSort={setSort} />
                <SortableHeader label="TA" field="yellow" title="Tarjetas amarillas mostradas en partidos dirigidos" sort={sort} onSort={setSort} />
                <SortableHeader label="TR" field="red" title="Tarjetas rojas mostradas en partidos dirigidos" sort={sort} onSort={setSort} />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ referee, statistics }) => (
                <tr key={`${scope}-${referee.referee_id}`}>
                  <td className="referee-order-cell">{statistics.published_order}</td>
                  <td className="referee-name-cell"><RefereeLink referee={referee} /></td>
                  <td>{formatNullable(referee.age_years)}</td>
                  <td>{formatBirthDate(referee.birth_date)}</td>
                  <td>{formatNullable(referee.birthplace)}</td>
                  <td>{formatNullable(referee.province)}</td>
                  <td className="referee-number-cell">{formatNullable(statistics.matches_officiated)}</td>
                  <td className="referee-number-cell">{formatNullable(statistics.yellow_cards)}</td>
                  <td className="referee-number-cell">{formatNullable(statistics.red_cards)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td className="referees-empty" colSpan={9}>No hay árbitros en este ámbito.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <p className="referees-coverage-note">{data.coverage_note}</p>
    </section>
  );
}

function SummaryItem({ label, value }: { label: string; value: number | null }) {
  return <div className="referee-summary-item"><span>{label}</span><strong>{formatNullable(value)}</strong></div>;
}

function SortableHeader({
  label,
  field,
  sort,
  onSort,
  title,
}: {
  label: string;
  field: SortField;
  sort: SortState;
  onSort: (value: SortState) => void;
  title?: string;
}) {
  const active = sort?.field === field;
  return (
    <th scope="col" aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" title={title} onClick={() => onSort(nextSort(sort, field))}>
        {label}<span aria-hidden="true">{active ? (sort.direction === "asc" ? " ↑" : " ↓") : " ↕"}</span>
      </button>
    </th>
  );
}

function RefereeLink({ referee }: { referee: Referee }) {
  return (
    <a className="referee-link" href={referee.profile_url} target="_blank" rel="noreferrer">
      <RefereePhoto referee={referee} />
      <span>{referee.display_name}</span>
    </a>
  );
}

function RefereePhoto({ referee }: { referee: Referee }) {
  const [failed, setFailed] = useState(false);
  if (!referee.photo_url || failed) {
    return <span className="referee-photo-fallback" aria-hidden="true">{referee.display_name.slice(0, 1)}</span>;
  }
  return <img className="referee-photo" src={referee.photo_url} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

function nextSort(current: SortState, field: SortField): SortState {
  if (current?.field !== field) return { field, direction: "asc" };
  return { field, direction: current.direction === "asc" ? "desc" : "asc" };
}

function compareRows(left: JoinedRow, right: JoinedRow, sort: NonNullable<SortState>): number {
  const leftValue = sortValue(left, sort.field);
  const rightValue = sortValue(right, sort.field);
  if (leftValue === null && rightValue !== null) return 1;
  if (leftValue !== null && rightValue === null) return -1;
  let comparison = 0;
  if (leftValue !== null && rightValue !== null) {
    comparison = typeof leftValue === "string" && typeof rightValue === "string"
      ? leftValue.localeCompare(rightValue, "es", { sensitivity: "base" })
      : Number(leftValue) - Number(rightValue);
    if (sort.direction === "desc") comparison *= -1;
  }
  return comparison || left.referee.referee_id.localeCompare(right.referee.referee_id);
}

function sortValue(row: JoinedRow, field: SortField): string | number | null {
  switch (field) {
    case "name": return row.referee.display_name;
    case "age": return row.referee.age_years;
    case "birthDate": return row.referee.birth_date;
    case "birthplace": return row.referee.birthplace;
    case "province": return row.referee.province;
    case "matches": return row.statistics.matches_officiated;
    case "yellow": return row.statistics.yellow_cards;
    case "red": return row.statistics.red_cards;
  }
}

function formatNullable(value: number | string | null): string {
  return value === null ? "—" : String(value);
}

function formatBirthDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
}
