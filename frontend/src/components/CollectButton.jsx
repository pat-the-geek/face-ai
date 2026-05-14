import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Bouton "Collecter" — force un pull WUDD ciblé sur l'entité affichée,
 * hors batch worker. Synchrone côté serveur (jusqu'à ~1 min selon le
 * nombre d'articles + politesse Wikimedia).
 *
 * Sortie : résumé inline (X articles nouveaux, Y images téléchargées,
 * Z déjà connus). Invalide la liste d'images de l'entité pour rafraîchir
 * la galerie une fois la collecte terminée.
 */
export default function CollectButton({ slug }) {
  const queryClient = useQueryClient();
  const [summary, setSummary] = useState(null);

  const collectMut = useMutation({
    mutationFn: () => api.collectEntity(slug, 200),
    onSuccess: (data) => {
      setSummary(data);
      // L'analyse en aval (face_processor / identity_audit) prend du temps :
      // on rafraîchit déjà la liste pour montrer les images en cours, et
      // une seconde fois après 8 s pour capter celles qui auront été
      // alignées par le worker entre-temps.
      queryClient.invalidateQueries({ queryKey: ["entity", slug] });
      queryClient.invalidateQueries({ queryKey: ["entityImages", slug] });
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["entity", slug] });
        queryClient.invalidateQueries({ queryKey: ["entityImages", slug] });
      }, 8000);
    },
  });

  return (
    <>
      <button
        onClick={() => collectMut.mutate()}
        disabled={collectMut.isPending}
        title="Force un pull WUDD complet pour cette personne (jusqu'à 200 articles récents). Les nouvelles images apparaîtront dans la galerie au fil de leur analyse."
        className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider transition-colors enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {collectMut.isPending ? "collecte…" : "↧ Collecter"}
      </button>
      {summary && (
        <span
          className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]"
          title={`Recherché : "${summary.person_searched}"`}
        >
          ✓ {summary.articles_new} art. nouveaux ·{" "}
          <span className="text-[var(--text-primary)]">
            {summary.images_downloaded} img
          </span>
          {summary.articles_already > 0 && (
            <> · {summary.articles_already} déjà connus</>
          )}
        </span>
      )}
      {collectMut.isError && (
        <span className="text-[10px] font-mono text-accent">
          erreur : {collectMut.error?.message}
        </span>
      )}
    </>
  );
}
