import { DEFAULT_SCALE, useFontScale } from "../hooks/useFontScale";

/**
 * Bouton triple A− / A / A+ pour ajuster la taille de police.
 * Persiste en localStorage. Valeurs entre 70% et 150%.
 */
export default function FontScaler() {
  const [scale, , { increase, decrease, reset, MIN, MAX }] = useFontScale();
  const atDefault = Math.abs(scale - DEFAULT_SCALE) < 0.001;

  return (
    <div className="flex items-center gap-1 text-xs font-mono text-[var(--text-secondary)]">
      <button
        onClick={decrease}
        disabled={scale <= MIN}
        className="px-2 py-0.5 transition-colors enabled:hover:text-[var(--accent)] disabled:opacity-30 disabled:cursor-not-allowed"
        title="Réduire la taille du texte"
        aria-label="Réduire la taille du texte"
      >
        A<span className="text-[10px]">−</span>
      </button>
      <button
        onClick={reset}
        disabled={atDefault}
        className="px-1.5 py-0.5 transition-colors enabled:hover:text-[var(--text-primary)] disabled:opacity-50"
        title={`Taille par défaut (actuelle : ${Math.round(scale * 100)}%)`}
      >
        {Math.round(scale * 100)}%
      </button>
      <button
        onClick={increase}
        disabled={scale >= MAX}
        className="px-2 py-0.5 transition-colors enabled:hover:text-[var(--accent)] disabled:opacity-30 disabled:cursor-not-allowed"
        title="Augmenter la taille du texte"
        aria-label="Augmenter la taille du texte"
      >
        A<span className="text-sm">+</span>
      </button>
    </div>
  );
}
