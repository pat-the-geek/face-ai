import { useCallback, useEffect, useState } from "react";

/**
 * Mode couleur de la galerie — `"light"` (défaut, ambient color extrait
 * du portrait actif) ou `"dark"` (palette sombre fixe).
 *
 * Spec §19 — toggle manuel ☀/🌙 indépendant du système OS. Persistance
 * localStorage. Quand `mode='dark'`, on inhibe `useAmbientColor` (cf.
 * son param `enabled`) et on applique une palette neutre dark.
 *
 * Le Flipbook a son propre style sombre intégré (gradient radial sur
 * background, couleurs `#e8e4de`/`#5a5550` hardcodées) — il n'est pas
 * affecté par ce mode.
 */
const KEY = "face_ai_color_mode";

// Palette dark — fond très sombre, texte clair tiède. Pas de saturation
// ambient ici : c'est volontairement un cadre neutre pour ne pas
// concurrencer les portraits affichés.
const DARK_PALETTE = {
  "--bg-primary": "hsl(30 4% 8%)",
  "--bg-secondary": "hsl(30 4% 12%)",
  "--border": "hsl(30 4% 22%)",
  "--text-primary": "hsl(30 8% 92%)",
  "--text-secondary": "hsl(30 6% 60%)",
};

// Palette light "neutre" — utilisée quand on bascule de dark vers light
// et qu'aucune image ne déclenche `useAmbientColor` (pas de portrait
// actif, ex. /audit). Sinon `useAmbientColor` la surclassera.
const LIGHT_NEUTRAL = {
  "--bg-primary": "hsl(0 0% 96%)",
  "--bg-secondary": "hsl(0 0% 92%)",
  "--border": "hsl(0 0% 85%)",
  "--text-primary": "#1a1814",
  "--text-secondary": "#8a8278",
};

function applyPalette(palette) {
  const root = document.documentElement.style;
  Object.entries(palette).forEach(([k, v]) => root.setProperty(k, v));
}

export function useColorMode() {
  const [mode, setModeRaw] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* navigation privée */
    }
    document.documentElement.setAttribute("data-color-mode", mode);
    if (mode === "dark") {
      applyPalette(DARK_PALETTE);
    } else {
      applyPalette(LIGHT_NEUTRAL);
      // useAmbientColor reprendra la main si une image est active
    }
  }, [mode]);

  const toggle = useCallback(() => {
    setModeRaw((m) => (m === "light" ? "dark" : "light"));
  }, []);

  return { mode, setMode: setModeRaw, toggle };
}
