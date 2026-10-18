import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InternalMatchLink } from "../components/InternalMatchLink";
import { matchInternalId, matchPath, matchPathForSourceId } from "../domain/matches";

describe("identidad y navegación de partidos", () => {
  it("distingue grupos al construir rutas para un mismo ID de fuente", () => {
    const groupOne = matchPathForSourceId("I", "2026-27", "272582");
    const groupTwo = matchPathForSourceId("II", "2026-27", "272582");
    expect(groupOne).toBe("/matches/pf-2026-27-group-i-bdfutbol-272582");
    expect(groupTwo).toBe("/matches/pf-2026-27-group-ii-bdfutbol-272582");
    expect(groupOne).not.toBe(groupTwo);
    expect(matchInternalId("2", "2026-27", "272525")).toBe("pf-2026-27-group-ii-bdfutbol-272525");
    expect(() => matchInternalId("III", "2026-27", "272525")).toThrow(RangeError);
    expect(() => matchPath("272525")).toThrow(RangeError);
  });

  it("intercepta clic normal y preserva Ctrl+clic del navegador", () => {
    const onNavigate = vi.fn();
    const { rerender } = render(<InternalMatchLink internalId="pf-2026-27-group-ii-bdfutbol-272582" onNavigate={onNavigate}>3–3</InternalMatchLink>);
    const link = screen.getByRole("link", { name: "3–3" });
    expect(link).toHaveAttribute("href", "/matches/pf-2026-27-group-ii-bdfutbol-272582");

    fireEvent.click(link);
    expect(onNavigate).toHaveBeenCalledWith("/matches/pf-2026-27-group-ii-bdfutbol-272582");

    onNavigate.mockClear();
    rerender(<InternalMatchLink internalId="pf-2026-27-group-ii-bdfutbol-272582" onNavigate={onNavigate} target="_blank">3–3</InternalMatchLink>);
    const modifiedLink = screen.getByRole("link", { name: "3–3" });
    fireEvent.click(modifiedLink, { ctrlKey: true });
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
