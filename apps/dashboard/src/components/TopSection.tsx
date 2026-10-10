import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  TopBootstrap,
  TopCategory,
  TopForeignPlayer,
  TopPlayer,
  TopProgressSeries,
} from "../api/contracts";

interface TopSectionProps {
  data: TopBootstrap | null;
  loadState: "idle" | "loading" | "error" | "ready";
  errorMessage: string;
  onRetry: () => void;
  idSuffix?: string;
}

type ForeignSortField = "player" | "age" | "matches" | "minutes" | "goals" | "yellow" | "red" | "team";
type SortDirection = "asc" | "desc";

const categoryOrder: TopCategory[] = ["goals", "minutes", "yellow_cards", "red_cards", "youngest", "oldest"];
const categoriesWithoutProgress = new Set<TopCategory>(["youngest", "oldest"]);

export function buildTopProgressData(
  matchdays: number[],
  series: TopProgressSeries[],
  selectedPlayerIds: number[],
) {
  const selected = new Set(selectedPlayerIds);
  const chosen = series.filter((item) => selected.has(item.player_id));
  return matchdays.map((matchday) => {
    const point: Record<string, number | null> = { matchday };
    for (const record of chosen) {
      const matchdayPoint = record.points.find((item) => item.matchday === matchday);
      point[`player_${record.player_id}`] = matchdayPoint?.value ?? null;
    }
    return point;
  });
}

export function TopSection({ data, loadState, errorMessage, onRetry, idSuffix = "" }: TopSectionProps) {
  if (loadState === "idle" || loadState === "loading") {
    return (
      <section className="top-load-state" role="tabpanel" id={`top-panel${idSuffix}`} aria-labelledby={`top-tab${idSuffix}`} aria-busy="true">
        <div className="state-card top-inline-state" role="status">
          <span className="loading-ball" />
          <div><span className="section-kicker">DESTACADOS</span><h1>Cargando rankings…</h1></div>
        </div>
      </section>
    );
  }
  if (loadState === "error" || !data) {
    return (
      <section className="top-load-state" role="tabpanel" id={`top-panel${idSuffix}`} aria-labelledby={`top-tab${idSuffix}`}>
        <div className="state-card top-inline-state" role="alert">
          <span className="state-icon error-icon">!</span>
          <div><span className="section-kicker">DESTACADOS NO DISPONIBLE</span><h1>No se pudo cargar esta sección</h1><p>{errorMessage}</p></div>
          <button className="primary-button" onClick={onRetry} type="button">Reintentar Destacados</button>
        </div>
      </section>
    );
  }
  return <TopDashboard data={data} idSuffix={idSuffix} />;
}

function TopDashboard({ data, idSuffix }: { data: TopBootstrap; idSuffix: string }) {
  const [category, setCategory] = useState<TopCategory>("goals");
  const [showAllGoals, setShowAllGoals] = useState(false);
  const [selectedByCategory, setSelectedByCategory] = useState<Record<TopCategory, number[]>>(
    () => defaultPlayerSelections(data.progress),
  );
  const selected = selectedByCategory[category] ?? [];
  const currentOption = data.categories.find((option) => option.category === category)!;
  const rankings = useMemo(
    () => data.rankings.filter((item) => item.category === category).sort((a, b) => a.rank - b.rank),
    [data.rankings, category],
  );
  const playersById = useMemo(() => new Map(data.players.map((player) => [player.player_id, player])), [data.players]);
  const series = useMemo(() => data.progress.filter((item) => item.category === category), [data.progress, category]);
  const chartData = useMemo(
    () => buildTopProgressData(data.availability.matchdays, series, selected),
    [data.availability.matchdays, series, selected],
  );
  const displayedRankings = category === "goals" && !showAllGoals ? rankings.slice(0, 10) : rankings;
  const foreignCountLabel = data.foreigners_summary.source_percentage === null
    ? "—"
    : new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2, minimumFractionDigits: 2 })
      .format(data.foreigners_summary.source_percentage) + " %";

  function togglePlayer(playerId: number) {
    setSelectedByCategory((current) => {
      const active = current[category] ?? [];
      return {
        ...current,
        [category]: active.includes(playerId)
          ? active.filter((id) => id !== playerId)
          : [...active, playerId],
      };
    });
  }

  function changeCategory(next: TopCategory) {
    setCategory(next);
    setShowAllGoals(false);
  }

  return (
    <section className="top-section" role="tabpanel" id={`top-panel${idSuffix}`} aria-labelledby={`top-tab${idSuffix}`}>
      <div className="competition-hero top-hero">
        <h1>Destacados</h1>
        <div className="dataset-meta" aria-label="Actualización de Destacados">
          <span>{data.availability.players} jugadores identificados</span>
          <time dateTime={data.metadata.captured_at}>Actualizado {formatCaptureDate(data.metadata.captured_at)}</time>
        </div>
      </div>

      <section className="top-rankings-card" aria-labelledby="top-rankings-title">
        <div className="section-heading top-rankings-heading">
          <div><span className="section-kicker">RANKINGS INDIVIDUALES</span><h2 id="top-rankings-title">{currentOption.label}</h2></div>
          <span className="table-meta">{currentOption.available_count} registros publicados</span>
        </div>
        <div className="top-category-switcher" role="group" aria-label="Categoría de destacados">
          {categoryOrder.map((item) => {
            const option = data.categories.find((entry) => entry.category === item)!;
            return (
              <button
                key={item}
                type="button"
                className={category === item ? "is-active" : ""}
                aria-pressed={category === item}
                onClick={() => changeCategory(item)}
              >{option.label}</button>
            );
          })}
        </div>
        <p className="top-coverage-note">{category === "goals" ? "Goles incluye los registros disponibles en la tabla y en los datos destacados de BDFutbol." : "Se muestran los diez registros publicados por BDFutbol para esta categoría."}</p>

        <div className={`top-ranking-layout${categoriesWithoutProgress.has(category) ? " no-top-chart" : ""}`}>
          <div className="top-ranking-side">
          <div className="top-ranking-scroll" role="region" aria-label={`Ranking de ${currentOption.label}`} tabIndex={0}>
            <table className="top-ranking-table">
              <thead><tr>
                <th scope="col">#</th><th scope="col">Jugador</th><th scope="col">País</th><th scope="col">Pos.</th>{!categoriesWithoutProgress.has(category) && <th scope="col">Edad</th>}<th scope="col">Club</th><th scope="col">{metricHeading(category)}</th>
                {!categoriesWithoutProgress.has(category) && <th scope="col" className="graph-select-heading">Gráfico</th>}
              </tr></thead>
              <tbody>
                {displayedRankings.map((ranking) => {
                  const player = playersById.get(ranking.player_id);
                  if (!player) return null;
                  const hasSeries = series.some((record) => record.player_id === player.player_id);
                  return (
                    <tr key={`${ranking.category}:${ranking.player_id}`}>
                      <td className="top-rank-number">{ranking.rank}</td>
                      <td><PlayerLink player={player} /></td>
                      <td>{player.nationality ?? <span className="muted-dash">—</span>}</td>
                      <td>{player.position_name ?? <span className="muted-dash">—</span>}</td>
                      {!categoriesWithoutProgress.has(category) && <td>{formatNullable(player.age_years)}</td>}
                      <td><TopTeamLink player={player} /></td>
                      <td className="top-metric-value">{ranking.metric_value}<span>{metricSuffix(category)}</span></td>
                      {!categoriesWithoutProgress.has(category) && <td className="top-graph-toggle-cell">{hasSeries ? <input aria-label={`Incluir a ${player.display_name} en el gráfico`} type="checkbox" checked={selected.includes(player.player_id)} onChange={() => togglePlayer(player.player_id)} /> : <span className="muted-dash" aria-label="Sin serie de evolución">—</span>}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {category === "goals" && rankings.length > 10 && (
            <button className="top-expand-button" type="button" onClick={() => setShowAllGoals((value) => !value)}>
              {showAllGoals ? "Mostrar primeros 10" : `Ver todos (${rankings.length})`}
            </button>
          )}
          </div>
          {!categoriesWithoutProgress.has(category) && (
            <section className="top-chart-panel" aria-label={`Evolución de ${currentOption.label}`}>
              <div className="top-chart-heading"><div><span className="section-kicker">ACUMULADO POR JORNADA</span><h3>Evolución</h3></div><span>{data.availability.matchdays.length} jornadas</span></div>
              <div className="top-chart-area">
                {selected.length === 0 ? <div className="chart-empty"><strong>Selecciona jugadores para comparar</strong></div> : (
                  <ResponsiveContainer width="100%" height="100%" minHeight={275}>
                    <LineChart data={chartData} margin={{ top: 12, right: 18, left: -8, bottom: 0 }}>
                      <CartesianGrid stroke="var(--line-soft)" strokeDasharray="3 5" vertical={false} />
                      <XAxis dataKey="matchday" axisLine={false} tickLine={false} tickMargin={10} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(value: number) => `J${value}`} />
                      <YAxis axisLine={false} tickLine={false} width={43} tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border-strong)", borderRadius: 9, color: "var(--text)", fontSize: 11 }}
                        formatter={(value, name) => [value === null || value === undefined ? "Sin dato" : `${value} ${unitLabel(category)}`, String(name)]}
                        labelFormatter={(value) => `Jornada ${value}`}
                      />
                      {selected.map((playerId) => {
                        const player = playersById.get(playerId);
                        if (!player || !series.some((item) => item.player_id === playerId)) return null;
                        return <Line key={playerId} dataKey={`player_${playerId}`} name={player.display_name} type="linear" stroke={colorForPlayer(playerId)} strokeWidth={2.2} dot={{ r: 2.5 }} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />;
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
              <div className="top-chart-legend" aria-label="Jugadores seleccionados">
                {selected.map((playerId) => {
                  const player = playersById.get(playerId);
                  return player ? <span key={playerId}><i style={{ background: colorForPlayer(playerId) }} />{player.display_name}</span> : null;
                })}
              </div>
            </section>
          )}
        </div>
      </section>

      <ForeignersTable data={data} percentageLabel={foreignCountLabel} />
    </section>
  );
}

function ForeignersTable({ data, percentageLabel }: { data: TopBootstrap; percentageLabel: string }) {
  const [country, setCountry] = useState("");
  const [sort, setSort] = useState<{ field: ForeignSortField; direction: SortDirection }>({ field: "player", direction: "asc" });
  const playersById = useMemo(() => new Map(data.players.map((player) => [player.player_id, player])), [data.players]);
  const filtered = useMemo(() => {
    const source = data.foreigners.flatMap((foreign, index) => {
      const player = playersById.get(foreign.player_id);
      return player && (!country || player.nationality_code === country)
        ? [{ foreign, player, index }]
        : [];
    });
    const textValue = (player: TopPlayer, field: ForeignSortField) => field === "player"
      ? player.full_name ?? player.display_name
      : field === "team" ? player.team_name ?? "" : "";
    const numericValue = (player: TopPlayer, foreign: TopForeignPlayer, field: ForeignSortField): number | null => {
      if (field === "age") return player.age_years;
      if (field === "matches") return foreign.statistics.matches_played;
      if (field === "minutes") return foreign.statistics.minutes_played;
      if (field === "goals") return foreign.statistics.goals;
      if (field === "yellow") return foreign.statistics.yellow_cards;
      if (field === "red") return foreign.statistics.red_cards;
      return null;
    };
    return source.sort((left, right) => {
      const leftValue = numericValue(left.player, left.foreign, sort.field);
      const rightValue = numericValue(right.player, right.foreign, sort.field);
      const stableTieBreak = () => left.player.player_id - right.player.player_id || left.index - right.index;
      let comparison = 0;
      if (leftValue !== null || rightValue !== null) {
        if (leftValue === null && rightValue === null) return stableTieBreak();
        if (leftValue === null) return 1;
        if (rightValue === null) return -1;
        comparison = leftValue - rightValue;
      } else {
        comparison = textValue(left.player, sort.field).localeCompare(textValue(right.player, sort.field), "es", { sensitivity: "base" });
      }
      if (comparison === 0) return stableTieBreak();
      return sort.direction === "asc" ? comparison : -comparison;
    });
  }, [country, data.foreigners, playersById, sort]);

  function sortBy(field: ForeignSortField) {
    setSort((current) => ({ field, direction: current.field === field && current.direction === "asc" ? "desc" : "asc" }));
  }

  const sortableHeader = (label: string, field: ForeignSortField) => (
    <th scope="col" aria-sort={sort.field === field ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => sortBy(field)}>{label}<span aria-hidden="true">{sort.field === field ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}</span></button>
    </th>
  );

  return (
    <section className="foreigners-card" aria-labelledby="foreigners-title">
      <div className="section-heading foreigners-heading">
        <div><span className="section-kicker">PLANTILLA INTERNACIONAL</span><h2 id="foreigners-title">Extranjeros — {data.availability.foreign_players}{data.foreigners_summary.source_count !== data.availability.foreign_players ? ` disponibles · ${data.foreigners_summary.source_count} publicados` : ""} ({percentageLabel})</h2></div>
        <label className="country-filter">País
          <select aria-label="Filtrar extranjeros por país" value={country} onChange={(event) => setCountry(event.target.value)}>
            {data.foreigners_summary.country_options.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
          </select>
        </label>
      </div>
      <div className="foreigners-result-count" aria-live="polite">{filtered.length} {filtered.length === 1 ? "jugador" : "jugadores"}</div>
      <div className="foreigners-scroll" role="region" aria-label="Estadísticas de jugadores extranjeros" tabIndex={0}>
        <table className="foreigners-table">
          <thead><tr>
            {sortableHeader("Jugador", "player")}<th scope="col">País</th><th scope="col">Pos.</th>{sortableHeader("Edad", "age")}{sortableHeader("PJ", "matches")}{sortableHeader("Min", "minutes")}{sortableHeader("Goles", "goals")}{sortableHeader("TA", "yellow")}{sortableHeader("TR", "red")}{sortableHeader("Club", "team")}
          </tr></thead>
          <tbody>{filtered.map(({ foreign, player }) => (
            <tr key={foreign.player_id}>
              <td><PlayerLink player={player} /></td>
              <td>{player.nationality ?? <span className="muted-dash">—</span>}</td>
              <td>{player.position_name ?? <span className="muted-dash">—</span>}</td>
              <td className="foreign-number">{formatNullable(player.age_years)}</td>
              <td className="foreign-number">{formatNullable(foreign.statistics.matches_played)}</td>
              <td className="foreign-number">{formatNullable(foreign.statistics.minutes_played)}</td>
              <td className="foreign-number">{formatNullable(foreign.statistics.goals)}</td>
              <td className="foreign-number">{formatNullable(foreign.statistics.yellow_cards)}</td>
              <td className="foreign-number">{formatNullable(foreign.statistics.red_cards)}</td>
              <td><TopTeamLink player={player} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function defaultPlayerSelections(series: TopProgressSeries[]): Record<TopCategory, number[]> {
  return Object.fromEntries(categoryOrder.map((category) => [
    category,
    series.filter((item) => item.category === category && item.graph_selected_by_default).map((item) => item.player_id),
  ])) as Record<TopCategory, number[]>;
}

function PlayerLink({ player }: { player: TopPlayer }) {
  const label = player.full_name ?? player.display_name;
  return <a className="top-player-link" href={player.profile_url ?? undefined} target={player.profile_url ? "_blank" : undefined} rel={player.profile_url ? "noreferrer" : undefined}>
    {player.photo_url ? <img className="top-player-photo" src={player.photo_url} alt="" loading="lazy" /> : <span className="top-player-photo-fallback" aria-hidden="true">{player.display_name.slice(0, 1)}</span>}
    <span>{label}</span>
  </a>;
}

function TopTeamLink({ player }: { player: TopPlayer }) {
  if (!player.team_name) return <span className="muted-dash" aria-label="Equipo no determinado">—</span>;
  const content = <>{player.crest_url ? <img className="top-team-crest" src={player.crest_url} alt="" loading="lazy" /> : <span className="top-team-crest-fallback" aria-hidden="true">{player.team_name.slice(0, 1)}</span>}<span>{player.team_name}</span></>;
  return player.team_url ? <a className="top-team-link" href={player.team_url} target="_blank" rel="noreferrer">{content}</a> : <span className="top-team-link">{content}</span>;
}

function metricHeading(category: TopCategory): string {
  if (category === "goals") return "Goles";
  if (category === "minutes") return "Minutos";
  if (category === "yellow_cards") return "TA";
  if (category === "red_cards") return "TR";
  return "Edad";
}

function metricSuffix(category: TopCategory): string {
  if (category === "minutes") return " min";
  if (category === "youngest" || category === "oldest") return " años";
  return "";
}

function unitLabel(category: TopCategory): string {
  if (category === "minutes") return "min";
  if (category === "youngest" || category === "oldest") return "años";
  if (category === "goals") return "goles";
  return "tarjetas";
}

function colorForPlayer(playerId: number): string {
  const hue = (playerId * 137.508) % 360;
  return `hsl(${hue.toFixed(1)} 67% 72%)`;
}

function formatNullable(value: number | null): string {
  return value === null ? "—" : String(value);
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Madrid" }).format(new Date(value));
}
