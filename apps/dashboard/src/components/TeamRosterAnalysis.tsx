import { useMemo, useState } from "react";
import type { TeamRoster } from "../api/contracts";
import {
  matchesRosterSearch,
  PlayerIdentity,
  positionCodeLabel,
  RosterSearch,
  showRosterValue,
  SortableHeader,
  sortRosterRows,
  type SortDirection,
  type SortValue,
} from "./TeamRosterShared";

interface Props {
  roster: TeamRoster;
  query: string;
  onQueryChange: (query: string) => void;
}

const statisticColumns = [
  ["matches_played", "PJ", "Partidos jugados"],
  ["starts", "PT", "Partidos como titular"],
  ["full_matches", "PC", "Partidos completos"],
  ["substitute_appearances", "PS", "Partidos como suplente"],
  ["matches_substituted", "PX", "Partidos en los que fue sustituido"],
  ["unused_substitute_calls", "C", "Convocado sin jugar"],
  ["minutes_played", "MIN", "Minutos jugados"],
  ["yellow_cards", "TA", "Tarjetas amarillas"],
  ["red_cards", "TR", "Tarjetas rojas"],
  ["goals", "G", "Goles"],
  ["minutes_per_goal", "MIN/G", "Minutos por gol"],
  ["penalty_goals", "GP", "Goles de penalti"],
  ["own_goals", "GPP", "Goles en propia puerta"],
  ["goals_conceded", "GE", "Goles encajados"],
  ["team_wins", "PG", "Victorias del equipo"],
  ["team_draws", "PE", "Empates del equipo"],
  ["team_losses", "PP", "Derrotas del equipo"],
] as const;

type StatisticKey = typeof statisticColumns[number][0];
type SortKey = "jersey_number" | "display_name" | "source_position_code" | StatisticKey;

export function TeamRosterAnalysis({ roster, query, onQueryChange }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection } | null>(null);
  const memberships = useMemo(() => new Map(roster.memberships.map((membership) => [membership.player_id, membership])), [roster.memberships]);
  const statistics = useMemo(() => new Map(roster.statistics.map((item) => [item.player_id, item])), [roster.statistics]);
  const filteredPlayers = roster.players.filter((player) => matchesRosterSearch(
    player,
    query,
    [String(memberships.get(player.player_id)?.jersey_number ?? ""), positionCodeLabel(player.source_position_code)],
  ));
  const visiblePlayers = sort
    ? sortRosterRows(filteredPlayers, (player) => sortValue(player, memberships, statistics, sort.key), sort.direction)
    : filteredPlayers;

  function toggleSort(key: SortKey) {
    setSort((current) => ({ key, direction: current?.key === key && current.direction === "ascending" ? "descending" : "ascending" }));
  }

  const sorted = (key: SortKey) => sort?.key === key ? sort.direction : null;

  return <section className="team-roster team-roster-content" aria-label="Estadísticas de la plantilla">
    <section className="team-profile-panel roster-table-panel roster-analysis-panel" aria-labelledby="roster-analysis-title">
      <div className="section-heading team-profile-panel-heading">
        <div><span className="section-kicker">TEMPORADA {formatSeason(roster.metadata.season)}</span><h2 id="roster-analysis-title">Estadísticas de temporada</h2></div>
        <span className="team-summary-source">{visiblePlayers.length}{query.trim() ? ` de ${roster.players.length}` : ""} jugadores</span>
      </div>
      <RosterSearch value={query} onChange={onQueryChange} label="Buscar en estadísticas" placeholder="Nombre, dorsal o demarcación" />
      <div className="roster-table-scroll roster-analysis-scroll" role="region" aria-label="Tabla de estadísticas de jugadores" tabIndex={0}>
        <table className="roster-table roster-analysis-table">
          <thead><tr>
            <SortableHeader label="Jugador" activeDirection={sorted("display_name")} onSort={() => toggleSort("display_name")} />
            <SortableHeader label="Dorsal" activeDirection={sorted("jersey_number")} onSort={() => toggleSort("jersey_number")} />
            <SortableHeader label="Código de demarcación" activeDirection={sorted("source_position_code")} onSort={() => toggleSort("source_position_code")} />
            {statisticColumns.map(([key, label, title]) => <SortableHeader key={key} label={`${label} · ${title}`} activeDirection={sorted(key)} onSort={() => toggleSort(key)} />)}
          </tr></thead>
          <tbody>{visiblePlayers.map((player) => {
            const membership = memberships.get(player.player_id);
            const playerStatistics = statistics.get(player.player_id);
            return <tr data-player-id={player.player_id} key={player.player_id}>
              <td><PlayerIdentity player={player} /></td>
              <td>{showRosterValue(membership?.jersey_number)}</td>
              <td><span title="BDFutbol publica un código numérico; su equivalencia táctica no está verificada.">{positionCodeLabel(player.source_position_code)}</span></td>
              {statisticColumns.map(([key, , title]) => <td key={key} title={title}>{showRosterValue(playerStatistics?.[key])}</td>)}
            </tr>;
          })}
          {visiblePlayers.length === 0 && <tr><td className="roster-no-results" colSpan={3 + statisticColumns.length}>No hay jugadores que coincidan con la búsqueda.</td></tr>}</tbody>
        </table>
      </div>
    </section>
  </section>;
}

function sortValue(
  player: TeamRoster["players"][number],
  memberships: Map<number, TeamRoster["memberships"][number]>,
  statistics: Map<number, TeamRoster["statistics"][number]>,
  key: SortKey,
): SortValue {
  if (key === "jersey_number") return memberships.get(player.player_id)?.jersey_number;
  if (key === "display_name" || key === "source_position_code") return player[key];
  return statistics.get(player.player_id)?.[key];
}

function formatSeason(season: string): string {
  const [start, end] = season.split("-");
  return start && end ? `${start}/${end}` : season;
}
