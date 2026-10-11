import { useMemo } from "react";
import type { Bootstrap } from "../api/contracts";
import { calculateStandings, createClassificationIndexes, type StandingsFilters } from "../domain/classification/engine";
import { TeamCrest } from "./TeamCard";
import type { CatalogTeam } from "../domain/teams";

interface Props {
  team: CatalogTeam;
  data: Bootstrap;
  onNavigate: (path: string) => void;
}

export function TeamOverview({ team, data, onNavigate }: Props) {
  const matchday = data.metadata.last_matchday_with_results ?? 1;
  const sourceContext = data.published_standings?.context;
  const sourceMatchesCalculation = Boolean(
    sourceContext &&
    sourceContext.classification_type === "general" &&
    sourceContext.range_type === "all" &&
    sourceContext.matchday === matchday,
  );
  const filters = useMemo<StandingsFilters>(() => ({
    classificationType: "general",
    matchdayCap: matchday,
    includePostponed: sourceMatchesCalculation ? sourceContext!.postponed_policy === "include" : true,
    rangeType: "all",
    dateStart: null,
    dateEnd: null,
    roundStart: 1,
    roundEnd: matchday,
  }), [matchday, sourceContext, sourceMatchesCalculation]);
  const indexes = useMemo(() => createClassificationIndexes(data.teams, data.matches), [data]);
  const calculated = useMemo(() => calculateStandings(data.teams, data.matches, filters, indexes), [data, filters, indexes]);
  const sourceRow = sourceMatchesCalculation
    ? data.published_standings?.rows.find((row) => row.team_id === team.team_id)
    : undefined;
  const calculatedRow = calculated.rows.find((row) => row.team.team_id === team.team_id);
  const summary = sourceRow ?? (calculatedRow ? {
    position: calculatedRow.position,
    points: calculatedRow.points,
    matches_played: calculatedRow.matchesPlayed,
    wins: calculatedRow.wins,
    draws: calculatedRow.draws,
    losses: calculatedRow.losses,
    goals_for: calculatedRow.goalsFor,
    goals_against: calculatedRow.goalsAgainst,
  } : null);
  const teamById = useMemo(() => new Map(data.teams.map((item) => [item.team_id, item])), [data.teams]);
  const recentMatches = useMemo(() => data.matches
    .filter((match) => match.status === "played" && (match.home_team_id === team.team_id || match.away_team_id === team.team_id))
    .sort((left, right) => (right.source_match_date ?? "").localeCompare(left.source_match_date ?? "") || right.matchday - left.matchday)
    .slice(0, 5), [data.matches, team.team_id]);

  return (
    <main className="dashboard-main team-profile-page">
      <div className="team-profile-actions">
        <a href="/teams" onClick={(event) => { if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onNavigate("/teams"); } }}>← Volver a Equipos</a>
        <a href="/" onClick={(event) => { if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onNavigate("/"); } }}>Competiciones</a>
      </div>

      <header className="team-profile-hero">
        <TeamCrest name={team.name} crestUrl={team.crest_url} className="team-profile-crest" />
        <div className="team-profile-title">
          <span className="section-kicker">GRUPO {team.group === "1" ? "I" : "II"} · TEMPORADA {formatSeason(team.season)}</span>
          <h1>{team.name}</h1>
          <p>Primera Federación</p>
        </div>
        {team.team_url && <a className="source-team-link" href={team.team_url} target="_blank" rel="noreferrer">BDFutbol ↗</a>}
      </header>

      <section className="team-profile-panel" aria-labelledby="team-summary-title">
        <div className="section-heading team-profile-panel-heading">
          <div><span className="section-kicker">JORNADA {matchday}</span><h2 id="team-summary-title">Resumen deportivo</h2></div>
          <span className="team-summary-source">{sourceRow ? "Clasificación publicada" : "Calculada con los resultados disponibles"}</span>
        </div>
        {summary ? (
          <dl className="team-stat-grid">
            {([
              ["Posición", summary.position], ["Puntos", summary.points], ["PJ", summary.matches_played],
              ["PG", summary.wins], ["PE", summary.draws], ["PP", summary.losses],
              ["GF", summary.goals_for], ["GC", summary.goals_against],
            ] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>)}
          </dl>
        ) : <p className="team-state">No hay estadísticas disponibles para este equipo.</p>}
      </section>

      <section className="team-profile-panel" aria-labelledby="team-recent-title">
        <div className="section-heading team-profile-panel-heading"><div><span className="section-kicker">RESULTADOS</span><h2 id="team-recent-title">Últimos partidos</h2></div></div>
        {recentMatches.length ? (
          <ol className="team-recent-list">
            {recentMatches.map((match) => {
              const home = teamById.get(match.home_team_id);
              const away = teamById.get(match.away_team_id);
              if (!home || !away) return null;
              const isHome = match.home_team_id === team.team_id;
              const opponent = isHome ? away : home;
              const ownGoals = isHome ? match.home_goals : match.away_goals;
              const opponentGoals = isHome ? match.away_goals : match.home_goals;
              return (
                <li key={match.match_id}>
                  <span className="team-recent-matchday">J{match.matchday}</span>
                  <span className="team-recent-venue">{isHome ? "Local" : "Visitante"}</span>
                  <TeamCrest name={opponent.name} crestUrl={opponent.crest_url} className="team-recent-crest" />
                  <span className="team-recent-opponent">{opponent.name}</span>
                  <strong className="team-recent-score">{ownGoals}–{opponentGoals}</strong>
                  <span className="team-recent-date">{match.source_match_date ? formatDate(match.source_match_date) : "Fecha no disponible"}</span>
                </li>
              );
            })}
          </ol>
        ) : <p className="team-state">Todavía no hay partidos disputados disponibles para este equipo.</p>}
      </section>
    </main>
  );
}

function formatDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatSeason(value: string): string {
  return value.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
}
