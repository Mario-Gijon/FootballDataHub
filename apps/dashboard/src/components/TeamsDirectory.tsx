import { useMemo, useState } from "react";
import type { CompetitionGroup } from "../api/client";
import type { LoadState } from "../domain/teams-ui";
import { searchTeams, type CatalogTeam } from "../domain/teams";
import { TeamCard } from "./TeamCard";

export type TeamLoadState = LoadState;

interface Props {
  teams: CatalogTeam[];
  loadState: Record<CompetitionGroup, TeamLoadState>;
  errors: Record<CompetitionGroup, string>;
  catalogError: string;
  onRetry: (group: CompetitionGroup) => void;
  onNavigate: (path: string) => void;
}

type GroupFilter = "all" | CompetitionGroup;

export function TeamsDirectory({ teams, loadState, errors, catalogError, onRetry, onNavigate }: Props) {
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState<GroupFilter>("all");
  const counts = useMemo(() => ({
    all: teams.length,
    "1": teams.filter((team) => team.group === "1").length,
    "2": teams.filter((team) => team.group === "2").length,
  }), [teams]);
  const filtered = useMemo(
    () => searchTeams(groupFilter === "all" ? teams : teams.filter((team) => team.group === groupFilter), query),
    [groupFilter, query, teams],
  );
  const loading = (["1", "2"] as const).some((group) => loadState[group] === "loading" || loadState[group] === "idle");
  const allUnavailable = teams.length === 0 && (["1", "2"] as const).every((group) => loadState[group] === "error");

  return (
    <main className="dashboard-main teams-page">
      <header className="teams-page-heading">
        <div>
          <span className="section-kicker">PRIMERA FEDERACIÓN</span>
          <h1>Equipos</h1>
          <p>Temporada 2026/27 · {teams.length} {teams.length === 1 ? "equipo disponible" : "equipos disponibles"}</p>
        </div>
      </header>

      <section className="teams-toolbar" aria-label="Buscar y filtrar equipos">
        <label className="team-search">
          <span aria-hidden="true" className="team-search-icon">⌕</span>
          <span className="visually-hidden">Buscar equipo</span>
          <input type="search" placeholder="Buscar equipo..." value={query} onChange={(event) => setQuery(event.currentTarget.value)} />
        </label>
        <div className="team-group-filter" role="group" aria-label="Filtrar por grupo">
          {([
            ["all", "Todos"], ["1", "Grupo I"], ["2", "Grupo II"],
          ] as const).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={groupFilter === value} className={groupFilter === value ? "is-active" : ""} onClick={() => setGroupFilter(value)}>
              {label}<span>{counts[value]}</span>
            </button>
          ))}
        </div>
      </section>

      {catalogError && <div className="team-state team-error" role="alert">{catalogError}</div>}
      {(["1", "2"] as const).map((group) => loadState[group] === "error" && (
        <div className="team-group-error" role="status" key={group}>
          <span>Grupo {group === "1" ? "I" : "II"}: {errors[group] || "No se pudieron cargar sus equipos."}</span>
          <button type="button" onClick={() => onRetry(group)}>Reintentar</button>
        </div>
      ))}

      {allUnavailable ? (
        <div className="team-state" role="status">No hay datos de equipos disponibles. Comprueba la conexión con la API.</div>
      ) : teams.length === 0 && loading ? (
        <div className="team-state" role="status">Cargando los catálogos de equipos…</div>
      ) : filtered.length > 0 ? (
        <section className="team-grid" aria-label="Directorio de equipos">
          {filtered.map((team) => <TeamCard key={team.team_id} team={team} onNavigate={onNavigate} />)}
        </section>
      ) : groupFilter !== "all" && counts[groupFilter] === 0 && loading ? (
        <div className="team-state" role="status">Cargando los equipos del Grupo {groupFilter === "1" ? "I" : "II"}…</div>
      ) : teams.length === 0 ? (
        <div className="team-state" role="status">No hay datos cargados para este grupo.</div>
      ) : (
        <div className="team-state" role="status">No hay equipos que coincidan con la búsqueda.</div>
      )}
    </main>
  );
}
