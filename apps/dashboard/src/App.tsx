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
  const publishedIsReference = useMemo(
    () => data && filters && table ? isPublishedContext(data, filters, table) : false,
    [data, filters, table],
  );

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
          <nav className="main-nav" aria-label="Navegación principal">
            <a aria-current="page" className="active" href="#clasificacion">Clasificación</a>
            <span className="future-nav-label">Football · datos y análisis</span>
          </nav>
          <div className="topbar-status"><span className="status-dot" />Datos disponibles</div>
        </div>
      </header>

      <main className="dashboard-main">
        <section className="competition-hero">
          <div className="hero-copy">
            <div className="eyebrow"><span />PRIMERA FEDERACIÓN <b>/</b> GRUPO II</div>
            <h1>La clasificación<span>.</span></h1>
            <p className="hero-subtitle">Cada punto cuenta. Sigue el pulso de la temporada 2026/27.</p>
          </div>
          <div className="hero-season" aria-label="Temporada 2026-27">
            <span>TEMPORADA</span>
            <strong>26<span>/</span>27</strong>
          </div>
        </section>

        <section className="capture-strip" aria-label="Corte de los datos">
          <div className="capture-marker"><span className="capture-icon">◷</span></div>
          <div className="capture-main">
            <strong>Datos al cierre de la Jornada {data.metadata.last_matchday_with_results ?? "—"}</strong>
            <span>Captura del {formatCaptureDate(data.metadata.captured_at)}</span>
          </div>
          <div className="capture-separator" />
          <div className="capture-stat">
            <strong>{table.matchesCounted}<small> / {data.metadata.availability.matches}</small></strong>
            <span>partidos disputados</span>
          </div>
          <div className="capture-separator capture-wide-separator" />
          <div className="capture-quality">
            <span className="quality-mark">i</span>
            <span>Los partidos sin marcador no se cuentan como 0–0.</span>
          </div>
        </section>

        {data.metadata.warnings.length > 0 && (
          <details className="quality-details">
            <summary>Ver notas sobre esta captura <span>{data.metadata.warnings.length}</span></summary>
            <ul>{data.metadata.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </details>
        )}

        <ClassificationControls filters={filters} onChange={(next) => setFilters(next)} matchdays={matchdays} />

        <div className="table-context-bar" id="clasificacion">
          <div>
            <span className="context-round">J{filters.matchdayCap}</span>
            <span className="context-description">
              {matchdayDate ? formatLongDate(matchdayDate) : "Sin fecha disponible"}
              <span> · </span>{filters.rangeType === "all" ? "Todas las fechas" : filters.rangeType === "dates" ? "Rango de fechas" : "Rango de jornadas"}
            </span>
          </div>
          {publishedIsReference ? (
            <span className="source-match-badge"><span>✓</span> Coincide con la tabla publicada · General J6</span>
          ) : (
            <span className="calculation-badge">Orden deportivo calculado</span>
          )}
        </div>

        <StandingsTable
          filters={filters}
          progress={data.progress}
          published={data.published_standings}
          table={table}
        />

        <p className="calculation-note">
          <span>ⓘ</span>
          La tabla se calcula aquí a partir de los resultados capturados. Al cambiar un filtro no se consulta de nuevo la API.
          {filters.classificationType === "general" && filters.rangeType === "all" && matchdayDate && (
            <> La fecha del rango se refiere al día del partido; la jornada marca el tope del cálculo.</>
          )}
        </p>

        <Suspense fallback={<div className="chart-loading" role="status">Preparando las series históricas…</div>}>
          <ProgressChart
            teams={data.teams}
            records={data.progress}
            throughMatchday={data.metadata.progress_context.available_through_matchday}
          />
        </Suspense>
      </main>

      <footer className="page-footer">
        <Brand />
        <span>Datos deportivos · Fuente: BDFutbol · Captura {data.metadata.capture_id}</span>
        <span>Las series de progreso mantienen su contexto general original.</span>
      </footer>
    </div>
  );
}

function initialFilters(data: Bootstrap): StandingsFilters {
  const last = data.metadata.last_matchday_with_results ?? 1;
  const playedDates = data.matches
    .filter((match) => match.status === "played" && match.source_match_date !== null)
    .map((match) => match.source_match_date as string)
    .sort();
  const firstDate = playedDates[0] ?? null;
  const lastDate = playedDates.at(-1) ?? firstDate;
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

function isPublishedContext(
  data: Bootstrap,
  filters: StandingsFilters,
  table: ReturnType<typeof calculateStandings>,
): boolean {
  const source = data.published_standings;
  if (!source || filters.classificationType !== "general" || filters.rangeType !== "all") return false;
  if (
    filters.matchdayCap !== source.context.matchday ||
    filters.includePostponed !== (source.context.postponed_policy === "include")
  ) return false;
  const sourceRows = new Map(source.rows.map((row) => [row.team_id, row]));
  return table.rows.every((row) => {
    const original = sourceRows.get(row.team.team_id);
    return Boolean(original) &&
      original?.position === row.position &&
      original.points === row.points &&
      original.matches_played === row.matchesPlayed &&
      original.wins === row.wins &&
      original.draws === row.draws &&
      original.losses === row.losses &&
      original.goals_for === row.goalsFor &&
      original.goals_against === row.goalsAgainst &&
      original.yellow_cards === row.yellowCards &&
      original.red_cards === row.redCards;
  });
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
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
