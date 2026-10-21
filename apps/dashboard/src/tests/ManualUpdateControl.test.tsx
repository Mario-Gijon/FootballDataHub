import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ManualUpdateControl } from "../components/ManualUpdateControl";
import type { ManualUpdateJob } from "../api/client";

const api = vi.hoisted(() => ({
  loadManualUpdateJob: vi.fn(),
  loadLatestCompetitionUpdate: vi.fn(),
  startCompetitionUpdate: vi.fn(),
}));

vi.mock("../api/client", () => api);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.useRealTimers();
  window.sessionStorage.clear();
});

function job(patch: Partial<ManualUpdateJob> = {}): ManualUpdateJob {
  return {
    job_id: "job-competition-1", scope: "competition", group: null,
    status: "queued", stage: "queued", created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z", finished_at: null, summary: null, error: null,
    ...patch,
  };
}

describe("ManualUpdateControl", () => {
  it("offers one global competition action without credentials or a review dialog", async () => {
    render(<ManualUpdateControl />);

    expect(screen.getByRole("button", { name: "Actualizar Primera Federación" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /equipo|revisar|aplicar/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/token|contraseña|revisor/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("starts only the global group I + II job and shows its progress", async () => {
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({ status: "running", stage: "capturing_group_ii" }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    await waitFor(() => expect(api.startCompetitionUpdate).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Actualizando… consultando Grupo II"), { timeout: 4000 });
    expect(screen.getByRole("button", { name: "Actualizando…" })).toBeDisabled();
  });

  it("shows Sin cambios when both groups compare equal", async () => {
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({
      status: "completed", stage: "no_changes", finished_at: "2026-10-20T10:02:00Z",
      summary: { message: "Sin cambios", changed_groups: { I: [], II: [] } },
    }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    expect(await screen.findByText("Sin cambios", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(api.loadManualUpdateJob).toHaveBeenCalledWith("job-competition-1");
  });

  it("reports the excluded blocked match even when there are no eligible detail candidates", async () => {
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({
      status: "completed", stage: "no_changes", finished_at: "2026-10-20T10:02:00Z",
      summary: { message: "Sin cambios", changed_groups: { I: [], II: [] },
        match_details_candidate_count: 0, match_details_blocked_excluded_count: 1 },
    }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    expect(await screen.findByText("Sin cambios", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 partido bloqueado excluido");
  });

  it("reports the automatic result summary and refreshes the visible competition", async () => {
    const onApplied = vi.fn();
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({
      status: "applied", stage: "completed", finished_at: "2026-10-20T10:04:00Z",
      summary: { message: "Actualización aplicada", newly_played: 2, result_corrected: 1,
        fixture_updated: 3, played_without_approved_details: 2 },
    }));
    const { container } = render(<ManualUpdateControl onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    expect(await screen.findByText(/2 partidos disputados nuevos · 1 marcadores corregidos · 3 cambios de calendario · 2 fichas detalladas pendientes/, {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
    expect(container.textContent).not.toMatch(/sha-?256|revisor|aprobar|huella/i);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("describes classification-only changes without claiming match changes", async () => {
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({
      status: "applied", stage: "completed", finished_at: "2026-10-20T10:04:00Z",
      summary: { message: "Actualización aplicada", changed_groups: { I: [], II: ["classification", "progress"] } },
    }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    expect(await screen.findByText("Grupo II: clasificación, progreso", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/0 partidos|0 marcadores|0 cambios de calendario/)).not.toBeInTheDocument();
  });

  it("reports partial completion instead of success when an optional source failed", async () => {
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({
      status: "applied", stage: "completed", finished_at: "2026-10-21T12:04:33Z",
      summary: {
        message: "Actualización parcial: una fuente relacionada dio error; se conservaron sus datos anteriores.",
        related_section_status: { groups: { I: {
          top: { status: "changed" },
          statistics: { status: "error", reason: "La captura no acredita identidad y validación." },
        } } },
        match_details_error: "ScalableCampaignError: Entrada inesperada en review v2",
        match_details_pending_count: 0,
      },
    }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    await screen.findByText("Actualización parcial.", {}, { timeout: 4000 });
    const status = await screen.findByRole("status", {}, { timeout: 4000 });
    expect(status).toHaveTextContent("Actualización parcial.");
    expect(status).not.toHaveTextContent("Actualización completada.");
    expect(status).toHaveTextContent("Destacados Grupo I");
    expect(status).not.toHaveTextContent("Destacados Grupo I: error");
    expect(status).toHaveTextContent("Estadísticas Grupo I");
    expect(status).toHaveTextContent("Entrada inesperada en review v2");
  });

  it("surfaces denied or failed access without retrying or opening review", async () => {
    api.startCompetitionUpdate.mockRejectedValue(new Error("HTTP_403: acceso detenido"));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP_403: acceso detenido");
    expect(api.startCompetitionUpdate).toHaveBeenCalledOnce();
    expect(api.loadManualUpdateJob).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("recovers the registered job when the POST response is lost, without starting a second job", async () => {
    const startedAt = Date.parse("2026-10-21T12:00:00.000Z");
    vi.spyOn(Date, "now").mockReturnValue(startedAt);
    api.startCompetitionUpdate.mockRejectedValue(new TypeError("Failed to fetch"));
    api.loadLatestCompetitionUpdate.mockResolvedValue(job({
      status: "running", stage: "capturing_group_i", created_at: new Date(startedAt).toISOString(),
    }));
    api.loadManualUpdateJob.mockResolvedValue(job({ status: "running", stage: "capturing_group_ii" }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    expect(await screen.findByText(/consultando Grupo II/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(api.startCompetitionUpdate).toHaveBeenCalledOnce();
    expect(api.loadLatestCompetitionUpdate).toHaveBeenCalledOnce();
    expect(api.loadManualUpdateJob).toHaveBeenCalledWith("job-competition-1");
  });

  it("does not mistake an older completed job for a start whose response was lost", async () => {
    const startedAt = Date.parse("2026-10-21T12:00:00.000Z");
    vi.spyOn(Date, "now").mockReturnValue(startedAt);
    api.startCompetitionUpdate.mockRejectedValue(new TypeError("Failed to fetch"));
    api.loadLatestCompetitionUpdate.mockResolvedValue(job({
      status: "applied", stage: "completed", created_at: "2026-10-20T12:00:00.000Z",
    }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("no hay un trabajo nuevo registrado"));
    expect(screen.getByRole("button", { name: "Actualizar Primera Federación" })).toBeEnabled();
    expect(api.startCompetitionUpdate).toHaveBeenCalledOnce();
    expect(api.loadManualUpdateJob).not.toHaveBeenCalled();
  });

  it("keeps the button locked while the API is unavailable, then recovers without a second POST", async () => {
    const startedAt = Date.parse("2026-10-21T12:00:00.000Z");
    vi.spyOn(Date, "now").mockReturnValue(startedAt);
    api.startCompetitionUpdate.mockRejectedValue(new TypeError("Failed to fetch"));
    api.loadLatestCompetitionUpdate
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(job({ status: "running", created_at: new Date(startedAt).toISOString() }));
    api.loadManualUpdateJob.mockResolvedValue(job({ status: "running", stage: "capturing_group_ii" }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    await vi.waitFor(() => expect(api.loadLatestCompetitionUpdate).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Recuperando…" })).toBeDisabled();
    await waitFor(() => expect(api.loadLatestCompetitionUpdate).toHaveBeenCalledTimes(2), { timeout: 6000 });
    expect(api.startCompetitionUpdate).toHaveBeenCalledOnce();
    expect(await screen.findByText(/consultando Grupo II/, {}, { timeout: 4000 })).toBeInTheDocument();
  }, 10000);

  it("restores the active job from this tab after a page remount", async () => {
    window.sessionStorage.setItem("fdh:manual-update:competition", JSON.stringify({
      jobId: "job-competition-1", startedAt: Date.parse("2026-10-21T12:00:00.000Z"),
    }));
    api.loadManualUpdateJob.mockResolvedValue(job({ status: "running", stage: "capturing_group_ii" }));
    render(<ManualUpdateControl />);

    expect(await screen.findByText(/consultando Grupo II/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(api.loadManualUpdateJob).toHaveBeenCalledWith("job-competition-1");
    expect(api.startCompetitionUpdate).not.toHaveBeenCalled();
  });

  it("shows the diagnosed normalization failure and leaves the global button available", async () => {
    api.startCompetitionUpdate.mockResolvedValue(job());
    api.loadManualUpdateJob.mockResolvedValue(job({
      status: "failed", stage: "failed", finished_at: "2026-10-20T10:02:00Z",
      error: "Falló la normalización de partidos del Grupo II: el informe de validación ya existía en una ruta compartida. Las capturas se conservaron y no se reintentó la adquisición.",
    }));
    render(<ManualUpdateControl />);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar Primera Federación" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(
      "Falló la normalización de partidos del Grupo II",
    ), { timeout: 4000 });
    expect(screen.getByRole("status")).not.toHaveTextContent(/código 1|ManualUpdateError/);
    expect(screen.getByRole("button", { name: "Actualizar Primera Federación" })).toBeEnabled();
    expect(api.startCompetitionUpdate).toHaveBeenCalledOnce();
  });

});
