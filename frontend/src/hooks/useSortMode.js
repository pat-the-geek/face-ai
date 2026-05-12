import { useEffect, useState } from "react";

/**
 * Mode de tri/affichage des noms d'entités.
 *
 * - `"canonical"` (défaut) : tri sur "Last, First", affichage idem.
 *   Cohérent avec la convention CLAUDE.md. Lettre alphabétique = nom de famille.
 * - `"first_name"` : tri sur le prénom (ce qui suit la virgule, ou le nom
 *   entier pour les mononymes), affichage "First Last". Pratique quand on
 *   cherche par prénom (Timothée, Beyoncé, Madonna). Limite : la barre
 *   alphabétique de l'AlphaNav reste indexée sur le nom de famille.
 *
 * Persistance localStorage — la préférence survit aux rechargements et aux
 * rebuilds Vite, comme `useFontScale`.
 */
const KEY = "face_ai_sort_mode";

export function useSortMode() {
  const [mode, setModeRaw] = useState(() => {
    try {
      const saved = localStorage.getItem(KEY);
      return saved === "first_name" ? "first_name" : "canonical";
    } catch {
      return "canonical";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* navigation privée, on ignore */
    }
  }, [mode]);

  const setMode = (next) => setModeRaw(next);
  const toggle = () =>
    setModeRaw((m) => (m === "canonical" ? "first_name" : "canonical"));

  return { mode, setMode, toggle };
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
