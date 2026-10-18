import { useEffect, useState } from "react";
import { loadLocalMatchPreview, loadMatchPage, MatchPageApiError } from "../api/client";
import type { MatchPage as MatchPageData } from "../api/contracts";
import { navigateOnPlainClick } from "../domain/internal-navigation";
import { InternalTeamLink } from "./InternalTeamLink";
import { InternalPlayerLink } from "./InternalPlayerLink";
import { TeamCrest } from "./TeamCard";
import { ProfileImage } from "./TeamRosterShared";

type PublishedDetails = NonNullable<MatchPageData["details"]>;
type PublishedPlayer = NonNullable<PublishedDetails["home"]["starters"]>[number];
type MatchEventKind = NonNullable<PublishedDetails["events"]>[number]["event_kind"];
type MatchEvent = NonNullable<PublishedDetails["events"]>[number];

interface Props {
  internalId: string;
  localPreview?: boolean;
  onNavigate: (path: string) => void;
  onReturnToResults: () => void;
}

export function MatchPage({ internalId, localPreview = false, onNavigate, onReturnToResults }: Props) {
  const [page, setPage] = useState<MatchPageData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let current = true;
    setPage(null);
    setError("");
    setLoading(true);
    void (localPreview ? loadLocalMatchPreview(internalId) : loadMatchPage(internalId))
      .then((result) => { if (current) setPage(result); })
      .catch((reason: unknown) => {
        if (!current) return;
        const message = reason instanceof MatchPageApiError
          ? reason.message
          : reason instanceof Error ? reason.message : "No se pudo cargar el partido.";
        setError(message);
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [internalId, localPreview]);

  return (
    <main className="dashboard-main match-page">
      <a className="match-back-link" href="/" onClick={(event) => navigateOnPlainClick(event, "/", onReturnToResults)}>
        ← Volver a Resultados
      </a>
      {loading ? <section className="state-card" role="status"><h1>Cargando partido…</h1></section>
        : error || !page ? <section className="state-card error-card" role="alert">
          <h1>No se pudo cargar el partido</h1><p>{error || "El encuentro no está disponible en la generación publicada."}</p>
        </section>
          : <MatchPageContent page={page} onNavigate={onNavigate} />}
    </main>
  );
}

function MatchPageContent({ page, onNavigate }: { page: MatchPageData; onNavigate: (path: string) => void }) {
  const { match, metadata } = page;
  const played = match.status === "played";
  const hasFinalScore = played && match.home_goals !== null && match.away_goals !== null;
  const date = match.source_match_date ?? match.matchday_date;
  const dateLabel = match.source_match_date ? "Fecha" : "Fecha de jornada";
  const details = page.details;
  const hasPublishedContent = Boolean(details && (
    details.home.coach || details.away.coach ||
    Boolean(details.home.starters?.length || details.home.substitutes?.length || details.away.starters?.length || details.away.substitutes?.length) ||
    Boolean(details.events?.length)
  ));

  return <>
    {page.detail_status === "preview_only" && <div className="match-local-preview-banner" role="status">
      Vista previa local · datos exploratorios, no publicados
    </div>}
    <header className="match-page-hero">
      <div className="match-page-context">PRIMERA FEDERACIÓN · GRUPO {metadata.group} · TEMPORADA {formatSeason(metadata.season)}</div>
      <div className="match-page-scoreboard">
        <InternalTeamLink className="match-page-team" teamId={match.home_team.team_id} onNavigate={onNavigate}>
          <TeamCrest name={match.home_team.name} crestUrl={match.home_team.crest_url} className="match-page-crest" />
          <span>{match.home_team.name}</span>
        </InternalTeamLink>
        <div
          className={`match-page-score ${hasFinalScore ? "is-played" : match.status === "unplayed" ? "is-pending" : "is-incomplete"}`}
          aria-label={hasFinalScore ? `Resultado ${match.home_goals} a ${match.away_goals}` : match.status === "unplayed" ? "Partido pendiente" : "Marcador incompleto"}
        >
          {hasFinalScore ? <><strong>{match.home_goals}</strong><span>–</span><strong>{match.away_goals}</strong></>
            : <span>{match.status === "unplayed" ? "Pendiente" : "Datos incompletos"}</span>}
        </div>
        <InternalTeamLink className="match-page-team" teamId={match.away_team.team_id} onNavigate={onNavigate}>
          <TeamCrest name={match.away_team.name} crestUrl={match.away_team.crest_url} className="match-page-crest" />
          <span>{match.away_team.name}</span>
        </InternalTeamLink>
      </div>
      <div className="match-page-subtitle">
        {played && <span className="match-finished-label">Finalizado</span>}
        Jornada {match.matchday}{date ? ` · ${dateLabel.toLowerCase()} ${formatDate(date)}` : ""}
      </div>
    </header>

    {hasPublishedContent && details && details.events?.length
      ? <MatchHighlights events={details.events} homeName={match.home_team.name} awayName={match.away_team.name}
        homeTeamId={match.home_team.team_id} awayTeamId={match.away_team.team_id} onNavigate={onNavigate} />
      : null}

    <section className="match-page-panel match-info-panel" aria-labelledby="match-info-title">
      <div className="match-info-heading"><div><span className="section-kicker">ENCUENTRO</span><h1 id="match-info-title">Información del partido</h1></div></div>
      <dl className="match-info-grid">
        <div><dt>Jornada</dt><dd>{match.matchday}</dd></div>
        <div><dt>Grupo</dt><dd>{metadata.group}</dd></div>
        <div><dt>Temporada</dt><dd>{formatSeason(metadata.season)}</dd></div>
        {date && <div><dt>{dateLabel}</dt><dd><time dateTime={date}>{formatDate(date)}</time></dd></div>}
        <div><dt>Datos actualizados</dt><dd><time dateTime={metadata.source_captured_at}>{formatCaptureDate(metadata.source_captured_at)}</time></dd></div>
        {match.stadium_name && <div><dt>Estadio</dt><dd>{match.stadium_url
          ? <a href={match.stadium_url} target="_blank" rel="noreferrer">{match.stadium_name}</a>
          : match.stadium_name}</dd></div>}
        {match.referee_name && <div><dt>Árbitro</dt><dd>{match.referee_url
          ? <a href={match.referee_url} target="_blank" rel="noreferrer">{match.referee_name}</a>
          : match.referee_name}</dd></div>}
      </dl>
      {match.source_match_url && <a className="match-source-link" href={match.source_match_url} target="_blank" rel="noreferrer">Ficha en BDFutbol ↗</a>}
    </section>

    {hasPublishedContent && details
      ? <PublishedMatchDetails
        details={details}
        homeName={match.home_team.name}
        awayName={match.away_team.name}
        homeTeamId={match.home_team.team_id}
        awayTeamId={match.away_team.team_id}
        played={played}
        onNavigate={onNavigate}
      />
      : <p className="match-details-unavailable" role="status">Los detalles de este encuentro todavía no están disponibles.</p>}
  </>;
}

function PublishedMatchDetails({
  details,
  homeName,
  awayName,
  homeTeamId,
  awayTeamId,
  played,
  onNavigate,
}: {
  details: PublishedDetails;
  homeName: string;
  awayName: string;
  homeTeamId: number;
  awayTeamId: number;
  played: boolean;
  onNavigate: (path: string) => void;
}) {
  return <section className="match-page-panel match-details-panel" aria-labelledby="match-details-title">
    <div className="section-heading"><div><span className="section-kicker">DATOS DEPORTIVOS</span><h2 id="match-details-title">Alineaciones</h2></div></div>
    {(details.home.starters?.length || details.home.substitutes?.length || details.away.starters?.length || details.away.substitutes?.length) &&
      <div className="match-lineups">
        <LineupSide name={homeName} side={details.home} teamId={homeTeamId} events={details.events ?? []} onNavigate={onNavigate} />
        <LineupSide name={awayName} side={details.away} teamId={awayTeamId} events={details.events ?? []} onNavigate={onNavigate} />
      </div>}
    {details.events?.length ? <section className="match-timeline" aria-labelledby="match-timeline-title">
      <div className="section-heading"><div><span className="section-kicker">PARTIDO</span><h2 id="match-timeline-title">Cronología</h2></div>
        <span className="match-event-count">{details.events.length} {details.events.length === 1 ? "acontecimiento" : "acontecimientos"}</span>
      </div>
      <ol className="match-events">{buildTimelineItems(details.events).map((item) => item.type === "substitutions"
        ? <SubstitutionTimelineItem key={item.key} item={item} homeName={homeName} awayName={awayName}
          homeTeamId={homeTeamId} awayTeamId={awayTeamId} onNavigate={onNavigate} />
        : <EventTimelineItem key={item.key} event={item.event} homeName={homeName} awayName={awayName}
          homeTeamId={homeTeamId} awayTeamId={awayTeamId} played={played} onNavigate={onNavigate} />)}</ol>
    </section> : null}
  </section>;
}

function LineupSide({
  name,
  side,
  teamId,
  events,
  onNavigate,
}: {
  name: string;
  side: NonNullable<MatchPageData["details"]>["home"];
  teamId: number;
  events: MatchEvent[];
  onNavigate: (path: string) => void;
}) {
  return <section className="match-lineup-side" aria-label={`Alineación de ${name}`}>
    <h3>{name}</h3>
    {side.coach && <p className="match-lineup-coach"><span>Entrenador</span><strong>{side.coach.display_name}</strong></p>}
    {side.starters?.length ? <div className="match-lineup-group"><h4>Titulares <span>{side.starters.length}</span></h4>
      <PlayerList players={side.starters} teamId={teamId} sideTeamId={side.team_id} events={events} onNavigate={onNavigate} /></div> : null}
    {side.substitutes?.length ? <div className="match-lineup-group is-substitutes"><h4>Suplentes <span>{side.substitutes.length}</span></h4>
      <PlayerList players={side.substitutes} teamId={teamId} sideTeamId={side.team_id} events={events} onNavigate={onNavigate} /></div> : null}
  </section>;
}

function PlayerList({ players, teamId, sideTeamId, events, onNavigate }: {
  players: PublishedPlayer[];
  teamId: number;
  sideTeamId: number;
  events: MatchEvent[];
  onNavigate: (path: string) => void;
}) {
  const verifiedTeam = sideTeamId === teamId;
  return <ul>{players.map((player, index) => {
    const annotations = verifiedTeam && player.player_id !== null
      ? events.filter((event) => event.team_id === teamId && event.player_id === player.player_id && event.player_id !== null)
      : [];
    return <li className="match-player-row" key={`${player.player_id ?? player.display_name}:${index}`}>
      <ProfileImage src={player.photo_url} name={player.display_name} className="match-player-photo" />
      {player.shirt_number !== null && <span className="match-player-number">{player.shirt_number}</span>}
      <span className="match-player-identity">{player.player_id && player.player_profile_available
        ? <InternalPlayerLink playerId={player.player_id} onNavigate={onNavigate}>{player.display_name}</InternalPlayerLink>
        : <span>{player.display_name}</span>}
        {player.position && <small className="match-player-position">{player.position}</small>}
      </span>
      <span className="match-player-annotations">
        {annotations.map((event, eventIndex) => <PlayerEventMarker key={`${event.event_kind}:${event.minute}:${eventIndex}`} event={event} />)}
      </span>
      {player.role === "substitute" && player.participation_status === "no_entry_marker" && <span className="match-participation-note">Sin entrada registrada</span>}
      {player.role === "substitute" && player.participation_status === "entered" && !annotations.some((event) => event.event_kind === "substitution_in") &&
        <span className="match-participation-note">Entrada registrada</span>}
    </li>;
  })}</ul>;
}

function MatchHighlights({ events, homeName, awayName, homeTeamId, awayTeamId, onNavigate }: {
  events: MatchEvent[];
  homeName: string;
  awayName: string;
  homeTeamId: number;
  awayTeamId: number;
  onNavigate: (path: string) => void;
}) {
  const highlights = sortMatchEvents(events.filter((event) => isHighlight(event.event_kind)));
  if (!highlights.length) return null;
  return <section className="match-page-panel match-highlights" aria-labelledby="match-highlights-title">
    <div className="section-heading"><div><span className="section-kicker">LO MÁS DESTACADO</span><h2 id="match-highlights-title">Momentos del partido</h2></div>
      <span className="match-event-count">{highlights.length}</span>
    </div>
    <ol>{highlights.map((event, index) => <li className={`match-highlight match-event-${event.event_kind}`} key={`${event.event_kind}:${event.minute}:${event.team_id}:${index}`}>
      <time>{event.minute ?? "—"}</time>
      <EventGlyph kind={event.event_kind} />
      <span className="match-highlight-copy"><strong>{eventLabel(event.event_kind)}</strong>
        <span>{event.player_name && event.player_id && event.player_profile_available
          ? <InternalPlayerLink playerId={event.player_id} onNavigate={onNavigate}>{event.player_name}</InternalPlayerLink>
          : event.player_name ?? "Jugador no indicado"}
          {event.team_id === homeTeamId ? ` · ${homeName}` : event.team_id === awayTeamId ? ` · ${awayName}` : ""}
        </span>
      </span>
      {event.score_after_home !== null && event.score_after_away !== null &&
        <span className="match-event-score" aria-label={`Marcador ${event.score_after_home} a ${event.score_after_away}`}>{event.score_after_home}–{event.score_after_away}</span>}
    </li>)}</ol>
  </section>;
}

type TimelineItem =
  | { type: "event"; event: MatchEvent; key: string }
  | { type: "substitutions"; minute: string | null; teamId: number; events: MatchEvent[]; key: string };

function buildTimelineItems(events: MatchEvent[]): TimelineItem[] {
  const sorted = sortMatchEvents(events);
  const result: TimelineItem[] = [];
  const substitutionGroups = new Map<string, Extract<TimelineItem, { type: "substitutions" }>>();
  sorted.forEach((event, index) => {
    if (event.event_kind !== "substitution_in" && event.event_kind !== "substitution_out") {
      result.push({ type: "event", event, key: `event:${index}:${event.event_kind}:${event.minute ?? "unknown"}` });
      return;
    }
    const minuteKey = event.minute === null ? "unknown" : parseMinute(event.minute)?.join("+") ?? `raw:${event.minute.trim()}`;
    const key = `${event.team_id}:${minuteKey}`;
    const existing = substitutionGroups.get(key);
    if (existing) existing.events.push(event);
    else {
      const item: Extract<TimelineItem, { type: "substitutions" }> = {
        type: "substitutions", minute: event.minute, teamId: event.team_id, events: [event], key: `substitution:${key}:${index}`,
      };
      substitutionGroups.set(key, item);
      result.push(item);
    }
  });
  return result;
}

function SubstitutionTimelineItem({ item, homeName, awayName, homeTeamId, awayTeamId, onNavigate }: {
  item: Extract<TimelineItem, { type: "substitutions" }>;
  homeName: string;
  awayName: string;
  homeTeamId: number;
  awayTeamId: number;
  onNavigate: (path: string) => void;
}) {
  const outgoing = item.events.filter((event) => event.event_kind === "substitution_out");
  const incoming = item.events.filter((event) => event.event_kind === "substitution_in");
  const teamName = item.teamId === homeTeamId ? homeName : item.teamId === awayTeamId ? awayName : "Equipo";
  return <li className="match-event-row match-substitution-row">
    <time>{item.minute ?? "—"}</time><EventGlyph kind="substitution" />
    <div className="match-event-main"><strong className="match-event-team">{teamName}</strong>
      <div className="match-substitution-columns">
        {outgoing.length > 0 && <SubstitutionList label="Salieron" direction="outgoing" events={outgoing} onNavigate={onNavigate} />}
        {incoming.length > 0 && <SubstitutionList label="Entraron" direction="incoming" events={incoming} onNavigate={onNavigate} />}
      </div>
    </div>
  </li>;
}

function SubstitutionList({ label, direction, events, onNavigate }: {
  label: string;
  direction: "incoming" | "outgoing";
  events: MatchEvent[];
  onNavigate: (path: string) => void;
}) {
  return <div className={`match-substitution-list is-${direction}`}><span>{label}</span><ul>{events.map((event, index) => <li key={`${event.player_id}:${index}`}>
    {renderEventPlayer(event, onNavigate)}
  </li>)}</ul></div>;
}

function EventTimelineItem({ event, homeName, awayName, homeTeamId, awayTeamId, played, onNavigate }: {
  event: MatchEvent;
  homeName: string;
  awayName: string;
  homeTeamId: number;
  awayTeamId: number;
  played: boolean;
  onNavigate: (path: string) => void;
}) {
  const teamName = event.team_id === homeTeamId ? homeName : event.team_id === awayTeamId ? awayName : "Equipo";
  return <li className={`match-event-row match-event-${event.event_kind}`}>
    <time>{event.minute ?? "—"}</time><EventGlyph kind={event.event_kind} />
    <div className="match-event-main"><div className="match-event-title"><strong>{eventLabel(event.event_kind)}</strong>
      {event.score_after_home !== null && event.score_after_away !== null &&
        <span className="match-event-score" aria-label={`Marcador ${event.score_after_home} a ${event.score_after_away}`}>{event.score_after_home}–{event.score_after_away}</span>}
    </div>
      <div className="match-event-meta"><span>{renderEventPlayer(event, onNavigate)}</span><span>{teamName}</span>
        {event.related_player_name && <span className="match-event-related">Relacionado: {event.related_player_id && event.related_player_profile_available
          ? <InternalPlayerLink playerId={event.related_player_id} onNavigate={onNavigate}>{event.related_player_name}</InternalPlayerLink>
          : event.related_player_name}</span>}
        {!played && <span className="match-not-final-note">Partido no finalizado</span>}
      </div>
    </div>
  </li>;
}

function renderEventPlayer(event: MatchEvent, onNavigate: (path: string) => void) {
  if (!event.player_name) return <span>Jugador no indicado</span>;
  return event.player_id && event.player_profile_available
    ? <InternalPlayerLink playerId={event.player_id} onNavigate={onNavigate}>{event.player_name}</InternalPlayerLink>
    : <span>{event.player_name}</span>;
}

function PlayerEventMarker({ event }: { event: MatchEvent }) {
  const description = accessibleEventDescription(event);
  return <span className={`match-player-marker match-event-${event.event_kind}`} aria-label={description} title={description}>
    <EventGlyph kind={event.event_kind} /><span className="match-marker-minute">{event.minute ?? ""}</span>
  </span>;
}

function EventGlyph({ kind }: { kind: MatchEventKind }) {
  if (kind === "goal" || kind === "penalty" || kind === "own_goal") return <svg className={`match-event-glyph is-${kind}`} viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="8" cy="8" r="6.5" /><path d="m8 4 2.35 1.7-.9 2.75h-2.9l-.9-2.75L8 4Zm-3.9 1.5L2 6.4m9.9-.9 2.1.9m-7 2.05L5.5 11m5-2.55L13 11m-5-1.25v3.1" />
  </svg>;
  if (kind === "yellow_card" || kind === "second_yellow") return <svg className="match-event-glyph is-yellow" viewBox="0 0 12 16" aria-hidden="true"><rect x="1" y="1" width="10" height="14" rx="1.5" /></svg>;
  if (kind === "red_card") return <svg className="match-event-glyph is-red" viewBox="0 0 12 16" aria-hidden="true"><rect x="1" y="1" width="10" height="14" rx="1.5" /></svg>;
  if (kind === "substitution" || kind === "substitution_in" || kind === "substitution_out") return <svg className={`match-event-glyph is-${kind}`} viewBox="0 0 16 16" aria-hidden="true">
    <path d={kind === "substitution_in" ? "M2 8h11m0 0-4-4m4 4-4 4" : kind === "substitution_out" ? "M14 8H3m0 0 4-4m-4 4 4 4" : "M2 5h10m0 0-2.5-2.5M12 5 9.5 7.5M14 11H4m0 0 2.5-2.5M4 11l2.5 2.5"} />
  </svg>;
  if (kind === "missed_penalty") return <svg className="match-event-glyph is-missed-penalty" viewBox="0 0 16 16" aria-hidden="true">
    <g className="missed-penalty-ball">
      <circle cx="6.2" cy="6.2" r="5.1" />
      <path d="m6.2 3.2 1.8 1.3-.7 2.1H5.1l-.7-2.1 1.8-1.3Zm-3 1.2-1.5.7m7.5-.7 1.5.7m-5.4 1.5-1.7 1.8m3.8-1.8 1.7 1.8m-1.9-1v2.3" />
    </g>
    <path className="missed-penalty-cross" d="m10.8 10.8 3.7 3.7m0-3.7-3.7 3.7" />
  </svg>;
  return <span className="match-event-glyph is-other" aria-hidden="true">·</span>;
}

function isHighlight(kind: MatchEventKind): boolean {
  return ["goal", "penalty", "own_goal", "missed_penalty", "red_card", "second_yellow"].includes(kind);
}

function accessibleEventDescription(event: MatchEvent): string {
  const minute = event.minute ? `, ${event.minute} minuto` : "";
  return `${eventLabel(event.event_kind)}${minute}`;
}

function eventLabel(kind: MatchEventKind): string {
  const labels: Record<string, string> = {
    goal: "Gol", penalty: "Gol de penalti", missed_penalty: "Penalti fallado", own_goal: "Gol en propia puerta", yellow_card: "Tarjeta amarilla",
    red_card: "Expulsión", second_yellow: "Segunda amarilla · expulsión", substitution: "Sustitución",
    substitution_in: "Entró", substitution_out: "Salió", other: "Evento",
  };
  return labels[kind] ?? "Evento";
}

function sortMatchEvents<T extends { minute: string | null }>(events: T[]): T[] {
  return events.map((event, index) => ({ event, index, minute: event.minute ? parseMinute(event.minute) : null }))
    .sort((left, right) => {
      if (left.minute === null || right.minute === null) {
        return left.minute === right.minute ? left.index - right.index : left.minute === null ? 1 : -1;
      }
      return left.minute[0] - right.minute[0] || left.minute[1] - right.minute[1] || left.index - right.index;
    })
    .map(({ event }) => event);
}

function parseMinute(value: string): [number, number] | null {
  const match = /^(\d+)(?:\+(\d+))?\s*['’]?$/.exec(value.trim());
  return match ? [Number(match[1]), Number(match[2] ?? 0)] : null;
}

function formatDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}

function formatCaptureDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
}

function formatSeason(value: string): string {
  return value.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
}
