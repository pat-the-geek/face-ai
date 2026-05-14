import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Toggle favori — étoile pleine / vide.
 *
 * Stratégie d'affichage immédiat (le bug initial : l'étoile ne basculait
 * qu'après refresh complet) :
 *
 * 1. **State local** `localFavorite` qui drive l'icône → bascule instantané
 *    au clic, sans dépendre du cache TanStack Query.
 * 2. **`useEffect` sync sur la prop** : si la prop `isFavorite` change
 *    depuis l'extérieur (refresh serveur, autre composant, échec mutation
 *    qui invalide), le local s'aligne.
 * 3. **Optimistic update sur le cache** TanStack en parallèle, pour que
 *    GalleryHeader et la liste se mettent à jour aussi (sans attendre
 *    le refetch).
 * 4. **Invalidation après mutation** pour confirmer côté serveur. Si
 *    erreur, le refetch ramène la vraie valeur et l'effet ci-dessus
 *    re-aligne le local.
 */
export default function FavoriteToggle({ slug, isFavorite, size = "md", onClick }) {
  const queryClient = useQueryClient();
  const [localFavorite, setLocalFavorite] = useState(Boolean(isFavorite));

  useEffect(() => {
    setLocalFavorite(Boolean(isFavorite));
  }, [isFavorite]);

  const mutation = useMutation({
    mutationFn: (next) =>
      next ? api.setFavorite(slug) : api.unsetFavorite(slug),
    onMutate: (next) => {
      // Cache TanStack — mise à jour optimiste pour tous les autres
      // composants qui lisent ces données (GalleryHeader notamment).
      queryClient.setQueryData(["entity", slug], (old) =>
        old ? { ...old, is_favorite: next } : old,
      );
      const matches = queryClient.getQueriesData({ queryKey: ["entities"] });
      for (const [qkey, data] of matches) {
        if (!data?.entities) continue;
        queryClient.setQueryData(qkey, {
          ...data,
          entities: data.entities.map((e) =>
            e.slug === slug ? { ...e, is_favorite: next } : e,
          ),
        });
      }
    },
    onSettled: () => {
      // Confirmation serveur. Si erreur, les queries refetched ramèneront
      // la vraie valeur et le useEffect ci-dessus re-sync le local.
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["letters"] });
      queryClient.invalidateQueries({ queryKey: ["entity", slug] });
    },
  });

  const sizeClass = size === "sm" ? "text-base" : "text-2xl";

  const handleClick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !localFavorite;
    setLocalFavorite(next); // ← bascule visuelle IMMÉDIATE
    mutation.mutate(next);
    onClick?.(e);
  };

  return (
    <button
      onClick={handleClick}
      className={`${sizeClass} leading-none transition-colors ${
        localFavorite
          ? "text-accent"
          : "text-[var(--border)] hover:text-[var(--text-secondary)]"
      }`}
      title={localFavorite ? "Retirer des favoris" : "Ajouter aux favoris"}
      aria-label={localFavorite ? "Retirer des favoris" : "Ajouter aux favoris"}
    >
      {localFavorite ? "★" : "☆"}
    </button>
  );
}
