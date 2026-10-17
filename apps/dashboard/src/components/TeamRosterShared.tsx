import { useState, type ReactNode } from "react";
import type { TeamRoster } from "../api/contracts";
import { InternalPlayerLink } from "./InternalPlayerLink";

export type RosterPlayer = TeamRoster["players"][number];
export type SortDirection = "ascending" | "descending";
export type SortValue = string | number | null | undefined;

export function readRosterSort<Key extends string>(teamId: number, view: string, allowedKeys: readonly Key[]): { key: Key; direction: SortDirection } | null {
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(`football-data-hub:team-roster-sort:${teamId}:${view}`) ?? "null") as { key?: unknown; direction?: unknown } | null;
    return stored && typeof stored.key === "string" && allowedKeys.includes(stored.key as Key)
      && (stored.direction === "ascending" || stored.direction === "descending")
      ? { key: stored.key as Key, direction: stored.direction }
      : null;
  } catch { return null; }
}

export function storeRosterSort(teamId: number, view: string, sort: { key: string; direction: SortDirection }): void {
  try { window.sessionStorage.setItem(`football-data-hub:team-roster-sort:${teamId}:${view}`, JSON.stringify(sort)); }
  catch { /* Sorting remains usable when session storage is unavailable. */ }
}

const indicatorColors: Record<string, string> = {
  played_in_first_division: "first-division",
  played_in_second_division: "second-division",
  youth_international: "youth-international",
  new_signing: "new-signing",
};

export function normalizeRosterText(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-ES").trim();
}

export function matchesRosterSearch(player: RosterPlayer, query: string, additionalValues: Array<string | null | undefined> = []): boolean {
  const normalizedQuery = normalizeRosterText(query);
  if (!normalizedQuery) return true;
  return normalizeRosterText([
    player.display_name,
    player.full_name ?? "",
    player.birthplace ?? "",
    player.birthplace_province ?? "",
    ...additionalValues.map((value) => value ?? ""),
  ].join(" ")).includes(normalizedQuery);
}

export function formatSpanishDate(value: string | null): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "—";
}

export function showRosterValue(value: number | string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

export function positionCodeLabel(code: string | null): string {
  return code ? `Código ${code} · equivalencia no verificada` : "Sin código publicado";
}

export function compareRosterValues(left: SortValue, right: SortValue, direction: SortDirection): number {
  const leftMissing = left === null || left === undefined || left === "";
  const rightMissing = right === null || right === undefined || right === "";
  if (leftMissing || rightMissing) {
    if (leftMissing && rightMissing) return 0;
    return leftMissing ? 1 : -1;
  }
  const compared = typeof left === "number" && typeof right === "number"
    ? left - right
    : String(left).localeCompare(String(right), "es", { numeric: true, sensitivity: "base" });
  return direction === "ascending" ? compared : -compared;
}

export function sortRosterRows<T>(
  rows: T[],
  getValue: (row: T) => SortValue,
  direction: SortDirection,
): T[] {
  return rows.map((row, sourceIndex) => ({ row, sourceIndex }))
    .sort((left, right) => compareRosterValues(getValue(left.row), getValue(right.row), direction) || left.sourceIndex - right.sourceIndex)
    .map(({ row }) => row);
}

export function SortableHeader({
  label,
  activeDirection,
  onSort,
}: {
  label: string;
  activeDirection: SortDirection | null;
  onSort: () => void;
}) {
  return <th aria-sort={activeDirection ?? "none"} scope="col">
    <button className="roster-sort-button" onClick={onSort} type="button" aria-label={`Ordenar por ${label}`}>
      {label}<span aria-hidden="true">{activeDirection === "ascending" ? " ↑" : activeDirection === "descending" ? " ↓" : " ↕"}</span>
    </button>
  </th>;
}

export function RosterSearch({
  value,
  onChange,
  label,
  placeholder = "Nombre o apellido",
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
}) {
  return <label className="roster-search"><span>{label}</span>
    <input aria-label={label} onChange={(event) => onChange(event.currentTarget.value)} placeholder={placeholder} value={value} />
  </label>;
}

export function ProfileImage({ src, name, className }: { src: string | null; name: string; className: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className={`${className} profile-image-fallback`} aria-label={`Sin fotografía para ${name}`}>{initials(name)}</span>;
  return <img className={className} src={src} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

export function PlayerIdentity({
  player,
  indicatorCodes = [],
  secondary,
  showFullName = true,
  onNavigate,
}: {
  player: RosterPlayer;
  indicatorCodes?: string[];
  secondary?: ReactNode;
  showFullName?: boolean;
  onNavigate: (path: string) => void;
}) {
  return <InternalPlayerLink className="roster-player-identity roster-player-identity-link" playerId={player.player_id} onNavigate={onNavigate} aria-label={player.display_name}>
    <ProfileImage src={player.photo_url} name={player.display_name} className="roster-photo" />
    <span className="roster-player-name">
      <span className="roster-player-display-name">{player.display_name}</span>
      {secondary ?? (showFullName && player.full_name && player.full_name !== player.display_name ? <small>{player.full_name}</small> : null)}
      {indicatorCodes.length > 0 && <span className="roster-player-indicators" aria-label="Indicadores publicados por BDFutbol">
        {indicatorCodes.map((code) => <span className={`roster-indicator-dot is-${indicatorColors[code] ?? "unknown"}`} key={code} title={code} />)}
      </span>}
    </span>
  </InternalPlayerLink>;
}

function initials(name: string): string {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toLocaleUpperCase("es-ES");
}
