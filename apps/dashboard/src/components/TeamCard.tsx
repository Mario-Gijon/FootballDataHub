import { useState } from "react";
import type { CatalogTeam } from "../domain/teams";
import { InternalTeamLink } from "./InternalTeamLink";

interface Props {
  team: CatalogTeam;
  onNavigate: (path: string) => void;
}

export function TeamCard({ team, onNavigate }: Props) {
  return (
    <InternalTeamLink
      className={`team-card ${team.team_id === 49 ? "is-jaen-team" : ""}`.trim()}
      teamId={team.team_id}
      onNavigate={onNavigate}
      aria-label={`Abrir ficha de ${team.name}, Grupo ${team.group === "1" ? "I" : "II"}`}
    >
      <TeamCrest name={team.name} crestUrl={team.crest_url} />
      <span className="team-card-copy">
        <strong>{team.name}</strong>
        <small>Grupo {team.group === "1" ? "I" : "II"}</small>
      </span>
      <span className="team-card-arrow" aria-hidden="true">↗</span>
    </InternalTeamLink>
  );
}

export function TeamCrest({ name, crestUrl, className = "" }: { name: string; crestUrl: string | null; className?: string }) {
  const [failed, setFailed] = useState(false);
  const [initial, ...rest] = name.trim().split(/\s+/);
  const initials = `${initial?.[0] ?? ""}${rest[0]?.[0] ?? ""}`.toLocaleUpperCase("es-ES");
  return crestUrl && !failed ? (
    <img className={`team-card-crest ${className}`.trim()} src={crestUrl} alt="" loading="lazy" onError={() => setFailed(true)} />
  ) : (
    <span className={`team-card-crest-fallback ${className}`.trim()} aria-hidden="true">{initials || "•"}</span>
  );
}
