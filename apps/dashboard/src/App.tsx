import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  loadGroupBootstrap,
  loadGroupRefereesBootstrap,
  loadGroupStatisticsBootstrap,
  loadGroupTopBootstrap,
  loadMatchResultsBootstrap,
  type CompetitionGroup,
} from "./api/client";
import type {
  Bootstrap,
  Match,
  RefereeBootstrap,
  StatisticsBootstrap,
  TopBootstrap,
  MatchResultsBootstrap,
} from "./api/contracts";
import { MainNavigation } from "./components/MainNavigation";
import { TeamsDirectory } from "./components/TeamsDirectory";
import { TeamOverview } from "./components/TeamOverview";
const PlayersPage = lazy(() => import("./components/PlayersPage").then((module) => ({ default: module.PlayersPage })));
import { ClassificationControls } from "./components/ClassificationControls";
const ProgressChart = lazy(() => import("./components/ProgressChart").then((module) => ({ default: module.ProgressChart })));
import { StandingsTable } from "./components/StandingsTable";
import { ResultsSection, type ResultsMatchday, type ResultsViewData } from "./components/ResultsSection";
import { RefereesSection } from "./components/RefereesSection";
const StatisticsSection = lazy(() => import("./components/StatisticsSection").then((module) => ({ default: module.StatisticsSection })));
const TopSection = lazy(() => import("./components/TopSection").then((module) => ({ default: module.TopSection })));
import {
  calculateStandings,
  createClassificationIndexes,
  type StandingsFilters,
} from "./domain/classification/engine";
import { buildTeamCatalog, findTeamGroup, type CatalogTeam } from "./domain/teams";
import type { LoadState } from "./domain/teams-ui";

type Section = "standings" | "results" | "top" | "referees" | "statistics";
type GroupValues<T> = Record<CompetitionGroup, T>;

const groups: CompetitionGroup[] = ["1", "2"];
const sectionTabs: { id: Section; label: string }[] = [
  { id: "standings", label: "Clasificación" },
  { id: "results", label: "Resultados" },
  { id: "top", label: "Destacados" },
  { id: "referees", label: "Árbitros" },
  { id: "statistics", label: "Estadísticas" },
];

export default function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const route = parseRoute(pathname);
  const [activeGroup, setActiveGroup] = useState<CompetitionGroup>("2");
  const [activeSection, setActiveSection] = useState<Section>("standings");
  const [baseData, setBaseData] = useState<GroupValues<Bootstrap | null>>({ "1": null, "2": null });
  const [baseState, setBaseState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [baseErrors, setBaseErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [visitedCompetitionGroups, setVisitedCompetitionGroups] = useState(() => new Set<CompetitionGroup>());
  const [topData, setTopData] = useState<GroupValues<TopBootstrap | null>>({ "1": null, "2": null });
  const [topState, setTopState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [topErrors, setTopErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [statisticsData, setStatisticsData] = useState<GroupValues<StatisticsBootstrap | null>>({ "1": null, "2": null });
  const [statisticsState, setStatisticsState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [statisticsErrors, setStatisticsErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [refereesData, setRefereesData] = useState<GroupValues<RefereeBootstrap | null>>({ "1": null, "2": null });
  const [refereesState, setRefereesState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [refereesErrors, setRefereesErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [matchResultsData, setMatchResultsData] = useState<MatchResultsBootstrap | null>(null);
  const [matchResultsState, setMatchResultsState] = useState<LoadState>("idle");
  const [matchResultsError, setMatchResultsError] = useState("");
  const [matchResultsRequestVersion, setMatchResultsRequestVersion] = useState(0);
  const pending = useRef(new Set<string>());
  const navigate = useCallback((path: string) => {
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setPathname(path);
    if (window.scrollY > 0) window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (route.kind !== "competitions") return;
    setVisitedCompetitionGroups((current) => {
      if (current.has(activeGroup)) return current;
      return new Set(current).add(activeGroup);
    });
  }, [activeGroup, route.kind]);

  useEffect(() => {
    const groupsToLoad = route.kind === "competitions"
      ? [activeGroup]
      : route.kind === "teams" || route.kind === "team"
        ? groups
        : [];
    for (const group of groupsToLoad) {
      if (baseData[group] || baseState[group] !== "idle") continue;
      const key = `${group}:classification`;
      if (pending.current.has(key)) continue;
      pending.current.add(key);
      setBaseState((current) => ({ ...current, [group]: "loading" }));
      setBaseErrors((current) => ({ ...current, [group]: "" }));
      void loadGroupBootstrap(group)
        .then((payload) => {
          // Each response is cached under the requested group, so late results
          // never replace the currently visible competition context.
          setBaseData((current) => ({ ...current, [group]: payload }));
          setBaseState((current) => ({ ...current, [group]: "ready" }));
        })
        .catch((error: unknown) => {
          setBaseErrors((current) => ({ ...current, [group]: messageOf(error, "No se pudieron cargar los datos del grupo.") }));
          setBaseState((current) => ({ ...current, [group]: "error" }));
        })
        .finally(() => pending.current.delete(key));
    }
  }, [activeGroup, baseData, baseState, route.kind]);

  const directory = useMemo(() => {
    try {
      return { teams: buildTeamCatalog(baseData), error: "" };
    } catch (error) {
      return { teams: [] as CatalogTeam[], error: messageOf(error, "No se pudo validar el catálogo de equipos.") };
    }
  }, [baseData]);
  const selectedTeam = route.kind === "team"
    ? directory.teams.find((team) => team.team_id === route.teamId)
    : undefined;
  let teamGroup: CompetitionGroup | null = null;
  if (route.kind === "team") {
    try {
      teamGroup = findTeamGroup(baseData, route.teamId);
    } catch {
      // A duplicate ID is reported by the catalog validator below; don't crash
      // the route while the user can still navigate back or retry.
    }
  }
  const teamName = selectedTeam?.name;
  const pageTitle = route.kind === "teams"
    ? "Equipos · FootballDataHub"
    : route.kind === "players" || route.kind === "player"
      ? `${route.kind === "player" ? "Jugador" : "Jugadores"} · FootballDataHub`
    : route.kind === "team"
      ? `${teamName ?? "Equipo"} · FootballDataHub`
      : route.kind === "not-found"
        ? "Página no encontrada · FootballDataHub"
        : "Clasificación · FootballDataHub";

  useEffect(() => { document.title = pageTitle; }, [pageTitle]);

  useEffect(() => {
    const group = activeGroup;
    if (route.kind !== "competitions" || activeSection !== "top" || topData[group] || topState[group] !== "idle") return;
    const key = `${group}:top`;
    if (pending.current.has(key)) return;
    pending.current.add(key);
    setTopState((current) => ({ ...current, [group]: "loading" }));
    setTopErrors((current) => ({ ...current, [group]: "" }));
    void loadGroupTopBootstrap(group)
      .then((payload) => {
        setTopData((current) => ({ ...current, [group]: payload }));
        setTopState((current) => ({ ...current, [group]: "ready" }));
      })
      .catch((error: unknown) => {
        setTopErrors((current) => ({ ...current, [group]: messageOf(error, "No se pudieron cargar los datos de Destacados.") }));
        setTopState((current) => ({ ...current, [group]: "error" }));
      })
      .finally(() => pending.current.delete(key));
  }, [activeGroup, activeSection, route.kind, topData, topState]);

  useEffect(() => {
    const group = activeGroup;
    if (route.kind !== "competitions" || activeSection !== "statistics" || statisticsData[group] || statisticsState[group] !== "idle") return;
    const key = `${group}:statistics`;
    if (pending.current.has(key)) return;
    pending.current.add(key);
    setStatisticsState((current) => ({ ...current, [group]: "loading" }));
    setStatisticsErrors((current) => ({ ...current, [group]: "" }));
    void loadGroupStatisticsBootstrap(group)
      .then((payload) => {
        setStatisticsData((current) => ({ ...current, [group]: payload }));
        setStatisticsState((current) => ({ ...current, [group]: "ready" }));
      })
      .catch((error: unknown) => {
        setStatisticsErrors((current) => ({ ...current, [group]: messageOf(error, "No se pudieron cargar las estadísticas.") }));
        setStatisticsState((current) => ({ ...current, [group]: "error" }));
      })
      .finally(() => pending.current.delete(key));
  }, [activeGroup, activeSection, route.kind, statisticsData, statisticsState]);

  useEffect(() => {
    const group = activeGroup;
    if (route.kind !== "competitions" || activeSection !== "referees" || refereesState[group] !== "idle") return;
    const key = `${group}:referees`;
    if (pending.current.has(key)) return;
    pending.current.add(key);
    setRefereesState((current) => ({ ...current, [group]: "loading" }));
    setRefereesErrors((current) => ({ ...current, [group]: "" }));
    void loadGroupRefereesBootstrap(group)
      .then((payload) => {
        setRefereesData((current) => ({ ...current, [group]: payload }));
        setRefereesState((current) => ({ ...current, [group]: "ready" }));
      })
      .catch((error: unknown) => {
        setRefereesErrors((current) => ({ ...current, [group]: messageOf(error, "No se pudieron cargar los datos de Árbitros.") }));
        setRefereesState((current) => ({ ...current, [group]: "error" }));
      })
      .finally(() => pending.current.delete(key));
  }, [activeGroup, activeSection, route.kind, refereesState]);

  useEffect(() => {
    if (route.kind !== "competitions" || activeSection !== "results" || matchResultsData || matchResultsState !== "idle") return;
    setMatchResultsState("loading");
    setMatchResultsError("");
    const controller = new AbortController();
    let settled = false;
    void loadMatchResultsBootstrap(controller.signal)
      .then((payload) => {
        settled = true;
        setMatchResultsData(payload);
        setMatchResultsState("ready");
      })
      .catch((error: unknown) => {
        settled = true;
        if (!controller.signal.aborted) {
          setMatchResultsError(messageOf(error, "No se pudieron cargar los Resultados."));
          setMatchResultsState("error");
        }
      });
    return () => {
      controller.abort();
      if (!settled) setMatchResultsState("idle");
    };
  }, [activeSection, matchResultsData, matchResultsRequestVersion, route.kind]);

  return (
    <div className="app-shell" id="top">
      <header className="topbar">
        <div className="topbar-inner">
          <Brand onNavigate={navigate} />
          <MainNavigation activePage={route.kind === "competitions" ? "competitions" : route.kind === "teams" || route.kind === "team" ? "teams" : "players"} onNavigate={navigate} />
          {route.kind === "competitions" && <div className="topbar-competition">
            <span>Primera Federación</span>
            <span className="topbar-divider" aria-hidden="true">/</span>
            <label className="group-picker">
              <span className="visually-hidden">Grupo de competición</span>
              <select aria-label="Seleccionar grupo" value={activeGroup} onChange={(event) => setActiveGroup(event.currentTarget.value as CompetitionGroup)}>
                <option value="1">Grupo I</option>
                <option value="2">Grupo II</option>
              </select>
            </label>
          </div>}
          <div className="topbar-season">Temporada <strong>2026/27</strong></div>
        </div>
      </header>

      <div
        className={route.kind === "competitions" ? undefined : "competition-view-suspended"}
        aria-hidden={route.kind !== "competitions"}
        inert={route.kind !== "competitions"}
      >
        {groups.map((group) => {
        const data = baseData[group];
        const dashboardHasBeenVisited = visitedCompetitionGroups.has(group);
        const shouldRenderDashboard = Boolean(data) && (
          dashboardHasBeenVisited || (route.kind === "competitions" && group === activeGroup)
        );
        if (route.kind !== "competitions" && !shouldRenderDashboard) return null;
        if (route.kind === "competitions" && group !== activeGroup && !dashboardHasBeenVisited) return null;
        if (group !== activeGroup && !data) return null;
        return (
          <div
            key={group}
            className={group === activeGroup ? undefined : "competition-group-suspended"}
            aria-hidden={group !== activeGroup}
            inert={group !== activeGroup}
          >
            {data ? (
              <GroupDashboard
                group={group}
                data={data}
                matchResultsData={matchResultsData}
                matchResultsState={matchResultsState}
                matchResultsError={matchResultsError}
                onMatchResultsRetry={() => {
                  setMatchResultsState("idle");
                  setMatchResultsRequestVersion((current) => current + 1);
                }}
                teamCatalog={directory.teams}
                onNavigate={navigate}
                activeSection={activeSection}
                onSectionChange={setActiveSection}
                topData={topData[group]}
                topState={topState[group]}
                topError={topErrors[group]}
                onTopRetry={() => setTopState((current) => ({ ...current, [group]: "idle" }))}
                refereesData={refereesData[group]}
                refereesState={refereesState[group]}
                refereesError={refereesErrors[group]}
                onRefereesRetry={() => setRefereesState((current) => ({ ...current, [group]: "idle" }))}
                statisticsData={statisticsData[group]}
                statisticsState={statisticsState[group]}
                statisticsError={statisticsErrors[group]}
                onStatisticsRetry={() => setStatisticsState((current) => ({ ...current, [group]: "idle" }))}
              />
            ) : baseState[group] === "error" ? (
              <main className="dashboard-main">
                <div className="state-card error-card" role="alert">
                  <span className="section-kicker">GRUPO {group === "1" ? "I" : "II"} NO DISPONIBLE</span>
                  <h1>No pudimos cargar la clasificación</h1>
                  <p>{baseErrors[group]}</p>
                  <button className="primary-button" onClick={() => setBaseState((current) => ({ ...current, [group]: "idle" }))} type="button">Reintentar conexión</button>
                </div>
              </main>
            ) : (
              <LoadingPage />
            )}
          </div>
        );
        })}
      </div>

      {route.kind === "teams" && (
        <TeamsDirectory
          teams={directory.teams}
          loadState={baseState}
          errors={baseErrors}
          catalogError={directory.error}
          onRetry={(group) => setBaseState((current) => ({ ...current, [group]: "idle" }))}
          onNavigate={navigate}
        />
      )}
      {(route.kind === "players" || route.kind === "player") && (
        <Suspense fallback={<LoadingPage />}>
          <PlayersPage playerId={route.kind === "player" ? route.playerId : null} onNavigate={navigate} />
        </Suspense>
      )}
      {route.kind === "team" && teamGroup && baseData[teamGroup] && (
        <TeamOverview
          key={route.teamId}
          team={selectedTeam!}
          data={baseData[teamGroup]!}
          teamCatalog={directory.teams}
          activeSection={route.section}
          onNavigate={navigate}
        />
      )}
      {route.kind === "team" && !teamGroup && (
        <TeamRouteState
          routeTeamId={route.teamId}
          catalogError={directory.error}
          loadState={baseState}
          errors={baseErrors}
          onRetry={(group) => setBaseState((current) => ({ ...current, [group]: "idle" }))}
          onNavigate={navigate}
        />
      )}
      {route.kind === "not-found" && (
        <main className="dashboard-main team-route-state">
          <section className="state-card"><span className="section-kicker">PÁGINA NO DISPONIBLE</span><h1>No encontramos esta página</h1><a href="/" onClick={(event) => { event.preventDefault(); navigate("/"); }}>Volver a Competiciones</a></section>
        </main>
      )}

      <footer className="page-footer">
        <span>Fuente <a href="https://www.bdfutbol.com/" target="_blank" rel="noreferrer">BDFutbol</a></span>
      </footer>
    </div>
  );
}

type AppRoute =
  | { kind: "competitions" }
  | { kind: "teams" }
  | { kind: "players" }
  | { kind: "player"; playerId: number }
  | { kind: "team"; teamId: number; section: "summary" | "roster" | "follow" | "transfers" | "matches" }
  | { kind: "not-found" };

function parseRoute(pathname: string): AppRoute {
  if (pathname === "/" || pathname === "") return { kind: "competitions" };
  if (/^\/teams\/?$/.test(pathname)) return { kind: "teams" };
  if (/^\/players\/?$/.test(pathname)) return { kind: "players" };
  const playerMatch = pathname.match(/^\/players\/(\d+)\/?$/);
  if (playerMatch) {
    const playerId = Number(playerMatch[1]);
    if (Number.isSafeInteger(playerId) && playerId > 0) return { kind: "player", playerId };
  }
  const match = pathname.match(/^\/teams\/(\d+)(?:\/(roster|follow|transfers|matches))?\/?$/);
  if (match) {
    const teamId = Number(match[1]);
    if (Number.isSafeInteger(teamId) && teamId > 0) {
      const section = match[2] === "roster" || match[2] === "follow" || match[2] === "transfers" || match[2] === "matches" ? match[2] : "summary";
      return { kind: "team", teamId, section };
    }
  }
  return { kind: "not-found" };
}

function TeamRouteState({
  routeTeamId,
  catalogError,
  loadState,
  errors,
  onRetry,
  onNavigate,
}: {
  routeTeamId: number;
  catalogError: string;
  loadState: GroupValues<LoadState>;
  errors: GroupValues<string>;
  onRetry: (group: CompetitionGroup) => void;
  onNavigate: (path: string) => void;
}) {
  const failed = groups.filter((group) => loadState[group] === "error");
  const loading = groups.some((group) => loadState[group] === "loading" || loadState[group] === "idle");
  const title = catalogError
    ? "No se pudo validar el catálogo"
    : failed.length && !loading
      ? "No se pudo verificar el equipo"
      : "Equipo no encontrado";
  return (
    <main className="dashboard-main team-route-state">
      <section className="state-card" role={catalogError || failed.length ? "alert" : "status"}>
        <span className="section-kicker">FICHA DE EQUIPO</span>
        <h1>{loading ? "Cargando equipo…" : title}</h1>
        <p>{catalogError ? catalogError : loading ? `Consultando los catálogos para el identificador ${routeTeamId}.` : failed.length ? failed.map((group) => `Grupo ${group === "1" ? "I" : "II"}: ${errors[group]}`).join(" ") : `No hay un equipo con el identificador ${routeTeamId} en los catálogos disponibles.`}</p>
        {failed.map((group) => <button className="primary-button" key={group} onClick={() => onRetry(group)} type="button">Reintentar Grupo {group === "1" ? "I" : "II"}</button>)}
        <a href="/teams" onClick={(event) => { event.preventDefault(); onNavigate("/teams"); }}>Ir al directorio</a>
      </section>
    </main>
  );
}

interface GroupDashboardProps {
  group: CompetitionGroup;
  data: Bootstrap;
  matchResultsData: MatchResultsBootstrap | null;
  matchResultsState: LoadState;
  matchResultsError: string;
  onMatchResultsRetry: () => void;
  teamCatalog: readonly CatalogTeam[];
  onNavigate: (path: string) => void;
  activeSection: Section;
  onSectionChange: (section: Section) => void;
  topData: TopBootstrap | null;
  topState: LoadState;
  topError: string;
  onTopRetry: () => void;
  refereesData: RefereeBootstrap | null;
  refereesState: LoadState;
  refereesError: string;
  onRefereesRetry: () => void;
  statisticsData: StatisticsBootstrap | null;
  statisticsState: LoadState;
  statisticsError: string;
  onStatisticsRetry: () => void;
}

function GroupDashboard({
  group,
  data,
  matchResultsData,
  matchResultsState,
  matchResultsError,
  onMatchResultsRetry,
  teamCatalog,
  onNavigate,
  activeSection,
  onSectionChange,
  topData,
  topState,
  topError,
  onTopRetry,
  refereesData,
  refereesState,
  refereesError,
  onRefereesRetry,
  statisticsData,
  statisticsState,
  statisticsError,
  onStatisticsRetry,
}: GroupDashboardProps) {
  const suffix = `-group${group}`;
  const [filters, setFilters] = useState<StandingsFilters>(() => initialFilters(data));
  const [resultsMatchday, setResultsMatchday] = useState<ResultsMatchday>(
    data.metadata.last_matchday_with_results ?? 1,
  );
  const indexes = useMemo(
    () => createClassificationIndexes(data.teams, data.matches),
    [data],
  );
  const table = useMemo(
    () => calculateStandings(data.teams, data.matches, filters, indexes),
    [data, filters, indexes],
  );
  const matchdays = useMemo(() => buildMatchdayOptions(data), [data]);
  const matchdayDate = table.selectedMatchdayDate ?? "";

  return (
    <main className="dashboard-main" id={`group-dashboard-${group}`}>
      <nav className="section-tabs" role="tablist" aria-label="Secciones de competición">
        {sectionTabs.map((tab) => (
          <button
            key={tab.id}
            id={`${tab.id}-tab${suffix}`}
            role="tab"
            aria-selected={activeSection === tab.id}
            aria-controls={`${tab.id}-panel${suffix}`}
            className={activeSection === tab.id ? "is-active" : ""}
            onClick={() => onSectionChange(tab.id)}
            type="button"
          >{tab.label}</button>
        ))}
      </nav>

      <section hidden={activeSection !== "standings"} role="tabpanel" id={`standings-panel${suffix}`} aria-labelledby={`standings-tab${suffix}`}>
        <section className="competition-hero">
          <h1>Clasificación</h1>
          <div className="dataset-meta" aria-label="Actualización de los datos">
            <span>Jornada {data.metadata.last_matchday_with_results ?? "—"} disponible</span>
            <time dateTime={data.metadata.captured_at}>Actualizado {formatCaptureDate(data.metadata.captured_at)}</time>
          </div>
        </section>
        <ClassificationControls filters={filters} onChange={setFilters} matchdays={matchdays} />
        <div className="table-context-bar" id={`clasificacion${suffix}`}>
          <div>
            <span className="context-round">J{filters.matchdayCap}</span>
            <span className="context-description">
              {matchdayDate ? formatLongDate(matchdayDate) : "Sin fecha disponible"}
              {filters.rangeType !== "all" && <span> · {rangeDescription(filters)}</span>}
            </span>
          </div>
        </div>
        <StandingsTable filters={filters} published={data.published_standings} table={table} onNavigate={onNavigate} />
        <Suspense fallback={<div className="chart-loading" role="status">Cargando gráfico…</div>}>
          <ProgressChart teams={data.teams} records={data.progress} />
        </Suspense>
      </section>

      <div hidden={activeSection !== "results"}>
        {matchResultsState === "loading" || matchResultsState === "idle" ? <div className="state-card" role="status">Cargando generación de Resultados…</div>
          : matchResultsState === "error" ? <section className="state-card error-card" role="alert"><h1>Resultados no disponibles</h1><p>{matchResultsError}</p><button className="primary-button" type="button" onClick={onMatchResultsRetry}>Reintentar</button></section>
            : matchResultsData ? <ResultsSection
              data={resultViewData(matchResultsData, group)}
              matchday={resultsMatchday}
              onMatchdayChange={setResultsMatchday}
              onNavigate={onNavigate}
              idSuffix={suffix}
            /> : null}
      </div>
      <div hidden={activeSection !== "top"}>
        <Suspense fallback={<div className="chart-loading" role="status">Cargando Destacados…</div>}>
          <TopSection data={topData} loadState={topState} errorMessage={topError} onRetry={onTopRetry} teams={teamCatalog} onNavigate={onNavigate} idSuffix={suffix} />
        </Suspense>
      </div>
      <div hidden={activeSection !== "referees"}>
        <RefereesSection
          data={refereesData}
          loadState={refereesState}
          errorMessage={refereesError}
          onRetry={onRefereesRetry}
          initialScope={group === "1" ? "group1" : "group2"}
          idSuffix={suffix}
        />
      </div>
      <div hidden={activeSection !== "statistics"}>
        <Suspense fallback={<div className="chart-loading" role="status">Cargando Estadísticas…</div>}>
          <StatisticsSection
            data={statisticsData}
            teams={data.teams}
            matches={data.matches}
            loadState={statisticsState}
            errorMessage={statisticsError}
            onRetry={onStatisticsRetry}
            onNavigate={onNavigate}
            idSuffix={suffix}
          />
        </Suspense>
      </div>
    </main>
  );
}

function initialFilters(data: Bootstrap): StandingsFilters {
  const last = data.metadata.last_matchday_with_results ?? 1;
  const playedDates = sortedMatchDates(data.matches.filter((match) => match.status === "played"));
  const scheduledDates = sortedMatchDates(data.matches);
  const availableDates = playedDates.length > 0 ? playedDates : scheduledDates;
  const firstDate = availableDates[0] ?? null;
  const lastDate = availableDates.at(-1) ?? firstDate;
  return {
    classificationType: "general",
    matchdayCap: last,
    includePostponed: true,
    rangeType: "all",
    dateStart: firstDate,
    dateEnd: lastDate,
    roundStart: 1,
    roundEnd: last,
  };
}

function sortedMatchDates(matches: Bootstrap["matches"]): string[] {
  return matches.map((match) => match.source_match_date).filter((date): date is string => date !== null).sort();
}

function buildMatchdayOptions(data: Bootstrap) {
  const results = new Set(data.matches.filter((match) => match.status === "played").map((match) => match.matchday));
  const dates = new Map<number, string>();
  for (const match of data.matches) {
    if (match.matchday_date && !dates.has(match.matchday)) dates.set(match.matchday, match.matchday_date);
  }
  return data.metadata.scheduled_matchdays.map((number) => ({
    number,
    date: dates.get(number) ?? null,
    hasResults: results.has(number),
  }));
}

function resultViewData(generation: MatchResultsBootstrap, group: CompetitionGroup): ResultsViewData {
  const code = group === "1" ? "I" : "II";
  const source = generation.groups[code];
  return {
    metadata: {
      captured_at: source.source_captured_at,
      scheduled_matchdays: source.scheduled_matchdays,
      generation_id: generation.metadata.generation_id,
      generation_sha256: generation.metadata.generation_sha256,
      source_capture_id: source.source_capture_id,
      counts: source.counts,
    },
    teams: source.teams,
    matches: source.matches.map((match): Match => ({
      match_id: match.source_match_id,
      matchday: match.matchday,
      matchday_date: match.matchday_date,
      source_match_date: match.source_match_date,
      home_team_id: match.home_team_id,
      away_team_id: match.away_team_id,
      home_goals: match.home_goals,
      away_goals: match.away_goals,
      home_yellow_cards: match.home_yellow_cards,
      away_yellow_cards: match.away_yellow_cards,
      home_red_cards: match.home_red_cards,
      away_red_cards: match.away_red_cards,
      status: match.status,
      unplayed_state: match.unplayed_state,
      postponed_by_source_rule: match.postponed_by_source_rule,
      source_match_url: match.source_match_url,
      stadium_id: match.stadium_id,
      stadium_name: match.stadium_name,
      stadium_url: match.stadium_url,
      referee_id: match.referee_id,
      referee_name: match.referee_name,
      referee_url: match.referee_url,
    })),
  };
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Madrid",
  }).format(new Date(value));
}

function rangeDescription(filters: StandingsFilters): string {
  if (filters.rangeType === "dates") return `${formatShortDate(filters.dateStart)} – ${formatShortDate(filters.dateEnd)}`;
  if (filters.rangeType === "rounds") return `J${filters.roundStart ?? 1} – J${filters.roundEnd ?? filters.matchdayCap}`;
  return "";
}

function formatShortDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatLongDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function LoadingPage() {
  return (
    <main className="dashboard-main">
      <div className="state-card" role="status">
        <span className="loading-ball" />
        <span className="section-kicker">PREPARANDO EL CAMPO</span>
        <p>Cargando datos de Primera Federación…</p>
      </div>
    </main>
  );
}

function Brand({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <a className="brand-lockup" href="/" aria-label="FootballDataHub inicio" onClick={(event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      onNavigate("/");
    }}>
      <span className="brand-mark"><i /><i /><i /><i /></span>
      <span>FOOTBALL<span className="brand-light">DATAHUB</span></span>
    </a>
  );
}
