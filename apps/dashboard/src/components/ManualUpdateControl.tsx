import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  loadLatestManualUpdate,
  loadManualUpdateCapabilities,
  loadManualUpdateStatus,
  loadManualUpdateJob,
  approveManualUpdate,
  startCompetitionUpdate,
  startTeamUpdate,
  type ManualUpdateJob,
  type ManualUpdateStatus,
} from "../api/client";

interface Props {
  scope: "competition" | "team";
  teamId?: number;
}

export function ManualUpdateControl({ scope, teamId }: Props) {
  const [authorized, setAuthorized] = useState(false);
  const [token, setToken] = useState("");
  const [job, setJob] = useState<ManualUpdateJob | null>(null);
  const [updateStatus, setUpdateStatus] = useState<ManualUpdateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState("");
  const tokenRef = useRef("");

  useEffect(() => {
    tokenRef.current = "";
    setToken("");
    setAuthorized(false);
    setJob(null);
    setUpdateStatus(null);
    setError("");
    return () => { tokenRef.current = ""; };
  }, [scope, teamId]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void loadManualUpdateJob(job.job_id, tokenRef.current)
        .then((next) => { if (active && next) setJob(next); })
        .catch((reason: unknown) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "No se pudo consultar el estado.");
            setJob((current) => current ? { ...current, status: "failed" } : current);
          }
        });
    }, 1800);
    return () => { active = false; window.clearTimeout(timer); };
  }, [job]);

  async function unlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const supplied = token.trim();
    if (!supplied) {
      setError("Introduce el token administrativo para continuar.");
      return;
    }
    setError("");
    setBusy(true);
    tokenRef.current = supplied;
    try {
      const scopes = await loadManualUpdateCapabilities(supplied);
      if (!scopes.includes(scope)) throw new Error("Este ámbito de actualización no está configurado en el servidor local.");
      const [status, latest] = await Promise.all([
        loadManualUpdateStatus(scope, supplied, teamId),
        loadLatestManualUpdate(scope, supplied, teamId),
      ]);
      setUpdateStatus(status);
      setJob(latest);
      setAuthorized(true);
    } catch (reason) {
      tokenRef.current = "";
      setToken("");
      setAuthorized(false);
      setError(reason instanceof Error ? reason.message : "No se pudo validar el acceso administrativo.");
    } finally {
      setBusy(false);
    }
  }

  async function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!authorized || !tokenRef.current) {
      setError("Vuelve a validar el acceso administrativo para continuar.");
      return;
    }
    setBusy(true);
    try {
      const created = scope === "competition"
        ? await startCompetitionUpdate(tokenRef.current)
        : teamId === undefined ? null : await startTeamUpdate(teamId, tokenRef.current);
      if (!created) throw new Error("La API no devolvió el trabajo de actualización.");
      setJob(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo iniciar la actualización.");
    } finally {
      setBusy(false);
    }
  }

  async function loadPrevious() {
    if (!authorized || !tokenRef.current) return;
    setError("");
    try {
      const [latest, status] = await Promise.all([
        loadLatestManualUpdate(scope, tokenRef.current, teamId),
        loadManualUpdateStatus(scope, tokenRef.current, teamId),
      ]);
      setJob(latest);
      setUpdateStatus(status);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo consultar el estado anterior.");
    }
  }

  async function approveCandidate() {
    if (!authorized || !job?.candidate_sha256 || !reviewer.trim() || !tokenRef.current) {
      setError("Se necesita el acceso administrativo y el nombre del revisor.");
      return;
    }
    const confirmed = window.confirm(
      `¿Aprobar y aplicar los cambios mostrados?\n\nÁmbito: ${scope === "team" ? "equipo" : "competición"}\nRevisor: ${reviewer.trim()}`,
    );
    if (!confirmed) return;
    setError("");
    setBusy(true);
    try {
      // The fingerprint remains internal to the client/server integrity check; it is never shown or requested from the operator.
      const updated = await approveManualUpdate(job.job_id, tokenRef.current, reviewer.trim(), job.candidate_sha256);
      if (!updated) throw new Error("La API no confirmó la activación.");
      setJob(updated);
      window.location.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo aplicar la actualización.");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    tokenRef.current = "";
    setToken("");
    setAuthorized(false);
    setJob(null);
    setUpdateStatus(null);
    setReviewer("");
    setError("");
  }

  const active = job && ["queued", "running"].includes(job.status);
  const label = scope === "competition" ? "Actualizar competición" : "Actualizar equipo";
  return (
    <section className="manual-update-control" aria-label={label}>
      {!authorized ? <form onSubmit={(event) => { void unlock(event); }}>
        <label>
          <span>Acceso administrador</span>
          <input
            aria-label="Token administrativo de actualización"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.currentTarget.value)}
            placeholder="Token de administración"
          />
        </label>
        <button className="manual-update-button" type="submit" disabled={busy}>
          {busy ? "Comprobando acceso…" : "Acceder"}
        </button>
      </form> : <>
        <form onSubmit={(event) => { void begin(event); }}>
          <label>
            <span>Acceso administrador verificado</span>
            <span className="manual-update-authenticated" aria-label="Sesión administrativa activa">Sesión activa</span>
          </label>
          <button className="manual-update-button is-secondary" type="button" onClick={() => { void loadPrevious(); }} disabled={busy}>
            Consultar última
          </button>
          <button className="manual-update-button" type="submit" disabled={busy || Boolean(active)}>
            {active ? "Actualizando…" : label}
          </button>
        </form>
        <button className="manual-update-logout" type="button" onClick={logout}>Cerrar sesión administrativa</button>
      </>}
      {job && <div className="manual-update-status" aria-live="polite" role="status">
        {active ? <><strong>En curso:</strong> {stageLabel(job.stage)}</>
          : job.status === "review_required" ? <><strong>Captura validada.</strong> Pendiente de revisión explícita.</>
          : job.status === "published" ? <><strong>Actualización aprobada y aplicada.</strong> {formatDate(job.finished_at ?? job.updated_at)}</>
            : job.status === "completed" ? <><strong>Sin cambios deportivos.</strong> La comprobación y sus capturas quedaron registradas.</>
            : job.status === "interrupted" ? <><strong>Interrumpida.</strong> No se repitió automáticamente.</>
              : job.status === "failed" ? <><strong>Actualización detenida.</strong> {job.error}</>
                : <><strong>Última comprobación:</strong> {formatDate(job.finished_at ?? job.created_at)}</>}
        {job.status === "review_required" && job.candidate && <p>{changeSummary(job.candidate)}</p>}
        {job.status === "review_required" && job.candidate && <ReviewChanges candidate={job.candidate} />}
        {job.status === "review_required" && job.candidate && job.candidate_sha256 && <div className="manual-update-approval">
          <label>
            <span>Revisor responsable</span>
            <input aria-label="Nombre del revisor" value={reviewer} onChange={(event) => setReviewer(event.currentTarget.value)} maxLength={120} />
          </label>
          <button type="button" className="manual-update-button" onClick={() => { void approveCandidate(); }} disabled={busy || !reviewer.trim()}>
            {busy ? "Aplicando…" : scope === "team" ? "Revisar y publicar perfil" : "Revisar y activar competición"}
          </button>
          <small>El servidor vuelve a verificar la integridad y registra la aprobación antes de aplicar los cambios.</small>
        </div>}
        {!active && job.finished_at && job.status !== "failed" && <time dateTime={job.finished_at}>Completada {formatDate(job.finished_at)}</time>}
      </div>}
      {error && <p className="manual-update-error" role="alert">{error}</p>}
      {authorized && <p className="manual-update-note">La captura se valida y compara; los cambios esperan tu revisión explícita.</p>}
      {authorized && updateStatus && <p className="manual-update-note">
        {updateStatus.last_updated_at && <>Última activación: {formatDate(updateStatus.last_updated_at)}. </>}
        {updateStatus.last_unchanged_check_at && <>Última comprobación sin cambios: {formatDate(updateStatus.last_unchanged_check_at)}. </>}
        {!updateStatus.last_updated_at && !updateStatus.last_unchanged_check_at && <>Aún no hay comprobaciones registradas.</>}
      </p>}
    </section>
  );
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    preflight: "comprobando el entorno",
    capturing_group_i: "capturando Grupo I",
    capturing_group_ii: "capturando Grupo II",
    building_generation: "validando resultados y clasificación",
    comparing_candidate: "comparando la generación",
    capturing_team: "capturando vistas del equipo",
    candidate_validated: "candidato listo para revisión",
  };
  return labels[stage] ?? stage.replaceAll("_", " ");
}

function changeSummary(candidate: Record<string, unknown>): string {
  if (candidate.kind === "team_profile_capture") {
    const files = Array.isArray(candidate.changed_files) ? candidate.changed_files.length : 0;
    return files ? `${files} archivos normalizados cambiaron.` : "No hay diferencias en los archivos publicados del equipo.";
  }
  const summary = candidate.summary;
  if (typeof summary !== "object" || summary === null) {
    const changedGroups = typeof candidate.changed_groups === "object" && candidate.changed_groups !== null
      ? Object.values(candidate.changed_groups as Record<string, unknown>).flatMap((value) => Array.isArray(value) ? value : [])
      : [];
    return `Se detectaron cambios en ${changedGroups.length} áreas de grupo; revisa el detalle antes de publicar.`;
  }
  const value = summary as Record<string, unknown>;
  return `Cambios: ${String(value.newly_played ?? 0)} partidos disputados nuevos, ${String(value.result_corrected ?? 0)} marcadores corregidos, ${String(value.fixture_updated ?? 0)} calendarios modificados; ${String(value.hard_conflicts ?? 0)} conflictos.`;
}

function ReviewChanges({ candidate }: { candidate: Record<string, unknown> }) {
  const fixtures = Array.isArray(candidate.changed_fixtures) ? candidate.changed_fixtures as Record<string, unknown>[] : [];
  const standings = typeof candidate.standings_changes === "object" && candidate.standings_changes !== null
    ? candidate.standings_changes as Record<string, unknown> : {};
  const standingRows = Object.entries(standings).flatMap(([group, rows]) =>
    Array.isArray(rows) ? rows.map((row) => ({ group, row: row as Record<string, unknown> })) : [],
  );
  const files = Array.isArray(candidate.changed_files) ? candidate.changed_files.map(String) : [];
  const progress = typeof candidate.progress_changes === "object" && candidate.progress_changes !== null
    ? candidate.progress_changes as Record<string, unknown> : {};
  const progressRows = Object.entries(progress).flatMap(([group, rows]) =>
    Array.isArray(rows) ? rows.map((row) => ({ group, row: row as Record<string, unknown> })) : [],
  );
  const total = fixtures.length + standingRows.length + progressRows.length + files.length;
  if (!total) return null;
  return (
    <details className="manual-update-diff" open>
      <summary>Ver {total} diferencia{total === 1 ? "" : "s"}</summary>
      <ul>
        {fixtures.map((fixture) => {
          const changes = Array.isArray(fixture.changes) ? fixture.changes as Record<string, unknown>[] : [];
          return <li key={String(fixture.internal_id)}><strong>{String(fixture.internal_id)}</strong> · {String(fixture.change_type)}{changes.length ? ` · ${changes.map(fieldChange).join("; ")}` : ""}</li>;
        })}
        {standingRows.map(({ group, row }, index) => {
          const changes = Array.isArray(row.changes) ? row.changes as Record<string, unknown>[] : [];
          return <li key={`${group}-${String(row.team_id)}-${index}`}><strong>Grupo {group} · equipo {String(row.team_id)}</strong> · {changes.length ? changes.map(fieldChange).join("; ") : String(row.kind)}</li>;
        })}
        {progressRows.map(({ group, row }, index) => {
          const changes = Array.isArray(row.changes) ? row.changes as Record<string, unknown>[] : [];
          return <li key={`progress-${group}-${String(row.team_id)}-${String(row.matchday)}-${index}`}><strong>Grupo {group} · equipo {String(row.team_id)} · J{String(row.matchday)}</strong> · {changes.length ? changes.map(fieldChange).join("; ") : String(row.kind)}</li>;
        })}
        {files.map((file) => <li key={file}><strong>Equipo:</strong> {file} ha cambiado</li>)}
      </ul>
    </details>
  );
}

function fieldChange(item: Record<string, unknown>): string {
  return `${String(item.field)}: ${displayValue(item.before)} → ${displayValue(item.after)}`;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("es-ES");
}
