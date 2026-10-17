import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InternalPlayerLink } from "../components/InternalPlayerLink";
import { playerPath } from "../domain/players";

afterEach(cleanup);

describe("InternalPlayerLink", () => {
  it("navega dentro de la aplicación conservando un href compartible", () => {
    const onNavigate = vi.fn();
    render(<InternalPlayerLink playerId={23751} onNavigate={onNavigate}>Manu Pedreño</InternalPlayerLink>);
    const link = screen.getByRole("link", { name: "Manu Pedreño" });

    expect(link).toHaveAttribute("href", "/players/23751");
    expect(fireEvent.click(link)).toBe(false);
    expect(onNavigate).toHaveBeenCalledWith("/players/23751");
  });

  it.each([
    ["Ctrl", { ctrlKey: true }],
    ["Cmd", { metaKey: true }],
    ["Shift", { shiftKey: true }],
    ["Alt", { altKey: true }],
    ["central", { button: 1 }],
  ])("deja al navegador gestionar el clic %s", (_label, options) => {
    const onNavigate = vi.fn();
    render(<InternalPlayerLink playerId={110652} onNavigate={onNavigate} target="_blank">Aarón</InternalPlayerLink>);
    const link = screen.getByRole("link", { name: "Aarón" });

    expect(link).toHaveAttribute("href", "/players/110652");
    expect(fireEvent.click(link, options)).toBe(true);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("rechaza identificadores que no pueden formar una ruta válida", () => {
    expect(() => playerPath(0)).toThrow(RangeError);
    expect(() => playerPath(Number.NaN)).toThrow(RangeError);
  });
});
