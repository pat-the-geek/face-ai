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

  // Cycle nom → prénom → activité → nom. En passant en mode activité, on
  // réinitialise le filtre lettre : ce mode est un classement global par
  // présence presse, la navigation alphabétique n'a plus de sens.
  const handleToggleSort = () => {
    const next =
      sortMode === "canonical"
        ? "first_name"
        : sortMode === "first_name"
          ? "activity"
          : "canonical";
    if (next === "activity") onSelect(null);
    toggleSort();
  };

  const sortLabel =
    sortMode === "first_name"
      ? "↕ prénom"
      : sortMode === "activity"
        ? "↕ activité"
        : "↕ nom";
  const sortTitle =
    sortMode === "first_name"
      ? "Tri par prénom — cliquer pour trier par activité presse"
      : sortMode === "activity"
        ? "Tri par activité presse (plus mentionnés d'abord) — cliquer pour revenir au nom"
        : "Tri par nom de famille — cliquer pour trier par prénom";

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
        onClick={handleToggleSort}
        className={`px-2 py-1 ml-1 text-xs uppercase tracking-wider transition-colors leading-none ${
          sortMode === "canonical"
            ? "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            : "text-accent"
        }`}
        title={sortTitle}
      >
        {sortLabel}
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
      {sortMode === "activity" ? (
        <span className="ml-3 text-xs text-[var(--text-secondary)] normal-case tracking-normal">
          classés par activité presse
        </span>
      ) : (
        <>
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
        </>
      )}
    </nav>
  );
}
