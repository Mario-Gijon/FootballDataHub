import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  loadManualUpdateJob,
  loadLatestCompetitionUpdate,
  startCompetitionUpdate,
  type ManualUpdateJob,
} from "../api/client";

interface Props {
  onApplied?: () => void;
}

const UPDATE_RECOVERY_KEY = "fdh:manual-update:competition";
const UPDATE_RECOVERY_CLOCK_SKEW_MS = 10_000;

interface StoredUpdateRecovery {
  jobId?: string;
  startedAt: number;
}

function readStoredRecovery(): StoredUpdateRecovery | null {
  try {
    const raw = window.sessionStorage.getItem(UPDATE_RECOVERY_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || !("startedAt" in value)) return null;
    const record = value as { startedAt?: unknown; jobId?: unknown };
    if (typeof record.startedAt !== "number" || !Number.isFinite(record.startedAt)) return null;
    return {
      startedAt: record.startedAt,
      ...(typeof record.jobId === "string" ? { jobId: record.jobId } : {}),
    };
  } catch {
    return null;
  }
}

function storeRecovery(value: StoredUpdateRecovery | null): void {
  try {
    if (value) window.sessionStorage.setItem(UPDATE_RECOVERY_KEY, JSON.stringify(value));
    else window.sessionStorage.removeItem(UPDATE_RECOVERY_KEY);
  } catch {
    // Recovery remains available for this mounted page even if browser storage is unavailable.
  }
}

function isTransportFailure(reason: unknown): boolean {
  if (reason instanceof TypeError) return true;
  return reason instanceof Error && /failed to fetch|fetch failed|networkerror|network request failed|load failed/i.test(reason.message);
}

function isAmbiguousStartFailure(reason: unknown): boolean {
  if (isTransportFailure(reason)) return true;
  if (typeof reason !== "object" || reason === null || !("statusCode" in reason)) return false;
  const statusCode = (reason as { statusCode?: unknown }).statusCode;
  return typeof statusCode === "number"
    && (statusCode === 408 || statusCode === 409 || statusCode === 425 || statusCode === 429 || statusCode >= 500);
}

function isActiveJob(value: ManualUpdateJob): boolean {
  return value.status === "queued" || value.status === "running";
}

function jobStartedAfter(value: ManualUpdateJob, startedAt: number): boolean {
  const createdAt = Date.parse(value.created_at);
  return Number.isFinite(createdAt) && createdAt >= startedAt - UPDATE_RECOVERY_CLOCK_SKEW_MS;
}

export function ManualUpdateControl({ onApplied }: Props) {
  const [job, setJob] = useState<ManualUpdateJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollAttempt, setPollAttempt] = useState(0);
  const [recoveryAttempt, setRecoveryAttempt] = useState(0);
  const [pendingStartAt, setPendingStartAt] = useState<number | null>(() => {
    const stored = readStoredRecovery();
    return stored?.jobId ? null : stored?.startedAt ?? null;
  });
  const [restoreJobId, setRestoreJobId] = useState<string | null>(() => readStoredRecovery()?.jobId ?? null);
  const notified = useRef(new Set<string>());

  useEffect(() => {
    if (!restoreJobId) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void loadManualUpdateJob(restoreJobId)
        .then((restored) => {
          if (!active) return;
          if (!restored) throw new Error("La API no encontró el trabajo que estaba guardado en esta pestaña.");
          setJob(restored);
          setRestoreJobId(null);
          setError("");
          setPollAttempt(0);
          if (isActiveJob(restored)) {
            const startedAt = Date.parse(restored.created_at);
            storeRecovery({ jobId: restored.job_id, startedAt: Number.isFinite(startedAt) ? startedAt : Date.now() });
          } else {
            storeRecovery(null);
            if (restored.status === "applied" && !notified.current.has(restored.job_id)) {
              notified.current.add(restored.job_id);
              onApplied?.();
            }
          }
        })
        .catch((reason: unknown) => {
          if (!active) return;
          setError(reason instanceof Error
            ? `No se pudo recuperar el trabajo guardado. Se volverá a consultar: ${reason.message}`
            : "No se pudo recuperar el trabajo guardado. Se volverá a consultar.");
          setRecoveryAttempt((value) => value + 1);
        });
    }, recoveryAttempt ? 4000 : 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [restoreJobId, recoveryAttempt, onApplied]);

  useEffect(() => {
    if (pendingStartAt === null || restoreJobId) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void loadLatestCompetitionUpdate()
        .then((latest) => {
          if (!active) return;
          if (latest && latest.scope === "competition" && (isActiveJob(latest) || jobStartedAfter(latest, pendingStartAt))) {
            setJob(latest);
            setPendingStartAt(null);
            setError("");
            setPollAttempt(0);
            const startedAt = Date.parse(latest.created_at);
            storeRecovery({ jobId: latest.job_id, startedAt: Number.isFinite(startedAt) ? startedAt : pendingStartAt });
            return;
          }
          setPendingStartAt(null);
          storeRecovery(null);
          setError("La API confirma que no hay un trabajo nuevo registrado. Puedes volver a pulsar «Actualizar Primera Federación».");
        })
        .catch(() => {
          if (!active) return;
          setError("Se perdió la conexión con la API. Estoy intentando recuperar el estado; no vuelvas a iniciar otra actualización mientras se comprueba.");
          setRecoveryAttempt((value) => value + 1);
        });
    }, recoveryAttempt ? 4000 : 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [pendingStartAt, restoreJobId, recoveryAttempt]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void loadManualUpdateJob(job.job_id)
        .then((next) => {
          if (!active) return;
          if (!next) throw new Error("La API no devolvió el trabajo solicitado.");
          setJob(next);
          setError("");
          if (isActiveJob(next)) {
            const startedAt = Date.parse(next.created_at);
            storeRecovery({ jobId: next.job_id, startedAt: Number.isFinite(startedAt) ? startedAt : Date.now() });
          } else {
            storeRecovery(null);
          }
          if (next.status === "applied" && !notified.current.has(next.job_id)) {
            notified.current.add(next.job_id);
            onApplied?.();
          }
        })
        .catch((reason: unknown) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "No se pudo consultar el progreso.");
            setPollAttempt((value) => value + 1);
          }
        });
    }, pollAttempt ? 4000 : 1800);
    return () => { active = false; window.clearTimeout(timer); };
  }, [job, onApplied, pollAttempt]);

  async function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingStartAt !== null || restoreJobId) return;
    setError("");
    setBusy(true);
    setJob(null);
    const startedAt = Date.now();
    storeRecovery({ startedAt });
    try {
      const created = await startCompetitionUpdate();
      if (!created) {
        setPendingStartAt(startedAt);
        setRecoveryAttempt(0);
        setError("La API no confirmó el inicio. Estoy comprobando si el trabajo llegó a registrarse.");
        return;
      }
      setJob(created);
      storeRecovery({ jobId: created.job_id, startedAt });
      setPollAttempt(0);
    } catch (reason) {
      if (isAmbiguousStartFailure(reason)) {
        setPendingStartAt(startedAt);
        setRecoveryAttempt(0);
        setError("No se pudo confirmar la respuesta de inicio. Estoy comprobando si el trabajo llegó a registrarse.");
      } else {
        storeRecovery(null);
        setError(reason instanceof Error ? reason.message : "No se pudo iniciar la actualización.");
      }
    } finally {
      setBusy(false);
    }
  }

  const active = job && isActiveJob(job);
  const recovering = pendingStartAt !== null || restoreJobId !== null;
  const result = job?.summary;
  const summaryHasFailures = Boolean(result && (
    typeof result.match_details_error === "string"
    || typeof result.match_details_reload_error === "string"
    || result.match_details_stopped === true
    || (typeof result.message === "string" && result.message.startsWith("Actualización parcial"))
    || hasRelatedSectionFailures(result.related_section_status)
  ));
  const outcome = result?.outcome;
  const isPartial = outcome === "partial" || (outcome === undefined && summaryHasFailures);
  const isNoChange = job?.status === "completed" && !isPartial && outcome !== "failed";
  const isApplied = job?.status === "applied";
  const isReloadFailure = job?.status === "applied_reload_failed";

  return (
    <section className="manual-update-control" aria-label="Actualizar Primera Federación">
      <form onSubmit={(event) => { void begin(event); }}>
        <button className="manual-update-button" type="submit" disabled={busy || Boolean(active) || recovering}>
          {busy || active ? "Actualizando…" : recovering ? "Recuperando…" : "Actualizar Primera Federación"}
        </button>
      </form>
      {(active || job || error || recovering) && <div className="manual-update-status" aria-live="polite" role="status">
        {recovering && <><strong>Recuperando estado…</strong> Comprobando el último trabajo registrado; no se iniciará otra actualización.</>}
        {active && <>
          <strong>Actualizando…</strong> {stageLabel(job.stage)}
          {job.progress && job.progress.total > 0 && <span> · Informes {job.progress.completed}/{job.progress.total}</span>}
          {job.stage === "refreshing_team_profiles" && job.team_progress && <span>
            {job.team_progress.preflight_checked < job.team_progress.total
              ? ` · Verificando capturas ${job.team_progress.preflight_checked}/${job.team_progress.total}`
              : ` · Capturas de equipos ${job.team_progress.captured}/${job.team_progress.total}`}
            {job.team_progress.failed > 0 && ` · ${job.team_progress.failed} pendientes por error`}
            {job.team_progress.current_team_id && ` · Equipo ${job.team_progress.current_team_id}`}
          </span>}
        </>}
        {isNoChange && <>
          <strong>{typeof result?.message === "string"
            ? result.message
            : result && (Number(result.match_details_candidate_count ?? 0) > 0 || Number(result.match_details_blocked_excluded_count ?? 0) > 0)
              ? "Sin cambios"
              : "Sin cambios"}</strong>
          {result && (Number(result.match_details_candidate_count ?? 0) > 0 || Number(result.match_details_blocked_excluded_count ?? 0) > 0) && <span> {summaryText(result)}</span>}
        </>}
        {isApplied && <>
          <strong>{isPartial ? "Actualización parcial." : "Actualización completada."}</strong>
          {result && <span> {summaryText(result)}</span>}
        </>}
        {job?.status === "completed" && isPartial && <>
          <strong>Actualización parcial.</strong>
          {result && <span> {summaryText(result)}</span>}
        </>}
        {isReloadFailure && <><strong>Datos aplicados, recarga pendiente.</strong> {job.error}</>}
        {job?.status === "failed" && <><strong>Actualización fallida.</strong> {job.error ?? result?.message}</>}
        {job?.status === "interrupted" && <><strong>Actualización interrumpida.</strong> {job.error}</>}
        {error && <p className="manual-update-error" role="alert">{error}</p>}
      </div>}
    </section>
  );
}

function hasRelatedSectionFailures(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const root = value as Record<string, unknown>;
  const groups = root.groups;
  if (typeof groups === "object" && groups !== null) {
    for (const group of Object.values(groups as Record<string, unknown>)) {
      if (typeof group !== "object" || group === null) continue;
      for (const item of Object.values(group as Record<string, unknown>)) {
        if (typeof item === "object" && item !== null) {
          const status = (item as Record<string, unknown>).status;
          if (status === "error" || status === "not_attempted") return true;
        }
      }
    }
  }
  const referees = root.referees;
  if (typeof referees === "object" && referees !== null
    && ["error", "not_attempted"].includes(String((referees as Record<string, unknown>).status))) return true;
  const teamFollow = root.team_follow;
  return typeof teamFollow === "object" && teamFollow !== null
    && (String((teamFollow as Record<string, unknown>).status) === "error"
      || String((teamFollow as Record<string, unknown>).status) === "partial"
      || Number((teamFollow as Record<string, unknown>).error_team_count ?? 0) > 0
      || Number((teamFollow as Record<string, unknown>).pending_team_count ?? 0) > 0);
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    preflight: "preparando la captura",
    capturing_group_i: "consultando Grupo I",
    capturing_group_ii: "consultando Grupo II",
    capturing_top_group_i: "actualizando Destacados del Grupo I",
    capturing_top_group_ii: "actualizando Destacados del Grupo II",
    capturing_statistics_group_i: "actualizando Estadísticas del Grupo I",
    capturing_statistics_group_ii: "actualizando Estadísticas del Grupo II",
    capturing_referees: "actualizando Árbitros",
    refreshing_team_profiles: "actualizando Seguimiento de los equipos con partidos nuevos",
    publishing_team_follow: "publicando los perfiles de equipo verificados",
    normalizing_matches_group_i: "normalizando partidos del Grupo I",
    normalizing_matches_group_ii: "normalizando partidos del Grupo II",
    building_generation: "validando calendario y resultados",
    comparing_candidate: "comparando los cambios",
    activating_generation: "aplicando los datos verificados",
    refreshing_api: "recargando los datos de la aplicación",
    refresh_failed: "la API necesita recargarse",
    checking_match_details: "buscando informes de partidos sin publicar",
    scanning_unpublished_matches: "comprobando partidos disputados sin informe",
    acquiring_match_details: "adquiriendo informes de partidos",
    validating_match_details: "validando y publicando informes completos",
    refreshing_match_details: "recargando los informes en la aplicación",
    completed: "completado",
  };
  return labels[stage] ?? "procesando los datos verificados";
}

function summaryText(summary: Record<string, unknown>): string {
  const groupSections = summary.changed_groups;
  const groupLabels = [
    ["classification", "clasificación"],
    ["progress", "progreso"],
    ["results_calendar", "resultados y calendario"],
  ] as const;
  const groupChanges = typeof groupSections === "object" && groupSections !== null
    ? (["I", "II"] as const).flatMap((group) => {
      const sections = (groupSections as Record<string, unknown>)[group];
      if (!Array.isArray(sections)) return [];
      const labels = groupLabels.flatMap(([key, label]) => sections.includes(key) ? [label] : []);
      return labels.length ? [`Grupo ${group}: ${labels.join(", ")}`] : [];
    })
    : [];
  const newlyPlayed = Number(summary.newly_played ?? 0);
  const corrected = Number(summary.result_corrected ?? 0);
  const fixtureUpdated = Number(summary.fixture_updated ?? 0);
  const pieces = [...groupChanges];
  const related = summary.related_section_status;
  if (typeof related === "object" && related !== null) {
    const sectionLabels: Record<string, string> = {
      top: "Destacados",
      statistics: "Estadísticas",
      referees: "Árbitros",
    };
    const groupStatus = (related as Record<string, unknown>).groups;
    if (typeof groupStatus === "object" && groupStatus !== null) {
      for (const group of ["I", "II"] as const) {
        const sections = (groupStatus as Record<string, unknown>)[group];
        if (typeof sections !== "object" || sections === null) continue;
        for (const [key, entry] of Object.entries(sections as Record<string, unknown>)) {
          if (typeof entry !== "object" || entry === null) continue;
          const state = (entry as Record<string, unknown>).status;
          if (state === "changed") pieces.push(`${sectionLabels[key] ?? key} Grupo ${group}`);
          if (state === "error") {
            const reason = (entry as Record<string, unknown>).reason;
            pieces.push(`${sectionLabels[key] ?? key} Grupo ${group}: error; se conservan los datos anteriores${typeof reason === "string" ? ` (${reason})` : ""}`);
          }
          if (state === "not_attempted") pieces.push(`${sectionLabels[key] ?? key} Grupo ${group}: no se intentó`);
        }
      }
    }
    const refereeState = (related as Record<string, unknown>).referees;
    if (typeof refereeState === "object" && refereeState !== null) {
      const state = (refereeState as Record<string, unknown>).status;
      if (state === "changed") pieces.push("Árbitros");
      if (state === "error") {
        const reason = (refereeState as Record<string, unknown>).reason;
        pieces.push(`Árbitros: error; se conservan los datos anteriores${typeof reason === "string" ? ` (${reason})` : ""}`);
      }
    }
    const followState = (related as Record<string, unknown>).team_follow;
    if (typeof followState === "object" && followState !== null) {
      const entry = followState as Record<string, unknown>;
      const changed = Number(entry.changed_team_count ?? 0);
      const unchanged = Number(entry.unchanged_team_count ?? 0);
      const pending = Number(entry.pending_team_count ?? 0);
      const errors = Number(entry.error_team_count ?? 0);
      if (changed) pieces.push(`Seguimiento actualizado en ${changed} equipos`);
      if (unchanged) pieces.push(`Seguimiento sin cambios en ${unchanged} equipos`);
      if (pending || errors) pieces.push(`Seguimiento pendiente en ${pending + errors} equipos`);
      if (typeof entry.reason === "string") pieces.push(`Seguimiento: ${entry.reason}`);
      const teamStatuses = entry.teams;
      if ((pending || errors) && typeof teamStatuses === "object" && teamStatuses !== null) {
        const firstProblem = Object.values(teamStatuses as Record<string, unknown>).find((item) =>
          typeof item === "object" && item !== null
          && ["error", "not_attempted", "pending"].includes(String((item as Record<string, unknown>).status)));
        if (typeof firstProblem === "object" && firstProblem !== null) {
          const reason = (firstProblem as Record<string, unknown>).reason;
          if (typeof reason === "string") pieces.push(`Detalle de Seguimiento: ${reason}`);
        }
      }
    }
  }
  if (newlyPlayed) pieces.push(`${newlyPlayed} partidos disputados nuevos`);
  if (corrected) pieces.push(`${corrected} marcadores corregidos`);
  if (fixtureUpdated) pieces.push(`${fixtureUpdated} cambios de calendario`);
  const detailPublished = Number(summary.match_details_published_count ?? 0);
  const detailPending = Number(summary.match_details_pending_count ?? 0);
  if (detailPublished) pieces.push(`${detailPublished} informes completos publicados`);
  if (detailPending) pieces.push(`${detailPending} informes pendientes de disponibilidad o revisión`);
  if (summary.match_details_stopped === true) pieces.push("adquisición detenida por una restricción o error");
  if (typeof summary.match_details_error === "string") pieces.push(`Informes: ${summary.match_details_error}`);
  if (typeof summary.match_details_reload_error === "string") pieces.push("recarga de informes pendiente");
  const excluded = Number(summary.match_details_blocked_excluded_count ?? 0);
  if (excluded) pieces.push(`${excluded} partido bloqueado excluido`);
  const pending = Number(summary.played_without_approved_details ?? 0);
  if (pending && summary.match_details_candidate_count === undefined) pieces.push(`${pending} fichas detalladas pendientes`);
  return pieces.length ? pieces.join(" · ") : "Los datos verificados se actualizaron.";
}
