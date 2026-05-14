import { useLetters } from "../hooks/useEntities";
import { useSortMode } from "../hooks/useSortMode";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

export default function AlphaNav({
  active,
  onSelect,
  favoritesOnly,
  onToggleFavorites,
}) {
  const { mode: sortMode, toggle: toggleSort } = useSortMode();
  const { data, isLoading } = useLetters(favoritesOnly, sortMode);
  const counts = data?.letters || {};

  return (
    <nav className="border-b divider px-4 py-3 flex items-center gap-1 text-sm font-mono select-none">
      <button
        onClick={onToggleFavorites}
        className={`px-2 py-1 transition-colors leading-none text-base ${
          favoritesOnly
            ? "text-accent"
            : "text-[var(--border)] hover:text-[var(--text-secondary)]"
        }`}
        title={favoritesOnly ? "Afficher toutes les entités" : "Afficher uniquement les favoris"}
      >
        {favoritesOnly ? "★" : "☆"}
      </button>
      <button
        onClick={toggleSort}
        className={`px-2 py-1 ml-1 text-xs uppercase tracking-wider transition-colors leading-none ${
          sortMode === "first_name"
            ? "text-accent"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        }`}
        title={
          sortMode === "first_name"
            ? "Tri par prénom actif (Cmd+K pour recherche libre)"
            : "Basculer sur le prénom (Timothée, Beyoncé, Madonna…) — la barre alphabétique suivra"
        }
      >
        {sortMode === "first_name" ? "↕ prénom" : "↕ nom"}
      </button>
      <span className="text-[var(--border)] mx-1">|</span>
      <button
        onClick={() => onSelect(null)}
        className={`px-2 py-1 transition-colors ${
          active === null
            ? "text-accent"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        }`}
      >
        TOUS{!isLoading && data ? ` · ${data.total}` : ""}
      </button>
      <span className="text-[var(--border)] mx-2">|</span>
      {ALPHABET.map((letter) => {
        const count = counts[letter] || 0;
        const disabled = count === 0;
        return (
          <button
            key={letter}
            disabled={disabled}
            onClick={() => onSelect(letter)}
            className={`w-7 py-1 transition-colors text-center ${
              active === letter
                ? "text-accent"
                : disabled
                  ? "text-[var(--border)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {letter}
          </button>
        );
      })}
      {counts["#"] > 0 && (
        <button
          onClick={() => onSelect("#")}
          className={`px-2 py-1 transition-colors ${
            active === "#"
              ? "text-accent"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          #
        </button>
      )}
    </nav>
  );
}
