import { describe, expect, it } from "vitest";
import {
  desiredSwapRate,
  governorStep,
  roundRobinIndices,
  MAX_SWAP_RATE,
  MIN_SWAP_RATE,
} from "./scheduler";

describe("desiredSwapRate", () => {
  it("fps × personnes affichées", () => {
    expect(desiredSwapRate(2, 10)).toBe(20);
    expect(desiredSwapRate(0.5, 4)).toBe(2);
  });
  it("borné à 0 pour entrées négatives", () => {
    expect(desiredSwapRate(-1, 10)).toBe(0);
    expect(desiredSwapRate(2, 0)).toBe(0);
  });
});

describe("governorStep", () => {
  it("réduit fortement le débit quand ça rame (jank > 1.5)", () => {
    const next = governorStep(100, { jankRatio: 2 });
    expect(next).toBeCloseTo(60);
  });

  it("réduit modérément quand ça tire (1.2 < jank < 1.5)", () => {
    const next = governorStep(100, { jankRatio: 1.3 });
    expect(next).toBeCloseTo(85);
  });

  it("remonte quand il y a de la marge (jank < 0.9)", () => {
    const next = governorStep(100, { jankRatio: 0.5 });
    expect(next).toBeGreaterThan(100);
  });

  it("stable dans la zone neutre", () => {
    expect(governorStep(100, { jankRatio: 1.0 })).toBe(100);
  });

  it("respecte le plancher et le plafond", () => {
    expect(governorStep(MIN_SWAP_RATE, { jankRatio: 3 })).toBe(MIN_SWAP_RATE);
    expect(governorStep(MAX_SWAP_RATE, { jankRatio: 0.1 })).toBe(MAX_SWAP_RATE);
  });

  it("converge vers le plancher sous gigue répétée", () => {
    let r = 200;
    for (let i = 0; i < 50; i++) r = governorStep(r, { jankRatio: 2 });
    expect(r).toBe(MIN_SWAP_RATE);
  });
});

describe("roundRobinIndices", () => {
  it("couvre toutes les cellules en plusieurs appels sans en sauter", () => {
    const total = 5;
    const seen = new Set();
    let cursor = 0;
    for (let i = 0; i < 5; i++) {
      const r = roundRobinIndices(cursor, 1, total);
      r.indices.forEach((x) => seen.add(x));
      cursor = r.cursor;
    }
    expect([...seen].sort()).toEqual([0, 1, 2, 3, 4]);
  });

  it("boucle correctement quand count > restant", () => {
    const r = roundRobinIndices(3, 4, 5); // 3,4,0,1
    expect(r.indices).toEqual([3, 4, 0, 1]);
    expect(r.cursor).toBe(2);
  });

  it("ne renvoie jamais plus que total indices", () => {
    const r = roundRobinIndices(0, 100, 5);
    expect(r.indices).toHaveLength(5);
  });

  it("entrées vides → rien", () => {
    expect(roundRobinIndices(0, 5, 0).indices).toEqual([]);
    expect(roundRobinIndices(0, 0, 5).indices).toEqual([]);
  });
});
