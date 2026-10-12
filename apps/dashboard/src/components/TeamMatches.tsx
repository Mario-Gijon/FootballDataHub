import { useMemo, useState, type MouseEvent } from "react";
import type { Bootstrap } from "../api/contracts";
import {
  buildTeamMatchCalendar,
  calculateTeamRecords,
  type TeamMatchEntry,
  type TeamRecord,
} from "../domain/team-matches";
import { teamPath, type CatalogTeam } from "../domain/teams";
import { TeamCrest } from "./TeamCard";
import { TeamProgressChart } from "./TeamProgressChart";

type StatusFilter = "all" | "played" | "unplayed" | "incomplete";
type VenueFilter = "all" | "home" | "away";

interface Props {
  team: CatalogTeam;
  data: Bootstrap;
  onNavigate: (path: string) => void;
}

export function TeamMatches({ team, data, onNavigate }: Props) {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [venueFilter, setVenueFilter] = useState<VenueFilter>("all");
  const calendar = useMemo(
    () => buildTeamMatchCalendar(team.team_id, data.teams, data.matches, data.progress),
    [data, team.team_id],
  );
  const visibleMatches = useMemo(() => calendar.matches.filter(({ match, venue }) =>
    (statusFilter === "all" || match.status === statusFilter) &&
    (venueFilter === "all" || venue === venueFilter),
  ), [calendar.matches, statusFilter, venueFilter]);
  const records = useMemo(() => calculateTeamRecords(calendar.matches), [calendar.matches]);
  const capturedAt = new Intl.DateTimeFormat("es-ES", {
    day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Madrid",
  }).format(new Date(data.metadata.captured_at));

  return (
    <div className="team-matches">
      <header className="team-profile-panel team-matches-header">
        <div>
          <span className="section-kicker">LIGA · PRIMERA FEDERACIÓN · {formatSeason(team.season)}</span>
          <h2>Partidos</h2>
          <p>{calendar.playedCount} disputados · {calendar.pendingCount} pendientes{calendar.incompleteCount ? ` · ${calendar.incompleteCount} incompletos` : ""}</p>
        </div>
        <div className="team-matches-capture" aria-label="Procedencia de los partidos">
          <time dateTime={data.metadata.captured_at}>Datos capturados el {capturedAt}</time>
          <span>Captura {data.metadata.capture_id}</span>
        </div>
      </header>

      <section className="team-profile-panel team-matches-panel" aria-labelledby="team-match-calendar-title">
        <div className="section-heading team-profile-panel-heading">
          <div><span className="section-kicker">CALENDARIO 2026/27</span><h3 id="team-match-calendar-title">Calendario y resultados</h3></div>
          <span className="team-match-count">{visibleMatches.length} de {calendar.matches.length} partidos</span>
        </div>

        <div className="team-match-filters">
          <label>
            <span>Estado</span>
            <select aria-label="Filtrar partidos por estado" value={statusFilter} onChange={(event) => setStatusFilter(event.currentTarget.value as StatusFilter)}>
              <option value="all">Todos</option>
              <option value="played">Disputados</option>
              <option value="unplayed">Pendientes</option>
              <option value="incomplete">Incompletos</option>
            </select>
          </label>
          <label>
            <span>Condición</span>
            <select aria-label="Filtrar partidos por condición" value={venueFilter} onChange={(event) => setVenueFilter(event.currentTarget.value as VenueFilter)}>
              <option value="all">Local y visitante</option>
              <option value="home">Local</option>
              <option value="away">Visitante</option>
            </select>
          </label>
        </div>

        <div className="team-match-table-scroll">
          <table className="team-match-table">
            <thead><tr>
              <th scope="col">Fecha</th><th scope="col">Competición</th><th scope="col">Jornada</th>
              <th scope="col">Local</th><th scope="col">Resultado</th><th scope="col">Visitante</th><th scope="col">Estadio</th>
            </tr></thead>
            <tbody>
              {visibleMatches.map((entry) => <MatchRow key={entry.match.match_id} entry={entry} onNavigate={onNavigate} />)}
              {!visibleMatches.length && <tr><td className="team-match-empty" colSpan={7}>No hay partidos para estos filtros.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="team-profile-panel team-matches-panel" aria-labelledby="team-progress-title">
        <div className="section-heading team-profile-panel-heading">
          <div><span className="section-kicker">POSICIÓN POR JORNADA</span><h3 id="team-progress-title">Progreso en Liga</h3></div>
          <span className="team-match-count">{calendar.progress.length} jornadas disponibles</span>
        </div>
        <TeamProgressChart teamName={team.name} records={calendar.progress} />
      </section>

      <section className="team-profile-panel team-matches-panel" aria-labelledby="team-records-title">
        <div className="section-heading team-profile-panel-heading">
          <div><span className="section-kicker">A PARTIR DE RESULTADOS DISPONIBLES</span><h3 id="team-records-title">Récords</h3></div>
        </div>
        <p className="team-records-method">Cálculos derivados de los encuentros disputados de esta captura.</p>
        <div className="team-record-grid">
          {records.map((record) => <RecordCard key={record.id} record={record} />)}
        </div>
      </section>
    </div>
  );
}

function MatchRow({ entry, onNavigate }: { entry: TeamMatchEntry; onNavigate: (path: string) => void }) {
  const { match, homeTeam, awayTeam } = entry;
  const date = match.source_match_date
    ? { value: match.source_match_date, label: formatDate(match.source_match_date), context: "" }
    : match.matchday_date
      ? { value: match.matchday_date, label: formatDate(match.matchday_date), context: "Fecha de jornada" }
      : null;
  const score = match.status === "played"
    ? `${match.home_goals} : ${match.away_goals}`
    : match.status === "incomplete" ? "Datos incompletos" : "— : —";
  const scoreClass = match.status === "played" ? ` is-${entry.result}` : match.status === "incomplete" ? " is-incomplete" : " is-pending";
  const scoreLabel = match.status === "played"
    ? entry.result === "win" ? "Victoria" : entry.result === "draw" ? "Empate" : "Derrota"
    : match.status === "incomplete" ? "Datos incompletos" : "Pendiente";

  return <tr data-match-id={match.match_id}>
    <td className="team-match-date">
      {date ? <><time dateTime={date.value}>{date.label}</time>{date.context && <small>{date.context}</small>}</> : "—"}
    </td>
    <td>Primera Federación</td>
    <td>J{match.matchday}</td>
    <td><TeamLink team={homeTeam} onNavigate={onNavigate} /></td>
    <td className="team-match-score-cell">
      {match.source_match_url ? (
        <a className={`team-match-score${scoreClass}`} href={match.source_match_url} target="_blank" rel="noreferrer" aria-label={`${scoreLabel}: ${score}`}>
          {score}
        </a>
      ) : <span className={`team-match-score${scoreClass}`} aria-label={`${scoreLabel}: ${score}`}>{score}</span>}
    </td>
    <td><TeamLink team={awayTeam} onNavigate={onNavigate} /></td>
    <td className="team-match-stadium">
      {match.stadium_name && match.stadium_url
        ? <a href={match.stadium_url} target="_blank" rel="noreferrer">{match.stadium_name}</a>
        : match.stadium_name ?? "—"}
    </td>
  </tr>;
}

function TeamLink({ team, onNavigate }: { team: TeamMatchEntry["homeTeam"]; onNavigate: (path: string) => void }) {
  const path = teamPath(team.team_id);
  return <a className="team-match-team" href={path} onClick={(event) => {
    if (!isPlainNavigation(event)) return;
    event.preventDefault();
    onNavigate(path);
  }}>
    <TeamCrest name={team.name} crestUrl={team.crest_url} className="team-match-crest" />
    <span>{team.name}</span>
  </a>;
}

function RecordCard({ record }: { record: TeamRecord }) {
  const value = record.value === null
    ? "—"
    : record.kind === "score" ? `${record.value} ${record.value === 1 ? "gol" : "goles"}` : `${record.value} ${record.value === 1 ? "partido" : "partidos"}`;
  const eventGroups = record.kind === "score" ? [record.matches] : record.runs;
  const eventRows = eventGroups.flatMap((entries, groupIndex) => entries.map((entry, entryIndex) => ({
    entry,
    key: `${entry.match.match_id}:${groupIndex}:${entryIndex}`,
    startsTiedRun: record.kind === "streak" && groupIndex > 0 && entryIndex === 0,
  })));
  return <article className="team-record-card">
    <div className="team-record-card-heading"><h4>{record.label}</h4><strong>{value}</strong></div>
    {eventRows.length ? (
      <ul>
        {eventRows.map(({ entry, key, startsTiedRun }) => <li className={startsTiedRun ? "is-new-run" : undefined} key={key}>
          <span>J{entry.match.matchday}</span>
          <span>{record.kind === "streak" ? streakResultLabel(entry) : ""}</span>
          <RecordMatchLink entry={entry} />
        </li>)}
      </ul>
    ) : <p>Sin datos disponibles</p>}
  </article>;
}

function RecordMatchLink({ entry }: { entry: TeamMatchEntry }) {
  const { match, homeTeam, awayTeam } = entry;
  const opponent = entry.venue === "home" ? awayTeam : homeTeam;
  const homeGoals = match.home_goals;
  const awayGoals = match.away_goals;
  const score = homeGoals === null || awayGoals === null ? "— : —" : `${homeGoals} : ${awayGoals}`;
  const text = `${opponent.name} (${score})`;
  return match.source_match_url
    ? <a href={match.source_match_url} target="_blank" rel="noreferrer">{text}</a>
    : <span>{text}</span>;
}

function streakResultLabel(entry: TeamMatchEntry): string {
  return entry.result === "win" ? "V" : entry.result === "draw" ? "E" : "D";
}

function isPlainNavigation(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function formatDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatSeason(value: string): string {
  return value.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
}
