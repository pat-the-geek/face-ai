import { describe, expect, it } from "vitest";
import { computeGrid, cellRect, sameLayout } from "./gridLayout";

describe("computeGrid — mode carré", () => {
  it("n=1 → une cellule carrée centrée", () => {
    const g = computeGrid(1, 1600, 900);
    expect(g.cols).toBe(1);
    expect(g.rows).toBe(1);
    expect(g.cellW).toBe(900);
    expect(g.cellH).toBe(900);
    expect(g.offsetX).toBeCloseTo((1600 - 900) / 2);
    expect(g.offsetY).toBe(0);
  });

  it("n=3 sur écran large → 3 colonnes", () => {
    const g = computeGrid(3, 1600, 900);
    expect(g.cols).toBe(3);
    expect(g.rows).toBe(1);
    expect(g.cellW).toBeCloseTo(1600 / 3);
    expect(g.cellW).toBe(g.cellH);
  });

  it("n=4 → grille 2×2 sur écran carré", () => {
    const g = computeGrid(4, 1000, 1000);
    expect(g.cols).toBe(2);
    expect(g.rows).toBe(2);
    expect(g.cellW).toBe(500);
    expect(g.cellH).toBe(500);
  });

  it("cellules carrées et sans débordement (n=100, 3000)", () => {
    for (const n of [100, 3000]) {
      const W = 1920;
      const H = 1080;
      const g = computeGrid(n, W, H);
      expect(g.cols * g.rows).toBeGreaterThanOrEqual(n);
      expect(g.cellW).toBe(g.cellH);
      expect(g.cols * g.cellW).toBeLessThanOrEqual(W + 1e-6);
      expect(g.rows * g.cellH).toBeLessThanOrEqual(H + 1e-6);
      expect(g.offsetX).toBeGreaterThanOrEqual(0);
      expect(g.offsetY).toBeGreaterThanOrEqual(0);
    }
  });

  it("entrées dégénérées → grille vide", () => {
    expect(computeGrid(0, 100, 100).cellW).toBe(0);
    expect(computeGrid(5, 0, 100).cellW).toBe(0);
  });
});

describe("computeGrid — mode plein cadre (fill)", () => {
  it("couvre exactement la zone, aucun letterbox", () => {
    const W = 1600;
    const H = 900;
    for (const n of [4, 50, 3000]) {
      const g = computeGrid(n, W, H, { fill: true });
      expect(g.offsetX).toBe(0);
      expect(g.offsetY).toBe(0);
      expect(g.cols * g.cellW).toBeCloseTo(W);
      expect(g.rows * g.cellH).toBeCloseTo(H);
      expect(g.cols * g.rows).toBeGreaterThanOrEqual(n);
    }
  });

  it("tuiles approximativement carrées", () => {
    const g = computeGrid(1000, 1600, 900, { fill: true });
    const ratio = g.cellW / g.cellH;
    expect(ratio).toBeGreaterThan(0.6);
    expect(ratio).toBeLessThan(1.6);
  });
});

describe("cellRect", () => {
  it("positionne les cellules ligne par ligne (x,y,w,h)", () => {
    const g = computeGrid(4, 1000, 1000); // 2×2, cell=500, offsets=0
    expect(cellRect(0, g)).toEqual({ x: 0, y: 0, w: 500, h: 500 });
    expect(cellRect(1, g)).toEqual({ x: 500, y: 0, w: 500, h: 500 });
    expect(cellRect(2, g)).toEqual({ x: 0, y: 500, w: 500, h: 500 });
    expect(cellRect(3, g)).toEqual({ x: 500, y: 500, w: 500, h: 500 });
  });
});

describe("sameLayout", () => {
  it("vrai si géométrie identique", () => {
    const a = { cols: 3, rows: 2, cellW: 100, cellH: 100, offsetX: 5 };
    const b = { cols: 3, rows: 2, cellW: 100, cellH: 100, offsetX: 0 };
    expect(sameLayout(a, b)).toBe(true);
  });
  it("faux si la cellule change de taille", () => {
    const a = { cols: 3, rows: 2, cellW: 100, cellH: 100 };
    const b = { cols: 3, rows: 3, cellW: 80, cellH: 80 };
    expect(sameLayout(a, b)).toBe(false);
  });
  it("faux si un argument manque", () => {
    expect(sameLayout(null, {})).toBe(false);
  });
});
