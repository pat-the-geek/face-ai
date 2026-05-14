import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

/**
 * Section "Doublons probables" du workflow d'audit P9.
 *
 * Affiche les groupes d'entités candidates à la fusion d'après
 * `GET /entities/duplicate-candidates` (logique partagée avec l'outil MCP
 * `find_duplicate_candidates`).
 *
 * Trois catégories distinctes, importance décroissante :
 *
 * 1. **same_qid** : entités au même `wikidata_qid`. Devrait être vide en
 *    régime normal — le worker `merge_loop` les fusionne automatiquement.
 *    Si non vide, alerte rouge : le worker plante ou est arrêté.
 *
 * 2. **same_surname** : entités au même nom de famille. Couvre les notations
 *    longue/courte (`Trump, Donald` vs `Trump`). Inclut les **homonymes
 *    légitimes** (Macron Emmanuel vs Brigitte Macron) — décision humaine
 *    requise.
 *
 * 3. **alias_collision** : nom d'une entité = alias d'une autre. Signal de
 *    canonicalisation incohérente.
 *
 * Pour chaque groupe, l'entité avec le plus d'images est proposée comme
 * canonical par défaut. Un seul clic merge → la cible absorbe les autres,
 * leurs slugs deviennent des aliases, leurs articles/images sont déplacés.
 */
export default function DuplicatesPanel() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["duplicate-candidates"],
    queryFn: api.duplicateCandidates,
  });

  if (isLoading) {
    return (
      <div className="font-mono text-sm text-[var(--text-secondary)]">
        chargement des doublons…
      </div>
    );
  }
  if (error) {
    return (
      <div className="font-mono text-sm text-accent">
        erreur : {error.message}
      </div>
    );
  }

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["duplicate-candidates"] });
    queryClient.invalidateQueries({ queryKey: ["entities"] });
    queryClient.invalidateQueries({ queryKey: ["letters"] });
  };

  const totals = data?.totals ?? {};
  const noDups =
    (data?.same_qid?.length ?? 0) === 0 &&
    (data?.same_surname?.length ?? 0) === 0 &&
    (data?.alias_collision?.length ?? 0) === 0;

  if (noDups) {
    return (
      <div className="text-sm font-mono text-[var(--text-secondary)] py-6 text-center">
        ✓ aucun doublon probable
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {data.same_qid?.length > 0 && (
        <Category
          title="Même QID Wikidata"
          subtitle={`${totals.same_qid_groups} groupe(s) — fusion certaine (preuve Wikidata). Si vous voyez cette liste non-vide en régime stable, le worker merge_loop est probablement arrêté.`}
          severity="auto"
        >
          {data.same_qid.map((group, idx) => (
            <CandidateGroup
              key={`qid-${idx}`}
              label={group.qid}
              entities={group.entities}
              canMerge={true}
              onMerged={invalidate}
            />
          ))}
        </Category>
      )}

      {data.alias_collision?.length > 0 && (
        <Category
          title="Collision d'alias"
          subtitle={`${totals.alias_collision_groups} groupe(s) — le nom d'une entité = alias d'une autre. Probablement une fusion ratée ou canonicalisation incohérente.`}
          severity="manual"
        >
          {data.alias_collision.map((group, idx) => (
            <CandidateGroup
              key={`alias-${idx}`}
              label={`alias "${group.collision_on}"`}
              entities={group.entities}
              canMerge={true}
              onMerged={invalidate}
            />
          ))}
        </Category>
      )}

      {data.same_surname?.length > 0 && (
        <Category
          title="Même nom de famille"
          subtitle={`${totals.same_surname_groups} groupe(s) — notations longue/courte ou homonymes légitimes (Macron Emmanuel vs Brigitte Macron). Vérifier avant de fusionner.`}
          severity="manual"
        >
          {data.same_surname.map((group, idx) => (
            <CandidateGroup
              key={`surname-${idx}`}
              label={group.surname}
              entities={group.entities}
              canMerge={true}
              onMerged={invalidate}
            />
          ))}
        </Category>
      )}
    </div>
  );
}

function Category({ title, subtitle, severity, children }) {
  return (
    <section>
      <h3 className="font-display text-2xl mb-1">{title}</h3>
      <p
        className={`text-xs leading-snug mb-3 max-w-3xl ${
          severity === "auto"
            ? "text-accent"
            : "text-[var(--text-secondary)]"
        }`}
      >
        {subtitle}
      </p>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function CandidateGroup({ label, entities, onMerged }) {
  // Convention de l'API : entities[0] est le canonical proposé (image_count
  // max). L'utilisateur peut changer en cliquant sur une autre entité.
  const [canonicalSlug, setCanonicalSlug] = useState(entities[0]?.slug);
  const [confirming, setConfirming] = useState(false);

  const sources = entities.filter((e) => e.slug !== canonicalSlug);

  const mergeMut = useMutation({
    mutationFn: async () => {
      // Fusion séquentielle : chaque source absorbée une par une dans le
      // canonical. `merge_entities` est idempotent (noop sur slug déjà absorbé),
      // donc une re-soumission après échec partiel est sûre.
      for (const source of sources) {
        await api.mergeEntities(canonicalSlug, source.slug);
      }
    },
    onSuccess: () => {
      setConfirming(false);
      onMerged();
    },
  });

  return (
    <article className="border divider p-3">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]">
          {label}
        </span>
        {!confirming && !mergeMut.isPending && (
          <button
            onClick={() => setConfirming(true)}
            className="px-2 py-0.5 border divider text-[10px] font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
          >
            ⇒ Fusionner
          </button>
        )}
        {confirming && !mergeMut.isPending && (
          <span className="flex items-center gap-2">
            <button
              onClick={() => mergeMut.mutate()}
              className="px-2 py-0.5 border border-accent text-[10px] font-mono uppercase tracking-wider text-accent animate-pulse"
            >
              ⚠ Confirmer
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              annuler
            </button>
          </span>
        )}
        {mergeMut.isPending && (
          <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]">
            fusion…
          </span>
        )}
      </div>

      <ul className="space-y-1">
        {entities.map((e) => {
          const isCanonical = e.slug === canonicalSlug;
          return (
            <li
              key={e.slug}
              className={`flex items-center justify-between gap-3 px-2 py-1 text-sm ${
                isCanonical ? "bg-bg-secondary" : ""
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <input
                  type="radio"
                  name={`canonical-${label}`}
                  checked={isCanonical}
                  onChange={() => setCanonicalSlug(e.slug)}
                  disabled={confirming || mergeMut.isPending}
                  className="accent-[var(--accent)]"
                  title="canonical (les autres seront absorbés)"
                />
                <Link
                  to={`/${e.slug}`}
                  className="font-display truncate hover:text-accent transition-colors"
                >
                  {e.name}
                </Link>
                {isCanonical && (
                  <span className="text-[9px] font-mono uppercase tracking-wider text-accent">
                    canonical
                  </span>
                )}
              </div>
              <span className="text-xs font-mono text-[var(--text-secondary)] shrink-0">
                {e.image_count} img
              </span>
            </li>
          );
        })}
      </ul>

      {mergeMut.isError && (
        <div className="mt-2 text-xs font-mono text-accent">
          erreur : {mergeMut.error.message}
        </div>
      )}
    </article>
  );
}
