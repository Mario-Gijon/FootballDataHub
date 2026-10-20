import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ManualUpdateControl } from "../components/ManualUpdateControl";
import type { ManualUpdateJob } from "../api/client";

const api = vi.hoisted(() => ({
  loadLatestManualUpdate: vi.fn(),
  loadManualUpdateCapabilities: vi.fn(),
  loadManualUpdateStatus: vi.fn(),
  loadManualUpdateJob: vi.fn(),
  approveManualUpdate: vi.fn(),
  startCompetitionUpdate: vi.fn(),
  startTeamUpdate: vi.fn(),
}));

vi.mock("../api/client", () => api);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

function reviewJob(): ManualUpdateJob {
  return {
    job_id: "job-test-01",
    scope: "competition",
    team_id: null,
    group: null,
    status: "review_required",
    stage: "candidate_validated",
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:01:00Z",
    finished_at: "2026-10-20T10:01:00Z",
    candidate_sha256: "abc123-secret-integrity-hash",
    candidate: {
      summary: { newly_played: 1, result_corrected: 0, fixture_updated: 0, hard_conflicts: 0 },
      changed_fixtures: [{ internal_id: "match-1", change_type: "newly_played", changes: [{ field: "status", before: "unplayed", after: "played" }] }],
    },
    error: null,
    log_tail: null,
  };
}

describe("ManualUpdateControl", () => {
  it("does not query update metadata until the administrator authenticates", () => {
    api.loadManualUpdateCapabilities.mockResolvedValue(["competition"]);
    api.loadManualUpdateStatus.mockResolvedValue({ scope: "competition", team_id: null, last_updated_at: null, last_unchanged_check_at: null, last_checked_at: null });
    api.loadLatestManualUpdate.mockResolvedValue(null);
    render(<ManualUpdateControl scope="competition" />);
    expect(screen.getByLabelText("Token administrativo de actualización")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Acceder" })).toBeInTheDocument();
    expect(api.loadManualUpdateCapabilities).not.toHaveBeenCalled();
    expect(api.loadManualUpdateStatus).not.toHaveBeenCalled();
  });

  it("shows in-progress state and the current capture stage", async () => {
    api.loadManualUpdateCapabilities.mockResolvedValue(["competition"]);
    api.loadManualUpdateStatus.mockResolvedValue({ scope: "competition", team_id: null, last_updated_at: null, last_unchanged_check_at: null, last_checked_at: null });
    api.loadLatestManualUpdate.mockResolvedValue({ ...reviewJob(), status: "running", stage: "capturing_group_ii" });

    render(<ManualUpdateControl scope="competition" />);
    fireEvent.change(screen.getByLabelText("Token administrativo de actualización"), { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Acceder" }));

    expect(await screen.findByRole("status")).toHaveTextContent("En curso: capturando Grupo II");
    expect(screen.getByRole("button", { name: "Actualizando…" })).toBeDisabled();
  });

  it("surfaces a stopped access error without restarting the job", async () => {
    api.loadManualUpdateCapabilities.mockResolvedValue(["competition"]);
    api.loadManualUpdateStatus.mockResolvedValue({ scope: "competition", team_id: null, last_updated_at: null, last_unchanged_check_at: null, last_checked_at: null });
    api.loadLatestManualUpdate.mockResolvedValue({ ...reviewJob(), status: "failed", error: "HTTP_403_STOPPED" });

    render(<ManualUpdateControl scope="competition" />);
    fireEvent.change(screen.getByLabelText("Token administrativo de actualización"), { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Acceder" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Actualización detenida. HTTP_403_STOPPED");
    expect(api.startCompetitionUpdate).not.toHaveBeenCalled();
  });

  it("authenticates, starts only its scope, shows diffs and keeps the fingerprint hidden", async () => {
    api.loadManualUpdateCapabilities.mockResolvedValue(["competition"]);
    api.loadManualUpdateStatus.mockResolvedValue({ scope: "competition", team_id: null, last_updated_at: null, last_unchanged_check_at: null, last_checked_at: null });
    api.loadLatestManualUpdate.mockResolvedValue(null);
    api.startCompetitionUpdate.mockResolvedValue(reviewJob());

    const { container } = render(<ManualUpdateControl scope="competition" />);
    fireEvent.change(screen.getByLabelText("Token administrativo de actualización"), { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Acceder" }));
    await screen.findByRole("button", { name: "Actualizar competición" });
    expect(api.loadManualUpdateCapabilities).toHaveBeenCalledWith("admin-secret");
    expect(api.loadManualUpdateStatus).toHaveBeenCalledWith("competition", "admin-secret", undefined);

    fireEvent.click(screen.getByRole("button", { name: "Actualizar competición" }));
    await waitFor(() => expect(api.startCompetitionUpdate).toHaveBeenCalledWith("admin-secret"));
    expect(api.startTeamUpdate).not.toHaveBeenCalled();
    expect(await screen.findByText(/Cambios: 1 partidos disputados nuevos/)).toBeInTheDocument();
    expect(screen.getByText(/status: unplayed → played/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("abc123-secret-integrity-hash");
    expect(container.querySelector(".manual-update-diff")).toHaveAttribute("open");
  });

  it("muestra errores de autenticación y no guarda credenciales", async () => {
    api.loadManualUpdateCapabilities.mockRejectedValue(new Error("Token incorrecto."));
    const { container } = render(<ManualUpdateControl scope="team" teamId={49} />);
    const tokenInput = screen.getByLabelText("Token administrativo de actualización");
    fireEvent.change(tokenInput, { target: { value: "wrong-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Acceder" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Token incorrecto.");
    expect(container.innerHTML).not.toContain("localStorage");
    expect(api.startTeamUpdate).not.toHaveBeenCalled();
  });

  it("actualiza solo el equipo de la ficha y presenta su estado y cambios", async () => {
    api.loadManualUpdateCapabilities.mockResolvedValue(["team"]);
    api.loadManualUpdateStatus.mockResolvedValue({ scope: "team", team_id: 49, last_updated_at: null, last_unchanged_check_at: null, last_checked_at: null });
    api.loadLatestManualUpdate.mockResolvedValue(null);
    api.startTeamUpdate.mockResolvedValue({
      ...reviewJob(),
      scope: "team",
      team_id: 49,
      candidate: { kind: "team_profile_capture", changed_files: ["normalized/roster.json"] },
    });

    render(<ManualUpdateControl scope="team" teamId={49} />);
    fireEvent.change(screen.getByLabelText("Token administrativo de actualización"), { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Acceder" }));
    await screen.findByRole("button", { name: "Actualizar equipo" });
    expect(api.loadManualUpdateStatus).toHaveBeenCalledWith("team", "admin-secret", 49);
    fireEvent.click(screen.getByRole("button", { name: "Actualizar equipo" }));
    await waitFor(() => expect(api.startTeamUpdate).toHaveBeenCalledWith(49, "admin-secret"));
    expect(api.startCompetitionUpdate).not.toHaveBeenCalled();
    expect(await screen.findByText("1 archivos normalizados cambiaron.")).toBeInTheDocument();
    expect(screen.getByText(/normalized\/roster.json ha cambiado/)).toBeInTheDocument();
  });

  it("aplica los cambios solo después de una confirmación explícita y envía la huella internamente", async () => {
    api.loadManualUpdateCapabilities.mockResolvedValue(["competition"]);
    api.loadManualUpdateStatus.mockResolvedValue({ scope: "competition", team_id: null, last_updated_at: null, last_unchanged_check_at: null, last_checked_at: null });
    api.loadLatestManualUpdate.mockResolvedValue(null);
    api.startCompetitionUpdate.mockResolvedValue(reviewJob());
    api.approveManualUpdate.mockResolvedValue({ ...reviewJob(), status: "published" });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ManualUpdateControl scope="competition" />);
    fireEvent.change(screen.getByLabelText("Token administrativo de actualización"), { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Acceder" }));
    await screen.findByRole("button", { name: "Actualizar competición" });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar competición" }));
    await screen.findByText(/Cambios: 1 partidos disputados nuevos/);

    fireEvent.change(screen.getByLabelText("Nombre del revisor"), { target: { value: "Analista local" } });
    fireEvent.click(screen.getByRole("button", { name: "Revisar y activar competición" }));
    await waitFor(() => expect(api.approveManualUpdate).toHaveBeenCalledWith(
      "job-test-01", "admin-secret", "Analista local", "abc123-secret-integrity-hash",
    ));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("¿Aprobar y aplicar los cambios mostrados?"));
    expect(document.body.textContent).not.toContain("abc123-secret-integrity-hash");
  });
});
