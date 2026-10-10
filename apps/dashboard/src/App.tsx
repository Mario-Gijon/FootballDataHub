import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { loadGroup2Bootstrap } from "./api/client";
import type { Bootstrap } from "./api/contracts";
import { ClassificationControls } from "./components/ClassificationControls";
const ProgressChart = lazy(() => import("./components/ProgressChart").then((module) => ({ default: module.ProgressChart })));
import { StandingsTable } from "./components/StandingsTable";
import {
  calculateStandings,
  createClassificationIndexes,
  type StandingsFilters,
} from "./domain/classification/engine";

type LoadState = "loading" | "error" | "ready";

export default function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [filters, setFilters] = useState<StandingsFilters | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [retryCount, setRetryCount] = useState(0);

  const indexes = useMemo(
    () => data ? createClassificationIndexes(data.teams, data.matches) : null,
    [data],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoadState("loading");
    setErrorMessage("");
    loadGroup2Bootstrap(controller.signal)
      .then((bootstrap) => {
        setData(bootstrap);
        setFilters(initialFilters(bootstrap));
        setLoadState("ready");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setErrorMessage(error instanceof Error ? error.message : "No se pudieron cargar los datos.");
        setLoadState("error");
      });
    return () => controller.abort();
  }, [retryCount]);

  const table = useMemo(
    () => data && filters && indexes
      ? calculateStandings(data.teams, data.matches, filters, indexes)
      : null,
    [data, filters, indexes],
  );
  const matchdays = useMemo(() => data ? buildMatchdayOptions(data) : [], [data]);

  if (loadState === "error") {
    return (
      <main className="state-page">
        <Brand />
        <div className="state-card error-card" role="alert">
          <span className="state-icon error-icon">!</span>
          <span className="section-kicker">CONEXIÓN NO DISPONIBLE</span>
          <h1>No pudimos cargar la clasificación</h1>
          <p>{errorMessage}</p>
          <button className="primary-button" onClick={() => setRetryCount((value) => value + 1)} type="button">
            Reintentar conexión
          </button>
          <small>Comprueba que la API de FootballDataHub esté disponible.</small>
        </div>
      </main>
    );
  }
  if (loadState === "loading" || !data || !filters) return <LoadingPage />;
  if (!data || !filters || !table) return <LoadingPage />;
  const matchdayDate = table.selectedMatchdayDate ?? "";

  return (
    <div className="app-shell" id="top">
      <header className="topbar">
        <div className="topbar-inner">
          <Brand />
          <div className="topbar-competition" aria-label="Primera Federación · Grupo II">
            <span>Primera Federación</span>
            <span className="topbar-divider" aria-hidden="true">/</span>
            <span>Grupo II</span>
          </div>
          <div className="topbar-season">Temporada <strong>2026/27</strong></div>
        </div>
      </header>

      <main className="dashboard-main">
        <section className="competition-hero">
          <h1>Clasificación</h1>
          <div className="dataset-meta" aria-label="Actualización de los datos">
            <span>Jornada {data.metadata.last_matchday_with_results ?? "—"} disponible</span>
            <time dateTime={data.metadata.captured_at}>Actualizado {formatCaptureDate(data.metadata.captured_at)}</time>
          </div>
        </section>

        <ClassificationControls filters={filters} onChange={(next) => setFilters(next)} matchdays={matchdays} />

        <div className="table-context-bar" id="clasificacion">
          <div>
            <span className="context-round">J{filters.matchdayCap}</span>
            <span className="context-description">
              {matchdayDate ? formatLongDate(matchdayDate) : "Sin fecha disponible"}
              {filters.rangeType !== "all" && <span> · {rangeDescription(filters)}</span>}
            </span>
          </div>
        </div>

        <StandingsTable
          filters={filters}
          published={data.published_standings}
          table={table}
        />

        <Suspense fallback={<div className="chart-loading" role="status">Cargando gráfico…</div>}>
          <ProgressChart
            teams={data.teams}
            records={data.progress}
          />
        </Suspense>
      </main>

      <footer className="page-footer">
        <span>Fuente <a href="https://www.bdfutbol.com/" target="_blank" rel="noreferrer">BDFutbol</a></span>
      </footer>
    </div>
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
  return matches
    .map((match) => match.source_match_date)
    .filter((date): date is string => date !== null)
    .sort();
}

function buildMatchdayOptions(data: Bootstrap) {
  const results = new Set(
    data.matches.filter((match) => match.status === "played").map((match) => match.matchday),
  );
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
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
}

function rangeDescription(filters: StandingsFilters): string {
  if (filters.rangeType === "dates") {
    return `${formatShortDate(filters.dateStart)} – ${formatShortDate(filters.dateEnd)}`;
  }
  if (filters.rangeType === "rounds") {
    return `J${filters.roundStart ?? 1} – J${filters.roundEnd ?? filters.matchdayCap}`;
  }
  return "";
}

function formatShortDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatLongDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function LoadingPage() {
  return (
    <main className="state-page loading-page" aria-label="Cargando clasificación">
      <Brand />
      <div className="loading-content">
        <span className="loading-ball" />
        <div>
          <span className="section-kicker">PREPARANDO EL CAMPO</span>
          <h1>Cargando clasificación</h1>
          <p>Conectando con los datos de Primera Federación.</p>
        </div>
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
