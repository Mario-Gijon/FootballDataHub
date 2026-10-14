import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InternalTeamLink } from "../components/InternalTeamLink";

afterEach(cleanup);

describe("InternalTeamLink", () => {
  it("mantiene un href real y navega dentro de la aplicación en un clic normal", () => {
    const onNavigate = vi.fn();
    render(<InternalTeamLink teamId={49} onNavigate={onNavigate}>Real Jaén</InternalTeamLink>);
    const link = screen.getByRole("link", { name: "Real Jaén" });

    expect(link).toHaveAttribute("href", "/teams/49");
    const click = fireEvent.click(link);
    expect(click).toBe(false);
    expect(onNavigate).toHaveBeenCalledWith("/teams/49");
  });

  it.each([
    ["Ctrl", { ctrlKey: true }],
    ["Meta", { metaKey: true }],
    ["Shift", { shiftKey: true }],
    ["Alt", { altKey: true }],
    ["central", { button: 1 }],
  ])("deja que el navegador gestione el clic %s", (_label, options) => {
    const onNavigate = vi.fn();
    render(<InternalTeamLink teamId={48} onNavigate={onNavigate} target="_blank">Racing de Ferrol</InternalTeamLink>);
    const link = screen.getByRole("link", { name: "Racing de Ferrol" });

    expect(link).toHaveAttribute("href", "/teams/48");
    expect(fireEvent.click(link, options)).toBe(true);
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
