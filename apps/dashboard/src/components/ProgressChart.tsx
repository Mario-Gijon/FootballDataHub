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
import type { ProgressRecord, Team } from "../api/contracts";

export type ProgressMetric = "position" | "points" | "goals_for" | "goals_against";

interface ChartPoint {
  matchday: number;
  matchday_date: string | null;
  [key: string]: number | string | null;
}

interface Props {
  teams: Team[];
  records: ProgressRecord[];
}

const metrics: { id: ProgressMetric; label: string }[] = [
  { id: "position", label: "Posición" },
  { id: "points", label: "Puntos" },
  { id: "goals_for", label: "Goles a favor" },
  { id: "goals_against", label: "Goles en contra" },
];

const lineColors = Array.from({ length: 12 }, (_, index) => `var(--chart-${index + 1})`);

export function buildProgressSeriesData(
  records: ProgressRecord[],
  metric: ProgressMetric,
  teamIds: number[],
): ChartPoint[] {
  const selected = new Set(teamIds);
  const points = new Map<number, ChartPoint>();
  for (const record of records) {
    if (!selected.has(record.team_id)) continue;
    const point = points.get(record.matchday) ?? {
      matchday: record.matchday,
      matchday_date: record.matchday_date,
    };
    point[`team_${record.team_id}`] = record[metric];
    points.set(record.matchday, point);
  }
  return [...points.values()].sort((a, b) => a.matchday - b.matchday);
}

export function ProgressChart({ teams, records }: Props) {
  const [metric, setMetric] = useState<ProgressMetric>("position");
  const [selectedIds, setSelectedIds] = useState<number[]>(() => initialSelection(teams));
  const seriesData = useMemo(
    () => buildProgressSeriesData(records, metric, selectedIds),
    [records, metric, selectedIds],
  );
  const selectedTeams = teams.filter((team) => selectedIds.includes(team.team_id));

  function toggleTeam(teamId: number) {
    setSelectedIds((current) => current.includes(teamId)
      ? current.filter((id) => id !== teamId)
      : [...current, teamId]);
  }

  return (
    <section className="progress-card" aria-labelledby="progress-title">
      <div className="section-heading progress-heading">
        <div>
          <div className="section-kicker">EVOLUCIÓN POR JORNADA</div>
          <h2 id="progress-title">Progreso</h2>
        </div>
      </div>

      <div className="chart-toolbar">
        <div className="metric-switcher" role="group" aria-label="Métrica del gráfico">
          {metrics.map((option) => (
            <button
              aria-pressed={metric === option.id}
              className={metric === option.id ? "is-active" : ""}
              key={option.id}
              onClick={() => setMetric(option.id)}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
        <span className="chart-unit">{metric === "position" ? "Puesto en la tabla" : metric === "points" ? "Puntos acumulados" : "Goles acumulados"}</span>
      </div>

      <div className="chart-layout">
        <div className="chart-area" aria-label={`Gráfico de ${metricLabel(metric)} por jornada`}>
          {selectedTeams.length === 0 ? (
            <div className="chart-empty">
              <strong>Elige algún equipo</strong>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%" minHeight={280}>
              <LineChart data={seriesData} margin={{ top: 14, right: 15, left: -10, bottom: 0 }}>
                <CartesianGrid stroke="var(--line-soft)" strokeDasharray="3 5" vertical={false} />
                <XAxis
                  axisLine={false}
                  dataKey="matchday"
                  tickFormatter={(value: number) => `J${value}`}
                  tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                  tickLine={false}
                  tickMargin={12}
                />
                <YAxis
                  axisLine={false}
                  domain={metric === "position" ? [1, 20] : ["auto", "auto"]}
                  orientation="left"
                  reversed={metric === "position"}
                  tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                  tickFormatter={(value: number) => metric === "position" ? `${value}º` : String(value)}
                  tickLine={false}
                  width={39}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border-strong)",
                    borderRadius: 12,
                    color: "var(--text)",
                    fontSize: 12,
                  }}
                  filterNull={false}
                  formatter={(value, name) => [
                    value === null || value === undefined ? "Sin dato" : formatMetric(Number(value), metric),
                    String(name),
                  ]}
                  labelFormatter={(label, payload) => {
                    const point = payload[0]?.payload as ChartPoint | undefined;
                    return point?.matchday_date
                      ? `Jornada ${label} · ${formatDate(point.matchday_date)}`
                      : `Jornada ${label}`;
                  }}
                />
                {selectedTeams.map((team, index) => (
                  <Line
                    activeDot={{ r: 5, strokeWidth: 0 }}
                    connectNulls={false}
                    dataKey={`team_${team.team_id}`}
                    dot={{ r: 2.5, strokeWidth: 0 }}
                    key={team.team_id}
                    name={team.name}
                    stroke={team.team_id === 49 ? "var(--chart-jaen)" : lineColors[index % lineColors.length]}
                    strokeWidth={2.5}
                    type="monotone"
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <aside className="team-selector" aria-label="Equipos del gráfico">
          <div className="team-selector-heading">
            <span>Equipos</span>
            <span>{selectedTeams.length} activos</span>
          </div>
          <div className="team-chip-list">
            {teams.map((team) => {
              const selected = selectedIds.includes(team.team_id);
              const colorIndex = Math.max(0, selectedTeams.findIndex((item) => item.team_id === team.team_id));
              const teamColor = team.team_id === 49 ? "var(--chart-jaen)" : lineColors[colorIndex % lineColors.length];
              return (
                <button
                  aria-pressed={selected}
                  aria-label={`${selected ? "Ocultar" : "Mostrar"} ${team.name} en el gráfico`}
                  className={`team-chip ${selected ? "is-selected" : ""} ${team.team_id === 49 ? "is-jaen" : ""}`}
                  key={team.team_id}
                  onClick={() => toggleTeam(team.team_id)}
                  type="button"
                >
                  <span
                    className="team-chip-mark"
                    style={{ backgroundColor: selected ? teamColor : undefined }}
                  />
                  <span>{team.name}</span>
                </button>
              );
            })}
          </div>
        </aside>
      </div>
    </section>
  );
}

function initialSelection(teams: Team[]): number[] {
  const preferred = [49, 39, 94, 107];
  const available = preferred.filter((id) => teams.some((team) => team.team_id === id));
  return available.length > 0 ? available : teams.slice(0, 4).map((team) => team.team_id);
}

function metricLabel(metric: ProgressMetric): string {
  return metrics.find((option) => option.id === metric)?.label ?? metric;
}

function formatMetric(value: number, metric: ProgressMetric): string {
  return metric === "position" ? `${value}º` : String(value);
}

function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}
