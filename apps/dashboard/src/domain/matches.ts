import type { MatchGenerationRecord } from "../api/contracts";

const INTERNAL_MATCH_ID = /^pf-(\d{4}-\d{2})-group-(i|ii)-bdfutbol-(\d+)$/;

export function matchInternalId(
  group: string,
  season: string,
  sourceMatchId: string,
): string {
  const groupCode = group === "1" || group === "I" ? "I" : group === "2" || group === "II" ? "II" : null;
  if (!/^\d{4}-\d{2}$/.test(season) || !/^\d+$/.test(sourceMatchId)) {
    throw new RangeError("La temporada o el identificador de partido no son válidos.");
  }
  if (!groupCode) throw new RangeError("El grupo de competición debe ser I o II.");
  return `pf-${season}-group-${groupCode.toLowerCase()}-bdfutbol-${sourceMatchId}`;
}

export function matchPath(internalId: string): string {
  if (!INTERNAL_MATCH_ID.test(internalId)) {
    throw new RangeError("El identificador interno de partido no es válido.");
  }
  return `/matches/${internalId}`;
}

export function matchPathForSourceId(
  group: "1" | "2" | "I" | "II",
  season: string,
  sourceMatchId: string,
): string {
  return matchPath(matchInternalId(group, season, sourceMatchId));
}

export function matchGenerationRecordToInternalMatchId(match: MatchGenerationRecord): string {
  const parsed = match.internal_id.match(INTERNAL_MATCH_ID);
  if (!parsed || parsed[1] !== "2026-27" || parsed[3] !== match.source_match_id) {
    throw new Error("La identidad interna de partido no coincide con el registro publicado.");
  }
  return match.internal_id;
}
