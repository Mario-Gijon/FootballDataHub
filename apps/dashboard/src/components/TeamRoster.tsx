import { useMemo, useState } from "react";
import type { TeamRoster } from "../api/contracts";

type RosterView = "alignment" | "players" | "statistics";
type SortField = "matches_played" | "starts" | "full_matches" | "substitute_appearances" | "minutes_played" | "goals" | "yellow_cards" | "red_cards";

const rosterViews: { id: RosterView; label: string }[] = [
  { id: "alignment", label: "Alineación" },
  { id: "players", label: "Plantilla" },
  { id: "statistics", label: "Estadísticas" },
];

const statisticColumns: { field: SortField; label: string; title: string }[] = [
  { field: "matches_played", label: "PJ", title: "Partidos jugados" },
  { field: "starts", label: "PT", title: "Partidos como titular" },
  { field: "full_matches", label: "PC", title: "Partidos completos" },
  { field: "substitute_appearances", label: "PS", title: "Partidos como suplente" },
  { field: "minutes_played", label: "Min", title: "Minutos jugados" },
  { field: "goals", label: "G", title: "Goles" },
  { field: "yellow_cards", label: "TA", title: "Tarjetas amarillas" },
  { field: "red_cards", label: "TR", title: "Tarjetas rojas" },
];

const extraColumns = [
  ["matches_substituted", "Sust."],
  ["unused_substitute_calls", "Conv. s/j"],
  ["minutes_per_goal", "Min/G"],
  ["penalty_goals", "Pen."],
  ["own_goals", "PP"],
  ["goals_conceded", "GE"],
  ["team_wins", "V equipo"],
  ["team_draws", "E equipo"],
  ["team_losses", "D equipo"],
] as const;

interface Props {
  roster: TeamRoster;
}

export function TeamRosterSection({ roster }: Props) {
  const [view, setView] = useState<RosterView>("alignment");
  const [query, setQuery] = useState("");
  const [sortField, setSortField] = useState<SortField>("minutes_played");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [showExtra, setShowExtra] = useState(false);
  const playersById = useMemo(() => new Map(roster.players.map((player) => [player.player_id, player])), [roster.players]);
  const membershipsById = useMemo(() => new Map(roster.memberships.map((membership) => [membership.player_id, membership])), [roster.memberships]);
  const statisticsById = useMemo(() => new Map(roster.statistics.map((stat) => [stat.player_id, stat])), [roster.statistics]);
  const normalizedQuery = normalize(query);
  const filteredPlayers = roster.players.filter((player) =>
    !normalizedQuery || normalize(`${player.display_name} ${player.full_name ?? ""}`).includes(normalizedQuery),
  );
  const sortedStatistics = [...filteredPlayers].sort((left, right) => {
    const leftValue = statisticsById.get(left.player_id)?.[sortField] ?? null;
    const rightValue = statisticsById.get(right.player_id)?.[sortField] ?? null;
    if (leftValue === null && rightValue !== null) return 1;
    if (leftValue !== null && rightValue === null) return -1;
    if (leftValue !== null && rightValue !== null && leftValue !== rightValue) {
      return sortDirection === "asc" ? leftValue - rightValue : rightValue - leftValue;
    }
    return left.display_name.localeCompare(right.display_name, "es", { sensitivity: "base" });
  });

  function changeSort(field: SortField) {
    if (sortField === field) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else {
      setSortField(field);
      setSortDirection("desc");
    }
  }

  return (
    <section className="team-roster" aria-label="Plantilla del equipo">
      <nav className="team-roster-tabs" aria-label="Vistas de Plantilla">
        {rosterViews.map((item) => (
          <button
            aria-pressed={view === item.id}
            className={view === item.id ? "team-roster-tab is-active" : "team-roster-tab"}
            key={item.id}
            onClick={() => setView(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>

      {view === "alignment" && (
        <div className="team-roster-content">
          {roster.coaches.length > 0 && (
            <section className="team-profile-panel roster-coaches" aria-labelledby="team-coaches-title">
              <div className="section-heading team-profile-panel-heading">
                <div><span className="section-kicker">TEMPORADA 2026/27</span><h2 id="team-coaches-title">Entrenadores publicados</h2></div>
              </div>
              <div className="coach-list">
                {roster.coaches.map((coach) => (
                  <article className="coach-card" key={coach.coach_id}>
                    <ProfileImage src={coach.photo_url} name={coach.display_name} className="coach-photo" />
                    <div className="coach-details">
                      <a href={coach.profile_url ?? undefined} target="_blank" rel="noreferrer">{coach.display_name}</a>
                      {coach.full_name && <span>{coach.full_name}</span>}
                      <div className="coach-metrics">
                        <span>Edad <strong>{showValue(coach.age_years)}</strong></span>
                        <span>Jornadas <strong>{coach.coached_matchdays_source ?? "—"}</strong></span>
                        <span>Partidos <strong>{showValue(coach.matches_managed)}</strong></span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
          {roster.squad_groups.length > 0 ? roster.squad_groups.map((group) => {
            const players = group.player_ids
              .map((playerId) => playersById.get(playerId))
              .filter((player): player is TeamRoster["players"][number] => Boolean(player));
            return (
              <section className="team-profile-panel roster-alignment-group" aria-labelledby={`roster-group-${slug(group.label)}`} key={group.label}>
                <div className="section-heading team-profile-panel-heading">
                  <div><span className="section-kicker">BDFUTBOL</span><h2 id={`roster-group-${slug(group.label)}`}>{group.label}</h2></div>
                  <span className="team-summary-source">{players.length} jugadores</span>
                </div>
                <PlayerCards players={players} membershipsById={membershipsById} statisticsById={statisticsById} />
              </section>
            );
          }) : <div className="team-state roster-empty-group">La fuente no publica categorías de Alineación en esta captura.</div>}
          {roster.warnings.map((warning) => <p className="roster-warning" key={warning}>{warning}</p>)}
        </div>
      )}

      {view === "players" && (
        <section className="team-profile-panel roster-table-panel" aria-labelledby="roster-players-title">
          <div className="section-heading team-profile-panel-heading">
            <div><span className="section-kicker">TEMPORADA 2026/27</span><h2 id="roster-players-title">Jugadores</h2></div>
            <span className="team-summary-source">{filteredPlayers.length} de {roster.players.length}</span>
          </div>
          <label className="roster-search"><span>Buscar jugador</span><input aria-label="Buscar jugador" onChange={(event) => setQuery(event.currentTarget.value)} placeholder="Nombre o apellido" value={query} /></label>
          <div className="roster-table-scroll">
            <table className="roster-table">
              <thead><tr><th>Jugador</th><th>Dorsal</th><th>Edad</th><th>Fecha de nacimiento</th><th>Lugar</th><th>Provincia</th><th>Categoría fuente</th></tr></thead>
              <tbody>
                {filteredPlayers.map((player) => {
                  const membership = membershipsById.get(player.player_id);
                  return <tr key={player.player_id}>
                    <td><PlayerIdentity player={player} photoClass="roster-photo" /></td>
                    <td>{showValue(membership?.jersey_number ?? null)}</td>
                    <td>{showValue(player.age_years)}</td>
                    <td>{formatBirthDate(player.birth_date)}</td>
                    <td>{player.birthplace ?? "—"}</td>
                    <td>{player.birthplace_province ?? "—"}</td>
                    <td>{player.source_position_code === null ? "—" : <span title="Código original de BDFutbol; no se traduce a demarcación.">Código {player.source_position_code}</span>}</td>
                  </tr>;
                })}
                {filteredPlayers.length === 0 && <tr><td className="roster-no-results" colSpan={7}>No hay jugadores que coincidan con la búsqueda.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {view === "statistics" && (
        <section className="team-profile-panel roster-table-panel" aria-labelledby="roster-statistics-title">
          <div className="section-heading team-profile-panel-heading">
            <div><span className="section-kicker">DATOS PUBLICADOS</span><h2 id="roster-statistics-title">Estadísticas de temporada</h2></div>
            <span className="team-summary-source">{filteredPlayers.length} jugadores</span>
          </div>
          <label className="roster-search"><span>Buscar jugador</span><input aria-label="Buscar jugador en estadísticas" onChange={(event) => setQuery(event.currentTarget.value)} placeholder="Nombre o apellido" value={query} /></label>
          <button className="roster-extra-toggle" aria-expanded={showExtra} onClick={() => setShowExtra((value) => !value)} type="button">
            {showExtra ? "Ocultar estadísticas adicionales" : "Ver estadísticas adicionales"}
          </button>
          <div className="roster-table-scroll">
            <table className="roster-table roster-statistics-table">
              <thead><tr>
                <th>Jugador</th>
                {statisticColumns.map((column) => <th key={column.field} title={column.title} aria-sort={sortField === column.field ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}>
                  <button type="button" className="roster-sort-button" onClick={() => changeSort(column.field)}>{column.label}{sortField === column.field ? (sortDirection === "asc" ? " ↑" : " ↓") : ""}</button>
                </th>)}
                {showExtra && extraColumns.map(([field, label]) => <th key={field} title={extraTitle(field)}>{label}</th>)}
              </tr></thead>
              <tbody>
                {sortedStatistics.map((player) => {
                  const stats = statisticsById.get(player.player_id);
                  const membership = membershipsById.get(player.player_id);
                  return <tr key={player.player_id}>
                    <td><span className="roster-number">{showValue(membership?.jersey_number ?? null)}</span><PlayerIdentity player={player} photoClass="roster-photo" /></td>
                    {statisticColumns.map((column) => <td key={column.field}>{showValue(stats?.[column.field] ?? null)}</td>)}
                    {showExtra && extraColumns.map(([field]) => <td key={field}>{showValue(stats?.[field] ?? null)}</td>)}
                  </tr>;
                })}
                {sortedStatistics.length === 0 && <tr><td className="roster-no-results" colSpan={1 + statisticColumns.length + (showExtra ? extraColumns.length : 0)}>No hay jugadores que coincidan con la búsqueda.</td></tr>}
              </tbody>
            </table>
          </div>
          {roster.warnings.map((warning) => <p className="roster-warning" key={warning}>{warning}</p>)}
        </section>
      )}
    </section>
  );
}

function PlayerCards({
  players,
  membershipsById,
  statisticsById,
}: {
  players: TeamRoster["players"];
  membershipsById: Map<number, TeamRoster["memberships"][number]>;
  statisticsById: Map<number, TeamRoster["statistics"][number]>;
}) {
  return <ul className="roster-player-cards">
    {players.map((player) => {
      const membership = membershipsById.get(player.player_id);
      const stats = statisticsById.get(player.player_id);
      return <li className="roster-player-card" key={player.player_id}>
        <PlayerIdentity player={player} photoClass="alignment-player-photo" />
        <span className="alignment-player-number">{showValue(membership?.jersey_number ?? null)}</span>
        <span className="alignment-player-age">{showValue(player.age_years)} años</span>
        <span className="alignment-player-summary">{showValue(stats?.matches_played ?? null)} PJ · {showValue(stats?.minutes_played ?? null)} min · {showValue(stats?.goals ?? null)} G</span>
      </li>;
    })}
    {players.length === 0 && <li className="team-state">La categoría no contiene jugadores publicados.</li>}
  </ul>;
}

function PlayerIdentity({ player, photoClass }: { player: TeamRoster["players"][number]; photoClass: string }) {
  return <span className="roster-player-identity">
    <ProfileImage src={player.photo_url} name={player.display_name} className={photoClass} />
    <span className="roster-player-name">
      {player.profile_url
        ? <a href={player.profile_url} target="_blank" rel="noreferrer">{player.display_name}</a>
        : <strong>{player.display_name}</strong>}
      {player.full_name && player.full_name !== player.display_name && <small>{player.full_name}</small>}
    </span>
  </span>;
}

function ProfileImage({ src, name, className }: { src: string | null; name: string; className: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className={`${className} profile-image-fallback`} aria-label={`Sin fotografía para ${name}`}>{initials(name)}</span>;
  return <img className={className} src={src} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-ES").trim();
}

function showValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

function formatBirthDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function initials(name: string): string {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toLocaleUpperCase("es-ES");
}

function slug(value: string): string {
  return normalize(value).replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function extraTitle(field: string): string {
  const labels: Record<string, string> = {
    matches_substituted: "Partidos sustituido",
    unused_substitute_calls: "Convocatorias sin jugar",
    minutes_per_goal: "Minutos por gol",
    penalty_goals: "Goles de penalti",
    own_goals: "Goles en propia puerta",
    goals_conceded: "Goles encajados",
    team_wins: "Victorias del equipo con el jugador",
    team_draws: "Empates del equipo con el jugador",
    team_losses: "Derrotas del equipo con el jugador",
  };
  return labels[field] ?? field;
}
