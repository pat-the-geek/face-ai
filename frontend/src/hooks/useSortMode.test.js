import { describe, expect, it, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useSortMode,
  getSortKey,
  getDisplayName,
} from "./useSortMode";

beforeEach(() => {
  localStorage.clear();
});

describe("useSortMode hook", () => {
  it("defaults to 'canonical'", () => {
    const { result } = renderHook(() => useSortMode());
    expect(result.current.mode).toBe("canonical");
  });

  it("toggle bascule canonical ↔ first_name", () => {
    const { result } = renderHook(() => useSortMode());
    act(() => result.current.toggle());
    expect(result.current.mode).toBe("first_name");
    act(() => result.current.toggle());
    expect(result.current.mode).toBe("canonical");
  });

  it("setMode pose une valeur explicite", () => {
    const { result } = renderHook(() => useSortMode());
    act(() => result.current.setMode("first_name"));
    expect(result.current.mode).toBe("first_name");
  });

  it("persiste dans localStorage", () => {
    const { result, unmount } = renderHook(() => useSortMode());
    act(() => result.current.setMode("first_name"));
    unmount();

    // Nouveau mount : doit retrouver l'état
    const { result: result2 } = renderHook(() => useSortMode());
    expect(result2.current.mode).toBe("first_name");
  });

  it("valeurs invalides en localStorage → fallback canonical", () => {
    localStorage.setItem("face_ai_sort_mode", "garbage");
    const { result } = renderHook(() => useSortMode());
    expect(result.current.mode).toBe("canonical");
  });
});

describe("getSortKey", () => {
  it("retourne le nom canonique en mode canonical", () => {
    expect(getSortKey("Chalamet, Timothée", "canonical")).toBe("Chalamet, Timothée");
  });

  it("extrait le prénom (après virgule) en mode first_name", () => {
    expect(getSortKey("Chalamet, Timothée", "first_name")).toBe("Timothée");
  });

  it("mononymes : retourne le nom entier en mode first_name", () => {
    expect(getSortKey("Madonna", "first_name")).toBe("Madonna");
  });

  it("gère null/undefined sans crasher", () => {
    expect(getSortKey(null, "first_name")).toBe("");
    expect(getSortKey(undefined, "canonical")).toBe("");
  });
});

describe("getDisplayName", () => {
  it("retourne tel quel en mode canonical", () => {
    expect(getDisplayName("Chalamet, Timothée", "canonical"))
      .toBe("Chalamet, Timothée");
  });

  it("convertit Last, First → First Last en mode first_name", () => {
    expect(getDisplayName("Chalamet, Timothée", "first_name"))
      .toBe("Timothée Chalamet");
  });

  it("mononymes : inchangés", () => {
    expect(getDisplayName("Madonna", "first_name")).toBe("Madonna");
  });

  it("gère null sans crasher", () => {
    expect(getDisplayName(null, "first_name")).toBe(null);
  });
});
