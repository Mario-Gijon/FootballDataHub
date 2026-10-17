import type { ReactNode } from "react";
import type { PlayerDetail } from "../api/contracts";
import type { CatalogTeam } from "../domain/teams";
import { InternalTeamLink } from "./InternalTeamLink";
import { ProfileImage } from "./TeamRosterShared";

export function PlayerIdentityPanel({ detail, teams, onNavigate }: { detail: PlayerDetail; teams: readonly CatalogTeam[]; onNavigate: (path: string) => void }) {
  const identity = detail.identity;
  const clubReference = detail.club_reference;
  const referenceTeamId = clubReference.status === "observed" ? clubReference.team_id : null;
  const referenceTeamName = clubReference.status === "observed" ? clubReference.team_name : null;
  const referenceTeam = referenceTeamId === null ? undefined : teams.find((team) => team.team_id === referenceTeamId);
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
        {referenceTeam
          ? <InternalTeamLink teamId={referenceTeam.team_id} onNavigate={onNavigate}>{referenceTeam.name} · Grupo {referenceTeam.group === "1" ? "I" : "II"}</InternalTeamLink>
          : <span>{referenceTeamName}{clubReference.group ? ` · Grupo ${clubReference.group}` : ""}</span>}
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

function formatDateOnly(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return `${String(day).padStart(2, "0")}/${String(month).padStart(2, "0")}/${year}`;
}
