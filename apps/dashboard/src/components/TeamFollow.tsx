import { useEffect, useState, type KeyboardEvent } from "react";
import { loadTeamFollow, type TeamFollowLoadResult, TeamFollowApiError } from "../api/client";
import type { TeamFollow as TeamFollowData } from "../api/contracts";
import { TeamFollowLegend } from "./TeamFollowLegend";
import { TeamFollowMatrix, type FollowMode } from "./TeamFollowMatrix";

const modes: Array<{ id: FollowMode; label: string }> = [
  { id: "p", label: "Partidos" },
  { id: "t", label: "Tarjetas" },
  { id: "go", label: "Goles" },
  { id: "tot", label: "Todo" },
];

export function TeamFollow({ teamId, season }: { teamId: number; season: string }) {
  const [result, setResult] = useState<TeamFollowLoadResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [modeState, setModeState] = useState<{ teamId: number; mode: FollowMode }>(() => ({ teamId, mode: readMode(teamId) }));
  const mode = modeState.teamId === teamId ? modeState.mode : readMode(teamId);

  useEffect(() => {
    if (modeState.teamId !== teamId) setModeState({ teamId, mode: readMode(teamId) });
  }, [modeState.teamId, teamId]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    void loadTeamFollow(teamId, season)
      .then((payload) => { if (current) setResult(payload); })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof TeamFollowApiError ? reason.message : "No se pudo cargar Seguimiento.");
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [retry, season, teamId]);

  function selectMode(next: FollowMode) {
    setModeState({ teamId, mode: next });
    try { window.sessionStorage.setItem(storageKey(teamId), next); } catch { /* The local mode remains usable. */ }
  }

  function onModeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const currentIndex = modes.findIndex((item) => item.id === mode);
    const nextIndex = event.key === "ArrowRight" ? (currentIndex + 1) % modes.length
      : event.key === "ArrowLeft" ? (currentIndex + modes.length - 1) % modes.length
        : event.key === "Home" ? 0 : event.key === "End" ? modes.length - 1 : -1;
    if (nextIndex < 0) return;
    event.preventDefault();
    const next = modes[nextIndex]!.id;
    selectMode(next);
    document.getElementById(`team-follow-mode-${next}`)?.focus();
  }

  return <section className="team-follow" aria-label="Seguimiento del equipo">
    <header className="team-profile-panel team-follow-header">
      <div className="team-follow-heading">
        <div>
          <span className="section-kicker">LIGA · TEMPORADA {formatSeason(season)}</span>
          <h2>Seguimiento</h2>
          <p>Participación y eventos individuales por jornada.</p>
        </div>
        {result?.status === "available" && <span className="team-follow-round-count">{result.follow.matchdays.length} jornadas capturadas</span>}
      </div>
      <div className="team-follow-controls">
        <span className="team-follow-control-label">Tipo</span>
        <div className="follow-mode-tabs" role="tablist" aria-label="Tipo de Seguimiento">
          {modes.map(({ id, label }) => <button
            aria-controls="team-follow-view"
            aria-selected={mode === id}
            className={mode === id ? "follow-mode-tab is-active" : "follow-mode-tab"}
            id={`team-follow-mode-${id}`}
            key={id}
            onClick={() => selectMode(id)}
            onKeyDown={onModeKeyDown}
            role="tab"
            tabIndex={mode === id ? 0 : -1}
            type="button"
          >{label}</button>)}
        </div>
      </div>
      {result?.status === "available" && <CaptureDetails follow={result.follow} />}
    </header>

    <div className="team-follow-view" id="team-follow-view" role="tabpanel" aria-labelledby={`team-follow-mode-${mode}`}>
      {loading && <section className="team-profile-panel roster-state" role="status"><h2>Cargando Seguimiento…</h2></section>}
      {!loading && error && <section className="team-profile-panel roster-state" role="alert">
        <h2>No se pudo cargar Seguimiento</h2><p>{error}</p>
        <button className="primary-button" onClick={() => { setResult(null); setRetry((value) => value + 1); }} type="button">Reintentar</button>
      </section>}
      {!loading && !error && result?.status === "not_captured" && <section className="team-profile-panel roster-state" role="status">
        <h2>Seguimiento aún no adquirido</h2>
        <p>El resto de la ficha del equipo permanece disponible.</p>
      </section>}
      {!loading && !error && result?.status === "available" && <FollowContent follow={result.follow} mode={mode} />}
    </div>
  </section>;
}

function FollowContent({ follow, mode }: { follow: TeamFollowData; mode: FollowMode }) {
  const coverage = new Map(follow.coverage.map((item) => [item.state, item]));
  const requiredState = mode === "p" ? "p" : mode;
  const missingMode = mode !== "tot" && !coverage.get(requiredState)?.available;
  const partialTodo = mode === "tot" && (!coverage.get("t")?.available || !coverage.get("go")?.available);

  if (missingMode) {
    return <section className="team-profile-panel roster-state" role="status">
      <TeamFollowLegend mode={mode} />
      <p>Los eventos individuales de este tipo todavía no están disponibles en la captura del equipo.</p>
      <CoverageSummary follow={follow} />
    </section>;
  }

  return <>
    <section className="team-profile-panel team-follow-panel" aria-label="Matriz de Seguimiento">
      <TeamFollowLegend mode={mode} />
      {partialTodo && <p className="follow-coverage-note" role="status">La captura permite mostrar los minutos. Tarjetas y goles no están disponibles todavía para este equipo.</p>}
      <TeamFollowMatrix follow={follow} mode={mode} />
    </section>
    <CoverageSummary follow={follow} />
    {follow.warnings.map((warning) => <p className="follow-warning" key={warning}>{warning}</p>)}
  </>;
}

function CaptureDetails({ follow }: { follow: TeamFollowData }) {
  return <details className="follow-capture-details">
    <summary>Captura {formatDateTime(follow.metadata.captured_at)}</summary>
    <dl>
      <div><dt>Identificador</dt><dd>{follow.metadata.capture_id}</dd></div>
      <div><dt>Fuente</dt><dd><a href={follow.metadata.url} target="_blank" rel="noreferrer">BDFutbol ↗</a></dd></div>
      <div><dt>Catálogo de partidos</dt><dd>{follow.metadata.match_capture_id}</dd></div>
    </dl>
  </details>;
}

function CoverageSummary({ follow }: { follow: TeamFollowData }) {
  const labels = { p: "Partidos", t: "Tarjetas", go: "Goles", tot: "Todo" } as const;
  return <dl className="team-profile-panel follow-coverage" aria-label="Cobertura de Seguimiento">
    {follow.coverage.map((item) => <div key={item.state}>
      <dt>{labels[item.state]}</dt>
      <dd>{item.available ? `${item.matchdays.length} jornadas` : "No capturado"}</dd>
    </div>)}
  </dl>;
}

function readMode(teamId: number): FollowMode {
  try {
    const stored = window.sessionStorage.getItem(storageKey(teamId));
    return stored === "t" || stored === "go" || stored === "tot" ? stored : "p";
  } catch { return "p"; }
}

function storageKey(teamId: number): string { return `football-data-hub:team-follow-mode:${teamId}`; }
function formatSeason(value: string): string { return value.replace(/^(\d{4})-(\d{2})$/, "$1/$2"); }
function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
