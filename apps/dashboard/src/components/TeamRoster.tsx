import { useEffect, useState, type KeyboardEvent } from "react";
import type { TeamRoster } from "../api/contracts";
import { TeamRosterAnalysis } from "./TeamRosterAnalysis";
import { TeamRosterBiography } from "./TeamRosterBiography";
import { TeamRosterAlignment } from "./TeamRosterAlignment";

type RosterMode = "alignment" | "roster" | "analysis";
const modeOptions: Array<{ mode: RosterMode; label: string }> = [
  { mode: "alignment", label: "Alineación" },
  { mode: "roster", label: "Plantilla" },
  { mode: "analysis", label: "Análisis" },
];

interface Props {
  roster: TeamRoster;
  onNavigate?: (path: string) => void;
}

export function TeamRosterSection({ roster, onNavigate = () => undefined }: Props) {
  const teamId = roster.team.team_id;
  const [modeState, setModeState] = useState<{ teamId: number; mode: RosterMode }>(() => ({ teamId, mode: readMode(teamId) }));
  const [queryState, setQueryState] = useState<{ teamId: number; value: string }>(() => ({ teamId, value: readQuery(teamId) }));
  const mode = modeState.teamId === teamId ? modeState.mode : readMode(teamId);
  const query = queryState.teamId === teamId ? queryState.value : readQuery(teamId);

  useEffect(() => {
    if (modeState.teamId !== teamId) setModeState({ teamId, mode: readMode(teamId) });
    if (queryState.teamId !== teamId) setQueryState({ teamId, value: readQuery(teamId) });
  }, [modeState.teamId, queryState.teamId, teamId]);

  function selectMode(nextMode: RosterMode) {
    setModeState({ teamId, mode: nextMode });
    try {
      window.sessionStorage.setItem(storageKey(teamId), nextMode);
    } catch {
      // The view remains usable when session storage is unavailable.
    }
  }

  function changeQuery(value: string) {
    setQueryState({ teamId, value });
    try { window.sessionStorage.setItem(queryStorageKey(teamId), value); }
    catch { /* Search remains usable when session storage is unavailable. */ }
  }

  return <section className="team-roster" aria-label="Plantilla del equipo">
    <div className="roster-mode-tabs" role="tablist" aria-label="Vistas de Plantilla">
      {modeOptions.map(({ mode: option, label }) => <button
        aria-controls="team-roster-view"
        aria-selected={mode === option}
        className={mode === option ? "roster-mode-tab is-active" : "roster-mode-tab"}
        id={`roster-mode-${option}`}
        key={option}
        onClick={() => selectMode(option)}
        onKeyDown={(event) => handleModeKeyDown(event, mode, selectMode)}
        role="tab"
        tabIndex={mode === option ? 0 : -1}
        type="button"
      >{label}</button>)}
    </div>

    <div aria-labelledby={`roster-mode-${mode}`} className="roster-view" id="team-roster-view" role="tabpanel">
      {mode === "alignment" && <TeamRosterAlignment roster={roster} query={query} onQueryChange={changeQuery} onNavigate={onNavigate} />}
      {mode === "roster" && <TeamRosterBiography roster={roster} query={query} onQueryChange={changeQuery} onNavigate={onNavigate} />}
      {mode === "analysis" && <TeamRosterAnalysis roster={roster} query={query} onQueryChange={changeQuery} onNavigate={onNavigate} />}
      {roster.warnings.map((warning) => <p className="roster-warning" key={warning}>{warning}</p>)}
    </div>
  </section>;
}

function readMode(teamId: number): RosterMode {
  try {
    const stored = window.sessionStorage.getItem(storageKey(teamId));
    return stored === "roster" || stored === "analysis" ? stored : "alignment";
  } catch {
    return "alignment";
  }
}

function storageKey(teamId: number): string {
  return `football-data-hub:team-roster-mode:${teamId}`;
}

function queryStorageKey(teamId: number): string {
  return `football-data-hub:team-roster-query:${teamId}`;
}

function readQuery(teamId: number): string {
  try { return window.sessionStorage.getItem(queryStorageKey(teamId)) ?? ""; }
  catch { return ""; }
}

function handleModeKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentMode: RosterMode, selectMode: (mode: RosterMode) => void) {
  const currentIndex = modeOptions.findIndex((option) => option.mode === currentMode);
  const nextIndex = event.key === "ArrowRight" ? (currentIndex + 1) % modeOptions.length
    : event.key === "ArrowLeft" ? (currentIndex + modeOptions.length - 1) % modeOptions.length
      : event.key === "Home" ? 0
        : event.key === "End" ? modeOptions.length - 1
          : -1;
  if (nextIndex < 0) return;
  event.preventDefault();
  const nextMode = modeOptions[nextIndex]!.mode;
  selectMode(nextMode);
  document.getElementById(`roster-mode-${nextMode}`)?.focus();
}
