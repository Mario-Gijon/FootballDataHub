import type { MouseEvent, ReactNode } from "react";
import type { PlayerDetail } from "../api/contracts";
import { teamPath } from "../domain/teams";
import { ProfileImage } from "./TeamRosterShared";

export function PlayerIdentityPanel({ detail, onNavigate }: { detail: PlayerDetail; onNavigate: (path: string) => void }) {
  const identity = detail.identity;
  const clubReference = detail.club_reference;
  const referenceTeamId = clubReference.status === "observed" ? clubReference.team_id : null;
  const referenceTeamName = clubReference.status === "observed" ? clubReference.team_name : null;
  const name = identity.display_name || detail.player.display_name || `Jugador ${detail.player.player_id}`;
  const birthplace = identity.birth_place
    ? `${identity.birth_place}${identity.birthplace_province ? ` (${identity.birthplace_province})` : ""}`
    : identity.birthplace_province;
  const facts: Array<[string, ReactNode]> = [
    ["Fecha de nacimiento", identity.birth_date ? formatDateOnly(identity.birth_date) : null],
    ["Edad", identity.age_years],
    ["Lugar de nacimiento", birthplace || null],
    ["País de nacimiento", identity.country_of_birth],
    ["Nacionalidad", identity.nationality],
    ["Altura", identity.height_cm === null ? null : `${identity.height_cm} cm`],
    ["Peso", identity.weight_kg === null ? null : `${identity.weight_kg} kg`],
  ];

  return <header className="player-detail-hero">
    <ProfileImage src={detail.player.photo_url} name={name} className="player-detail-photo" />
    <div className="player-detail-primary">
      <h1>{name}</h1>
      {identity.full_name && identity.full_name !== name && <p className="player-detail-full-name">{identity.full_name}</p>}
      {identity.position_name && <span className="player-position-label">{identity.position_name}</span>}
      {referenceTeamId !== null && referenceTeamName && <p className="player-reference-team">
        <span>Equipo de referencia</span>
        <a href={teamPath(referenceTeamId)} onClick={(event) => navigateTeam(event, referenceTeamId, onNavigate)}>
          {referenceTeamName}{clubReference.group ? ` · Grupo ${clubReference.group}` : ""}
        </a>
      </p>}
      <dl className="player-detail-facts">
        {facts.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => <div key={label}>
          <dt>{label}</dt><dd>{value}</dd>
        </div>)}
      </dl>
      {detail.player.profile_url && <a className="external-player-link" href={detail.player.profile_url} target="_blank" rel="noreferrer">BDFutbol ↗</a>}
    </div>
  </header>;
}

function navigateTeam(event: MouseEvent<HTMLAnchorElement>, teamId: number, onNavigate: (path: string) => void) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  onNavigate(teamPath(teamId));
}

function formatDateOnly(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return `${String(day).padStart(2, "0")}/${String(month).padStart(2, "0")}/${year}`;
}
