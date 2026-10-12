export type FollowMode = "p" | "t" | "go" | "tot";

export function TeamFollowLegend({ mode }: { mode: FollowMode }) {
  const entries = mode === "p"
    ? [{ className: "follow-legend-minutes", label: "Minutos publicados" }]
    : mode === "t"
      ? [{ className: "follow-legend-minutes", label: "Minutos jugados" }, { className: "follow-legend-yellow", label: "Amarilla verificada" }, { className: "follow-legend-red", label: "Roja verificada" }]
      : mode === "go"
        ? [{ className: "follow-legend-goal", label: "Goles verificados" }]
        : [{ className: "follow-legend-minutes", label: "Minutos jugados" }, { className: "follow-legend-yellow", label: "Amarillas verificadas" }, { className: "follow-legend-red", label: "Rojas verificadas" }, { className: "follow-legend-goal", label: "Goles verificados" }];
  return <ul className="team-follow-legend" aria-label="Leyenda de Seguimiento">
    {entries.map((entry) => <li key={entry.label}><span className={entry.className} aria-hidden="true" />{entry.label}</li>)}
  </ul>;
}
