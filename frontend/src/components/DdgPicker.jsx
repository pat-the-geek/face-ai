import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Bouton "DDG" + modale picker pour ingérer des images de la personne
 * depuis DuckDuckGo Images. Élargit le corpus vs WUDD seul (cf. CLAUDE.md
 * §1.5, désactivé par défaut côté backend via env FACE_AI_ENABLE_DDG).
 *
 * Workflow :
 * 1. Clic "DDG" → POST /search-ddg → reçoit ~20 candidates (URLs +
 *    thumbnails)
 * 2. Affiche grille de vignettes avec checkbox
 * 3. L'utilisateur coche celles à ingérer
 * 4. "Ingérer (N)" → 1 POST /ingest-ddg-image par image cochée, en
 *    parallèle
 * 5. À la fermeture, invalidate la galerie pour voir les nouvelles
 *    images apparaître au fur et à mesure de leur analyse (face_processor
 *    + identity_audit en aval).
 *
 * Si l'API renvoie 403 (DDG désactivé côté serveur), un message clair
 * remplace les résultats.
 */
export default function DdgPicker({ slug }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Chercher des images supplémentaires via DuckDuckGo (hors corpus WUDD — décision manuelle par image)"
        className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
      >
        🦆 DDG
      </button>
      {open && <Modal slug={slug} onClose={() => setOpen(false)} />}
    </>
  );
}

function Modal({ slug, onClose }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState({ loading: true });
  const [selected, setSelected] = useState(new Set());
  const [ingestedIds, setIngestedIds] = useState(new Set());
  const [ingesting, setIngesting] = useState(false);

  // Recherche au montage de la modale (synchrone, ~2-5 s côté DDG)
  useEffect(() => {
    let alive = true;
    api.searchDdg(slug, 24).then(
      (data) => alive && setState({ loading: false, data }),
      (err) => alive && setState({ loading: false, error: err }),
    );
    return () => {
      alive = false;
    };
  }, [slug]);

  const ingestMut = useMutation({
    mutationFn: (item) =>
      api.ingestDdgImage(slug, {
        url: item.image_url,
        title: item.title,
        source_page: item.source_page,
      }),
  });

  const onSubmit = async () => {
    setIngesting(true);
    const items = (state.data?.candidates || []).filter((_, i) =>
      selected.has(i),
    );
    for (const item of items) {
      try {
        await ingestMut.mutateAsync(item);
        setIngestedIds((prev) => new Set(prev).add(item.image_url));
      } catch {
        /* on continue silencieusement, l'erreur est dans le bouton row */
      }
    }
    setIngesting(false);
    queryClient.invalidateQueries({ queryKey: ["entity", slug] });
    queryClient.invalidateQueries({ queryKey: ["entityImages", slug] });
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-12 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl bg-[var(--bg-primary)] border divider shadow-2xl flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-6 py-4 border-b divider flex items-center justify-between">
          <div>
            <div className="font-display-italic text-2xl">DuckDuckGo · images</div>
            {state.data?.query && (
              <div className="text-xs font-mono text-[var(--text-secondary)] mt-1">
                requête : « {state.data.query} » · {state.data.count} résultats
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-[var(--accent)]"
          >
            ✕ Fermer (Échap)
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {state.loading && (
            <div className="py-12 text-center text-xs font-mono text-[var(--text-secondary)]">
              recherche DDG en cours…
            </div>
          )}

          {state.error && (
            <div className="py-12 text-center text-xs font-mono text-[var(--accent)]">
              erreur : {state.error.message}
              {state.error.message?.includes("disabled") && (
                <div className="mt-3 text-[var(--text-secondary)] normal-case">
                  Pour activer DDG, redémarrer l'API avec{" "}
                  <code>FACE_AI_ENABLE_DDG=true</code> en variable d'environnement.
                </div>
              )}
            </div>
          )}

          {state.data?.candidates?.length === 0 && (
            <div className="py-12 text-center text-xs font-mono text-[var(--text-secondary)]">
              aucun résultat
            </div>
          )}

          {state.data?.candidates?.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {state.data.candidates.map((c, i) => {
                const isSelected = selected.has(i);
                const isIngested = ingestedIds.has(c.image_url);
                return (
                  <Candidate
                    key={c.image_url}
                    candidate={c}
                    selected={isSelected}
                    ingested={isIngested}
                    onToggle={() =>
                      setSelected((prev) => {
                        const next = new Set(prev);
                        if (next.has(i)) next.delete(i);
                        else next.add(i);
                        return next;
                      })
                    }
                  />
                );
              })}
            </div>
          )}
        </div>

        <footer className="px-6 py-3 border-t divider flex items-center justify-between text-xs font-mono">
          <div className="text-[var(--text-secondary)]">
            {selected.size > 0
              ? `${selected.size} sélectionnée${selected.size > 1 ? "s" : ""}`
              : "Coche les images pertinentes (pipeline ArcFace en aval qualifiera)"}
          </div>
          <button
            onClick={onSubmit}
            disabled={selected.size === 0 || ingesting}
            className="px-4 py-1.5 border border-[var(--accent)] uppercase tracking-wider text-[var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {ingesting
              ? `ingestion… (${ingestedIds.size}/${selected.size})`
              : `↧ Ingérer (${selected.size})`}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

function Candidate({ candidate, selected, ingested, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={ingested}
      className={`relative border transition-colors text-left ${
        ingested
          ? "opacity-50 border-divider cursor-default"
          : selected
            ? "border-[var(--accent)]"
            : "border-divider hover:border-[var(--text-secondary)]"
      }`}
    >
      <div
        className="bg-[var(--bg-secondary)] flex items-center justify-center"
        style={{ aspectRatio: "1 / 1" }}
      >
        <img
          src={candidate.thumbnail}
          alt={candidate.title || ""}
          loading="lazy"
          referrerPolicy="no-referrer"
          className="max-w-full max-h-full object-contain"
        />
      </div>
      <div className="absolute top-2 right-2">
        {ingested ? (
          <span className="bg-[var(--bg-primary)] text-[var(--accent)] text-[10px] font-mono px-2 py-0.5 border border-[var(--accent)]">
            ✓ ingéré
          </span>
        ) : (
          <span
            className={`block w-5 h-5 border ${
              selected
                ? "bg-[var(--accent)] border-[var(--accent)] text-white"
                : "bg-[var(--bg-primary)] border-divider"
            } text-xs flex items-center justify-center font-mono`}
          >
            {selected ? "✓" : ""}
          </span>
        )}
      </div>
      <div className="px-2 py-1.5 text-[10px] font-mono text-[var(--text-secondary)] leading-snug min-h-[32px]">
        <div className="line-clamp-2">{candidate.title || "(sans titre)"}</div>
        {candidate.width && candidate.height && (
          <div className="mt-0.5 opacity-60">
            {candidate.width} × {candidate.height}
          </div>
        )}
      </div>
    </button>
  );
}
