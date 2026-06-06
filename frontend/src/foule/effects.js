/**
 * Effets visuels de la « Foule » — helpers purs (sans DOM), testables.
 *
 * Ces fonctions ne font que du calcul d'ordre / de timing / d'interpolation ;
 * le rendu (canvas) reste dans le moteur useFoule.
 */

/**
 * Ordre de balayage en **onde diagonale** : indices de cellules 0..count-1
 * triés par (row + col) croissant, puis col. Parcourus en round-robin, ils
 * font traverser la grille par un front diagonal (haut-gauche → bas-droite).
 */
export function diagonalOrder(cols, rows, count) {
  const n = Math.min(count, cols * rows);
  const order = [];
  for (let i = 0; i < n; i++) order.push(i);
  order.sort((a, b) => {
    const ra = Math.floor(a / cols);
    const ca = a % cols;
    const rb = Math.floor(b / cols);
    const cb = b % cols;
    const da = ra + ca;
    const db = rb + cb;
    if (da !== db) return da - db;
    return ca - cb;
  });
  return order;
}

/** La pulsation Galton est-elle due ? (fenêtre glissante simple) */
export function pulseDue(nowMs, lastMs, intervalMs) {
  return nowMs - lastMs >= intervalMs;
}

/** Lissage cubique (smoothstep) pour des fondus doux. t clampé à [0,1]. */
export function easeInOut(t) {
  const x = t < 0 ? 0 : t > 1 ? 1 : t;
  return x * x * (3 - 2 * x);
}

/**
 * Index dans un buffer RGBA (largeur `cols`) de la cellule (col, row).
 * Sert l'échantillonnage de la photomosaïque (couleur cible par cellule).
 */
export function rgbaIndex(col, row, cols) {
  return (row * cols + col) * 4;
}
