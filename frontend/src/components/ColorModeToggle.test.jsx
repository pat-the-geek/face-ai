import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ColorModeToggle from "./ColorModeToggle";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-color-mode");
});

describe("ColorModeToggle", () => {
  it("affiche 🌙 en mode light par défaut", () => {
    render(<ColorModeToggle />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveTextContent("🌙");
    expect(btn).toHaveAttribute("aria-label", "Mode sombre");
  });

  it("bascule en mode dark au clic et affiche ☀", async () => {
    const user = userEvent.setup();
    render(<ColorModeToggle />);
    await user.click(screen.getByRole("button"));
    const btn = screen.getByRole("button");
    expect(btn).toHaveTextContent("☀");
    expect(btn).toHaveAttribute("aria-label", "Mode clair");
    expect(document.documentElement.getAttribute("data-color-mode")).toBe("dark");
  });

  it("retoggle vers light après un second clic", async () => {
    const user = userEvent.setup();
    render(<ColorModeToggle />);
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveTextContent("🌙");
    expect(document.documentElement.getAttribute("data-color-mode")).toBe("light");
  });
});
