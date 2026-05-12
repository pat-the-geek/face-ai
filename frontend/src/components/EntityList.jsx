import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useEntitiesProgressive } from "../hooks/useEntities";
import { getSortKey, useSortMode } from "../hooks/useSortMode";
import EntityRow from "./EntityRow";

/**
 * Pagination UI progressive — affiche 200 rows à la fois, étend par
 * tranche de 200 quand l'utilisateur scrolle vers le bas (via un
 * sentinel IntersectionObserver). Au-delà du scroll, possibilité de
 * "Tout afficher" en un clic.
 *
 * Pourquoi pas la virtualization : 5 tentatives échouées (cf. historique
 * du composant et MIGRATION_POSTGRES.md §G.5 pour le diagnostic). Le
 * layout grid `fit-content(380px)` ne propage pas une hauteur
 * mesurable aux libs (`@tanstack/react-virtual`, `react-window` v2,
 * `react-virtuoso` v4 testée 2 fois). La pagination UI contourne ce
 * problème : le DOM reste compact (~200 rows max au début, étendu à la
 * demande), pas besoin que la lib connaisse la hauteur du parent.
 *
 * Compromis vs virtualization :
 * - **+** : marche sans dépendance, indépendant du layout, debug
 *   simple, scroll natif fiable
 * - **−** : si l'utilisateur clique "Tout afficher" sur 16k entités,
 *   le DOM grossit à 16k nodes (~50 ms de rendu). Reste exploitable.
 */
const PAGE_SIZE = 200;

export default function EntityList({ letter, favoritesOnly = false }) {
  const { mode: sortMode } = useSortMode();
  const { data, isLoading, error } = useEntitiesProgressive(
    letter,
    favoritesOnly,
    sortMode,
  );
  const { slug: activeSlug } = useParams();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef(null);

  const entities = useMemo(() => {
    const list = data?.entities || [];
    if (sortMode !== "first_name") return list;
    return [...list].sort((a, b) => {
      const ka = getSortKey(a.name, sortMode).toLowerCase();
      const kb = getSortKey(b.name, sortMode).toLowerCase();
      return ka.localeCompare(kb, "fr");
    });
  }, [data, sortMode]);

  // Reset visibleCount quand le jeu de données change (filtre, tri).
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [letter, favoritesOnly, sortMode]);

  // Infinite scroll : quand le sentinel entre dans le viewport, étend
  // visibleCount de PAGE_SIZE. IntersectionObserver natif, pas de lib.
  useEffect(() => {
    if (!sentinelRef.current) return;
    if (visibleCount >= entities.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisibleCount((c) => Math.min(c + PAGE_SIZE, entities.length));
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [visibleCount, entities.length]);

  if (isLoading) {
    return (
      <div className="p-6 text-sm font-mono text-[var(--text-secondary)]">
        chargement…
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-sm font-mono text-[var(--accent)]">
        erreur : {error.message}
      </div>
    );
  }
  if (!entities.length) {
    return (
      <div className="p-6 text-sm font-mono text-[var(--text-secondary)]">
        aucune entité
      </div>
    );
  }

  const visible = entities.slice(0, visibleCount);
  const remaining = entities.length - visible.length;

  return (
    <ul className="overflow-y-auto h-full">
      {visible.map((e) => (
        <li key={e.id}>
          <EntityRow
            entity={e}
            sortMode={sortMode}
            active={e.slug === activeSlug}
          />
        </li>
      ))}
      {remaining > 0 && (
        <li
          ref={sentinelRef}
          className="px-4 py-4 text-center text-xs font-mono text-[var(--text-secondary)] border-t divider"
        >
          chargement de la suite… ({remaining} restantes)
          <button
            onClick={() => setVisibleCount(entities.length)}
            className="ml-3 underline hover:text-[var(--accent)]"
          >
            tout afficher
          </button>
        </li>
      )}
    </ul>
  );
}
