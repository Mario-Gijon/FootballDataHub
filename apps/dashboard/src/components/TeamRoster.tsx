import { useMemo, useState } from "react";
import type { TeamRoster } from "../api/contracts";
import { TeamTacticalPitch } from "./TeamTacticalPitch";

const statisticColumns = [
  ["matches_played", "PJ", "Partidos jugados"],
  ["starts", "PT", "Partidos como titular"],
  ["full_matches", "PC", "Partidos completos"],
  ["substitute_appearances", "PS", "Partidos como suplente"],
  ["unused_substitute_calls", "C", "Convocado sin jugar"],
  ["minutes_played", "Min", "Minutos jugados"],
  ["yellow_cards", "TA", "Tarjetas amarillas"],
  ["red_cards", "TR", "Tarjetas rojas"],
  ["goals", "G", "Goles"],
] as const;

const indicatorDefinitions = [
  { code: "played_in_first_division", label: "Ha jugado en 1ª división", color: "first-division" },
  { code: "played_in_second_division", label: "Ha jugado en 2ª división", color: "second-division" },
  { code: "youth_international", label: "Internacional en categorías inferiores", color: "youth-international" },
  { code: "new_signing", label: "Nueva incorporación", color: "new-signing" },
] as const;

interface Props {
  roster: TeamRoster;
}

export function TeamRosterSection({ roster }: Props) {
  const [query, setQuery] = useState("");
  const playersById = useMemo(() => new Map(roster.players.map((player) => [player.player_id, player])), [roster.players]);
  const membershipsById = useMemo(() => new Map(roster.memberships.map((membership) => [membership.player_id, membership])), [roster.memberships]);
  const statisticsById = useMemo(() => new Map(roster.statistics.map((stat) => [stat.player_id, stat])), [roster.statistics]);
  const normalizedQuery = normalize(query);
  const matchesQuery = (player: TeamRoster["players"][number]) =>
    !normalizedQuery || normalize(`${player.display_name} ${player.full_name ?? ""}`).includes(normalizedQuery);
  const observedIndicators = new Set(roster.players.flatMap((player) => player.verified_indicators));

  const renderPlayerGroup = (label: "Titulares" | "Suplentes") => {
    const group = roster.squad_groups.find((item) => item.label === label);
    const players = (group?.player_ids ?? [])
      .map((playerId) => playersById.get(playerId))
      .filter((player): player is TeamRoster["players"][number] => player !== undefined)
      .filter(matchesQuery);

    return (
      <section className="team-profile-panel roster-alignment-group" aria-labelledby={`roster-${label.toLocaleLowerCase("es-ES")}`} key={label}>
        <div className="section-heading team-profile-panel-heading">
          <div><span className="section-kicker">BDFUTBOL · TEMPORADA 2026/27</span><h2 id={`roster-${label.toLocaleLowerCase("es-ES")}`}>{label}</h2></div>
          <span className="team-summary-source">{players.length}{normalizedQuery ? ` de ${group?.player_ids.length ?? 0}` : ""} jugadores</span>
        </div>
        {group ? (
          <div className="roster-table-scroll" role="region" aria-label={`Tabla de ${label}`} tabIndex={0}>
            <table className="roster-table roster-squad-table">
              <thead><tr>
                <th scope="col">#</th>
                <th scope="col">Jugador</th>
                <th scope="col" title="Edad publicada por BDFutbol">Edad</th>
                {statisticColumns.map(([field, heading, title]) => <th scope="col" key={field} title={title}>{heading}</th>)}
              </tr></thead>
              <tbody>
                {players.map((player) => {
                  const membership = membershipsById.get(player.player_id);
                  const statistics = statisticsById.get(player.player_id);
                  return (
                    <tr data-player-id={player.player_id} key={player.player_id}>
                      <td>{showValue(membership?.jersey_number)}</td>
                      <td><PlayerIdentity player={player} indicatorCodes={player.verified_indicators} /></td>
                      <td>{showValue(player.age_years)}</td>
                      {statisticColumns.map(([field]) => <td key={field}>{showValue(statistics?.[field])}</td>)}
                    </tr>
                  );
                })}
                {players.length === 0 && <tr><td className="roster-no-results" colSpan={3 + statisticColumns.length}>
                  {normalizedQuery ? "No hay jugadores que coincidan con la búsqueda." : "La fuente no publica jugadores en esta agrupación."}
                </td></tr>}
              </tbody>
            </table>
          </div>
        ) : <p className="team-state roster-empty-group">La captura no publica la agrupación «{label}».</p>}
      </section>
    );
  };

  return (
    <section className="team-roster team-roster-content" aria-label="Plantilla del equipo">
      <CoachesTable roster={roster} />

      <label className="roster-search"><span>Buscar jugador</span>
        <input aria-label="Buscar jugador en titulares y suplentes" onChange={(event) => setQuery(event.currentTarget.value)} placeholder="Nombre o apellido" value={query} />
      </label>

      {renderPlayerGroup("Titulares")}
      {renderPlayerGroup("Suplentes")}

      <IndicatorLegend observedIndicators={observedIndicators} />
      <TeamTacticalPitch roster={roster} playersById={playersById} />
      {roster.warnings.map((warning) => <p className="roster-warning" key={warning}>{warning}</p>)}
    </section>
  );
}

function CoachesTable({ roster }: Props) {
  return (
    <section className="team-profile-panel roster-coaches" aria-labelledby="team-coaches-title">
      <div className="section-heading team-profile-panel-heading">
        <div><span className="section-kicker">TEMPORADA 2026/27</span><h2 id="team-coaches-title">Entrenadores publicados</h2></div>
        <span className="team-summary-source">{roster.coaches.length}</span>
      </div>
      {roster.coaches.length ? (
        <div className="roster-table-scroll roster-coach-scroll" role="region" aria-label="Tabla de entrenadores" tabIndex={0}>
          <table className="roster-table roster-coach-table">
            <thead><tr><th scope="col">Entrenador</th><th scope="col">Edad</th><th scope="col">Jornadas</th><th scope="col">Partidos</th><th scope="col">TA</th><th scope="col">TR</th></tr></thead>
            <tbody>{roster.coaches.map((coach) => <tr key={coach.coach_id}>
              <td>
                <span className="roster-player-identity">
                  <ProfileImage src={coach.photo_url} name={coach.display_name} className="roster-photo" />
                  <span className="roster-player-name">
                    {coach.profile_url ? <a href={coach.profile_url} target="_blank" rel="noreferrer">{coach.display_name}</a> : <strong>{coach.display_name}</strong>}
                    {coach.full_name && coach.full_name !== coach.display_name && <small>{coach.full_name}</small>}
                  </span>
                </span>
              </td>
              <td>{showValue(coach.age_years)}</td>
              <td>{coach.coached_matchdays_source ?? "—"}</td>
              <td>{showValue(coach.matches_managed)}</td>
              <td>{showValue(coach.yellow_cards)}</td>
              <td>{showValue(coach.red_cards)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      ) : <p className="team-state roster-empty-group">La captura no publica entrenadores para esta temporada.</p>}
    </section>
  );
}

function PlayerIdentity({ player, indicatorCodes }: { player: TeamRoster["players"][number]; indicatorCodes: string[] }) {
  return <span className="roster-player-identity">
    <ProfileImage src={player.photo_url} name={player.display_name} className="roster-photo" />
    <span className="roster-player-name">
      {player.profile_url ? <a href={player.profile_url} target="_blank" rel="noreferrer">{player.display_name}</a> : <strong>{player.display_name}</strong>}
      {player.full_name && player.full_name !== player.display_name && <small>{player.full_name}</small>}
      {indicatorCodes.length > 0 && <span className="roster-player-indicators" aria-label="Indicadores publicados por BDFutbol">
        {indicatorDefinitions.filter((item) => indicatorCodes.includes(item.code)).map((item) => <span
          aria-label={item.label}
          className={`roster-indicator-dot is-${item.color}`}
          key={item.code}
          title={item.label}
        />)}
      </span>}
    </span>
  </span>;
}

function IndicatorLegend({ observedIndicators }: { observedIndicators: Set<string> }) {
  return (
    <section className="team-profile-panel roster-indicator-legend" aria-labelledby="roster-indicator-title">
      <div className="section-heading team-profile-panel-heading"><div><span className="section-kicker">BDFUTBOL</span><h2 id="roster-indicator-title">Indicadores</h2></div></div>
      <ul>{indicatorDefinitions.filter((item) => observedIndicators.has(item.code)).map((item) => <li key={item.code}>
        <span aria-hidden="true" className={`roster-indicator-dot is-${item.color}`} />{item.label}
      </li>)}</ul>
    </section>
  );
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

function initials(name: string): string {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toLocaleUpperCase("es-ES");
}
