import { describe, expect, it, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useColorMode } from "./useColorMode";

beforeEach(() => {
  localStorage.clear();
  // Reset les variables CSS posées par un test précédent
  const root = document.documentElement.style;
  ["--bg-primary", "--bg-secondary", "--border", "--text-primary", "--text-secondary"].forEach(
    (v) => root.removeProperty(v),
  );
  document.documentElement.removeAttribute("data-color-mode");
});

describe("useColorMode hook", () => {
  it("defaults to 'light'", () => {
    const { result } = renderHook(() => useColorMode());
    expect(result.current.mode).toBe("light");
  });

  it("toggle bascule light ↔ dark", () => {
    const { result } = renderHook(() => useColorMode());
    act(() => result.current.toggle());
    expect(result.current.mode).toBe("dark");
    act(() => result.current.toggle());
    expect(result.current.mode).toBe("light");
  });

  it("pose l'attribut data-color-mode sur <html>", () => {
    const { result } = renderHook(() => useColorMode());
    act(() => result.current.setMode("dark"));
    expect(document.documentElement.getAttribute("data-color-mode")).toBe("dark");
    act(() => result.current.setMode("light"));
    expect(document.documentElement.getAttribute("data-color-mode")).toBe("light");
  });

  it("applique la palette dark via CSS vars en mode dark", () => {
    const { result } = renderHook(() => useColorMode());
    act(() => result.current.setMode("dark"));
    // Palette dark : HSL ~30° tiède
    const bg = document.documentElement.style.getPropertyValue("--bg-primary");
    expect(bg).toMatch(/hsl\(/);
    expect(bg).toContain("8%"); // luminosité dark fond primaire
  });

  it("applique la palette light neutre en mode light", () => {
    const { result } = renderHook(() => useColorMode());
    act(() => result.current.setMode("light"));
    const bg = document.documentElement.style.getPropertyValue("--bg-primary");
    expect(bg).toMatch(/hsl\(/);
    expect(bg).toContain("96%"); // luminosité light fond primaire
  });

  it("persiste dans localStorage", () => {
    const { result, unmount } = renderHook(() => useColorMode());
    act(() => result.current.setMode("dark"));
    unmount();

    const { result: result2 } = renderHook(() => useColorMode());
    expect(result2.current.mode).toBe("dark");
  });
});
