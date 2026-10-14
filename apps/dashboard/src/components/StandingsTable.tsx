import { useMemo, useState } from "react";
import type { PublishedStanding, Team } from "../api/contracts";
import type { CalculatedTable, StandingRow, StandingsFilters } from "../domain/classification/engine";
import { InternalTeamLink } from "./InternalTeamLink";

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
  published: {
    context: {
      classification_type: StandingsFilters["classificationType"];
      matchday: number;
      postponed_policy: "include" | "exclude";
      range_type: StandingsFilters["rangeType"];
    };
    rows: PublishedStanding[];
  } | null;
  onNavigate: (path: string) => void;
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

export function StandingsTable({ table, filters, published, onNavigate }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; direction: "asc" | "desc" } | null>(null);
  const publishedById = useMemo(
    () => new Map(published?.rows.map((row) => [row.team_id, row]) ?? []),
    [published],
  );
  const sourceContextLabel = published
    ? `${classificationName(published.context.classification_type)} J${published.context.matchday}`
    : null;
  const publishedContextMatches =
    published !== null &&
    filters.classificationType === published.context.classification_type &&
    filters.rangeType === published.context.range_type &&
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

  const officialZonesAvailable = publishedContextMatches && table.rows.every(
    (row) => publishedById.get(row.team.team_id)?.sports_zone,
  );

  return (
    <section className="standings-card" aria-labelledby="standings-title">
      <div className="section-heading standings-heading">
        <h2 id="standings-title">{classificationName(filters.classificationType)}</h2>
        <div className="table-meta">
          <span>{table.matchesCounted} partidos</span>
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
                <span title={movementDescription(publishedContextMatches, sourceContextLabel)}>Δ</span>
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
              const visualZone = zoneForPosition(row.position);
              const officialZone = publishedContextMatches ? sourceRow?.sports_zone ?? null : null;
              const movement = resolveMovement(
                publishedContextMatches,
                sourceRow,
                sourceContextLabel,
              );
              const isJaen = row.team.team_id === 49;
              return (
                <tr
                  className={`zone-${visualZone} ${isJaen ? "is-jaen" : ""}`.trim()}
                  data-official-zone={officialZone ?? undefined}
                  data-position={row.position}
                  data-team-id={row.team.team_id}
                  data-visual-zone={visualZone}
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
                    <InternalTeamLink className="club-team-link" teamId={row.team.team_id} onNavigate={onNavigate}>
                      <TeamCrest team={row.team} />
                      <span className="club-name">{row.team.name}</span>
                      {isJaen && <span className="jaen-tag">JAÉN</span>}
                    </InternalTeamLink>
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
        <ZoneLegend official={officialZonesAvailable} />
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
  publishedContextMatches: boolean,
  published: PublishedStanding | undefined,
  sourceContextLabel: string | null,
): { direction: "up" | "down" | "same"; label: string; title: string } | null {
  if (publishedContextMatches && published?.position_change) {
    const direction = published.position_change;
    return {
      direction,
      label: direction === "same" ? "Sin cambio" : direction === "up" ? "Sube posiciones" : "Baja posiciones",
      title: `Indicador de movimiento publicado por BDFutbol para ${sourceContextLabel ?? "esta clasificación"}.`,
    };
  }
  return null;
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

function movementDescription(sourceContextMatches: boolean, sourceContextLabel: string | null): string {
  if (sourceContextMatches) {
    return `Movimiento publicado para ${sourceContextLabel ?? "esta clasificación"}.`;
  }
  return "Movimiento no disponible para este filtro.";
}

type VisualZone = "direct" | "promotion" | "stay" | "relegation";

function zoneForPosition(position: number): VisualZone {
  if (position === 1) return "direct";
  if (position <= 5) return "promotion";
  if (position <= 15) return "stay";
  return "relegation";
}

function ZoneLegend({ official }: { official: boolean }) {
  const suffix = official ? "" : " · ref.";
  return (
    <div className="zone-legend" aria-label={official ? "Zonas deportivas publicadas" : "Zonas de referencia por posición"}>
      <span><i className="legend-direct" />{`Ascenso directo${suffix}`}</span>
      <span><i className="legend-promotion" />{`Promoción ascenso${suffix}`}</span>
      <span><i className="legend-relegation" />{`Descenso${suffix}`}</span>
    </div>
  );
}
