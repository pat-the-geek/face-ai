import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useLetters(favoritesOnly = false, sortBy = "canonical") {
  return useQuery({
    queryKey: ["letters", favoritesOnly, sortBy],
    queryFn: () => api.letters({ favoritesOnly, sortBy }),
  });
}

export function useEntities(letter, favoritesOnly = false) {
  return useQuery({
    queryKey: ["entities", letter || "all", favoritesOnly],
    // Échelle cible 16k+ (CLAUDE.md). Tant que la virtualization
    // @tanstack/react-virtual n'est pas en place, on récupère tout
    // en un coup. Payload léger (~150 o/entité = ~2 Mo à 16k).
    queryFn: () => api.entities({ letter, favoritesOnly, limit: 20000 }),
  });
}

/**
 * Variante progressive : charge d'abord 200 entités (TTI rapide), puis
 * le reste après idle. La concaténation est exposée comme une seule
 * liste, transparente pour l'appelant. Utilisée par EntityList pour
 * que la sidebar soit interactive en ~50 ms même à 16k entités.
 */
export function useEntitiesProgressive(
  letter,
  favoritesOnly = false,
  sortBy = "canonical",
) {
  const [loadRest, setLoadRest] = useState(false);

  const first = useQuery({
    queryKey: ["entities-first", letter || "all", favoritesOnly, sortBy],
    queryFn: () =>
      api.entities({ letter, favoritesOnly, sortBy, limit: 200, offset: 0 }),
  });

  // Quand la 1re page est arrivée, planifie le reste après idle (ou 100 ms
  // fallback). On évite ainsi de bloquer le main thread juste après le
  // 1er paint, et on laisse le navigateur peindre le reste de la page.
  useEffect(() => {
    if (!first.isSuccess || loadRest) return;
    const fn = () => setLoadRest(true);
    const ric = window.requestIdleCallback;
    const id = ric ? ric(fn, { timeout: 500 }) : setTimeout(fn, 100);
    return () => {
      if (ric) window.cancelIdleCallback?.(id);
      else clearTimeout(id);
    };
  }, [first.isSuccess, loadRest]);

  const rest = useQuery({
    queryKey: ["entities-rest", letter || "all", favoritesOnly, sortBy],
    queryFn: () =>
      api.entities({
        letter,
        favoritesOnly,
        sortBy,
        limit: 20000,
        offset: 200,
      }),
    enabled: loadRest && first.isSuccess,
  });

  // Concaténation. Important : on retourne une référence stable tant
  // que les sous-jacents n'ont pas bougé, pour ne pas invalider les memo
  // d'EntityList à chaque re-render.
  return useMemo(() => {
    const firstList = first.data?.entities || [];
    const restList = rest.data?.entities || [];
    return {
      data: {
        entities: restList.length ? [...firstList, ...restList] : firstList,
        total: first.data?.total ?? 0,
      },
      isLoading: first.isLoading,
      isRestLoading: rest.isFetching && !rest.isSuccess,
      error: first.error || rest.error,
    };
  }, [first.data, rest.data, first.isLoading, first.error, rest.error, rest.isFetching, rest.isSuccess]);
}

export function useEntity(slug) {
  return useQuery({
    queryKey: ["entity", slug],
    queryFn: () => api.entity(slug),
    enabled: Boolean(slug),
  });
}

export function useEntityImages(slug, filters) {
  return useQuery({
    queryKey: ["entityImages", slug, filters],
    queryFn: () => api.entityImages(slug, filters),
    enabled: Boolean(slug),
  });
}
