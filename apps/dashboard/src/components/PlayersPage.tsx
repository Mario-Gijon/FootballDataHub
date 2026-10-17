import { useEffect, useState } from "react";
import { loadPlayerDetail, loadPlayerDirectory } from "../api/client";
import type { PlayerDetail, PlayerDirectory, PlayerIndexRecord } from "../api/contracts";
import { navigateOnPlainClick } from "../domain/internal-navigation";
import type { CatalogTeam } from "../domain/teams";
import { InternalPlayerLink } from "./InternalPlayerLink";
import { InternalTeamLink } from "./InternalTeamLink";
import { ProfileImage } from "./TeamRosterShared";
import { PlayerIdentityPanel } from "./PlayerIdentityPanel";
import { PlayerIndividualViews } from "./PlayerIndividualViews";

interface Props {
  playerId: number | null;
  teams: readonly CatalogTeam[];
  onNavigate: (path: string) => void;
}

export function PlayersPage({ playerId, teams, onNavigate }: Props) {
  const [directory, setDirectory] = useState<PlayerDirectory | null>(null);
  const [detail, setDetail] = useState<PlayerDetail | null>(null);
  const [query, setQuery] = useState(() => readDirectoryState().query);
  const [group, setGroup] = useState<"all" | "I" | "II">(() => readDirectoryState().group);
  const [teamId, setTeamId] = useState(() => readDirectoryState().teamId);
  const [page, setPage] = useState(() => readDirectoryState().page);
  const [retryNonce, setRetryNonce] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    try { window.sessionStorage.setItem("football-data-hub:players-directory", JSON.stringify({ query, group, teamId, page })); }
    catch { /* Filters remain usable for the current session. */ }
  }, [query, group, teamId, page]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    if (playerId !== null) {
      setDetail(null);
      void loadPlayerDetail(playerId, controller.signal)
        .then(setDetail)
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) setError(messageOf(reason));
        })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    } else {
      setDirectory(null);
      const timeout = window.setTimeout(() => {
        void loadPlayerDirectory({
          q: query,
          group: group === "all" ? undefined : group,
          teamId: teamId === "all" ? undefined : Number(teamId),
          page,
          pageSize: 25,
        }, controller.signal)
          .then(setDirectory)
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) setError(messageOf(reason));
          })
          .finally(() => { if (!controller.signal.aborted) setLoading(false); });
      }, 180);
      return () => {
        window.clearTimeout(timeout);
        controller.abort();
      };
    }
    return () => controller.abort();
  }, [playerId, query, group, teamId, page, retryNonce]);

  if (playerId !== null) {
    return <PlayerDetailPage detail={detail} loading={loading} error={error} teams={teams} onNavigate={onNavigate} />;
  }

  const filteredTeams = (directory?.available_teams ?? []).filter((team) => group === "all" || team.group === group);
  const pages = directory ? Math.max(1, Math.ceil(directory.total / directory.page_size)) : 1;
  return (
    <main className="dashboard-main players-page">
      <header className="teams-page-heading">
        <div><span className="section-kicker">PRIMERA FEDERACIÓN · 2026/27</span><h1>Jugadores</h1>
          <p>Consulta futbolistas relacionados con los clubes de Primera Federación.</p></div>
      </header>

      <section className="players-toolbar" aria-label="Buscar jugadores">
        <label className="players-search"><span>Buscar jugador</span><input type="search" value={query} onChange={(event) => { setQuery(event.currentTarget.value); setPage(1); }} placeholder="Nombre, posición, nacionalidad o equipo" /></label>
        <label><span>Grupo</span><select aria-label="Filtrar por grupo" value={group} onChange={(event) => { setGroup(event.currentTarget.value as typeof group); setTeamId("all"); setPage(1); }}>
          <option value="all">Todos</option><option value="I">Grupo I</option><option value="II">Grupo II</option>
        </select></label>
        <label className="players-team-filter"><span>Equipo relacionado</span><select aria-label="Filtrar por equipo relacionado" value={teamId} onChange={(event) => { setTeamId(event.currentTarget.value); setPage(1); }}>
          <option value="all">Todos los equipos</option>{filteredTeams.map((team) => <option key={`${team.group}-${team.team_id}`} value={team.team_id}>{team.team_name} · Grupo {team.group}</option>)}
        </select></label>
      </section>
      <p className="players-filter-note">Filtra por grupo y equipo relacionado durante la temporada.</p>

      {error ? <section className="state-card error-card" role="alert"><h2>No se pudo cargar el inventario</h2><p>{error}</p><button className="primary-button" onClick={() => setRetryNonce((current) => current + 1)} type="button">Reintentar</button></section>
        : loading ? <div className="state-card" role="status">Cargando jugadores…</div>
          : directory && <>
            <div className="players-list-meta"><span>{directory.total.toLocaleString("es-ES")} resultados</span></div>
            <section className="players-grid" aria-label="Resultados de jugadores">
              {directory.players.map((player) => <PlayerCard key={player.player_id} player={player} directory={directory} onNavigate={onNavigate} />)}
              {directory.players.length === 0 && <p className="players-empty">No hay jugadores para estos filtros.</p>}
            </section>
            <nav className="players-pagination" aria-label="Páginas de jugadores">
              <button type="button" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>Anterior</button>
              <span>Página {page} de {pages}</span>
              <button type="button" disabled={page >= pages} onClick={() => setPage((current) => Math.min(pages, current + 1))}>Siguiente</button>
            </nav>
          </>}
    </main>
  );
}

function PlayerCard({ player, directory, onNavigate }: { player: PlayerIndexRecord; directory: PlayerDirectory; onNavigate: (path: string) => void }) {
  const name = player.display_name || `ID ${player.player_id}`;
  const availableTeams = new Map(directory.available_teams.map((team) => [team.team_id, team]));
  return <article className="player-card">
    <InternalPlayerLink className="player-card-link" playerId={player.player_id} onNavigate={onNavigate}>
      <ProfileImage src={player.photo_url} name={name} className="player-card-photo" />
      <span className="player-card-main"><strong>{name}</strong>{player.full_name && player.full_name !== player.display_name && <small>{player.full_name}</small>}
        {player.position_name && <span className="player-card-tags"><em>{player.position_name}</em></span>}
      </span>
    </InternalPlayerLink>
    {player.nationality && <div className="player-card-meta"><span>{player.nationality}</span></div>}
    <div className="player-card-teams">{player.team_associations.map((association) => {
      const team = availableTeams.get(association.team_id);
      const verified = team?.group === association.group;
      return <span key={`${association.group}-${association.team_id}`}>
        {verified
          ? <InternalTeamLink teamId={team.team_id} onNavigate={onNavigate}>{team.team_name} · Grupo {team.group}</InternalTeamLink>
          : `${association.team_name} · Grupo ${association.group}`}
      </span>;
    })}</div>
  </article>;
}

function PlayerDetailPage({ detail, loading, error, teams, onNavigate }: { detail: PlayerDetail | null; loading: boolean; error: string; teams: readonly CatalogTeam[]; onNavigate: (path: string) => void }) {
  if (loading) return <main className="dashboard-main players-page"><div className="state-card" role="status">Cargando ficha…</div></main>;
  if (error || !detail) return <main className="dashboard-main players-page"><section className="state-card error-card" role="alert"><a href="/players" onClick={(event) => navigateOnPlainClick(event, "/players", onNavigate)}>← Jugadores</a><h1>No se pudo cargar la ficha</h1><p>{error || "El jugador no está en el inventario."}</p></section></main>;
  return <main className="dashboard-main players-page player-detail-page">
    <a className="player-back-link" href="/players" onClick={(event) => navigateOnPlainClick(event, "/players", onNavigate)}>← Volver a Jugadores</a>
    <PlayerIdentityPanel detail={detail} teams={teams} onNavigate={onNavigate} />
    <PlayerIndividualViews
      key={detail.player.player_id}
      playerId={detail.player.player_id}
      views={detail.verified_individual_views}
      movement={detail.movement_resolution === "identified" ? detail.last_observed_movement : null}
      teams={teams}
      onNavigate={onNavigate}
    />
    {detail.verified_individual_views.length === 0 && <p className="player-data-empty">Todavía no hay una trayectoria individual disponible para esta ficha.</p>}
  </main>;
}

function messageOf(error: unknown): string { return error instanceof Error ? error.message : "Error desconocido."; }

type PlayerDirectoryFilters = { query: string; group: "all" | "I" | "II"; teamId: string; page: number };

function readDirectoryState(): PlayerDirectoryFilters {
  const fallback: PlayerDirectoryFilters = { query: "", group: "all", teamId: "all", page: 1 };
  try {
    const value = JSON.parse(window.sessionStorage.getItem("football-data-hub:players-directory") ?? "null") as Partial<PlayerDirectoryFilters> | null;
    return {
      query: typeof value?.query === "string" ? value.query : fallback.query,
      group: value?.group === "I" || value?.group === "II" ? value.group : "all",
      teamId: value?.teamId === "all" || (typeof value?.teamId === "string" && /^[1-9]\d*$/.test(value.teamId)) ? value.teamId : "all",
      page: typeof value?.page === "number" && Number.isSafeInteger(value.page) && value.page > 0 ? value.page : 1,
    };
  } catch { return fallback; }
}
