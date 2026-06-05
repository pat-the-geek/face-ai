import { useCountries } from "../hooks/useEntities";

/**
 * Barre de filtre par pays (v030) — chips à drapeaux emoji, scroll horizontal.
 *
 * Placée sous l'AlphaNav. S'applique en parallèle du filtre alphabétique. Un
 * seul pays actif à la fois ; chip « Tous » pour réinitialiser. L'état
 * `selected` (code ISO alpha-2 ou null) est porté par App et partagé avec la
 * liste ET la carte (cf. MapView ?country=).
 *
 * Drapeau fourni par le backend (`country_flag`, construit côté serveur depuis
 * le code ISO). Données pays dérivées de Wikidata P27→P297.
 */
export default function CountryFilter({ selected, onSelect }) {
  const { data: countries, isLoading } = useCountries();

  if (isLoading || !countries?.length) return null;

  return (
    <div className="flex items-center gap-1.5 px-8 py-1.5 border-b divider overflow-x-auto whitespace-nowrap text-xs font-mono">
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
      {countries.map((c) => {
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
    </div>
  );
}
