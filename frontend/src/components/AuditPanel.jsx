import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import DuplicatesPanel from "./DuplicatesPanel";

const SOURCE_PROVIDER_FILTERS = [
  { value: null, label: "Toutes" },
  { value: "wudd", label: "Corpus WUDD" },
  { value: "ddg", label: "DDG (hors corpus)" },
  { value: "manual", label: "Manual" },
];

/**
 * Workflow P9 — correction des associations `flagged` par l'audit ArcFace.
 *
 * Pour chaque image flagged, l'opérateur a deux actions :
 * - **Supprimer** : l'image ne représente clairement pas la personne (faux
 *   positif du scraper). Cascade fichiers.
 * - **Réassocier à...** : l'image est valide mais attribuée à la mauvaise
 *   entité. Search-as-you-type sur le nom + sélection. La nouvelle entité
 *   reçoit l'image avec status `manual` (décision humaine définitive).
 */
export default function AuditPanel() {
  const queryClient = useQueryClient();
  const [providerFilter, setProviderFilter] = useState(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["flagged", providerFilter || "all"],
    queryFn: () => api.flagged(providerFilter),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["flagged"] });
    queryClient.invalidateQueries({ queryKey: ["entities"] });
    queryClient.invalidateQueries({ queryKey: ["letters"] });
    queryClient.invalidateQueries({ queryKey: ["entityImages"] });
  };

  if (isLoading) {
    return <div className="p-8 font-mono text-sm text-[var(--text-secondary)]">chargement…</div>;
  }
  if (error) {
    return <div className="p-8 font-mono text-sm text-accent">erreur : {error.message}</div>;
  }

  const items = data?.flagged || [];

  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto">
      <header className="mb-6">
        <div className="font-display text-4xl">Audit · associations suspectes</div>
        <p className="mt-2 text-sm text-[var(--text-secondary)] max-w-2xl">
          Images dont la signature ArcFace s'écarte du centroïde d'identité de leur entité
          (distance &gt; 0.55, spec §5.5). Décision humaine = définitive et n'est plus
          ré-auditée automatiquement. Les images <strong>hors corpus WUDD</strong>
          (DDG, manual) remontent en haut de queue : sans caption d'article, ArcFace
          est l'unique signal de qualification, audit renforcé conseillé.
        </p>
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]">
            origine :
          </span>
          {SOURCE_PROVIDER_FILTERS.map((f) => (
            <button
              key={f.value || "all"}
              onClick={() => setProviderFilter(f.value)}
              className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider border transition-colors ${
                providerFilter === f.value
                  ? "border-accent text-accent"
                  : "divider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
            >
              {f.label}
            </button>
          ))}
          {data?.total !== undefined && (
            <span className="ml-2 text-[10px] font-mono text-[var(--text-secondary)]">
              {data.total} image{data.total > 1 ? "s" : ""}
            </span>
          )}
        </div>
      </header>

      {items.length === 0 ? (
        <div className="text-sm font-mono text-[var(--text-secondary)] py-12 text-center">
          ✓ aucune association suspecte
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((img) => (
            <FlaggedRow key={img.id} image={img} onChanged={invalidate} />
          ))}
        </div>
      )}

      <section className="mt-12 pt-8 border-t divider">
        <header className="mb-6">
          <div className="font-display text-3xl">Doublons probables</div>
          <p className="mt-2 text-sm text-[var(--text-secondary)] max-w-2xl">
            Entités candidates à la fusion (même QID Wikidata, même nom de famille,
            ou collision d'alias). Choisir le canonical, confirmer, les autres sont
            absorbées (leurs noms deviennent des aliases du canonical).
          </p>
        </header>
        <DuplicatesPanel />
      </section>
    </div>
  );
}

function FlaggedRow({ image, onChanged }) {
  const [reassigning, setReassigning] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const deleteMut = useMutation({
    mutationFn: () => api.deleteImage(image.id),
    onSuccess: onChanged,
  });

  const reassignMut = useMutation({
    mutationFn: (slug) => api.reassignImage(image.id, slug),
    onSuccess: onChanged,
  });

  const confirmMut = useMutation({
    mutationFn: () => api.confirmImage(image.id),
    onSuccess: onChanged,
  });

  const isPending =
    deleteMut.isPending || reassignMut.isPending || confirmMut.isPending;

  return (
    <article className="border divider p-4 flex gap-4">
      <div className="shrink-0 w-32 h-32 bg-bg-secondary overflow-hidden">
        {image.aligned_url ? (
          <img
            src={image.aligned_url}
            alt={image.caption || ""}
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-xs font-mono text-[var(--text-secondary)]">
            pas d'aligné
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] flex items-center gap-2">
          <span>attribuée à</span>
          <OriginBadge by={image.flagged_by} />
          <SourceProviderBadge provider={image.source_provider} />
        </div>
        <Link
          to={`/${image.entity_slug}`}
          className="font-display text-2xl hover:text-accent transition-colors"
        >
          {image.entity_name}
        </Link>

        {image.caption && (
          <p className="mt-2 text-sm leading-snug text-[var(--text-primary)]">{image.caption}</p>
        )}
        {image.article_title && (
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            article : {image.article_title}
          </p>
        )}

        {image.flagged_by === "human" ? (
          <div className="mt-2 text-xs font-mono text-accent">
            ⚠ signalée manuellement
            {image.identity_match_score !== null && image.identity_match_score !== undefined && (
              <span className="text-[var(--text-secondary)] ml-2">
                (distance ArcFace dernière mesurée : {image.identity_match_score.toFixed(3)})
              </span>
            )}
          </div>
        ) : (
          <div className="mt-2 text-xs font-mono text-accent">
            ⚠ distance ArcFace {image.identity_match_score?.toFixed(3)} (seuil 0.55)
          </div>
        )}

        <div className="mt-4 flex items-center gap-3 flex-wrap">
          {!confirmingDelete && !reassigning && !isPending && (
            <>
              <button
                onClick={() => confirmMut.mutate()}
                title="L'attribution actuelle est correcte — ArcFace s'est trompé"
                className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
              >
                ✓ Confirmer
              </button>
              <button
                onClick={() => setReassigning(true)}
                className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
              >
                ⤴ Réassocier à…
              </button>
              <button
                onClick={() => setConfirmingDelete(true)}
                className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:border-accent hover:text-accent transition-colors"
              >
                ⌫ Supprimer
              </button>
            </>
          )}

          {confirmingDelete && !isPending && (
            <>
              <button
                onClick={() => deleteMut.mutate()}
                className="px-3 py-1 border border-accent text-xs font-mono uppercase tracking-wider text-accent animate-pulse"
              >
                ⚠ Confirmer suppression
              </button>
              <button
                onClick={() => setConfirmingDelete(false)}
                className="px-2 py-1 text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              >
                annuler
              </button>
            </>
          )}

          {reassigning && !isPending && (
            <ReassignSearch
              onCancel={() => setReassigning(false)}
              onSelect={(slug) => {
                reassignMut.mutate(slug);
                setReassigning(false);
              }}
              currentSlug={image.entity_slug}
            />
          )}

          {isPending && (
            <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)]">
              traitement…
            </span>
          )}
        </div>
      </div>
    </article>
  );
}

function SourceProviderBadge({ provider }) {
  // `wudd` est l'origine par défaut historique → pas de badge (signal
  // faible visuel). Seuls DDG et manual portent une marque distinctive
  // pour signaler l'audit renforcé.
  if (!provider || provider === "wudd") return null;
  const label = provider.toUpperCase();
  return (
    <span
      className="px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider rounded bg-accent/20 text-accent border border-accent"
      title={`Image hors corpus WUDD (origine ${provider}) — pas de caption d'article, ArcFace est le seul signal de qualification`}
    >
      {label === "DDG" ? "🦆 ddg" : label.toLowerCase()}
    </span>
  );
}

function OriginBadge({ by }) {
  // Distingue visuellement les deux origines de signalement dans la queue.
  // ArcFace = détection algorithmique (centroïde d'identité distance > 0.55)
  // Humain = décision posée à la main via bouton ⚠ sur la galerie
  if (by === "human") {
    return (
      <span
        className="px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider rounded bg-accent text-white"
        title="Signalée manuellement par l'utilisateur"
      >
        humain
      </span>
    );
  }
  return (
    <span
      className="px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider rounded bg-bg-secondary text-[var(--text-secondary)]"
      title="Détectée par l'audit ArcFace (distance > 0.55)"
    >
      arcface
    </span>
  );
}


function ReassignSearch({ onCancel, onSelect, currentSlug }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q),
    enabled: q.length >= 2,
  });

  const results = (data?.results || []).filter((e) => e.slug !== currentSlug);

  return (
    <div className="flex flex-col gap-2 w-full">
      <div className="flex items-center gap-2">
        <input
          type="text"
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="chercher entité cible…"
          className="px-2 py-1 border divider text-xs font-mono bg-transparent flex-1 max-w-md outline-none focus:border-accent"
        />
        <button
          onClick={onCancel}
          className="px-2 py-1 text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          annuler
        </button>
      </div>
      {results.length > 0 && (
        <ul className="border divider max-w-md">
          {results.slice(0, 8).map((e) => (
            <li key={e.id}>
              <button
                onClick={() => onSelect(e.slug)}
                className="w-full text-left px-2 py-1 text-sm font-display hover:bg-bg-secondary transition-colors flex justify-between"
              >
                <span>{e.name}</span>
                <span className="text-xs font-mono text-[var(--text-secondary)]">
                  {e.unique_image_count}/{e.image_count} img
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
