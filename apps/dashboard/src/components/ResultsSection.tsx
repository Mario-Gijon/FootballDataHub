import { useMemo } from "react";
import type { MatchGenerationRecord, Team } from "../api/contracts";
import { buildResultsMatrix, listResults, type ListedMatch, type MatchOutcome } from "../domain/results";
import { formatMatchDateTime, matchDateTimeAttribute } from "../domain/match-date-time";
import { InternalTeamLink } from "./InternalTeamLink";
import { InternalMatchLink } from "./InternalMatchLink";

export type ResultsMatchday = number | "all";

interface ResultsSectionProps {
  data: ResultsViewData;
  matchday: ResultsMatchday;
  onMatchdayChange: (value: ResultsMatchday) => void;
  onNavigate: (path: string) => void;
  idSuffix?: string;
}

export interface ResultsViewData {
  metadata: {
    group: "I" | "II";
    captured_at: string;
    scheduled_matchdays: number[];
    counts: { teams: number; matches: number; played: number; unplayed: number; incomplete: number };
  };
  teams: Team[];
  matches: MatchGenerationRecord[];
}

export function ResultsSection({ data, matchday, onMatchdayChange, onNavigate, idSuffix = "" }: ResultsSectionProps) {
  const entries = useMemo(
    () => listResults(data.teams, data.matches, matchday === "all" ? null : matchday),
    [data.matches, data.teams, matchday],
  );
  const matrix = useMemo(() => buildResultsMatrix(data.teams, data.matches), [data.matches, data.teams]);
  const groups = useMemo(() => {
    const byMatchday = new Map<number, ListedMatch[]>();
    for (const entry of entries) {
      const group = byMatchday.get(entry.match.matchday) ?? [];
      group.push(entry);
      byMatchday.set(entry.match.matchday, group);
    }
    return [...byMatchday.entries()].sort(([left], [right]) => left - right);
  }, [entries]);
  const playedCount = entries.filter(({ match }) => match.status === "played").length;
  const unplayedCount = entries.filter(({ match }) => match.status === "unplayed").length;

  return (
    <section className="results-section" role="tabpanel" id={`results-panel${idSuffix}`} aria-labelledby={`results-tab${idSuffix}`}>
      <div className="competition-hero results-hero">
        <h1>Resultados</h1>
        <div className="dataset-meta" aria-label="Cobertura de resultados">
          <span>Primera Federación · Grupo {data.metadata.group}</span>
          <span>{playedCount} disputados · {unplayedCount} pendientes</span>
          <time dateTime={data.metadata.captured_at}>Actualizado {formatCaptureDate(data.metadata.captured_at)}</time>
        </div>
      </div>

      <section className="results-controls" aria-label="Filtro de jornada de resultados">
        <label htmlFor={`results-matchday${idSuffix}`}>Jornada de resultados</label>
        <div className="results-round-picker">
          <button
            className="round-step-button"
            type="button"
            aria-label="Jornada anterior"
            disabled={matchday === "all" || matchday <= 1}
            onClick={() => matchday !== "all" && onMatchdayChange(Math.max(1, matchday - 1))}
          >
            ‹
          </button>
          <select
            id={`results-matchday${idSuffix}`}
            value={matchday}
            onChange={(event) => onMatchdayChange(event.target.value === "all" ? "all" : Number(event.target.value))}
          >
            <option value="all">Todas</option>
            {data.metadata.scheduled_matchdays.map((number) => (
              <option key={number} value={number}>Jornada {number}</option>
            ))}
          </select>
          <button
            className="round-step-button"
            type="button"
            aria-label="Jornada siguiente"
            disabled={matchday === "all" || matchday >= 38}
            onClick={() => matchday !== "all" && onMatchdayChange(Math.min(38, matchday + 1))}
          >
            ›
          </button>
        </div>
        <span className="results-match-count">
          {entries.length} {entries.length === 1 ? "partido" : "partidos"}
        </span>
      </section>

      <section className="results-list-card" aria-label="Listado de partidos">
        <div className="results-list-scroll" role="region" aria-label="Partidos por jornada" tabIndex={0}>
          <table className="results-table">
            <thead>
              <tr>
                <th scope="col">Fecha</th>
                <th scope="col">Local</th>
                <th scope="col">Resultado</th>
                <th scope="col">Visitante</th>
                <th scope="col">Estadio</th>
                <th scope="col">Árbitro</th>
              </tr>
            </thead>
            {groups.map(([number, matches]) => (
              <tbody key={number}>
                <tr className="results-round-divider">
                  <th scope="rowgroup" colSpan={6}>
                    <span>Jornada {number}</span>
                    <span>{matches.length} partidos</span>
                  </th>
                </tr>
                {matches.map((entry) => <MatchRow key={entry.match.internal_id} entry={entry} onNavigate={onNavigate} />)}
              </tbody>
            ))}
            {groups.length === 0 && (
              <tbody><tr><td className="results-empty" colSpan={6}>No hay partidos para esta selección.</td></tr></tbody>
            )}
          </table>
        </div>
      </section>

      <section className="results-matrix-card" aria-labelledby="results-matrix-title">
        <div className="section-heading results-matrix-heading">
          <div>
            <h2 id="results-matrix-title">Enfrentamientos</h2>
            <p>La fila identifica al local; la columna, al visitante.</p>
          </div>
          <span className="table-meta">20 × 20 · {data.matches.length} partidos</span>
        </div>
        <div className="matrix-legend" aria-label="Colores del resultado desde la perspectiva local">
          <span><i className="matrix-swatch matrix-home-win" />Victoria local</span>
          <span><i className="matrix-swatch matrix-draw" />Empate</span>
          <span><i className="matrix-swatch matrix-home-loss" />Derrota local</span>
          <span><i className="matrix-swatch matrix-pending" />Pendiente</span>
        </div>
        <div className="results-matrix-scroll" role="region" aria-label="Matriz local por visitante" tabIndex={0}>
          <table className="results-matrix">
            <thead>
              <tr>
                <th className="matrix-corner" scope="col">Local ↓<br />Visitante →</th>
                {matrix.map(({ team }) => <MatrixTeamHeader key={team.team_id} team={team} onNavigate={onNavigate} />)}
              </tr>
            </thead>
            <tbody>
              {matrix.map((row) => (
                <tr key={row.team.team_id} className={row.team.team_id === 49 ? "is-jaen-match" : undefined}>
                  <th className="matrix-row-team" scope="row" title={row.team.name}>
                    <InternalTeamLink className="matrix-row-team-link" teamId={row.team.team_id} onNavigate={onNavigate}>
                      <TeamCrest team={row.team} />
                      <span>{row.team.name}</span>
                    </InternalTeamLink>
                  </th>
                  {row.cells.map((cell) => (
                    <MatrixCell
                      key={`${cell.rowTeamId}:${cell.columnTeamId}`}
                      cell={cell}
                      rowTeam={row.team}
                      columnTeam={data.teams.find((team) => team.team_id === cell.columnTeamId)!}
                      onNavigate={onNavigate}
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

function MatchRow({ entry, onNavigate }: { entry: ListedMatch; onNavigate: (path: string) => void }) {
  const { match, homeTeam, awayTeam } = entry;
  const involvesJaen = homeTeam.team_id === 49 || awayTeam.team_id === 49;
  return (
    <tr
      className={involvesJaen ? "results-match-row is-jaen-match" : "results-match-row"}
    >
      <td className="result-date">{match.source_match_date
        ? <time dateTime={matchDateTimeAttribute(match.source_match_date, match.kickoff_time_local)}>{formatMatchDateTime(match.source_match_date, match.kickoff_time_local, "compact")}</time>
        : match.matchday_date
          ? <time dateTime={matchDateTimeAttribute(match.matchday_date, match.kickoff_time_local)} title="Fecha de jornada">{formatMatchDateTime(match.matchday_date, match.kickoff_time_local, "compact")}</time>
          : <span aria-label="Fecha no disponible">—</span>}</td>
      <td><TeamLink team={homeTeam} onNavigate={onNavigate} /></td>
      <td className="result-score-cell">
        {match.status === "played" && match.home_goals !== null && match.away_goals !== null
          ? <InternalMatchLink className="result-score" internalId={match.internal_id} onNavigate={onNavigate} aria-label={`Abrir ficha: ${homeTeam.name} ${match.home_goals} a ${match.away_goals} ${awayTeam.name}`}>
              {match.home_goals}<span>–</span>{match.away_goals}
            </InternalMatchLink>
          : match.status === "unplayed"
            ? <InternalMatchLink className="result-pending" internalId={match.internal_id} onNavigate={onNavigate} aria-label="Abrir ficha del partido pendiente">Pendiente</InternalMatchLink>
            : <InternalMatchLink className="result-pending" internalId={match.internal_id} onNavigate={onNavigate} aria-label="Abrir ficha con datos incompletos">Datos incompletos</InternalMatchLink>}
      </td>
      <td><TeamLink team={awayTeam} onNavigate={onNavigate} /></td>
      <td>{match.stadium_name ? <SourceLink href={match.stadium_url} label={match.stadium_name} /> : <span className="result-unavailable">—</span>}</td>
      <td>{match.referee_name ? <SourceLink href={match.referee_url} label={match.referee_name} /> : <span className="result-unavailable">—</span>}</td>
    </tr>
  );
}

function MatrixTeamHeader({ team, onNavigate }: { team: Team; onNavigate: (path: string) => void }) {
  return (
    <th className={team.team_id === 49 ? "matrix-column-team is-jaen-column" : "matrix-column-team"} scope="col" title={team.name}>
      <InternalTeamLink className="matrix-column-team-link" teamId={team.team_id} onNavigate={onNavigate}>
        <span>{team.name}</span>
      </InternalTeamLink>
    </th>
  );
}

function MatrixCell({
  cell,
  rowTeam,
  columnTeam,
  onNavigate,
}: {
  cell: ReturnType<typeof buildResultsMatrix>[number]["cells"][number];
  rowTeam: Team;
  columnTeam: Team;
  onNavigate: (path: string) => void;
}) {
  if (cell.state === "diagonal") {
    return <td className="matrix-diagonal" aria-label={`${rowTeam.name}: diagonal`}>·</td>;
  }
  if (cell.state === "missing" || !cell.match) {
    return <td className="matrix-missing" aria-label={`${rowTeam.name} local contra ${columnTeam.name}: fixture ausente`}>—</td>;
  }
  const { match } = cell;
  const label = match.status === "played"
    ? `${rowTeam.name} ${match.home_goals} a ${match.away_goals} ${columnTeam.name}; ${outcomeLabel(cell.outcome)}`
    : `${rowTeam.name} local contra ${columnTeam.name}: ${match.status === "unplayed" ? "pendiente" : "datos incompletos"}`;
  const className = `matrix-result-cell ${matrixOutcomeClass(cell.outcome)} ${match.status === "unplayed" ? "is-pending" : match.status === "incomplete" ? "is-incomplete" : ""}`;
  const score = match.status === "played" ? `${match.home_goals}–${match.away_goals}` : "—";
  return (
    <td className={className} aria-label={label}>
      <InternalMatchLink internalId={match.internal_id} onNavigate={onNavigate} title={label}>{score}</InternalMatchLink>
    </td>
  );
}

function TeamLink({ team, onNavigate }: { team: Team; onNavigate: (path: string) => void }) {
  const content = <><TeamCrest team={team} /><span>{team.name}</span>{team.team_id === 49 && <small>RJ</small>}</>;
  return <InternalTeamLink className="result-team-link" teamId={team.team_id} onNavigate={onNavigate}>{content}</InternalTeamLink>;
}

function TeamCrest({ team }: { team: Team }) {
  return team.crest_url
    ? <img className="result-team-crest" src={team.crest_url} alt="" loading="lazy" />
    : <span className="result-team-crest-fallback" aria-hidden="true">{team.name.slice(0, 1)}</span>;
}

function SourceLink({ href, label }: { href: string | null; label: string }) {
  return href
    ? <a className="result-source-link" href={href} target="_blank" rel="noreferrer">{label}</a>
    : <span className="result-source-link">{label}</span>;
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Madrid",
  }).format(new Date(value));
}

function outcomeLabel(outcome: MatchOutcome | null): string {
  if (outcome === "home_win") return "victoria local";
  if (outcome === "draw") return "empate";
  if (outcome === "home_loss") return "derrota local";
  return "resultado sin clasificar";
}

function matrixOutcomeClass(outcome: MatchOutcome | null): string {
  if (outcome === "home_win") return "is-home-win";
  if (outcome === "draw") return "is-draw";
  if (outcome === "home_loss") return "is-home-loss";
  return "";
}
