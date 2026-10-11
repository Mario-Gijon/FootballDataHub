import { useState, type CSSProperties } from "react";
import type { TeamRoster } from "../api/contracts";

interface Props {
  roster: TeamRoster;
  playersById: Map<number, TeamRoster["players"][number]>;
}

export function TeamTacticalPitch({ roster, playersById }: Props) {
  const tactic = roster.tactical_visualization;

  return (
    <section className="team-profile-panel tactical-panel" aria-labelledby="team-tactical-title">
      <div className="section-heading team-profile-panel-heading">
        <div><span className="section-kicker">DISPOSICIÓN PUBLICADA</span><h2 id="team-tactical-title">Táctica</h2></div>
        {tactic && <span className="team-summary-source">{tactic.positions.length} posiciones enlazadas</span>}
      </div>
      {tactic ? (
        <>
          <div className="team-tactical-pitch" role="group" aria-label="Representación aproximada de la táctica">
            <svg aria-hidden="true" className="team-tactical-markings" viewBox="0 0 100 60" preserveAspectRatio="none">
              <rect x="1" y="1" width="98" height="58" rx="1.5" />
              <line x1="50" y1="1" x2="50" y2="59" />
              <circle cx="50" cy="30" r="8" />
              <circle cx="50" cy="30" r="0.7" className="tactical-center-spot" />
              <rect x="1" y="15" width="14" height="30" />
              <rect x="1" y="22" width="5" height="16" />
              <rect x="85" y="15" width="14" height="30" />
              <rect x="94" y="22" width="5" height="16" />
              <path d="M15 24 A8 8 0 0 1 15 36" />
              <path d="M85 24 A8 8 0 0 0 85 36" />
            </svg>
            <div className="team-tactical-markers">
              {tactic.positions.map((position) => {
                const player = playersById.get(position.player_id);
                if (!player) return null;
                const placement: CSSProperties = { left: `${position.horizontal * 100}%`, top: `${position.vertical * 100}%` };
                return (
                  <article className="tactical-player-marker" data-player-id={player.player_id} key={player.player_id} style={placement}>
                    <TacticalPlayerPhoto src={player.photo_url} name={player.display_name} />
                    <span>{player.display_name}</span>
                  </article>
                );
              })}
            </div>
          </div>
          <p className="tactical-disclaimer">Representación aproximada basada en los datos de origen. No corresponde necesariamente al dibujo táctico real.</p>
        </>
      ) : (
        <p className="team-state roster-empty-group">Esta captura no contiene posiciones tácticas enlazadas de forma fiable a sus titulares.</p>
      )}
    </section>
  );
}

function TacticalPlayerPhoto({ src, name }: { src: string | null; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className="tactical-player-photo profile-image-fallback" aria-label={`Sin fotografía para ${name}`}>{initials(name)}</span>;
  return <img className="tactical-player-photo" src={src} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

function initials(name: string): string {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toLocaleUpperCase("es-ES");
}
