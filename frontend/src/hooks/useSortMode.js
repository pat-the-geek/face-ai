import { useSyncExternalStore } from "react";

/**
 * Mode de tri/affichage des noms d'entités.
 *
 * - `"canonical"` (défaut) : tri sur "Last, First", affichage idem.
 *   Cohérent avec la convention CLAUDE.md. Lettre alphabétique = nom de famille.
 * - `"first_name"` : tri sur le prénom (ce qui suit la virgule, ou le nom
 *   entier pour les mononymes), affichage "First Last". Pratique quand on
 *   cherche par prénom (Timothée, Beyoncé, Madonna). Limite : la barre
 *   alphabétique de l'AlphaNav reste indexée sur le nom de famille.
 * - `"activity"` : tri sur l'activité presse (`article_count` décroissant,
 *   puis nom de famille). Affichage canonique "Last, First". C'est un
 *   classement, pas une navigation alphabétique : l'AlphaNav masque la
 *   barre des lettres dans ce mode. Le tri est fait côté backend (cf.
 *   `/entities?sort_by=activity`) pour rester correct avec la pagination.
 *
 * **Store partagé** (pas un simple `useState` par instance) : AlphaNav (le
 * toggle) et EntityList (le consommateur) appellent tous deux `useSortMode`.
 * Avec un état local, changer le mode dans AlphaNav ne se propageait pas à
 * EntityList dans la même session — il fallait recharger la page pour que
 * les deux relisent localStorage. On utilise donc un store module-level +
 * `useSyncExternalStore` : toutes les instances partagent la même valeur et
 * se re-rendent ensemble. Persistance localStorage (survit aux reloads /
 * rebuilds Vite) + synchro cross-onglet via l'événement `storage`.
 */
const KEY = "face_ai_sort_mode";
const MODES = ["canonical", "first_name", "activity"];

function readStored() {
  try {
    const saved = localStorage.getItem(KEY);
    return MODES.includes(saved) ? saved : "canonical";
  } catch {
    return "canonical";
  }
}

let current = readStored();
const listeners = new Set();

function emit() {
  listeners.forEach((l) => l());
}

function setModeGlobal(next) {
  const value = MODES.includes(next) ? next : "canonical";
  if (value === current) return;
  current = value;
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* navigation privée, on ignore */
  }
  emit();
}

// Synchro cross-onglet : un changement de mode dans un autre onglet met à
// jour ce store sans recharger.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY) return;
    const value = readStored();
    if (value !== current) {
      current = value;
      emit();
    }
  });
}

function subscribe(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function getSnapshot() {
  return current;
}

export function useSortMode() {
  const mode = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const setMode = (next) => setModeGlobal(next);
  // Cycle : nom → prénom → activité → nom.
  const toggle = () =>
    setModeGlobal(MODES[(MODES.indexOf(current) + 1) % MODES.length]);

  return { mode, setMode, toggle };
}

/**
 * Réinitialise le store depuis localStorage. Réservé aux tests : un store
 * module-level survit entre les `it()` d'un même fichier, donc on relit
 * l'état persistant (et on purge les abonnés) avant chaque cas.
 */
export function __resetSortModeForTests() {
  current = readStored();
  listeners.clear();
}

// Helpers de transformation. Exportés séparément pour qu'EntityList /
// EntityRow puissent les réutiliser sans le hook.

export function getSortKey(name, mode) {
  if (mode !== "first_name" || !name) return name || "";
  // "Chalamet, Timothée" → "Timothée"
  if (name.includes(",")) {
    const idx = name.indexOf(",");
    return name.slice(idx + 1).trim();
  }
  // Mononyme (Madonna, Beyoncé) → utilise tel quel
  return name;
}

export function getDisplayName(name, mode) {
  if (mode !== "first_name" || !name || !name.includes(",")) return name;
  const idx = name.indexOf(",");
  const last = name.slice(0, idx).trim();
  const first = name.slice(idx + 1).trim();
  return `${first} ${last}`;
}
