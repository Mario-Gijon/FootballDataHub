import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ProgressRecord } from "../api/contracts";

interface Props {
  teamName: string;
  records: ProgressRecord[];
}

export function TeamProgressChart({ teamName, records }: Props) {
  if (!records.length) {
    return <p className="team-state">No hay una serie de progreso disponible para este equipo.</p>;
  }

  return (
    <div className="team-match-chart" data-testid="team-progress-chart" data-progress-count={records.length} aria-label={`Posición de ${teamName} por jornada`}>
      <ResponsiveContainer width="100%" height="100%" minHeight={220}>
        <LineChart data={records} margin={{ top: 14, right: 20, left: -8, bottom: 2 }}>
          <CartesianGrid stroke="var(--line-soft)" strokeDasharray="3 5" vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="matchday"
            tickFormatter={(value: number) => `J${value}`}
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            tickLine={false}
            tickMargin={10}
          />
          <YAxis
            axisLine={false}
            domain={[1, 20]}
            reversed
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            tickFormatter={(value: number) => `${value}º`}
            tickLine={false}
            width={39}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface-raised)",
              border: "1px solid var(--border-strong)",
              borderRadius: 10,
              color: "var(--text)",
              fontSize: 12,
            }}
            formatter={(value) => [value === null || value === undefined ? "Sin dato" : `${value}º`, "Posición"]}
            labelFormatter={(label, payload) => {
              const point = payload[0]?.payload as ProgressRecord | undefined;
              return point?.matchday_date
                ? `Jornada ${label} · ${formatDate(point.matchday_date)}`
                : `Jornada ${label}`;
            }}
          />
          <Line
            dataKey="position"
            name={teamName}
            type="monotone"
            stroke="var(--purple-bright)"
            strokeWidth={2.5}
            dot={{ r: 3, strokeWidth: 0, fill: "var(--purple-bright)" }}
            activeDot={{ r: 5, strokeWidth: 0 }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}
