import type { PlayerDetail } from "../api/contracts";

export function playerIdentityHighlights(detail: PlayerDetail): string[] {
  const identity = detail.identity;
  return [
    identity.position_name,
    identity.height_cm === null ? null : `${identity.height_cm} cm`,
    identity.weight_kg === null ? null : `${identity.weight_kg} kg`,
  ].filter((value): value is string => Boolean(value));
}
