import { useEffect, useRef, useState } from "react";
import ColorThief from "colorthief";

const colorThief = new ColorThief();

/* ──────────────────────────────────────────────────────────────────────
   Conversions couleur
   ──────────────────────────────────────────────────────────────────── */

function rgbToHsl([r, g, b]) {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case rn:
        h = ((gn - bn) / d + (gn < bn ? 6 : 0)) * 60;
        break;
      case gn:
        h = ((bn - rn) / d + 2) * 60;
        break;
      default:
        h = ((rn - gn) / d + 4) * 60;
    }
  }
  return [h, s * 100, l * 100];
}

function hslToRgb(h, s, l) {
  const sn = s / 100;
  const ln = l / 100;
  const k = (n) => (n + h / 30) % 12;
  const a = sn * Math.min(ln, 1 - ln);
  const f = (n) =>
    ln - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return [f(0), f(8), f(4)];
}

/* ──────────────────────────────────────────────────────────────────────
   WCAG luminance + ratio de contraste
   Spec §10.4 (clampForContrast)
   ──────────────────────────────────────────────────────────────────── */

function relLuminance([r, g, b]) {
  const lin = (c) =>
    c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrastRatio(L1, L2) {
  const [hi, lo] = L1 > L2 ? [L1, L2] : [L2, L1];
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * Renvoie une luminance HSL (0-100) telle que (h, s, L) atteint
 * `minRatio` de contraste avec `bgL` (luminance relative WCAG du fond).
 *
 * `direction` :
 *  - "darken" : on part de `seedL` et on descend (texte foncé sur fond clair)
 *  - "lighten" : on part de `seedL` et on monte (cas inverse, non utilisé en
 *    mode galerie clair mais prêt pour le mode dark)
 *
 * Recherche linéaire par pas de 2 % — 50 itérations max suffisent à couvrir
 * tout l'espace. L'algorithme est imprécis mais bon marché ; on n'a pas
 * besoin de mieux pour de la teinte de fond.
 */
function clampLightnessForContrast({
  h,
  s,
  seedL,
  bgL,
  minRatio,
  direction = "darken",
}) {
  const step = direction === "darken" ? -2 : 2;
  let l = seedL;
  for (let i = 0; i < 50; i++) {
    const rgb = hslToRgb(h, s, l);
    if (contrastRatio(relLuminance(rgb), bgL) >= minRatio) return l;
    l += step;
    if (l <= 0 || l >= 100) break;
  }
  return direction === "darken" ? 0 : 100;
}

/* ──────────────────────────────────────────────────────────────────────
   Choix de la teinte ambiante
   ──────────────────────────────────────────────────────────────────── */

function isSkinTone(rgb) {
  const [h, s] = rgbToHsl(rgb);
  return h >= 0 && h <= 30 && s > 20;
}

/**
 * Sélection du candidat ambiant dans une palette ColorThief.
 *
 * Heuristique :
 * - Filtre les teintes peau (qui dominent souvent les portraits frontaux).
 * - Trie par saturation décroissante : on veut une teinte qui se voit,
 *   pas un gris sourd extrait d'un fond flou.
 */
function pickAmbient(palette) {
  if (!palette || palette.length === 0) return null;
  const nonSkin = palette.filter((rgb) => !isSkinTone(rgb));
  const candidates = nonSkin.length ? nonSkin : palette;
  const ranked = candidates
    .map((rgb) => ({ rgb, hsl: rgbToHsl(rgb) }))
    .sort((a, b) => b.hsl[1] - a.hsl[1]);
  return ranked[0];
}

/* ──────────────────────────────────────────────────────────────────────
   Hook principal
   ──────────────────────────────────────────────────────────────────── */

const SOURCE_SAT_CAP = 45; // saturation max retenue de l'image source

// Saturations cibles (proportion de la source clampée), par rôle. Donnent
// une teinte perceptible sans surcharger l'UI.
const ROLE_SAT = {
  bg: 0.7,
  border: 1.0,
  text: 0.55,
};

// Luminance « graine » avant ajustement WCAG. Texte foncé sur fond clair.
// Fond légèrement assombri (94 au lieu de 96) pour que la teinte ressorte
// davantage — un blanc à 96 % paraît toujours blanc même avec 15 % de S.
const SEED_L = {
  bgPrimary: 94,
  bgSecondary: 89,
  border: 78,
  textPrimary: 13,
  textSecondary: 38,
};

const NEUTRAL = {
  "--ambient-hue": "0",
  "--ambient-sat": "0",
  "--bg-primary": "hsl(0 0% 96%)",
  "--bg-secondary": "hsl(0 0% 92%)",
  "--border": "hsl(0 0% 85%)",
  "--text-primary": "#1a1814",
  "--text-secondary": "#8a8278",
};

// Arrondi à 1 décimale : suffisant pour la précision visuelle, lisible côté
// debug, et évite les CSS variables à 15 décimales (artefact float).
const r1 = (n) => Math.round(n * 10) / 10;

function computePalette(h, sourceSat) {
  const s = Math.min(sourceSat, SOURCE_SAT_CAP);
  const sBg = s * ROLE_SAT.bg;
  const sBorder = s * ROLE_SAT.border;
  const sText = s * ROLE_SAT.text;

  // Luminance du fond primaire (référence pour les ratios de contraste)
  const bgRgb = hslToRgb(h, sBg, SEED_L.bgPrimary);
  const bgLum = relLuminance(bgRgb);

  // Ajustement des couleurs sombres si le contraste descend sous 4.5
  const textPrimaryL = clampLightnessForContrast({
    h,
    s: sText,
    seedL: SEED_L.textPrimary,
    bgL: bgLum,
    minRatio: 7, // AAA — on a la marge, autant viser large
    direction: "darken",
  });
  const textSecondaryL = clampLightnessForContrast({
    h,
    s: sText,
    seedL: SEED_L.textSecondary,
    bgL: bgLum,
    minRatio: 4.5, // AA texte normal
    direction: "darken",
  });

  const hR = r1(h);
  const sBgR = r1(sBg);
  const sBorderR = r1(sBorder);
  const sTextR = r1(sText);

  return {
    "--ambient-hue": String(Math.round(h)),
    "--ambient-sat": String(Math.round(s)),
    "--bg-primary": `hsl(${hR} ${sBgR}% ${SEED_L.bgPrimary}%)`,
    "--bg-secondary": `hsl(${hR} ${sBgR}% ${SEED_L.bgSecondary}%)`,
    "--border": `hsl(${hR} ${sBorderR}% ${SEED_L.border}%)`,
    "--text-primary": `hsl(${hR} ${sTextR}% ${r1(textPrimaryL)}%)`,
    "--text-secondary": `hsl(${hR} ${sTextR}% ${r1(textSecondaryL)}%)`,
  };
}

/**
 * Extrait la teinte dominante d'une image et injecte une palette CSS
 * cohérente (fonds + bordures + texte) sur `:root`. Les couleurs de texte
 * sont clampées en luminance pour garantir WCAG AA 4.5:1 (et AAA 7:1 pour
 * le texte primaire), peu importe la teinte source.
 *
 * Sur image absente / cross-origin sans CORS / erreur : retombe sur la
 * palette neutre (les valeurs par défaut de `tokens.css`).
 */
export function useAmbientColor(imageUrl, { enabled = true } = {}) {
  const [palette, setPalette] = useState(NEUTRAL);
  const lastUrl = useRef(null);

  useEffect(() => {
    if (!enabled) {
      // Mode dark actif (cf. useColorMode) — on ne touche pas à :root,
      // le mode dark gère sa propre palette neutre.
      return;
    }
    if (!imageUrl) {
      setPalette(NEUTRAL);
      lastUrl.current = null;
      return;
    }
    if (imageUrl === lastUrl.current) return;
    lastUrl.current = imageUrl;

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const winner = pickAmbient(colorThief.getPalette(img, 5));
        if (!winner) {
          console.debug("[ambient] palette vide pour", imageUrl);
          setPalette(NEUTRAL);
          return;
        }
        const [h, s] = winner.hsl;
        console.debug(
          "[ambient]",
          imageUrl,
          `→ h=${Math.round(h)} s=${Math.round(s)} (source)`,
        );
        setPalette(computePalette(h, s));
      } catch (e) {
        console.debug("[ambient] échec extraction (CORS ?) :", e?.message);
        setPalette(NEUTRAL);
      }
    };
    img.onerror = () => {
      console.debug("[ambient] image impossible à charger :", imageUrl);
      setPalette(NEUTRAL);
    };
    img.src = imageUrl;
  }, [imageUrl, enabled]);

  useEffect(() => {
    if (!enabled) return;
    const root = document.documentElement.style;
    Object.entries(palette).forEach(([k, v]) => root.setProperty(k, v));
  }, [palette, enabled]);
}
