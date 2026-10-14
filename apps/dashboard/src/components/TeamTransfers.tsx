import { useEffect, useMemo, useState } from "react";
import { loadTeamTransfers, TeamTransfersApiError, type TeamTransfersLoadResult } from "../api/client";
import type { Team, TeamTransferRecord, TeamTransfers as TeamTransfersData } from "../api/contracts";
import { ProfileImage } from "./TeamRosterShared";
import { InternalTeamLink } from "./InternalTeamLink";

export function TeamTransfers({ teamId, season, teams, onNavigate }: { teamId: number; season: string; teams: readonly Team[]; onNavigate: (path: string) => void }) {
  const [result, setResult] = useState<TeamTransfersLoadResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    void loadTeamTransfers(teamId, season)
      .then((payload) => { if (current) setResult(payload); })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof TeamTransfersApiError ? reason.message : "No se pudieron cargar los Traspasos.");
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [retry, season, teamId]);

  const transfers = result?.status === "available" ? result.transfers : null;
  const normalizedQuery = normalize(query);
  const incoming = useMemo(
    () => filterRows(transfers?.incoming ?? [], normalizedQuery),
    [transfers, normalizedQuery],
  );
  const outgoing = useMemo(
    () => filterRows(transfers?.outgoing ?? [], normalizedQuery),
    [transfers, normalizedQuery],
  );

  return <section className="team-transfers" aria-label="Traspasos del equipo">
    <header className="team-profile-panel team-transfers-header">
      <div>
        <span className="section-kicker">LIGA · TEMPORADA {formatSeason(season)}</span>
        <h2>Traspasos</h2>
      </div>
      {transfers && <time dateTime={transfers.metadata.captured_at}>
        Captura {formatDate(transfers.metadata.captured_at)}
      </time>}
      {transfers && <label className="team-transfers-search">
        <span>Buscar futbolista o equipo</span>
        <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder="Nombre o equipo" />
      </label>}
    </header>

    {loading && <section className="team-profile-panel roster-state" role="status"><h2>Cargando Traspasos…</h2></section>}
    {!loading && error && <section className="team-profile-panel roster-state" role="alert">
      <h2>No se pudieron cargar los Traspasos</h2><p>{error}</p>
      <button className="primary-button" onClick={() => { setResult(null); setRetry((value) => value + 1); }} type="button">Reintentar</button>
    </section>}
    {!loading && !error && result?.status === "not_captured" && <section className="team-profile-panel roster-state" role="status">
      <h2>Traspasos aún no adquiridos</h2>
    </section>}
    {!loading && !error && transfers && <>
      <TransferTable title="Altas" columnLabel="Equipo de origen" rows={incoming} section={section(transfers, "incoming")} teams={teams} onNavigate={onNavigate} />
      <TransferTable title="Bajas" columnLabel="Equipo de destino" rows={outgoing} section={section(transfers, "outgoing")} teams={teams} onNavigate={onNavigate} />
    </>}
  </section>;
}

function TransferTable({
  title,
  columnLabel,
  rows,
  section,
  teams,
  onNavigate,
}: {
  title: "Altas" | "Bajas";
  columnLabel: "Equipo de origen" | "Equipo de destino";
  rows: TeamTransferRecord[];
  section: TeamTransfersData["sections"][number];
  teams: readonly Team[];
  onNavigate: (path: string) => void;
}) {
  return <section className="team-profile-panel team-transfers-panel" aria-labelledby={`transfers-${section.direction}`}>
    <div className="team-transfers-section-heading">
      <h3 id={`transfers-${section.direction}`}>{title}</h3>
      <span>{section.row_count}</span>
    </div>
    {section.status === "verified_empty" ? (
      <p className="team-transfers-empty">No hay movimientos publicados en esta sección para la captura seleccionada.</p>
    ) : rows.length === 0 ? (
      <p className="team-transfers-empty" role="status">No hay resultados para la búsqueda.</p>
    ) : (
      <div className="team-transfers-table-scroll">
        <table className="team-transfers-table">
          <thead><tr>
            <th scope="col">Foto</th>
            <th scope="col">Futbolista</th>
            <th scope="col">Nombre completo</th>
            <th scope="col">Edad</th>
            <th scope="col">Demarcación</th>
            <th scope="col">{columnLabel}</th>
          </tr></thead>
          <tbody>{rows.map((row) => <TransferRow key={`${row.direction}:${row.player_id}`} row={row} teams={teams} onNavigate={onNavigate} />)}</tbody>
        </table>
      </div>
    )}
  </section>;
}

function TransferRow({ row, teams, onNavigate }: { row: TeamTransferRecord; teams: readonly Team[]; onNavigate: (path: string) => void }) {
  const relatedTeam = row.other_team_id === null ? undefined : teams.find((team) => team.team_id === row.other_team_id);
  return <tr>
    <td><ProfileImage src={row.player_photo_url} name={row.player_display_name} className="team-transfer-photo" /></td>
    <td><a href={row.player_profile_url} target="_blank" rel="noreferrer">{row.player_display_name}</a></td>
    <td>{row.player_full_name ?? "—"}</td>
    <td>{row.age_years ?? "—"}</td>
    <td>{row.source_position_code ? `Código ${row.source_position_code} · sin equivalencia validada` : "—"}</td>
    <td>{row.other_team_name
      ? relatedTeam
        ? <InternalTeamLink teamId={relatedTeam.team_id} onNavigate={onNavigate}>{relatedTeam.name}</InternalTeamLink>
        : row.other_team_url
          ? <a href={row.other_team_url} target="_blank" rel="noreferrer" title="Referencia histórica de BDFutbol" aria-label={`${row.other_team_name} · referencia histórica de BDFutbol`}>
            {row.other_team_name} <span aria-hidden="true">↗</span>
          </a>
          : row.other_team_name
      : "—"}</td>
  </tr>;
}

function section(transfers: TeamTransfersData, direction: "incoming" | "outgoing") {
  return transfers.sections.find((item) => item.direction === direction)!;
}

function filterRows(rows: TeamTransferRecord[], query: string): TeamTransferRecord[] {
  if (!query) return rows;
  return rows.filter((row) => normalize([
    row.player_display_name,
    row.player_full_name ?? "",
    row.other_team_name ?? "",
  ].join(" ")).includes(query));
}

function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-ES").trim();
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value));
}

function formatSeason(value: string): string {
  return value.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
}
