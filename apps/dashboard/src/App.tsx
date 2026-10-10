import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  loadGroupBootstrap,
  loadGroupRefereesBootstrap,
  loadGroupStatisticsBootstrap,
  loadGroupTopBootstrap,
  type CompetitionGroup,
} from "./api/client";
import type {
  Bootstrap,
  RefereeBootstrap,
  StatisticsBootstrap,
  TopBootstrap,
} from "./api/contracts";
import { ClassificationControls } from "./components/ClassificationControls";
const ProgressChart = lazy(() => import("./components/ProgressChart").then((module) => ({ default: module.ProgressChart })));
import { StandingsTable } from "./components/StandingsTable";
import { ResultsSection, type ResultsMatchday } from "./components/ResultsSection";
import { RefereesSection } from "./components/RefereesSection";
const StatisticsSection = lazy(() => import("./components/StatisticsSection").then((module) => ({ default: module.StatisticsSection })));
const TopSection = lazy(() => import("./components/TopSection").then((module) => ({ default: module.TopSection })));
import {
  calculateStandings,
  createClassificationIndexes,
  type StandingsFilters,
} from "./domain/classification/engine";

type Section = "standings" | "results" | "top" | "referees" | "statistics";
type LoadState = "idle" | "loading" | "error" | "ready";
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
  const [activeGroup, setActiveGroup] = useState<CompetitionGroup>("2");
  const [activeSection, setActiveSection] = useState<Section>("standings");
  const [baseData, setBaseData] = useState<GroupValues<Bootstrap | null>>({ "1": null, "2": null });
  const [baseState, setBaseState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [baseErrors, setBaseErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [topData, setTopData] = useState<GroupValues<TopBootstrap | null>>({ "1": null, "2": null });
  const [topState, setTopState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [topErrors, setTopErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [statisticsData, setStatisticsData] = useState<GroupValues<StatisticsBootstrap | null>>({ "1": null, "2": null });
  const [statisticsState, setStatisticsState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [statisticsErrors, setStatisticsErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const [refereesData, setRefereesData] = useState<GroupValues<RefereeBootstrap | null>>({ "1": null, "2": null });
  const [refereesState, setRefereesState] = useState<GroupValues<LoadState>>({ "1": "idle", "2": "idle" });
  const [refereesErrors, setRefereesErrors] = useState<GroupValues<string>>({ "1": "", "2": "" });
  const pending = useRef(new Set<string>());

  useEffect(() => {
    const group = activeGroup;
    if (baseData[group] || baseState[group] !== "idle") return;
    const key = `${group}:classification`;
    if (pending.current.has(key)) return;
    pending.current.add(key);
    setBaseState((current) => ({ ...current, [group]: "loading" }));
    setBaseErrors((current) => ({ ...current, [group]: "" }));
    void loadGroupBootstrap(group)
      .then((payload) => {
        // Responses are cached under the request's group. A late result cannot
        // change which group's data is rendered in the active view.
        setBaseData((current) => ({ ...current, [group]: payload }));
        setBaseState((current) => ({ ...current, [group]: "ready" }));
      })
      .catch((error: unknown) => {
        setBaseErrors((current) => ({ ...current, [group]: messageOf(error, "No se pudieron cargar los datos del grupo.") }));
        setBaseState((current) => ({ ...current, [group]: "error" }));
      })
      .finally(() => pending.current.delete(key));
  }, [activeGroup, baseData, baseState]);

  useEffect(() => {
    const group = activeGroup;
    if (activeSection !== "top" || topData[group] || topState[group] !== "idle") return;
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
  }, [activeGroup, activeSection, topData, topState]);

  useEffect(() => {
    const group = activeGroup;
    if (activeSection !== "statistics" || statisticsData[group] || statisticsState[group] !== "idle") return;
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
  }, [activeGroup, activeSection, statisticsData, statisticsState]);

  useEffect(() => {
    const group = activeGroup;
    if (activeSection !== "referees" || refereesState[group] !== "idle") return;
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
  }, [activeGroup, activeSection, refereesState]);

  return (
    <div className="app-shell" id="top">
      <header className="topbar">
        <div className="topbar-inner">
          <Brand />
          <div className="topbar-competition">
            <span>Primera Federación</span>
            <span className="topbar-divider" aria-hidden="true">/</span>
            <label className="group-picker">
                <span className="visually-hidden">Grupo de competición</span>
              <select aria-label="Seleccionar grupo" value={activeGroup} onChange={(event) => setActiveGroup(event.currentTarget.value as CompetitionGroup)}>
                <option value="1">Grupo I</option>
                <option value="2">Grupo II</option>
              </select>
            </label>
          </div>
          <div className="topbar-season">Temporada <strong>2026/27</strong></div>
        </div>
      </header>

      {groups.map((group) => {
        const data = baseData[group];
        if (group !== activeGroup && !data) return null;
        return (
          <div key={group} hidden={group !== activeGroup}>
            {data ? (
              <GroupDashboard
                group={group}
                data={data}
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

      <footer className="page-footer">
        <span>Fuente <a href="https://www.bdfutbol.com/" target="_blank" rel="noreferrer">BDFutbol</a></span>
      </footer>
    </div>
  );
}

interface GroupDashboardProps {
  group: CompetitionGroup;
  data: Bootstrap;
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
        <StandingsTable filters={filters} published={data.published_standings} table={table} />
        <Suspense fallback={<div className="chart-loading" role="status">Cargando gráfico…</div>}>
          <ProgressChart teams={data.teams} records={data.progress} />
        </Suspense>
      </section>

      <div hidden={activeSection !== "results"}>
        <ResultsSection
          data={data}
          matchday={resultsMatchday}
          onMatchdayChange={setResultsMatchday}
          idSuffix={suffix}
        />
      </div>
      <div hidden={activeSection !== "top"}>
        <Suspense fallback={<div className="chart-loading" role="status">Cargando Destacados…</div>}>
          <TopSection data={topData} loadState={topState} errorMessage={topError} onRetry={onTopRetry} idSuffix={suffix} />
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

function Brand() {
  return (
    <a className="brand-lockup" href="#top" aria-label="FootballDataHub inicio">
      <span className="brand-mark"><i /><i /><i /><i /></span>
      <span>FOOTBALL<span className="brand-light">DATAHUB</span></span>
    </a>
  );
}
