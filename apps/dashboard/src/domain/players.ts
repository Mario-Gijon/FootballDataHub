export function playerPath(playerId: number): string {
  if (!Number.isSafeInteger(playerId) || playerId <= 0) {
    throw new RangeError("El identificador del jugador debe ser un entero positivo.");
  }
  return `/players/${playerId}`;
}
