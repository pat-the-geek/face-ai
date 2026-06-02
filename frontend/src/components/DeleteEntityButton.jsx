import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

const CONFIRM_TIMEOUT_MS = 4000;

/**
 * Bouton 2-state pour le droit d'opposition (spec §1.5 / §19).
 *
 * 1er clic : passe en mode "armé" pendant 4 s, label en accent rouge,
 *           explicite ce qui va être supprimé.
 * 2e clic dans la fenêtre : exécute le DELETE, invalide les caches
 *           letters/entities et navigue vers `/`.
 *
 * Pas de modale : surface minimale, esthétique cohérente avec le reste
 * de l'UI, et un `setTimeout` qui rétracte automatiquement l'état armé
 * pour qu'on ne reste pas par inadvertance dans une posture destructive.
 */
export default function DeleteEntityButton({ entity }) {
  const [armed, setArmed] = useState(false);
  const timerRef = useRef(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const mutation = useMutation({
    mutationFn: () => api.deleteEntity(entity.slug),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["letters"] });
      // La sidebar de gauche (EntityList) charge via useEntitiesProgressive,
      // dont les clés sont "entities-first"/"entities-rest" — pas "entities".
      // invalidateQueries matche par préfixe d'élément exact, donc ces clés
      // doivent être invalidées explicitement sinon la liste ne se rafraîchit pas.
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["entities-first"] });
      queryClient.invalidateQueries({ queryKey: ["entities-rest"] });
      queryClient.removeQueries({ queryKey: ["entity", entity.slug] });
      queryClient.removeQueries({ queryKey: ["entityImages", entity.slug] });
      navigate("/", { replace: true });
      // Notification minimale via title bar — pas de toast lib pour rester lean
      console.info(
        `[FACE.ai] supprimé · ${data.images_removed} images, ${data.files_removed} fichiers, ${data.orphan_articles} articles orphelins`,
      );
    },
  });

  useEffect(() => {
    if (!armed) return;
    timerRef.current = setTimeout(() => setArmed(false), CONFIRM_TIMEOUT_MS);
    return () => clearTimeout(timerRef.current);
  }, [armed]);

  if (mutation.isPending) {
    return (
      <span className="px-3 py-1 text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)]">
        suppression…
      </span>
    );
  }

  if (!armed) {
    return (
      <button
        onClick={() => setArmed(true)}
        className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:border-accent hover:text-accent transition-colors"
        title="Droit d'opposition (RGPD art. 17, 21 / nLPD art. 32)"
      >
        ⌫ Supprimer
      </button>
    );
  }

  return (
    <button
      onClick={() => mutation.mutate()}
      className="px-3 py-1 border border-accent text-xs font-mono uppercase tracking-wider text-accent animate-pulse"
      title="Cliquer à nouveau pour confirmer · annulation auto dans 4 s"
    >
      ⚠ Confirmer · {entity.image_count} img + entité
    </button>
  );
}
