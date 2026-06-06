/**
 * Disposition de la grille « Foule » (logique pure, sans DOM).
 *
 * Deux modes :
 *  - **carré (défaut)** : cellules carrées qui maximisent la taille dans la
 *    zone, grille centrée (letterbox) — le découpage « un carré de plus par
 *    personne » d'origine.
 *  - **plein cadre (`fill`)** : les tuiles couvrent TOUTE la zone sans bord
 *    noir (cellules potentiellement non carrées) — requis par la photomosaïque
 *    pour qu'elle remplisse l'écran.
 *
 * Propriété exploitée par le moteur : tant que cols/rows/cellW/cellH ne
 * changent pas, les cellules déjà affichées ne bougent pas → on ne repeint que
 * la nouvelle (cf. `sameLayout`).
 */
export function computeGrid(n, width, height, opts = {}) {
  if (n <= 0 || width <= 0 || height <= 0) {
    return { cols: 0, rows: 0, cellW: 0, cellH: 0, offsetX: 0, offsetY: 0 };
  }
  if (opts.fill) {
    // cols ≈ √(n·ratio) pour des tuiles aussi carrées que possible, puis on
    // étire pour couvrir exactement la zone (aucun letterbox).
    let cols = Math.round(Math.sqrt((n * width) / height));
    cols = Math.max(1, Math.min(n, cols));
    const rows = Math.ceil(n / cols);
    return {
      cols,
      rows,
      cellW: width / cols,
      cellH: height / rows,
      offsetX: 0,
      offsetY: 0,
    };
  }
  // Mode carré : on cherche le nb de colonnes qui maximise la cellule carrée.
  let best = null;
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const cell = Math.min(width / cols, height / rows);
    if (!best || cell > best.cell) best = { cols, rows, cell };
  }
  const { cols, rows, cell } = best;
  return {
    cols,
    rows,
    cellW: cell,
    cellH: cell,
    offsetX: (width - cols * cell) / 2,
    offsetY: (height - rows * cell) / 2,
  };
}

/** Rectangle (px CSS) de la cellule d'indice `i` (i = row·cols + col). */
export function cellRect(i, grid) {
  const { cols, cellW, cellH, offsetX, offsetY } = grid;
  const row = Math.floor(i / cols);
  const col = i % cols;
  return {
    x: offsetX + col * cellW,
    y: offsetY + row * cellH,
    w: cellW,
    h: cellH,
  };
}

/** Deux dispositions sont « équivalentes en repeinture » si la géométrie est identique. */
export function sameLayout(a, b) {
  if (!a || !b) return false;
  return (
    a.cols === b.cols &&
    a.rows === b.rows &&
    a.cellW === b.cellW &&
    a.cellH === b.cellH
  );
}
