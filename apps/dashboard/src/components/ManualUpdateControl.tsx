import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  loadManualUpdateJob,
  startCompetitionUpdate,
  type ManualUpdateJob,
} from "../api/client";

interface Props {
  onApplied?: () => void;
}

export function ManualUpdateControl({ onApplied }: Props) {
  const [job, setJob] = useState<ManualUpdateJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollAttempt, setPollAttempt] = useState(0);
  const notified = useRef(new Set<string>());

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void loadManualUpdateJob(job.job_id)
        .then((next) => {
          if (!active || !next) return;
          setJob(next);
          setError("");
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
    setError("");
    setBusy(true);
    try {
      const created = await startCompetitionUpdate();
      if (!created) throw new Error("La API no devolvió el trabajo de actualización.");
      setJob(created);
      setPollAttempt(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo iniciar la actualización.");
    } finally {
      setBusy(false);
    }
  }

  const active = job && ["queued", "running"].includes(job.status);
  const result = job?.summary;
  const isNoChange = job?.status === "completed";
  const isApplied = job?.status === "applied";
  const isReloadFailure = job?.status === "applied_reload_failed";

  return (
    <section className="manual-update-control" aria-label="Actualizar Primera Federación">
      <form onSubmit={(event) => { void begin(event); }}>
        <button className="manual-update-button" type="submit" disabled={busy || Boolean(active)}>
          {busy || active ? "Actualizando…" : "Actualizar Primera Federación"}
        </button>
      </form>
      {(active || job || error) && <div className="manual-update-status" aria-live="polite" role="status">
        {active && <><strong>Actualizando…</strong> {stageLabel(job.stage)}</>}
        {isNoChange && <strong>Sin cambios</strong>}
        {isApplied && <>
          <strong>Actualización completada.</strong>
          {result && <span> {summaryText(result)}</span>}
        </>}
        {isReloadFailure && <><strong>Datos aplicados, recarga pendiente.</strong> {job.error}</>}
        {job?.status === "failed" && <><strong>Actualización detenida.</strong> {job.error}</>}
        {job?.status === "interrupted" && <><strong>Actualización interrumpida.</strong> {job.error}</>}
        {error && <p className="manual-update-error" role="alert">{error}</p>}
      </div>}
    </section>
  );
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    preflight: "preparando la captura",
    capturing_group_i: "consultando Grupo I",
    capturing_group_ii: "consultando Grupo II",
    building_generation: "validando calendario y resultados",
    comparing_candidate: "comparando los cambios",
    activating_generation: "aplicando los datos verificados",
    refreshing_api: "recargando los datos de la aplicación",
    refresh_failed: "la API necesita recargarse",
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
  if (newlyPlayed) pieces.push(`${newlyPlayed} partidos disputados nuevos`);
  if (corrected) pieces.push(`${corrected} marcadores corregidos`);
  if (fixtureUpdated) pieces.push(`${fixtureUpdated} cambios de calendario`);
  const pending = Number(summary.played_without_approved_details ?? 0);
  if (pending) pieces.push(`${pending} fichas detalladas pendientes`);
  return pieces.length ? pieces.join(" · ") : "Los datos verificados se actualizaron.";
}
