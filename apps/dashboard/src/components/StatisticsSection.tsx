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
import type { Bootstrap, StatisticsBootstrap, Team } from "../api/contracts";

interface StatisticsSectionProps {
  data: StatisticsBootstrap | null;
  teams: Bootstrap["teams"];
  matches: Bootstrap["matches"];
  loadState: "idle" | "loading" | "error" | "ready";
  errorMessage: string;
  onRetry: () => void;
}

type RoundMetric = "goals" | "yellow_cards" | "red_cards";
type RoundPoint = StatisticsBootstrap["statistics"]["rounds"][number];

const metricOptions: { id: RoundMetric; label: string; color: string }[] = [
  { id: "goals", label: "Goles", color: "#ad86d3" },
  { id: "yellow_cards", label: "Tarjetas amarillas", color: "#e2bf79" },
  { id: "red_cards", label: "Tarjetas rojas", color: "#df817e" },
];

const recordLabels = {
  largest_home_win: "Mayor victoria local",
  largest_away_win: "Mayor victoria visitante",
  most_goals: "Partido con más goles",
} as const;

const streakLabels = {
  winning: "Mejor racha ganadora",
  losing: "Peor racha perdedora",
  unbeaten: "Mejor racha sin perder",
  winless: "Peor racha sin ganar",
} as const;

export function StatisticsSection({
  data,
  teams,
  matches,
  loadState,
  errorMessage,
  onRetry,
}: StatisticsSectionProps) {
  if (loadState === "idle" || loadState === "loading") {
    return (
      <section className="statistics-state" role="tabpanel" id="statistics-panel" aria-labelledby="statistics-tab" aria-busy="true">
        <div className="state-card" role="status"><span className="loading-ball" /><h1>Cargando estadísticas…</h1></div>
      </section>
    );
  }
  if (loadState === "error" || !data) {
    return (
      <section className="statistics-state" role="tabpanel" id="statistics-panel" aria-labelledby="statistics-tab">
        <div className="state-card error-card statistics-error" role="alert">
          <span className="state-icon error-icon">!</span>
          <div><span className="section-kicker">ESTADÍSTICAS NO DISPONIBLES</span><h1>No se pudieron cargar los datos</h1><p>{errorMessage}</p></div>
          <button className="primary-button" onClick={onRetry} type="button">Reintentar Estadísticas</button>
        </div>
      </section>
    );
  }
  return <StatisticsDashboard data={data} teams={teams} matches={matches} />;
}

function StatisticsDashboard({
  data,
  teams,
  matches,
}: {
  data: StatisticsBootstrap;
  teams: Bootstrap["teams"];
  matches: Bootstrap["matches"];
}) {
  const [visibleMetrics, setVisibleMetrics] = useState<RoundMetric[]>(["goals", "yellow_cards", "red_cards"]);
  const teamsById = useMemo(() => new Map(teams.map((team) => [team.team_id, team])), [teams]);
  const matchesById = useMemo(() => new Map(matches.map((match) => [match.match_id, match])), [matches]);
  const rounds = data.statistics.rounds;

  function toggleMetric(metric: RoundMetric) {
    setVisibleMetrics((current) => current.includes(metric)
      ? current.filter((item) => item !== metric)
      : [...current, metric]);
  }

  return (
    <section className="statistics-section" role="tabpanel" id="statistics-panel" aria-labelledby="statistics-tab">
      <header className="competition-hero statistics-hero">
        <div><span className="section-kicker">PRIMERA FEDERACIÓN · GRUPO II</span><h1>Estadísticas</h1></div>
        <div className="statistics-meta" aria-label="Procedencia de las capturas">
          <span title={`Captura de Resultados ${data.metadata.match_dataset_capture_id}`}>
            Resultados <time dateTime={data.metadata.match_dataset_captured_at}>{formatCaptureDate(data.metadata.match_dataset_captured_at)}</time>
          </span>
          <span title={`Captura de Estadísticas ${data.metadata.capture_id}`}>
            BDFutbol <time dateTime={data.metadata.captured_at}>{formatCaptureDate(data.metadata.captured_at)}</time>
          </span>
        </div>
      </header>

      <section className="statistics-summary" aria-label="Resultados generales">
        <SummaryCard label="Equipos" value={data.statistics.team_count} />
        <SummaryCard label="Partidos disputados" value={data.statistics.played_matches} />
        <SummaryCard label="Victorias locales" value={data.statistics.home_wins} />
        <SummaryCard label="Victorias visitantes" value={data.statistics.away_wins} />
        <SummaryCard label="Empates" value={data.statistics.draws} />
      </section>

      <section className="statistics-summary statistics-summary-metrics" aria-label="Goles y tarjetas">
        <SummaryCard label="Goles" value={data.statistics.goals} secondary={formatMean(data.statistics.goals_per_match)} />
        <SummaryCard label="Goles por partido" value={formatMean(data.statistics.goals_per_match)} />
        <SummaryCard label="Tarjetas amarillas" value={data.statistics.yellow_cards} secondary={formatMean(data.statistics.yellow_cards_per_match)} />
        <SummaryCard label="Amarillas por partido" value={formatMean(data.statistics.yellow_cards_per_match)} />
        <SummaryCard label="Tarjetas rojas" value={data.statistics.red_cards} secondary={formatMean(data.statistics.red_cards_per_match)} />
        <SummaryCard label="Rojas por partido" value={formatMean(data.statistics.red_cards_per_match)} />
      </section>

      <section className="statistics-panel penalty-panel" aria-labelledby="penalty-title">
        <div className="statistics-panel-heading">
          <div><span className="section-kicker">DATO EXCLUSIVO DE LA FUENTE</span><h2 id="penalty-title">Penaltis</h2></div>
          <span className="source-date">Captura {formatCaptureDate(data.metadata.captured_at)}</span>
        </div>
        <div className="penalty-grid">
          <SummaryCard label="Señalados" value={data.penalties.penalties_awarded} />
          <SummaryCard label="Marcados" value={data.penalties.penalties_scored} />
          <SummaryCard label="Fallados" value={data.penalties.penalties_missed} />
        </div>
        <a className="statistics-source-link" href={data.penalties.source_url} target="_blank" rel="noreferrer">Fuente: Estadísticas de BDFutbol ↗</a>
      </section>

      <section className="statistics-panel" aria-labelledby="records-title">
        <div className="statistics-panel-heading"><div><span className="section-kicker">MARCADORES</span><h2 id="records-title">Récords</h2></div></div>
        <div className="record-grid">
          {data.records.match_records.map((record) => (
            <article className="record-card" key={record.kind}>
              <h3>{recordLabels[record.kind]}</h3>
              {record.matches.map((recordMatch) => {
                const match = matchesById.get(recordMatch.match_id);
                const home = teamsById.get(recordMatch.home_team_id);
                const away = teamsById.get(recordMatch.away_team_id);
                if (!home || !away) return null;
                return (
                  <div className="record-match" key={recordMatch.match_id}>
                    <TeamName team={home} />
                    <a className="record-score" href={match?.source_match_url ?? undefined} target={match?.source_match_url ? "_blank" : undefined} rel={match?.source_match_url ? "noreferrer" : undefined} aria-label={`${home.name} ${recordMatch.home_goals} a ${recordMatch.away_goals} ${away.name}`}>
                      <strong>{recordMatch.home_goals} – {recordMatch.away_goals}</strong><small>J{recordMatch.matchday}</small>
                    </a>
                    <TeamName team={away} />
                    {recordMatch.home_goals !== recordMatch.away_goals && (
                      <span className="record-winner">Ganador: {recordMatch.home_goals > recordMatch.away_goals ? home.name : away.name}</span>
                    )}
                  </div>
                );
              })}
            </article>
          ))}
        </div>
      </section>

      <section className="statistics-panel" aria-labelledby="streaks-title">
        <div className="statistics-panel-heading"><div><span className="section-kicker">SERIES DE RESULTADOS</span><h2 id="streaks-title">Rachas</h2></div></div>
        <div className="streak-grid">
          {(Object.keys(streakLabels) as (keyof typeof streakLabels)[]).map((kind) => {
            const candidates = data.records.streaks.filter((streak) => streak.kind === kind);
            const maximum = Math.max(0, ...candidates.map((streak) => streak.match_count));
            const leaders = candidates.filter((streak) => streak.match_count === maximum);
            return (
              <article className="streak-card" key={kind}>
                <h3>{streakLabels[kind]}</h3>
                {leaders.length ? leaders.map((streak) => {
                  const team = teamsById.get(streak.team_id);
                  return team ? (
                    <div className="streak-leader" key={`${streak.team_id}-${streak.matchday_start}-${streak.matchday_end}`}>
                      <TeamName team={team} />
                      <strong>{streak.match_count} {streak.match_count === 1 ? "partido" : "partidos"}</strong>
                      <span>J{streak.matchday_start}–J{streak.matchday_end}</span>
                    </div>
                  ) : null;
                }) : <span className="statistics-muted">Sin rachas registradas</span>}
              </article>
            );
          })}
        </div>
      </section>

      <section className="statistics-panel statistics-chart-panel" aria-labelledby="round-chart-title">
        <div className="statistics-panel-heading">
          <div><span className="section-kicker">EVOLUCIÓN POR JORNADA</span><h2 id="round-chart-title">Goles y disciplina</h2></div>
          <span className="chart-unit">Totales de cada jornada</span>
        </div>
        <div className="statistics-legend" role="group" aria-label="Series del gráfico">
          {metricOptions.map((metric) => (
            <button
              aria-pressed={visibleMetrics.includes(metric.id)}
              className={visibleMetrics.includes(metric.id) ? "is-active" : ""}
              key={metric.id}
              onClick={() => toggleMetric(metric.id)}
              type="button"
            ><i style={{ backgroundColor: metric.color }} />{metric.label}</button>
          ))}
        </div>
        <div className="statistics-chart" aria-label="Gráfico de goles y tarjetas por jornada">
          <ResponsiveContainer width="100%" height="100%" minHeight={260}>
            <LineChart data={rounds} margin={{ top: 14, right: 15, left: -12, bottom: 0 }}>
              <CartesianGrid stroke="var(--line-soft)" strokeDasharray="3 5" vertical={false} />
              <XAxis dataKey="matchday" axisLine={false} tickLine={false} tickMargin={10} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(value: number) => `J${value}`} />
              <YAxis axisLine={false} tickLine={false} width={34} tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <Tooltip content={<RoundTooltip />} />
              {metricOptions.filter((metric) => visibleMetrics.includes(metric.id)).map((metric) => (
                <Line
                  key={metric.id}
                  dataKey={metric.id}
                  name={metric.label}
                  type="monotone"
                  stroke={metric.color}
                  strokeWidth={2.5}
                  dot={{ r: 3, strokeWidth: 0 }}
                  activeDot={{ r: 5, strokeWidth: 0 }}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <DiscrepancyNotes data={data} rounds={rounds} />
        <div className="chart-coverage-note">Las jornadas futuras o sin resultados conservan sus valores como no disponibles.</div>
      </section>

      <footer className="statistics-provenance">
        <span>Resultados calculados desde la captura {data.metadata.match_dataset_capture_id}.</span>
        <span>Datos exclusivos de la captura de Estadísticas {data.metadata.capture_id}.</span>
        {data.limitations.map((limitation) => <span key={limitation}>{limitation}</span>)}
      </footer>
    </section>
  );
}

function SummaryCard({ label, value, secondary }: { label: string; value: number | string | null; secondary?: string }) {
  return <article className="statistics-summary-card"><span>{label}</span><strong>{formatValue(value)}</strong>{secondary && <small>Media {secondary}</small>}</article>;
}

function TeamName({ team }: { team: Team }) {
  return (
    <span className="statistics-team">
      {team.crest_url ? <img src={team.crest_url} alt="" loading="lazy" /> : <i aria-hidden="true" />}
      <span>{team.name}</span>
    </span>
  );
}

function RoundTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number | null; color?: string; payload?: RoundPoint }>;
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  return (
    <div className="statistics-tooltip">
      <strong>Jornada {label}</strong>
      <small>{point?.played_matches ?? 0} de {point?.scheduled_matches ?? 0} partidos disputados</small>
      {payload.map((item) => (
        <span key={item.name}>
          <i style={{ backgroundColor: item.color }} />{item.name}: {formatValue(item.value ?? null)}
        </span>
      ))}
    </div>
  );
}

function DiscrepancyNotes({ data, rounds }: { data: StatisticsBootstrap; rounds: RoundPoint[] }) {
  const differences = data.reconciliation.round_series.filter(
    (row) => row.statistic === "goals" && row.status !== "match" && row.calculated !== null && row.published !== null,
  );
  if (!differences.length) return null;
  const roundsByNumber = new Map(rounds.map((round) => [round.matchday, round]));
  return (
    <div className="statistics-discrepancies" aria-label="Diferencias con el gráfico publicado de BDFutbol">
      {differences.map((difference) => {
        const round = roundsByNumber.get(difference.matchday);
        return (
          <p key={`${difference.matchday}-${difference.statistic}`}>
            <strong>J{difference.matchday}</strong> ({round?.played_matches ?? difference.played_matches} de {round?.scheduled_matches ?? difference.scheduled_matches} partidos): el gráfico original de BDFutbol publica {formatValue(difference.published)} goles; los resultados registrados suman {formatValue(difference.calculated)}.
          </p>
        );
      })}
    </div>
  );
}

function formatValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 }).format(value);
}

function formatMean(value: number | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
}
