import type { ClassificationType, RangeType, StandingsFilters } from "../domain/classification/engine";

interface MatchdayOption {
  number: number;
  date: string | null;
  hasResults: boolean;
}

interface Props {
  filters: StandingsFilters;
  onChange: (next: StandingsFilters) => void;
  matchdays: MatchdayOption[];
}

const classificationOptions: { value: ClassificationType; label: string }[] = [
  { value: "general", label: "General" },
  { value: "local", label: "Local" },
  { value: "visitor", label: "Visitante" },
];

const rangeOptions: { value: RangeType; label: string }[] = [
  { value: "all", label: "Todas" },
  { value: "dates", label: "Por fechas" },
  { value: "rounds", label: "Por jornadas" },
];

export function ClassificationControls({ filters, onChange, matchdays }: Props) {
  const maxRound = filters.matchdayCap;

  function changeRoundRange(start: number, end: number) {
    const boundedStart = Math.min(start, maxRound);
    const boundedEnd = Math.max(boundedStart, Math.min(end, maxRound));
    onChange({ ...filters, roundStart: boundedStart, roundEnd: boundedEnd });
  }

  return (
    <section className="filter-panel" aria-label="Filtros de clasificación">
      <div className="filter-main-row">
        <fieldset className="filter-group classification-filter">
          <legend>Clasificación</legend>
          <div className="segmented-control" role="group" aria-label="Tipo de clasificación">
            {classificationOptions.map((option) => (
              <button
                aria-pressed={filters.classificationType === option.value}
                className={filters.classificationType === option.value ? "is-active" : ""}
                key={option.value}
                onClick={() => onChange({ ...filters, classificationType: option.value })}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="filter-group matchday-filter">
          <span className="filter-label">Jornada límite</span>
          <select
            aria-label="Jornada límite"
            value={filters.matchdayCap}
            onChange={(event) => {
              const matchdayCap = Number(event.target.value);
              let roundStart = filters.roundStart;
              let roundEnd = filters.roundEnd;
              if (filters.rangeType === "rounds") {
                roundStart = Math.min(roundStart ?? 1, matchdayCap);
                roundEnd = Math.max(roundStart, Math.min(roundEnd ?? matchdayCap, matchdayCap));
              }
              onChange({ ...filters, matchdayCap, roundStart, roundEnd });
            }}
          >
            {matchdays.map((matchday) => (
              <option
                disabled={!matchday.hasResults}
                key={matchday.number}
                value={matchday.number}
              >
                {`J${matchday.number}${matchday.date ? ` · ${formatShortDate(matchday.date)}` : ""}${matchday.hasResults ? "" : " · sin resultados"}`}
              </option>
            ))}
          </select>
        </label>

        <fieldset className="filter-group postponed-filter">
          <legend>Aplazados</legend>
          <div className="segmented-control compact-control" role="group" aria-label="Incluir aplazados">
            <button
              aria-pressed={filters.includePostponed}
              className={filters.includePostponed ? "is-active" : ""}
              onClick={() => onChange({ ...filters, includePostponed: true })}
              type="button"
            >
              Incluir
            </button>
            <button
              aria-pressed={!filters.includePostponed}
              className={!filters.includePostponed ? "is-active" : ""}
              onClick={() => onChange({ ...filters, includePostponed: false })}
              type="button"
            >
              Excluir
            </button>
          </div>
        </fieldset>

        <label className="filter-group range-filter">
          <span className="filter-label">Filtrar fechas</span>
          <select
            aria-label="Tipo de rango"
            value={filters.rangeType}
            onChange={(event) => {
              const rangeType = event.target.value as RangeType;
              onChange({
                ...filters,
                rangeType,
                dateStart: rangeType === "dates" ? filters.dateStart : null,
                dateEnd: rangeType === "dates" ? filters.dateEnd : null,
                roundStart: rangeType === "rounds" ? Math.min(filters.roundStart ?? 1, maxRound) : null,
                roundEnd: rangeType === "rounds" ? Math.min(filters.roundEnd ?? maxRound, maxRound) : null,
              });
            }}
          >
            {rangeOptions.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>

      {filters.rangeType === "dates" && (
        <div className="range-detail-row" aria-label="Rango de fechas inclusivo">
          <span className="range-detail-title">Rango inclusivo</span>
          <label>
            <span>Desde</span>
            <input
              aria-label="Fecha inicial"
              required
              type="date"
              value={filters.dateStart ?? ""}
              onChange={(event) => {
                if (!event.target.value) return;
                const dateStart = event.target.value;
                const dateEnd = filters.dateEnd && dateStart && filters.dateEnd < dateStart
                  ? dateStart
                  : filters.dateEnd;
                onChange({ ...filters, dateStart, dateEnd });
              }}
            />
          </label>
          <span className="range-connector">—</span>
          <label>
            <span>Hasta</span>
            <input
              aria-label="Fecha final"
              required
              type="date"
              value={filters.dateEnd ?? ""}
              onChange={(event) => {
                if (!event.target.value) return;
                const dateEnd = event.target.value;
                const dateStart = filters.dateStart && dateEnd && filters.dateStart > dateEnd
                  ? dateEnd
                  : filters.dateStart;
                onChange({ ...filters, dateStart, dateEnd });
              }}
            />
          </label>
        </div>
      )}

      {filters.rangeType === "rounds" && (
        <div className="range-detail-row" aria-label="Rango de jornadas inclusivo">
          <span className="range-detail-title">Jornadas incluidas</span>
          <label>
            <span>Desde</span>
            <select
              aria-label="Jornada inicial"
              value={filters.roundStart ?? 1}
              onChange={(event) => changeRoundRange(Number(event.target.value), filters.roundEnd ?? maxRound)}
            >
              {rangeRounds(maxRound).map((round) => <option key={round} value={round}>J{round}</option>)}
            </select>
          </label>
          <span className="range-connector">—</span>
          <label>
            <span>Hasta</span>
            <select
              aria-label="Jornada final"
              value={filters.roundEnd ?? maxRound}
              onChange={(event) => changeRoundRange(filters.roundStart ?? 1, Number(event.target.value))}
            >
              {rangeRounds(maxRound).map((round) => (
                <option key={round} value={round} disabled={round < (filters.roundStart ?? 1)}>
                  J{round}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <div className="filter-footnote">
        <span className="info-dot" aria-hidden="true">i</span>
        <span>Rangos inclusivos · la jornada seleccionada actúa como límite superior.</span>
      </div>
    </section>
  );
}

function rangeRounds(maxRound: number): number[] {
  return Array.from({ length: maxRound }, (_, index) => index + 1);
}

function formatShortDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year!, month! - 1, day!)));
}
