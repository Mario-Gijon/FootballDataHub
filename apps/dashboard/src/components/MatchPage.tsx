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
  const played = match.status === "played" && match.home_goals !== null && match.away_goals !== null;
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
          className={`match-page-score ${played ? "is-played" : match.status === "unplayed" ? "is-pending" : "is-incomplete"}`}
          aria-label={played ? `Resultado ${match.home_goals} a ${match.away_goals}` : match.status === "unplayed" ? "Partido pendiente" : "Marcador incompleto"}
        >
          {played ? <><strong>{match.home_goals}</strong><span>–</span><strong>{match.away_goals}</strong></>
            : <span>{match.status === "unplayed" ? "Pendiente" : "Datos incompletos"}</span>}
        </div>
        <InternalTeamLink className="match-page-team" teamId={match.away_team.team_id} onNavigate={onNavigate}>
          <TeamCrest name={match.away_team.name} crestUrl={match.away_team.crest_url} className="match-page-crest" />
          <span>{match.away_team.name}</span>
        </InternalTeamLink>
      </div>
      <div className="match-page-subtitle">Jornada {match.matchday}{date ? ` · ${dateLabel.toLowerCase()} ${formatDate(date)}` : ""}</div>
    </header>

    <section className="match-page-panel" aria-labelledby="match-info-title">
      <div className="section-heading"><div><span className="section-kicker">ENCUENTRO</span><h1 id="match-info-title">Información del partido</h1></div></div>
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
  onNavigate,
}: {
  details: PublishedDetails;
  homeName: string;
  awayName: string;
  homeTeamId: number;
  awayTeamId: number;
  onNavigate: (path: string) => void;
}) {
  return <section className="match-page-panel match-details-panel" aria-labelledby="match-details-title">
    <div className="section-heading"><div><span className="section-kicker">DATOS DEPORTIVOS</span><h2 id="match-details-title">Alineaciones y eventos</h2></div></div>
    {(details.home.coach || details.away.coach) && <div className="match-coaches">
      {details.home.coach && <p><span>Entrenador local</span><strong>{details.home.coach.display_name}</strong></p>}
      {details.away.coach && <p><span>Entrenador visitante</span><strong>{details.away.coach.display_name}</strong></p>}
    </div>}
    {(details.home.starters?.length || details.home.substitutes?.length || details.away.starters?.length || details.away.substitutes?.length) &&
      <div className="match-lineups">
        <LineupSide name={homeName} side={details.home} onNavigate={onNavigate} />
        <LineupSide name={awayName} side={details.away} onNavigate={onNavigate} />
      </div>}
    {details.events?.length ? <ol className="match-events">
      {sortMatchEvents(details.events).map((event, index) => <li key={`${event.event_kind}:${event.minute ?? "unknown"}:${event.team_id}:${index}`}>
        <time>{event.minute ?? "—"}</time>
        <span>{eventLabel(event.event_kind)}</span>
        <span>{event.team_id === homeTeamId ? homeName : event.team_id === awayTeamId ? awayName : ""}</span>
        <span>{event.player_name && event.player_id && event.player_profile_available
          ? <InternalPlayerLink playerId={event.player_id} onNavigate={onNavigate}>{event.player_name}</InternalPlayerLink>
          : event.player_name ?? ""}</span>
        {event.score_after_home !== null && event.score_after_away !== null &&
          <span className="match-event-score">{event.score_after_home}–{event.score_after_away}</span>}
        {event.related_player_name && <span className="match-event-related">{event.related_player_id && event.related_player_profile_available
          ? <InternalPlayerLink playerId={event.related_player_id} onNavigate={onNavigate}>{event.related_player_name}</InternalPlayerLink>
          : event.related_player_name}</span>}
      </li>)}
    </ol> : null}
  </section>;
}

function LineupSide({
  name,
  side,
  onNavigate,
}: {
  name: string;
  side: NonNullable<MatchPageData["details"]>["home"];
  onNavigate: (path: string) => void;
}) {
  return <section className="match-lineup-side" aria-label={`Alineación de ${name}`}>
    <h3>{name}</h3>
    {side.starters?.length ? <div><h4>Titulares</h4><PlayerList players={side.starters} onNavigate={onNavigate} /></div> : null}
    {side.substitutes?.length ? <div><h4>Suplentes</h4><PlayerList players={side.substitutes} onNavigate={onNavigate} /></div> : null}
  </section>;
}

function PlayerList({ players, onNavigate }: { players: PublishedPlayer[]; onNavigate: (path: string) => void }) {
  return <ul>{players.map((player, index) => <li key={`${player.player_id ?? player.display_name}:${index}`}>
    <ProfileImage src={player.photo_url} name={player.display_name} className="match-player-photo" />
    {player.shirt_number !== null && <span className="match-player-number">{player.shirt_number}</span>}
    {player.player_id && player.player_profile_available
      ? <InternalPlayerLink playerId={player.player_id} onNavigate={onNavigate}>{player.display_name}</InternalPlayerLink>
      : <span>{player.display_name}</span>}
    {player.position && <small>{player.position}</small>}
    {player.role === "substitute" && player.participation_status === "entered" && <small>Entró</small>}
    {player.role === "substitute" && player.participation_status === "no_entry_marker" && <small>Sin entrada registrada</small>}
  </li>)}</ul>;
}

function eventLabel(kind: MatchEventKind): string {
  const labels: Record<string, string> = {
    goal: "Gol", penalty: "Gol de penalti", missed_penalty: "Penalti fallado", own_goal: "Gol en propia puerta", yellow_card: "Tarjeta amarilla",
    red_card: "Tarjeta roja", second_yellow: "Segunda amarilla", substitution: "Sustitución",
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
      return left.minute[0] - right.minute[0]
        || left.minute[1] - right.minute[1]
        || left.index - right.index;
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
