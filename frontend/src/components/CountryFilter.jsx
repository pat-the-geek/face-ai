import { useMemo, useState } from "react";
import { useCountries } from "../hooks/useEntities";

/**
 * Barre de filtre par pays (v030) — recherche tapée + chips à drapeaux emoji.
 *
 * Placée sous l'AlphaNav. S'applique en parallèle du filtre alphabétique. Un
 * seul pays actif à la fois ; chip « Tous » pour réinitialiser. L'état
 * `selected` (code ISO alpha-2 ou null) est porté par App et partagé avec la
 * liste ET la carte (cf. MapView ?country=).
 *
 * Navigation : champ de recherche en tête de barre qui filtre les chips en
 * direct, **insensible aux accents/casse** (taper « s » → Suisse, Suède… ;
 * « sui » → Suisse). **Entrée** sélectionne le 1er résultat. Indispensable
 * dès qu'il y a beaucoup de pays (scroll horizontal sinon pénible).
 *
 * Drapeau fourni par le backend (`country_flag`). Pays dérivés de Wikidata P27→P297.
 */
const norm = (s) =>
  (s || "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

export default function CountryFilter({ selected, onSelect }) {
  const { data: countries, isLoading } = useCountries();
  const [query, setQuery] = useState("");

  // Tri alphabétique par nom (FR) — le backend renvoie par effectif décroissant
  // (utile au MCP/analyse), l'UI préfère l'ordre A→Z. Mémoïsé.
  const sorted = useMemo(
    () =>
      [...(countries || [])].sort((a, b) =>
        (a.name || a.code).localeCompare(b.name || b.code, "fr"),
      ),
    [countries],
  );

  // Filtre tapé : sous-chaîne insensible aux accents sur le nom, ou préfixe ISO.
  const nq = norm(query);
  const visible = useMemo(
    () =>
      nq
        ? sorted.filter(
            (c) => norm(c.name).includes(nq) || c.code.toLowerCase().startsWith(nq),
          )
        : sorted,
    [sorted, nq],
  );

  if (isLoading || !countries?.length) return null;

  const onKeyDown = (e) => {
    if (e.key === "Enter" && visible.length > 0) {
      onSelect(visible[0].code);
      setQuery("");
    } else if (e.key === "Escape") {
      setQuery("");
    }
  };

  return (
    <div className="flex items-center gap-1.5 px-8 py-1.5 border-b divider overflow-x-auto whitespace-nowrap text-xs font-mono">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="🔍 pays…"
        aria-label="Filtrer les pays"
        className="shrink-0 w-28 px-2 py-1 bg-transparent border divider rounded-full outline-none focus:border-accent text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]"
      />
      <button
        onClick={() => onSelect(null)}
        className={`px-3 py-1 border divider rounded-full transition-colors shrink-0 ${
          !selected
            ? "bg-accent text-white border-accent"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        }`}
      >
        Tous
      </button>
      {visible.map((c) => {
        const active = selected === c.code;
        return (
          <button
            key={c.code}
            onClick={() => onSelect(active ? null : c.code)}
            title={`${c.name} — ${c.count}`}
            className={`px-3 py-1 border divider rounded-full transition-colors shrink-0 ${
              active
                ? "bg-accent text-white border-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            <span className="mr-1">{c.flag}</span>
            {c.name}
            <span className="ml-1 opacity-70">({c.count})</span>
          </button>
        );
      })}
      {nq && visible.length === 0 && (
        <span className="shrink-0 px-2 text-[var(--text-secondary)]">
          aucun pays
        </span>
      )}
    </div>
  );
}
