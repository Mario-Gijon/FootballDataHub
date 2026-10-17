import type { TeamFollow } from "../api/contracts";
import { ProfileImage } from "./TeamRosterShared";
import type { FollowMode } from "./TeamFollowLegend";
import { InternalPlayerLink } from "./InternalPlayerLink";

export { type FollowMode };

export function TeamFollowMatrix({ follow, mode, onNavigate }: { follow: TeamFollow; mode: FollowMode; onNavigate: (path: string) => void }) {
  const minutesByCell = new Map(follow.minutes.map((item) => [`${item.player_id}:${item.match_id}`, item]));
  const metricsByCell = new Map<string, TeamFollow["metrics"]>();
  for (const metric of follow.metrics) {
    const key = `${metric.player_id}:${metric.match_id}`;
    metricsByCell.set(key, [...(metricsByCell.get(key) ?? []), metric]);
  }
  const matchByDay = new Map(follow.matches.map((match) => [match.matchday, match]));

  return <div className="team-follow-matrix-scroll" role="region" aria-label="Matriz por jugador y jornada" tabIndex={0}>
    <table className="team-follow-matrix" data-testid="team-follow-matrix">
      <thead><tr>
        <th className="follow-player-heading" scope="col">Jugador</th>
        {follow.matchdays.map((day) => {
          const match = matchByDay.get(day)!;
          return <th key={day} scope="col" title={matchTooltip(follow.team.team_id, match)}>
            <span>Jornada {day}</span>
            <small>{opponentFor(follow.team.team_id, match)}</small>
          </th>;
        })}
      </tr></thead>
      <tbody>{follow.players.map((player) => <tr data-player-id={player.player_id} key={player.player_id}>
        <th className="follow-player-cell" scope="row">
          <InternalPlayerLink className="follow-player-link" playerId={player.player_id} onNavigate={onNavigate}>
            <ProfileImage src={player.photo_url} name={player.display_name} className="follow-player-photo" />
            <span className="follow-player-copy">
            <span>{player.display_name}</span>
            {player.jersey_number !== null && <small>Dorsal {player.jersey_number}</small>}
            </span>
          </InternalPlayerLink>
        </th>
        {follow.matchdays.map((day) => {
          const match = matchByDay.get(day)!;
          const key = `${player.player_id}:${match.match_id}`;
          const minutes = minutesByCell.get(key);
          const metrics = metricsByCell.get(key) ?? [];
          return <td key={match.match_id} title={cellTooltip(follow.team.team_id, match, minutes?.minutes_played, metrics)}>
            <FollowCell mode={mode} minutes={minutes?.minutes_played} hasMinutesRecord={Boolean(minutes)} metrics={metrics} />
          </td>;
        })}
      </tr>)}</tbody>
    </table>
  </div>;
}

function FollowCell({ mode, minutes, hasMinutesRecord, metrics }: {
  mode: FollowMode;
  minutes: number | null | undefined;
  hasMinutesRecord: boolean;
  metrics: TeamFollow["metrics"];
}) {
  const goals = metrics.filter((item) => item.metric === "goals").reduce((total, item) => total + item.value, 0);
  const yellow = metrics.filter((item) => item.metric === "yellow_cards").reduce((total, item) => total + item.value, 0);
  const red = metrics.filter((item) => item.metric === "red_cards").reduce((total, item) => total + item.value, 0);
  if (mode === "go") return goals > 0 ? <span className="follow-goal-value" aria-label={goalQuantity(goals)}>{goals}</span>
    : <span className="follow-cell-empty" aria-label="Sin gol positivo registrado">—</span>;
  if (!hasMinutesRecord) {
    if (mode === "t" && (yellow || red)) return <span className="follow-cell-content">
      {yellow > 0 && <CardMarker color="yellow" count={yellow} />}
      {red > 0 && <CardMarker color="red" count={red} />}
    </span>;
    if (mode === "tot" && (yellow > 0 || red > 0 || goals > 0)) return <span className="follow-cell-content">
      {yellow > 0 && <CardMarker color="yellow" count={yellow} />}
      {red > 0 && <CardMarker color="red" count={red} />}
      {goals > 0 && <span className="follow-goal-marker" aria-label={verifiedGoalsLabel(goals)} title={verifiedGoalsLabel(goals)}>G {goals}</span>}
    </span>;
    return <span className="follow-cell-empty" aria-label="Sin registro de minutos">—</span>;
  }
  const minuteLabel = minutes === null || minutes === undefined ? "—" : String(minutes);
  return <span className="follow-cell-content">
    <span className="follow-minute-value" aria-label={minutes === null || minutes === undefined ? "Minutos ausentes" : `${minutes} minutos`}>{minuteLabel}</span>
    {(mode === "t" || mode === "tot") && yellow > 0 && <CardMarker color="yellow" count={yellow} />}
    {(mode === "t" || mode === "tot") && red > 0 && <CardMarker color="red" count={red} />}
    {mode === "tot" && goals > 0 && <span className="follow-goal-marker" aria-label={verifiedGoalsLabel(goals)} title={verifiedGoalsLabel(goals)}>G {goals}</span>}
  </span>;
}

function cellTooltip(
  teamId: number,
  match: TeamFollow["matches"][number],
  minutes: number | null | undefined,
  metrics: TeamFollow["metrics"],
): string {
  const side = match.home_team_id === teamId ? "Local" : "Visitante";
  const date = match.source_match_date ?? match.matchday_date;
  const result = match.home_goals === null || match.away_goals === null ? "Resultado no disponible" : `${match.home_goals}–${match.away_goals}`;
  const goalCount = metrics.filter((item) => item.metric === "goals").reduce((sum, item) => sum + item.value, 0);
  const yellow = metrics.filter((item) => item.metric === "yellow_cards").reduce((sum, item) => sum + item.value, 0);
  const red = metrics.filter((item) => item.metric === "red_cards").reduce((sum, item) => sum + item.value, 0);
  return [
    `Jornada ${match.matchday} · ${side} vs ${opponentFor(teamId, match)}`,
    date ? `Fecha: ${date}` : "Fecha no publicada",
    `Resultado: ${result}`,
    `Minutos: ${minutes === undefined ? "sin registro" : minutes === null ? "ausentes" : minutes}`,
    ...(yellow > 0 ? [`Tarjeta(s) amarilla(s) verificada(s): ${yellow}`] : []),
    ...(red > 0 ? [`Tarjeta(s) roja(s) verificada(s): ${red}`] : []),
    ...(goalCount > 0 ? [`Goles: ${goalCount}`] : []),
  ].join(" · ");
}

function matchTooltip(teamId: number, match: TeamFollow["matches"][number]): string {
  const side = match.home_team_id === teamId ? "Local" : "Visitante";
  const date = match.source_match_date ?? match.matchday_date;
  const result = match.home_goals === null || match.away_goals === null ? "Resultado no disponible" : `${match.home_goals}–${match.away_goals}`;
  return [
    `Jornada ${match.matchday} · ${side} vs ${opponentFor(teamId, match)}`,
    date ? `Fecha: ${date}` : "Fecha no publicada",
    `Resultado: ${result}`,
  ].join(" · ");
}

function opponentFor(teamId: number, match: TeamFollow["matches"][number]): string {
  return match.home_team_id === teamId ? match.away_team_name : match.home_team_name;
}

function CardMarker({ color, count }: { color: "yellow" | "red"; count: number }) {
  const label = color === "yellow"
    ? `${count} ${count === 1 ? "tarjeta amarilla" : "tarjetas amarillas"} verificada${count === 1 ? "" : "s"}`
    : `${count} ${count === 1 ? "tarjeta roja" : "tarjetas rojas"} verificada${count === 1 ? "" : "s"}`;
  return <span className={color === "yellow" ? "follow-yellow-marker" : "follow-red-marker"} aria-label={label} title={label}>
    {color === "yellow" ? "TA" : "TR"}{count > 1 ? ` ×${count}` : ""}
  </span>;
}

function goalQuantity(value: number): string { return `${value} ${value === 1 ? "gol" : "goles"}`; }
function verifiedGoalsLabel(value: number): string { return `${goalQuantity(value)} ${value === 1 ? "verificado" : "verificados"}`; }
