import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { loadTeamRoster, type TeamRosterLoadResult } from "../api/client";
import type { Bootstrap } from "../api/contracts";
import { calculateStandings, createClassificationIndexes, type StandingsFilters } from "../domain/classification/engine";
import { TeamCrest } from "./TeamCard";
import { teamPath, teamRosterPath, teamFollowPath, teamTransfersPath, teamMatchesPath, type CatalogTeam } from "../domain/teams";
import { TeamRosterSection } from "./TeamRoster";
import { TeamFollow } from "./TeamFollow";
import { TeamTransfers } from "./TeamTransfers";
import { TeamMatches } from "./TeamMatches";
import { InternalTeamLink } from "./InternalTeamLink";
import { InternalMatchLink } from "./InternalMatchLink";
import { matchInternalId } from "../domain/matches";

interface Props {
  team: CatalogTeam;
  data: Bootstrap;
  teamCatalog: readonly CatalogTeam[];
  activeSection: "summary" | "roster" | "follow" | "transfers" | "matches";
  onNavigate: (path: string) => void;
}

export function TeamOverview({ team, data, teamCatalog, activeSection, onNavigate }: Props) {
  const [rosterResult, setRosterResult] = useState<TeamRosterLoadResult | null>(null);
  const [rosterError, setRosterError] = useState("");
  const [rosterLoading, setRosterLoading] = useState(false);
  const [retryVersion, setRetryVersion] = useState(0);
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

  useEffect(() => {
    if (activeSection !== "roster") return;
    let current = true;
    setRosterLoading(true);
    setRosterError("");
    void loadTeamRoster(team.team_id, team.season)
      .then((result) => { if (current) setRosterResult(result); })
      .catch((error: unknown) => {
        if (current) setRosterError(error instanceof Error ? error.message : "No se pudo cargar la Plantilla.");
      })
      .finally(() => { if (current) setRosterLoading(false); });
    return () => { current = false; };
  }, [activeSection, retryVersion, team.season, team.team_id]);

  function navigateSection(section: "summary" | "roster" | "follow" | "transfers" | "matches") {
    onNavigate(section === "summary" ? teamPath(team.team_id)
      : section === "roster" ? teamRosterPath(team.team_id)
        : section === "follow" ? teamFollowPath(team.team_id)
          : section === "transfers" ? teamTransfersPath(team.team_id) : teamMatchesPath(team.team_id));
  }

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

      <nav className="team-section-tabs" aria-label={`Secciones de ${team.name}`}>
        <a
          aria-current={activeSection === "summary" ? "page" : undefined}
          className={activeSection === "summary" ? "team-section-tab is-active" : "team-section-tab"}
          href={teamPath(team.team_id)}
          onClick={(event) => { if (isPlainNavigation(event)) { event.preventDefault(); navigateSection("summary"); } }}
        >Resumen</a>
        <a
          aria-current={activeSection === "roster" ? "page" : undefined}
          className={activeSection === "roster" ? "team-section-tab is-active" : "team-section-tab"}
          href={teamRosterPath(team.team_id)}
          onClick={(event) => { if (isPlainNavigation(event)) { event.preventDefault(); navigateSection("roster"); } }}
        >Plantilla</a>
        <a
          aria-current={activeSection === "follow" ? "page" : undefined}
          className={activeSection === "follow" ? "team-section-tab is-active" : "team-section-tab"}
          href={teamFollowPath(team.team_id)}
          onClick={(event) => { if (isPlainNavigation(event)) { event.preventDefault(); navigateSection("follow"); } }}
        >Seguimiento</a>
        <a
          aria-current={activeSection === "transfers" ? "page" : undefined}
          className={activeSection === "transfers" ? "team-section-tab is-active" : "team-section-tab"}
          href={teamTransfersPath(team.team_id)}
          onClick={(event) => { if (isPlainNavigation(event)) { event.preventDefault(); navigateSection("transfers"); } }}
        >Traspasos</a>
        <a
          aria-current={activeSection === "matches" ? "page" : undefined}
          className={activeSection === "matches" ? "team-section-tab is-active" : "team-section-tab"}
          href={teamMatchesPath(team.team_id)}
          onClick={(event) => { if (isPlainNavigation(event)) { event.preventDefault(); navigateSection("matches"); } }}
        >Partidos</a>
      </nav>

      {activeSection === "summary" && <>
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
                  <InternalTeamLink className="team-recent-opponent-link" teamId={opponent.team_id} onNavigate={onNavigate}>
                    <TeamCrest name={opponent.name} crestUrl={opponent.crest_url} className="team-recent-crest" />
                    <span className="team-recent-opponent">{opponent.name}</span>
                  </InternalTeamLink>
                  <InternalMatchLink
                    className="team-recent-score"
                    internalId={matchInternalId(team.group, team.season, match.match_id)}
                    onNavigate={onNavigate}
                    aria-label={`Abrir ficha del partido: ${home.name} ${match.home_goals} a ${match.away_goals} ${away.name}`}
                  >{ownGoals}–{opponentGoals}</InternalMatchLink>
                  <span className="team-recent-date">{match.source_match_date ? formatDate(match.source_match_date) : "Fecha no disponible"}</span>
                </li>
              );
            })}
          </ol>
        ) : <p className="team-state">Todavía no hay partidos disputados disponibles para este equipo.</p>}
      </section>
      </>}

      {activeSection === "roster" && rosterLoading && (
        <section className="team-profile-panel roster-state" role="status">
          <span className="section-kicker">PLANTILLA 2026/27</span>
          <h2>Cargando Plantilla…</h2>
        </section>
      )}
      {activeSection === "roster" && !rosterLoading && rosterError && (
        <section className="team-profile-panel roster-state" role="alert">
          <span className="section-kicker">PLANTILLA 2026/27</span>
          <h2>No se pudo cargar la Plantilla</h2>
          <p>{rosterError}</p>
          <button className="primary-button" onClick={() => { setRosterResult(null); setRetryVersion((value) => value + 1); }} type="button">Reintentar</button>
        </section>
      )}
      {activeSection === "roster" && !rosterLoading && !rosterError && rosterResult?.status === "not_captured" && (
        <section className="team-profile-panel roster-state" role="status">
          <span className="section-kicker">PLANTILLA 2026/27</span>
          <h2>Plantilla aún no adquirida</h2>
          <p>La ficha deportiva del equipo está disponible, pero todavía no hay una captura validada de su Plantilla.</p>
        </section>
      )}
      {activeSection === "roster" && !rosterLoading && !rosterError && rosterResult?.status === "available" && (
        <TeamRosterSection key={`${team.team_id}:${rosterResult.roster.metadata.capture_id}`} roster={rosterResult.roster} onNavigate={onNavigate} />
      )}
      {activeSection === "follow" && <TeamFollow key={`${team.team_id}:${team.season}`} teamId={team.team_id} season={team.season} onNavigate={onNavigate} />}
      {activeSection === "transfers" && <TeamTransfers key={`${team.team_id}:${team.season}`} teamId={team.team_id} season={team.season} teams={teamCatalog} onNavigate={onNavigate} />}
      {activeSection === "matches" && <TeamMatches key={`${team.team_id}:${data.metadata.capture_id}`} team={team} data={data} onNavigate={onNavigate} />}
    </main>
  );
}

function isPlainNavigation(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function formatDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatSeason(value: string): string {
  return value.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
}
