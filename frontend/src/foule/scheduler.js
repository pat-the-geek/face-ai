/**
 * Cadence & gouverneur adaptatif de la « Foule » (logique pure, sans DOM).
 *
 * Deux rythmes partagent le même curseur de vitesse (fps), comme convenu :
 *  - croissance : +1 personne (= +1 carré) par « battement », soit `fps`
 *    personnes/seconde ;
 *  - défilement des photos : on voudrait que chaque carré change à `fps`, donc
 *    un débit *désiré* de `fps × N` swaps/seconde. Ce débit explose avec N ;
 *    le gouverneur le plafonne pour ne pas saturer le CPU. Conséquence
 *    thématiquement juste : plus la foule grossit, plus chaque visage change
 *    lentement.
 *
 * Le gouverneur observe la santé des frames (rapport entre la durée réelle
 * d'une frame et la cible ~16,7 ms). S'il y a de la gigue, il abaisse le débit
 * effectif ; s'il y a de la marge, il le remonte — sous un plafond absolu.
 */
export const SPEEDS = [0.5, 1, 2, 4];

export const TARGET_FRAME_MS = 1000 / 60;

// Bornes absolues du débit de swaps (images décodées+peintes par seconde),
// indépendantes de N. Le plancher garantit que ça ne se fige jamais totalement.
export const MAX_SWAP_RATE = 240;
export const MIN_SWAP_RATE = 4;

/** Débit de swaps « désiré » si chaque carré changeait à la vitesse choisie. */
export function desiredSwapRate(fps, peopleShown) {
  return Math.max(0, fps) * Math.max(0, peopleShown);
}

/**
 * Un pas du gouverneur : ajuste le débit max autorisé en fonction de la santé
 * de la frame. `jankRatio` = durée réelle de frame / cible. Retourne le nouveau
 * plafond, borné par [floor, ceiling].
 */
export function governorStep(
  current,
  { jankRatio, ceiling = MAX_SWAP_RATE, floor = MIN_SWAP_RATE },
) {
  let next = current;
  if (jankRatio > 1.5) next = current * 0.6; // ça rame franchement → coupe fort
  else if (jankRatio > 1.2) next = current * 0.85; // ça tire → on lève le pied
  else if (jankRatio < 0.9) next = current * 1.1 + 1; // de la marge → on remonte
  return Math.max(floor, Math.min(ceiling, next));
}

/**
 * Sélection round-robin de `count` indices de cellules à faire avancer, à
 * partir d'un curseur, en bouclant sur `total`. Garantit une couverture
 * équitable de toutes les cellules au fil des appels. Ne renvoie jamais deux
 * fois le même indice dans un même appel (count est borné à total).
 */
export function roundRobinIndices(cursor, count, total) {
  const indices = [];
  if (total <= 0 || count <= 0) return { indices, cursor: cursor % Math.max(1, total) };
  const k = Math.min(count, total);
  let c = ((cursor % total) + total) % total;
  for (let i = 0; i < k; i++) {
    indices.push(c);
    c = (c + 1) % total;
  }
  return { indices, cursor: c };
}
