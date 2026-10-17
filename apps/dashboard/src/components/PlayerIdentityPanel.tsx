import type { PlayerDetail } from "../api/contracts";

const fieldLabels: Record<string, string> = {
  display_name: "Nombre visible",
  full_name: "Nombre completo",
  birth_date: "Fecha de nacimiento",
  age_years: "Edad publicada",
  birth_place: "Lugar de nacimiento",
  birth_place_raw: "Lugar de nacimiento original",
  birthplace_province: "Provincia de nacimiento",
  country_of_birth: "País de nacimiento",
  nationality: "Nacionalidad",
  position_name: "Demarcación",
  height_cm: "Altura",
  height_raw: "Altura original",
  weight_kg: "Peso",
  weight_raw: "Peso original",
};

export function PlayerIdentityPanel({ detail }: { detail: PlayerDetail }) {
  const identity = detail.identity;
  const place = [identity.birth_place, identity.birthplace_province].filter(Boolean).join(" · ");
  return <article className="player-info-panel player-identity-panel">
    <h2>Datos personales</h2>
    <dl className="player-identity-facts">
      <dt>Fecha de nacimiento</dt><dd>{identity.birth_date ? formatDateOnly(identity.birth_date) : "—"}</dd>
      <dt>Edad publicada</dt><dd>{identity.age_years ?? "—"}</dd>
      <dt>Lugar de nacimiento</dt><dd>{place || "—"}</dd>
      <dt>País de nacimiento</dt><dd>{identity.country_of_birth ?? "No observado"}</dd>
      <dt>Nacionalidad</dt><dd>{identity.nationality ?? "No observada"}</dd>
    </dl>
    {identity.conflicts.length > 0 && <div className="player-identity-conflicts" role="status">
      <strong>Hay diferencias entre fuentes</strong>
      <ul>{identity.conflicts.map((conflict) => <li key={conflict.field}>
        {fieldLabels[conflict.field] ?? "Dato de identidad"}: inventario «{conflict.inventory_value}»; ficha individual «{conflict.individual_profile_value}». Se conserva el inventario como valor preferente.
      </li>)}</ul>
    </div>}
    <details className="player-identity-provenance">
      <summary>Ver procedencia de identidad</summary>
      <p>La ficha individual completa los campos vacíos del inventario; sus valores originales se conservan y las diferencias se muestran arriba.</p>
      {identity.birth_place_raw && <p>Lugar de nacimiento tal como aparece en la fuente: {identity.birth_place_raw}</p>}
      <dl>{Object.entries(identity.field_sources).map(([field, source]) => <div key={field}>
        <dt>{fieldLabels[field] ?? field}</dt><dd>{sourceLabel(source)}</dd>
      </div>)}</dl>
      <small>SHA-256 del inventario: {identity.inventory_sha256}</small>
      {identity.individual_profile_source_url && <p className="player-identity-source">
        Captura de perfil {identity.individual_profile_captured_at ? `del ${formatDateTime(identity.individual_profile_captured_at)}` : "sin fecha verificada"}
        {identity.individual_profile_sha256 && <> · SHA-256 {identity.individual_profile_sha256}</>}
      </p>}
    </details>
  </article>;
}

export function PlayerClubHistory({ detail }: { detail: PlayerDetail }) {
  const reference = detail.club_reference;
  const membershipByTeam = new Map(
    detail.membership_history.map((item) => [`${item.group}-${item.team_id}`, item]),
  );
  const movement = detail.last_observed_movement;
  return <section className="player-info-panel player-club-panel" aria-label="Club y relaciones observadas">
    <h2>Club de referencia</h2>
    {reference.status === "observed" ? <div className="player-club-reference">
      <strong>{reference.team_name} · Grupo {reference.group}</strong>
      <span>Referencia observada en una captura de 2026/27{reference.observed_at ? ` · ${formatDateTime(reference.observed_at)}` : " · fecha no disponible"}</span>
      <small>Es la pertenencia más reciente documentada; no certifica una afiliación vigente hoy.</small>
    </div> : <div className="player-club-unconfirmed" role="status">
      <strong>Club actual no confirmado</strong>
      <span>{clubReason(reference.reason)}</span>
    </div>}

    {movement && <div className="player-last-movement">
      <span className="section-kicker">ÚLTIMO MOVIMIENTO OBSERVADO</span>
      <strong>{movement.from_team_name}{movement.from_group ? ` · Grupo ${movement.from_group}` : ""} <span aria-hidden="true">→</span> {movement.to_team_name}{movement.to_group ? ` · Grupo ${movement.to_group}` : ""}</strong>
      <span>Temporada 2026/27 · {movement.transfer_date ? `fecha publicada ${formatDateOnly(movement.transfer_date)}` : "fecha de traspaso no publicada"}{movement.observed_at ? ` · referencia capturada ${formatDateTime(movement.observed_at)}` : ""}</span>
      <details><summary>{movement.evidence_count} referencias de origen</summary><ul>
        {movement.evidence.map((evidence, index) => <li key={`${evidence.capture_id}-${evidence.source_record_index}-${index}`}>
          {evidence.direction === "incoming" ? "Alta" : "Baja"}{evidence.group ? ` · Grupo ${evidence.group}` : ""}{evidence.captured_at ? ` · capturada ${formatDateTime(evidence.captured_at)}` : ""}{evidence.capture_id ? ` · captura ${evidence.capture_id}` : ""}
        </li>)}
      </ul></details>
    </div>}
    {detail.movement_resolution === "ambiguous" && !movement && <p className="player-club-unconfirmed">Las referencias de traspaso no tienen un orden fiable. Se conservan en el historial sin escoger una como la última.</p>}

    <h3>Historial de pertenencias y relaciones</h3>
    {detail.associations.length ? <ul className="player-association-list">{detail.associations.map((association) => {
      const membership = membershipByTeam.get(`${association.group}-${association.team_id}`);
      return <li key={`${association.group}-${association.team_id}`}>
        <strong>{association.team_name} · Grupo {association.group}</strong>
        <span>{association.evidence_types.map(associationLabel).join(" · ")}{membership?.captured_at ? ` · plantilla observada ${formatDateTime(membership.captured_at)}` : ""}{membership?.jersey_number === null || membership?.jersey_number === undefined ? "" : ` · dorsal ${membership.jersey_number}`}{membership?.squad_group_label ? ` · ${membership.squad_group_label}` : ""}</span>
      </li>;
    })}</ul> : <p>No hay pertenencias ni referencias de equipo observadas.</p>}
  </section>;
}

function sourceLabel(source: string): string {
  if (source === "inventory") return "Inventario verificado";
  if (source === "individual_profile") return "Ficha individual verificada";
  return "No observado";
}

function associationLabel(value: string): string {
  return value === "membership" ? "Pertenencia observada en plantilla" : "Referencia de traspaso";
}

function clubReason(value: string): string {
  const reasons: Record<string, string> = {
    no_membership_observed: "No hay una pertenencia de plantilla verificada para esta temporada.",
    membership_order_unavailable: "Las capturas disponibles no permiten ordenar las pertenencias y movimientos de forma fiable.",
    multiple_latest_memberships: "Más de un club comparte la evidencia de pertenencia más reciente.",
    later_or_simultaneous_outgoing_movement: "La pertenencia más reciente coincide con una referencia de salida de la misma captura o posterior.",
  };
  return reasons[value] ?? "Las evidencias disponibles no permiten confirmar un club actual.";
}

function formatDateOnly(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return `${String(day).padStart(2, "0")}/${String(month).padStart(2, "0")}/${year}`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Madrid",
  }).format(new Date(value));
}
