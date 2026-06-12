import { describe, expect, it } from "vitest";
import { diagonalOrder, pulseDue, easeInOut, rgbaIndex } from "./effects";

describe("diagonalOrder", () => {
  it("ordonne par diagonale (row+col) puis colonne", () => {
    // grille 3×2 (cols=3) :
    // indices  0 1 2
    //          3 4 5
    // diagonales : 0→0 ; {1,3}→1 ; {2,4}→2 ; 5→3
    // au sein d'une diagonale : colonne croissante (3 avant 1, 4 avant 2)
    const order = diagonalOrder(3, 2, 6);
    expect(order).toEqual([0, 3, 1, 4, 2, 5]);
  });

  it("borne au nombre de cellules réel", () => {
    expect(diagonalOrder(3, 3, 4)).toHaveLength(4);
  });

  it("couvre tous les indices une seule fois", () => {
    const order = diagonalOrder(5, 4, 20);
    expect([...order].sort((a, b) => a - b)).toEqual(
      Array.from({ length: 20 }, (_, i) => i),
    );
  });
});

describe("pulseDue", () => {
  it("vrai une fois l'intervalle écoulé", () => {
    expect(pulseDue(10000, 1000, 9000)).toBe(true);
    expect(pulseDue(9999, 1000, 9000)).toBe(false);
  });
});

describe("easeInOut", () => {
  it("clampe et lisse 0→1", () => {
    expect(easeInOut(-1)).toBe(0);
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(0.5)).toBeCloseTo(0.5);
    expect(easeInOut(1)).toBe(1);
    expect(easeInOut(2)).toBe(1);
  });
  it("monotone croissant", () => {
    expect(easeInOut(0.25)).toBeLessThan(easeInOut(0.75));
  });
});

describe("rgbaIndex", () => {
  it("offset RGBA pour (col,row) dans un buffer de largeur cols", () => {
    expect(rgbaIndex(0, 0, 4)).toBe(0);
    expect(rgbaIndex(1, 0, 4)).toBe(4);
    expect(rgbaIndex(0, 1, 4)).toBe(16);
    expect(rgbaIndex(3, 2, 4)).toBe((2 * 4 + 3) * 4);
  });
});
