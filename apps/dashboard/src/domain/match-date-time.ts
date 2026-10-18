export type MatchDateDisplayStyle = "long" | "compact";

export function formatMatchDateTime(
  date: string,
  kickoffTime: string | null | undefined,
  style: MatchDateDisplayStyle = "long",
): string {
  const [year, month, day] = date.split("-").map(Number);
  const formattedDate = new Intl.DateTimeFormat("es-ES", {
    day: style === "compact" ? "2-digit" : "numeric",
    month: style === "compact" ? "short" : "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year!, month! - 1, day!)));
  return kickoffTime ? `${formattedDate} · ${kickoffTime}` : formattedDate;
}

export function matchDateTimeAttribute(date: string, kickoffTime: string | null | undefined): string {
  return kickoffTime ? `${date}T${kickoffTime}` : date;
}
