import { useEffect, useState, type MouseEvent } from "react";
import { loadPlayerDetail, loadPlayerDirectory } from "../api/client";
import type { PlayerDetail, PlayerDirectory, PlayerIndexRecord } from "../api/contracts";
import { ProfileImage } from "./TeamRosterShared";
import { PlayerIndividualViews } from "./PlayerIndividualViews";

interface Props {
  playerId: number | null;
  onNavigate: (path: string) => void;
}

export function PlayersPage({ playerId, onNavigate }: Props) {
  const [directory, setDirectory] = useState<PlayerDirectory | null>(null);
  const [detail, setDetail] = useState<PlayerDetail | null>(null);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<"all" | "I" | "II">("all");
  const [teamId, setTeamId] = useState("all");
  const [page, setPage] = useState(1);
  const [retryNonce, setRetryNonce] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
    return <PlayerDetailPage detail={detail} loading={loading} error={error} onNavigate={onNavigate} />;
  }

  const filteredTeams = (directory?.available_teams ?? []).filter((team) => group === "all" || team.group === group);
  const pages = directory ? Math.max(1, Math.ceil(directory.total / directory.page_size)) : 1;
  return (
    <main className="dashboard-main players-page">
      <header className="teams-page-heading">
        <div><span className="section-kicker">PRIMERA FEDERACIÓN · 2026/27</span><h1>Jugadores</h1>
          <p>Inventario consolidado por ID de BDFutbol. Las relaciones de equipo proceden de las capturas disponibles.</p></div>
        {directory && <div className="players-coverage" aria-label="Cobertura del inventario">
          <strong>{directory.metadata.inventory_player_count.toLocaleString("es-ES")}</strong><span>IDs inventariados</span>
          <small>{directory.metadata.complete_individual_profile_count.toLocaleString("es-ES")} compactos con cuatro vistas publicadas · {directory.metadata.inventory_only_count.toLocaleString("es-ES")} sin compacto individual publicado</small>
        </div>}
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
      <p className="players-filter-note">El filtro de equipo incluye pertenencias observadas y referencias de traspasos; no acredita afiliación actual.</p>

      {error ? <section className="state-card error-card" role="alert"><h2>No se pudo cargar el inventario</h2><p>{error}</p><button className="primary-button" onClick={() => setRetryNonce((current) => current + 1)} type="button">Reintentar</button></section>
        : loading ? <div className="state-card" role="status">Cargando jugadores…</div>
          : directory && <>
            <div className="players-list-meta"><span>{directory.total.toLocaleString("es-ES")} resultados</span><span>Inventario generado {formatDate(directory.metadata.inventory_generated_at)}</span></div>
            <section className="players-grid" aria-label="Resultados de jugadores">
              {directory.players.map((player) => <PlayerCard key={player.player_id} player={player} onNavigate={onNavigate} />)}
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

function PlayerCard({ player, onNavigate }: { player: PlayerIndexRecord; onNavigate: (path: string) => void }) {
  const status = player.association_status === "roster_membership_observed" ? "Pertenencia observada" : "Referencia de traspaso";
  const name = player.display_name || `ID ${player.player_id}`;
  return <article className="player-card">
    <a className="player-card-link" href={`/players/${player.player_id}`} onClick={(event) => navigate(event, `/players/${player.player_id}`, onNavigate)}>
      <ProfileImage src={player.photo_url} name={name} className="player-card-photo" />
      <span className="player-card-main"><strong>{name}</strong>{player.full_name && player.full_name !== player.display_name && <small>{player.full_name}</small>}
        <span className="player-card-tags">{player.position_name && <em>{player.position_name}</em>}<em>{player.profile_status === "four_views_verified" ? "4 vistas publicadas" : player.profile_status === "partial_individual_views" ? "Perfil compacto parcial" : "Solo inventario publicado"}</em></span>
      </span>
    </a>
    <div className="player-card-meta"><span>{player.nationality ?? "Nacionalidad no observada"}</span><span>{status}</span></div>
    <div className="player-card-teams">{player.team_associations.map((team) => <span key={`${team.group}-${team.team_id}`}>{team.team_name} · {team.group}</span>)}</div>
  </article>;
}

function PlayerDetailPage({ detail, loading, error, onNavigate }: { detail: PlayerDetail | null; loading: boolean; error: string; onNavigate: (path: string) => void }) {
  if (loading) return <main className="dashboard-main players-page"><div className="state-card" role="status">Cargando ficha…</div></main>;
  if (error || !detail) return <main className="dashboard-main players-page"><section className="state-card error-card" role="alert"><a href="/players" onClick={(event) => navigate(event, "/players", onNavigate)}>← Jugadores</a><h1>No se pudo cargar la ficha</h1><p>{error || "El jugador no está en el inventario."}</p></section></main>;
  const { player } = detail;
  const name = player.display_name || `ID ${player.player_id}`;
  return <main className="dashboard-main players-page player-detail-page">
    <a className="player-back-link" href="/players" onClick={(event) => navigate(event, "/players", onNavigate)}>← Volver a Jugadores</a>
    <header className="player-detail-hero">
      <ProfileImage src={player.photo_url} name={name} className="player-detail-photo" />
      <div><span className="section-kicker">FICHA DE JUGADOR · ID {player.player_id}</span><h1>{name}</h1>
        {player.full_name && player.full_name !== player.display_name && <p>{player.full_name}</p>}
        <div className="player-detail-tags"><span>{statusLabel(player)}</span><span>{player.profile_status === "four_views_verified" ? "Cuatro vistas individuales publicadas" : player.profile_status === "partial_individual_views" ? "Vistas individuales parciales" : "Sin compacto individual publicado"}</span></div>
        {player.profile_url && <a className="external-player-link" href={player.profile_url} target="_blank" rel="noreferrer">Perfil original de BDFutbol ↗</a>}
      </div>
    </header>
    <section className="player-detail-grid">
      <article className="player-info-panel"><h2>Identidad y relaciones</h2>
        <dl><dt>Fecha de nacimiento</dt><dd>{player.birth_date ? formatDateOnly(player.birth_date) : "—"}</dd><dt>Edad publicada</dt><dd>{player.age_years ?? "—"}</dd><dt>Lugar de nacimiento</dt><dd>{[detail.birth_place, detail.birthplace_province].filter(Boolean).join(", ") || "—"}</dd><dt>Nacionalidad</dt><dd>{player.nationality ?? "—"}</dd><dt>Posición</dt><dd>{player.position_name ?? "—"}</dd><dt>Grupo observado</dt><dd>{player.groups.map((item) => `Grupo ${item}`).join(" · ") || "—"}</dd></dl>
        <h3>Equipos relacionados</h3>{detail.associations.length ? <ul className="player-association-list">{detail.associations.map((association) => <li key={`${association.group}-${association.team_id}`}><strong>{association.team_name}</strong><span>Grupo {association.group} · {association.evidence_types.map(associationLabel).join(" · ")}</span></li>)}</ul> : <p>No hay relaciones de equipo observadas.</p>}
      </article>
      <article className="player-info-panel"><h2>Estadísticas de temporada disponibles</h2>{detail.season_statistics.length ? <div className="player-table-scroll"><table className="player-data-table"><thead><tr><th>Equipo</th><th>PJ</th><th>Tit.</th><th>Min.</th><th>Goles</th><th>TA</th><th>TR</th></tr></thead><tbody>{detail.season_statistics.map((stat, index) => <tr key={`${stat.group}-${stat.team_id}-${stat.source_view}-${index}`}><td>{stat.team_name ?? "—"} · {stat.group}</td><td>{show(stat.matches_played)}</td><td>{show(stat.starts)}</td><td>{show(stat.minutes_played)}</td><td>{show(stat.goals)}</td><td>{show(stat.yellow_cards)}</td><td>{show(stat.red_cards)}</td></tr>)}</tbody></table></div> : <p>No hay estadísticas normalizadas disponibles.</p>}
        <h3>Datos por partido</h3><p className="player-data-note">Se muestran solo valores numéricos presentes en las capturas de Seguimiento.</p>{detail.match_minutes.length + detail.match_metrics.length ? <div className="player-table-scroll"><table className="player-data-table"><thead><tr><th>Jornada</th><th>Equipo</th><th>Métrica</th><th>Valor</th><th>Estado fuente</th></tr></thead><tbody>{[...detail.match_minutes, ...detail.match_metrics].map((metric, index) => <tr key={`${metric.group}-${metric.team_id}-${metric.match_id}-${metric.metric}-${index}`}><td>J{metric.matchday}</td><td>{metric.team_name ?? "—"}</td><td>{metricLabel(metric.metric)}</td><td>{metric.value}</td><td>{metric.source_state || "—"}</td></tr>)}</tbody></table></div> : <p>No hay registros por partido disponibles.</p>}
      </article>
    </section>
    {detail.transfer_references.length > 0 && <section className="player-info-panel"><h2>Referencias de traspasos</h2><ul className="player-association-list">{detail.transfer_references.map((item, index) => <li key={`${item.team_id}-${item.group}-${item.direction}-${index}`}><strong>{item.direction === "incoming" ? "Alta" : "Baja"} · {item.team_name ?? "Equipo no indicado"}</strong><span>{item.other_team_name ?? "Origen o destino no observado"} · Grupo {item.group}{item.age_years === null ? "" : ` · ${item.age_years} años`}</span></li>)}</ul></section>}
    <PlayerIndividualViews views={detail.verified_individual_views} />
    {detail.warnings.map((warning, index) => <p className="roster-warning" key={index}>{warning}</p>)}
  </main>;
}

function navigate(event: MouseEvent<HTMLAnchorElement>, path: string, onNavigate: (path: string) => void) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  onNavigate(path);
}

function messageOf(error: unknown): string { return error instanceof Error ? error.message : "Error desconocido."; }
function show(value: string | number | boolean | null): string { return value === null || value === undefined || value === "" ? "—" : String(value); }
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeZone: "Europe/Madrid" }).format(new Date(value)) : "—"; }
function formatDateOnly(value: string): string { const [year, month, day] = value.split("-").map(Number); return `${day}/${month}/${year}`; }
function statusLabel(player: PlayerIndexRecord): string { return player.association_status === "roster_membership_observed" ? "Pertenencia de plantilla observada" : "Referencia únicamente en traspasos"; }
function associationLabel(value: string): string { return value === "membership" ? "Plantilla observada" : "Referencia de traspaso"; }
function metricLabel(value: string | null): string { return value ? ({ minutes_played: "Minutos", goals: "Goles", yellow_cards: "Amarillas", red_cards: "Rojas", assists: "Asistencias" } as Record<string, string>)[value] ?? value : "—"; }
