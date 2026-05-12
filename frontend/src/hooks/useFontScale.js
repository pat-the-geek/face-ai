import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "face_ai_font_scale";
const MIN = 0.7;
const MAX = 1.5;
const STEP = 0.1;
export const DEFAULT_SCALE = 1;

function loadInitial() {
  if (typeof window === "undefined") return DEFAULT_SCALE;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  const parsed = raw ? parseFloat(raw) : DEFAULT_SCALE;
  if (!Number.isFinite(parsed)) return DEFAULT_SCALE;
  return Math.max(MIN, Math.min(MAX, parsed));
}

/**
 * Échelle typographique persistée en localStorage.
 *
 * Renvoie `[scale, setScale, { increase, decrease, reset }]`.
 * La valeur s'applique via la CSS variable `--font-scale` (cf. tokens.css)
 * qui multiplie le `font-size` racine — toutes les classes Tailwind text-*
 * en `rem` suivent automatiquement.
 */
export function useFontScale() {
  const [scale, setScaleState] = useState(loadInitial);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-scale", scale);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(scale));
    } catch {
      /* localStorage indisponible (mode privé Safari) — ignore */
    }
  }, [scale]);

  const setScale = useCallback((next) => {
    setScaleState(Math.max(MIN, Math.min(MAX, Math.round(next * 100) / 100)));
  }, []);

  const increase = useCallback(() => setScale(scale + STEP), [scale, setScale]);
  const decrease = useCallback(() => setScale(scale - STEP), [scale, setScale]);
  const reset = useCallback(() => setScale(DEFAULT_SCALE), [setScale]);

  return [scale, setScale, { increase, decrease, reset, MIN, MAX, STEP }];
}
