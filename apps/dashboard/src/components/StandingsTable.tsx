import { useMemo, useState } from "react";
import type { ProgressRecord, PublishedStanding, Team } from "../api/contracts";
import type { CalculatedTable, StandingRow, StandingsFilters } from "../domain/classification/engine";

type SortKey =
  | "position"
  | "team"
  | "points"
  | "matchesPlayed"
  | "wins"
  | "draws"
  | "losses"
  | "goalsFor"
  | "goalsAgainst"
  | "yellowCards"
  | "redCards";

interface Props {
  table: CalculatedTable;
  filters: StandingsFilters;
  progress: ProgressRecord[];
  published: { context: { classification_type: string; matchday: number; postponed_policy: string; range_type: string }; rows: PublishedStanding[] } | null;
}

const columns: { key: SortKey; label: string; className?: string }[] = [
  { key: "position", label: "#", className: "position-column" },
  { key: "team", label: "Equipo", className: "club-column" },
  { key: "points", label: "PTS", className: "points-column" },
  { key: "matchesPlayed", label: "PJ" },
  { key: "wins", label: "PG" },
  { key: "draws", label: "PE" },
  { key: "losses", label: "PP" },
  { key: "goalsFor", label: "GF", className: "secondary-column" },
  { key: "goalsAgainst", label: "GC", className: "secondary-column" },
  { key: "yellowCards", label: "TA", className: "discipline-column" },
  { key: "redCards", label: "TR", className: "discipline-column" },
];

export function StandingsTable({ table, filters, progress, published }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; direction: "asc" | "desc" } | null>(null);
  const publishedById = useMemo(
    () => new Map(published?.rows.map((row) => [row.team_id, row]) ?? []),
    [published],
  );
  const progressByRound = useMemo(() => {
    const index = new Map<string, ProgressRecord>();
    for (const record of progress) index.set(`${record.team_id}:${record.matchday}`, record);
    return index;
  }, [progress]);
  const publishedContextMatches =
    filters.classificationType === "general" &&
    filters.rangeType === "all" &&
    filters.matchdayCap === published?.context.matchday &&
    filters.includePostponed === (published?.context.postponed_policy === "include");

  const displayRows = useMemo(() => {
    if (!sort) return table.rows;
    return [...table.rows].sort((left, right) => {
      const a = sortValue(left, sort.key);
      const b = sortValue(right, sort.key);
      if (a === null && b === null) return left.position - right.position;
      if (a === null) return 1;
      if (b === null) return -1;
      const comparison = typeof a === "string" && typeof b === "string"
        ? a.localeCompare(b, "es")
        : Number(a) - Number(b);
      if (comparison === 0) return left.position - right.position;
      return sort.direction === "asc" ? comparison : -comparison;
    });
  }, [sort, table.rows]);

  function toggleSort(key: SortKey) {
    setSort((current) =>
      current?.key === key
        ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "team" ? "asc" : "desc" },
    );
  }

  const zonesAvailable = publishedContextMatches && displayRows.some(
    (row) => publishedById.get(row.team.team_id)?.sports_zone,
  );

  return (
    <section className="standings-card" aria-labelledby="standings-title">
      <div className="section-heading standings-heading">
        <div>
          <div className="section-kicker">TABLA DE CLASIFICACIÓN</div>
          <h2 id="standings-title">{classificationName(filters.classificationType)}</h2>
        </div>
        <div className="table-meta">
          <span className="computed-badge"><span />Calculada localmente</span>
          <span>{table.matchesCounted} partidos contabilizados</span>
        </div>
      </div>

      {table.warnings.length > 0 && (
        <div className="table-warning" role="status">
          <span className="warning-icon" aria-hidden="true">!</span>
          <span>{table.warnings.join(" ")}</span>
        </div>
      )}

      <div className="standings-scroll">
        <table className="standings-table">
          <thead>
            <tr>
              <th className="movement-column" scope="col" aria-label="Cambio de posición">
                <span title={movementDescription(filters, publishedContextMatches)}>Δ</span>
              </th>
              {columns.map((column) => {
                const selected = sort?.key === column.key;
                return (
                  <th
                    aria-sort={selected ? (sort?.direction === "asc" ? "ascending" : "descending") : "none"}
                    className={column.className ?? "numeric-column"}
                    key={column.key}
                    scope="col"
                  >
                    <button className="sort-button" onClick={() => toggleSort(column.key)} type="button">
                      {column.label}
                      <span className={`sort-indicator ${selected ? "is-visible" : ""}`} aria-hidden="true">
                        {selected ? (sort?.direction === "asc" ? "↑" : "↓") : "↕"}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row) => {
              const sourceRow = publishedById.get(row.team.team_id);
              const zone = publishedContextMatches ? sourceRow?.sports_zone ?? null : null;
              const movement = resolveMovement(
                row.team.team_id,
                filters,
                publishedContextMatches,
                sourceRow,
                progressByRound,
              );
              const isJaen = row.team.team_id === 49;
              return (
                <tr
                  className={`${zone ? `zone-${zone}` : ""} ${isJaen ? "is-jaen" : ""}`.trim()}
                  data-team-id={row.team.team_id}
                  key={row.team.team_id}
                >
                  <td className={`movement-cell movement-${movement?.direction ?? "none"}`}>
                    {movement ? (
                      <span aria-label={movement.label} title={movement.title}>
                        {movement.direction === "up" ? "↑" : movement.direction === "down" ? "↓" : "·"}
                      </span>
                    ) : <span className="muted-dash">—</span>}
                  </td>
                  <td className="position-cell">{row.position}</td>
                  <td className="club-cell">
                    <TeamCrest team={row.team} />
                    {row.team.team_url ? (
                      <a href={row.team.team_url} target="_blank" rel="noreferrer">
                        <span className="club-name">{row.team.name}</span>
                        {isJaen && <span className="jaen-tag">JAÉN</span>}
                      </a>
                    ) : (
                      <span className="club-name">{row.team.name}</span>
                    )}
                  </td>
                  <td className="points-cell">{row.points}</td>
                  <td>{row.matchesPlayed}</td>
                  <td>{row.wins}</td>
                  <td>{row.draws}</td>
                  <td>{row.losses}</td>
                  <td className="secondary-cell">{row.goalsFor}</td>
                  <td className="secondary-cell">{row.goalsAgainst}</td>
                  <td className="discipline-cell">{displayNumber(row.yellowCards)}</td>
                  <td className="discipline-cell">{displayNumber(row.redCards)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="table-footer">
        <span>{sort ? `Orden visual: ${columnLabel(sort.key)} ${sort.direction === "asc" ? "↑" : "↓"}` : "Orden deportivo · posición calculada"}</span>
        {zonesAvailable && <ZoneLegend />}
      </div>
    </section>
  );
}

function TeamCrest({ team }: { team: Team }) {
  const [failed, setFailed] = useState(false);
  if (!team.crest_url || failed) {
    return <span className="team-crest-fallback" aria-hidden="true">{team.name.slice(0, 1)}</span>;
  }
  return (
    <img
      alt=""
      className="team-crest"
      onError={() => setFailed(true)}
      src={team.crest_url}
    />
  );
}

function resolveMovement(
  teamId: number,
  filters: StandingsFilters,
  publishedContextMatches: boolean,
  published: PublishedStanding | undefined,
  progressByRound: Map<string, ProgressRecord>,
): { direction: "up" | "down" | "same"; label: string; title: string } | null {
  if (publishedContextMatches && published?.position_change) {
    const direction = published.position_change;
    return {
      direction,
      label: direction === "same" ? "Sin cambio" : direction === "up" ? "Sube posiciones" : "Baja posiciones",
      title: "Indicador de movimiento publicado por BDFutbol para General J6",
    };
  }
  if (filters.classificationType !== "general" || filters.rangeType !== "all" || filters.matchdayCap <= 1) {
    return null;
  }
  const current = progressByRound.get(`${teamId}:${filters.matchdayCap}`)?.position;
  const previous = progressByRound.get(`${teamId}:${filters.matchdayCap - 1}`)?.position;
  if (current === null || current === undefined || previous === null || previous === undefined) return null;
  const delta = previous - current;
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "same";
  return {
    direction,
    label: delta === 0 ? "Sin cambio" : `${delta > 0 ? "Sube" : "Baja"} ${Math.abs(delta)} ${Math.abs(delta) === 1 ? "puesto" : "puestos"}`,
    title: "Cambio calculado a partir de las series generales de progreso entre jornadas.",
  };
}

function sortValue(row: StandingRow, key: SortKey): number | string | null {
  if (key === "team") return row.team.name;
  const values: Record<Exclude<SortKey, "team">, number | null> = {
    position: row.position,
    points: row.points,
    matchesPlayed: row.matchesPlayed,
    wins: row.wins,
    draws: row.draws,
    losses: row.losses,
    goalsFor: row.goalsFor,
    goalsAgainst: row.goalsAgainst,
    yellowCards: row.yellowCards,
    redCards: row.redCards,
  };
  return values[key];
}

function displayNumber(value: number | null): number | string {
  return value === null ? "—" : value;
}

function classificationName(type: StandingsFilters["classificationType"]): string {
  return type === "general" ? "General" : type === "local" ? "Como local" : "Como visitante";
}

function columnLabel(key: SortKey): string {
  return columns.find((column) => column.key === key)?.label ?? key;
}

function movementDescription(filters: StandingsFilters, sourceContextMatches: boolean): string {
  if (sourceContextMatches) return "Cambio de posición publicado por BDFutbol para General J6.";
  if (filters.classificationType === "general" && filters.rangeType === "all") {
    return "Cambio calculado desde las series generales de progreso.";
  }
  return "Sin indicador de cambio para este filtro.";
}

function ZoneLegend() {
  return (
    <div className="zone-legend" aria-label="Zonas deportivas publicadas para General J6">
      <span><i className="legend-direct" />Ascenso directo</span>
      <span><i className="legend-promotion" />Promoción</span>
      <span><i className="legend-stay" />Permanencia</span>
      <span><i className="legend-relegation" />Descenso</span>
    </div>
  );
}
