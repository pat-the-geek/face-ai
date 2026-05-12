import { useColorMode } from "../hooks/useColorMode";

/**
 * Toggle ☀ / 🌙 — bascule le mode couleur de la galerie (spec §19).
 *
 * Indépendant du système OS (pas de `prefers-color-scheme`), persistance
 * localStorage. Quand actif, `useAmbientColor` est inhibé et une palette
 * dark fixe prend le relais. Le Flipbook reste sombre en permanence
 * (style hardcodé dans FlipbookOverlay), ce toggle n'affecte que la
 * galerie et les pages adjacentes (audit, admin).
 */
export default function ColorModeToggle() {
  const { mode, toggle } = useColorMode();
  const isDark = mode === "dark";
  return (
    <button
      onClick={toggle}
      title={isDark ? "Repasser en mode clair" : "Passer en mode sombre"}
      className="px-2 py-0.5 text-base leading-none text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
      aria-label={isDark ? "Mode clair" : "Mode sombre"}
    >
      {isDark ? "☀" : "🌙"}
    </button>
  );
}
