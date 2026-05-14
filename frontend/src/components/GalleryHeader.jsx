import { useState } from "react";
import CollectButton from "./CollectButton";
import CompareWithPicker from "./CompareWithPicker";
import DdgPicker from "./DdgPicker";
import DeleteEntityButton from "./DeleteEntityButton";
import FavoriteToggle from "./FavoriteToggle";
import GaltonComposite from "./GaltonComposite";
import PoseFilter from "./PoseFilter";

const FR_DATE = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

function formatDate(iso) {
  if (!iso) return null;
  try {
    return FR_DATE.format(new Date(iso));
  } catch {
    return iso;
  }
}

function BioRow({ label, children }) {
  if (!children) return null;
  return (
    <div className="flex gap-3">
      <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] w-24 shrink-0 pt-1">
        {label}
      </span>
      <span className="flex-1">{children}</span>
    </div>
  );
}

export default function GalleryHeader({
  entity,
  pose,
  onPoseChange,
  total,
  filtered,
  onOpenFlipbook,
  flipbookDisabled,
  uniqueOnly,
  onToggleUnique,
  images = [],
  galtonImages = null,
  galtonSelectionCount = 0,
  onClearGaltonSelection,
}) {
  const [galtonOpen, setGaltonOpen] = useState(false);
  if (!entity) return null;

  const birthLine = entity.birth_date
    ? `${formatDate(entity.birth_date)}${entity.birth_place ? ` — ${entity.birth_place}` : ""}`
    : null;
  const deathLine = entity.death_date
    ? `${formatDate(entity.death_date)}${entity.death_place ? ` — ${entity.death_place}` : ""}${entity.age_at_death ? ` · ${entity.age_at_death} ans` : ""}`
    : null;
  const hasBio =
    birthLine ||
    deathLine ||
    entity.nationalities?.length ||
    entity.occupations?.length ||
    entity.employer;

  return (
    <header className="px-8 py-6 border-b divider">
      <div className="flex items-start gap-6">
        {entity.wiki_thumbnail_url && (
          <img
            src={entity.wiki_thumbnail_url}
            alt=""
            referrerPolicy="no-referrer"
            className="w-24 h-24 rounded-full object-cover border divider shrink-0"
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <div className="font-display text-5xl leading-none">
              {entity.name}
            </div>
            <FavoriteToggle
              slug={entity.slug}
              isFavorite={entity.is_favorite}
              size="md"
            />
          </div>
          {entity.aliases?.length > 0 && (
            <div className="mt-2 text-xs font-mono text-[var(--text-secondary)]">
              aussi : {entity.aliases.join(" · ")}
            </div>
          )}
          {entity.wiki_summary && (
            <p className="mt-3 text-sm leading-relaxed max-w-3xl">
              {entity.wiki_summary}
            </p>
          )}
          {(entity.wiki_url || entity.wikidata_qid) && (
            <div className="mt-2 flex items-center gap-3 text-xs font-mono text-[var(--text-secondary)]">
              {entity.wiki_url && (
                <a
                  href={entity.wiki_url}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:text-accent transition-colors"
                >
                  → Wikipédia
                </a>
              )}
              {entity.wikidata_qid && (
                <a
                  href={`https://www.wikidata.org/wiki/${entity.wikidata_qid}`}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:text-accent transition-colors"
                >
                  → {entity.wikidata_qid}
                </a>
              )}
            </div>
          )}
        </div>
      </div>

      {hasBio && (
        <div className="mt-6 max-w-3xl space-y-1.5 text-sm">
          <BioRow label="Naissance">{birthLine}</BioRow>
          <BioRow label="Décès">{deathLine}</BioRow>
          <BioRow label="Nationalité">
            {entity.nationalities?.length
              ? entity.nationalities.join(" · ")
              : null}
          </BioRow>
          <BioRow label="Occupation">
            {entity.occupations?.length
              ? entity.occupations.join(" · ")
              : null}
          </BioRow>
          <BioRow label="Employeur">{entity.employer}</BioRow>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-4 flex-wrap">
          <PoseFilter active={pose} onChange={onPoseChange} />
          <button
            onClick={onToggleUnique}
            className={`px-3 py-1 border text-xs font-mono uppercase tracking-wider transition-colors ${
              uniqueOnly
                ? "border-accent text-accent"
                : "divider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
            title="Masquer les images marquées comme doublons par dedup"
          >
            ◉ Sans doublons
          </button>
          <button
            onClick={onOpenFlipbook}
            disabled={flipbookDisabled}
            className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider transition-colors enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed"
            title="Mode défilement rapide (Échap pour fermer)"
          >
            ⟷ Flipbook
          </button>
          <button
            onClick={() => setGaltonOpen(true)}
            disabled={!images.some((i) => i.aligned_url)}
            className={`px-3 py-1 border text-xs font-mono uppercase tracking-wider transition-colors enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed ${
              galtonSelectionCount > 0
                ? "border-accent text-accent"
                : "divider"
            }`}
            title={
              galtonSelectionCount > 0
                ? `Composite Galton sur ${galtonSelectionCount} image(s) sélectionnée(s)`
                : "Superposer toutes les images en composite Galton (visage moyen, esthétique forensique-musée). Astuce : ◯ sur chaque carte pour sélectionner un sous-ensemble."
            }
          >
            ⊕ Galton{galtonSelectionCount > 0 ? ` (${galtonSelectionCount})` : ""}
          </button>
          {galtonSelectionCount > 0 && (
            <button
              onClick={onClearGaltonSelection}
              className="px-2 py-1 text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
              title="Vider la sélection Galton"
            >
              ✕
            </button>
          )}
          <CompareWithPicker currentSlug={entity.slug} />
          <a
            href={`/api/entities/${entity.slug}/export.jpg`}
            download={`face_ai_${entity.slug}.jpg`}
            className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
            title="Exporter une planche composite JPG (spec §11.6)"
          >
            ⤓ Export JPG
          </a>
          <CollectButton slug={entity.slug} />
          <DdgPicker slug={entity.slug} />
          <DeleteEntityButton entity={entity} />
        </div>
        <div className="flex items-center gap-4 text-xs font-mono text-[var(--text-secondary)]">
          {entity.diversity_score > 0 && (
            <span title="Diversité visuelle : moyenne des distances pairwise (pHash) entre images uniques. 0 = identiques, ~0.4 = bonne couverture variée.">
              ⊕ diversité {entity.diversity_score.toFixed(2)}
            </span>
          )}
          <span>
            {filtered === total
              ? `${total} image${total > 1 ? "s" : ""}`
              : `${filtered} / ${total} images`}
          </span>
        </div>
      </div>
      {galtonOpen && (
        <GaltonComposite
          images={galtonImages || images}
          entitySlug={entity.slug}
          onClose={() => setGaltonOpen(false)}
        />
      )}
    </header>
  );
}
