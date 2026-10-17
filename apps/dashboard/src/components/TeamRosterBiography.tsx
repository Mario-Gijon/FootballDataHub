import { useMemo, useState } from "react";
import type { TeamRoster } from "../api/contracts";
import {
  formatSpanishDate,
  matchesRosterSearch,
  PlayerIdentity,
  positionCodeLabel,
  ProfileImage,
  readRosterSort,
  SortableHeader,
  storeRosterSort,
  sortRosterRows,
  type SortDirection,
} from "./TeamRosterShared";

interface Props {
  roster: TeamRoster;
  query: string;
  onQueryChange: (query: string) => void;
  onNavigate: (path: string) => void;
}

type PlayerSortKey = "jersey_number" | "display_name" | "full_name" | "birth_date" | "birthplace" | "birthplace_province" | "source_position_code";
const playerSortKeys: PlayerSortKey[] = ["jersey_number", "display_name", "full_name", "birth_date", "birthplace", "birthplace_province", "source_position_code"];

export function TeamRosterBiography({ roster, query, onQueryChange, onNavigate }: Props) {
  const [sort, setSort] = useState<{ key: PlayerSortKey; direction: SortDirection } | null>(() => readRosterSort(roster.team.team_id, "biography", playerSortKeys));
  const memberships = useMemo(() => new Map(roster.memberships.map((membership) => [membership.player_id, membership])), [roster.memberships]);
  const filteredPlayers = roster.players.filter((player) => matchesRosterSearch(
    player,
    query,
    [String(memberships.get(player.player_id)?.jersey_number ?? ""), positionCodeLabel(player.source_position_code)],
  ));
  const visiblePlayers = sort
    ? sortRosterRows(filteredPlayers, (player) => playerSortValue(player, memberships.get(player.player_id), sort.key), sort.direction)
    : filteredPlayers;

  function toggleSort(key: PlayerSortKey) {
    setSort((current) => {
      const next = { key, direction: current?.key === key && current.direction === "ascending" ? "descending" as const : "ascending" as const };
      storeRosterSort(roster.team.team_id, "biography", next);
      return next;
    });
  }

  const sorted = (key: PlayerSortKey) => sort?.key === key ? sort.direction : null;

  return <section className="team-roster team-roster-content" aria-label="Datos biográficos de la Plantilla">
    <section className="team-profile-panel roster-table-panel roster-biography-panel" aria-labelledby="roster-biography-title">
      <div className="section-heading team-profile-panel-heading">
        <div><span className="section-kicker">TEMPORADA {formatSeason(roster.metadata.season)}</span><h2 id="roster-biography-title">Jugadores</h2></div>
        <span className="team-summary-source">{visiblePlayers.length}{query.trim() ? ` de ${roster.players.length}` : ""} jugadores</span>
      </div>
      <label className="roster-search"><span>Buscar en la plantilla</span>
        <input aria-label="Buscar en la plantilla" onChange={(event) => onQueryChange(event.currentTarget.value)} placeholder="Nombre, dorsal o lugar de nacimiento" value={query} />
      </label>
      <div className="roster-table-scroll roster-biography-scroll" role="region" aria-label="Tabla biográfica de jugadores" tabIndex={0}>
        <table className="roster-table roster-biography-table">
          <thead><tr>
            <SortableHeader label="Jugador" activeDirection={sorted("display_name")} onSort={() => toggleSort("display_name")} />
            <SortableHeader label="Dorsal" activeDirection={sorted("jersey_number")} onSort={() => toggleSort("jersey_number")} />
            <SortableHeader label="Nombre completo" activeDirection={sorted("full_name")} onSort={() => toggleSort("full_name")} />
            <SortableHeader label="Fecha de nacimiento" activeDirection={sorted("birth_date")} onSort={() => toggleSort("birth_date")} />
            <SortableHeader label="Lugar de nacimiento" activeDirection={sorted("birthplace")} onSort={() => toggleSort("birthplace")} />
            <SortableHeader label="Provincia" activeDirection={sorted("birthplace_province")} onSort={() => toggleSort("birthplace_province")} />
            <SortableHeader label="Código de demarcación" activeDirection={sorted("source_position_code")} onSort={() => toggleSort("source_position_code")} />
          </tr></thead>
          <tbody>{visiblePlayers.map((player) => {
            const membership = memberships.get(player.player_id);
            return <tr data-player-id={player.player_id} key={player.player_id}>
              <td><PlayerIdentity player={player} showFullName={false} onNavigate={onNavigate} /></td>
              <td>{membership?.jersey_number ?? "—"}</td>
              <td>{player.full_name ?? "—"}</td>
              <td>{formatSpanishDate(player.birth_date)}</td>
              <td>{player.birthplace ?? "—"}</td>
              <td>{player.birthplace_province ?? "—"}</td>
              <td><span title="BDFutbol publica un código numérico; su equivalencia táctica no está verificada.">{positionCodeLabel(player.source_position_code)}</span></td>
            </tr>;
          })}
          {visiblePlayers.length === 0 && <tr><td className="roster-no-results" colSpan={7}>No hay jugadores que coincidan con la búsqueda.</td></tr>}</tbody>
        </table>
      </div>
    </section>

    <section className="team-profile-panel roster-table-panel roster-biography-panel" aria-labelledby="roster-coach-biography-title">
      <div className="section-heading team-profile-panel-heading">
        <div><span className="section-kicker">TEMPORADA {formatSeason(roster.metadata.season)}</span><h2 id="roster-coach-biography-title">Entrenadores</h2></div>
        <span className="team-summary-source">{roster.coaches.length}</span>
      </div>
      {roster.coaches.length ? <div className="roster-table-scroll roster-coach-bio-scroll" role="region" aria-label="Datos biográficos de entrenadores" tabIndex={0}>
        <table className="roster-table roster-coach-biography-table">
          <thead><tr><th scope="col">Entrenador</th><th scope="col">Nombre completo</th><th scope="col">Fecha de nacimiento</th><th scope="col">Lugar de nacimiento</th><th scope="col">Provincia</th></tr></thead>
          <tbody>{roster.coaches.map((coach) => <tr key={coach.coach_id}>
            <td><span className="roster-player-identity">
              <ProfileImage src={coach.photo_url} name={coach.display_name} className="roster-photo" />
              <span className="roster-player-name">{coach.profile_url ? <a href={coach.profile_url} target="_blank" rel="noreferrer">{coach.display_name}</a> : <strong>{coach.display_name}</strong>}</span>
            </span></td>
            <td>{coach.full_name ?? "—"}</td>
            <td>{formatSpanishDate(coach.birth_date)}</td>
            <td>{coach.birthplace ?? "—"}</td>
            <td>{coach.birthplace_province ?? "—"}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p className="team-state roster-empty-group">La captura no publica entrenadores para esta temporada.</p>}
    </section>
  </section>;
}

function playerSortValue(player: TeamRoster["players"][number], membership: TeamRoster["memberships"][number] | undefined, key: PlayerSortKey) {
  if (key === "jersey_number") return membership?.jersey_number;
  return player[key];
}

function formatSeason(season: string): string {
  const [start, end] = season.split("-");
  return start && end ? `${start}/${end}` : season;
}
