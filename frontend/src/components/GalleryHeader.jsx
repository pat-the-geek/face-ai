import { useState } from "react";
import BehavioralProfile from "./BehavioralProfile";
import CollectButton from "./CollectButton";
import CooccurrencePartners from "./CooccurrencePartners";
import EntityTimeline from "./EntityTimeline";
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
  detailsOpen = false,
  onToggleDetails,
  selectedDate = null,
  onSelectDate,
}) {
  const [galtonOpen, setGaltonOpen] = useState(false);
  if (!entity) return null;

  const birthLine = entity.birth_date
    ? `${formatDate(entity.birth_date)}${entity.birth_place ? ` — ${entity.birth_place}` : ""}${entity.current_age != null ? ` · ${entity.current_age} ans` : ""}`
    : null;
  const deathLine = entity.death_date
    ? `${formatDate(entity.death_date)}${entity.death_place ? ` — ${entity.death_place}` : ""}${entity.age_at_death ? ` · ${entity.age_at_death} ans` : ""}`
    : null;
  const join = (arr) => (arr?.length ? arr.join(" · ") : null);
  // Attributs sensibles (RGPD art. 9) — exposés par décision propriétaire
  // 2026-05-30. Regroupés sous un libellé distinct côté UI.
  const hasSensitive =
    entity.religion?.length ||
    entity.ethnic_group?.length ||
    entity.sexual_orientation ||
    entity.medical_condition?.length;
  const hasBio =
    birthLine ||
    deathLine ||
    entity.gender ||
    entity.nationalities?.length ||
    entity.occupations?.length ||
    entity.employer ||
    entity.political_party?.length ||
    entity.positions_held?.length ||
    entity.awards?.length ||
    entity.notable_works?.length ||
    hasSensitive;

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

      <button
        onClick={onToggleDetails}
        className="mt-5 text-[11px] font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent transition-colors"
        title={
          detailsOpen
            ? "Replier les infos et l'activité pour agrandir la galerie"
            : "Afficher la fiche bio et la heatmap d'activité"
        }
      >
        {detailsOpen ? "▾" : "▸"} Infos & activité
      </button>

      {detailsOpen && (
        // Zone dépliable « Infos & activité » : bio + heatmap presse +
        // partenaires regroupés dans UN SEUL bloc borné + scrollable, pleine
        // largeur. Le header étant hors de la zone scrollable de la galerie
        // (parent overflow-hidden), regrouper ici garantit que la timeline
        // reste atteignable (sinon une bio longue la repousse hors champ).
        // Pleine largeur → les longues listes s'étalent à l'horizontale.
        <div className="mt-4 w-full max-h-[55vh] overflow-y-auto pr-2">
          <EntityTimeline
            slug={entity.slug}
            selectedDate={selectedDate}
            onSelectDate={onSelectDate}
          />
          {hasBio && (
            <div className="space-y-1.5 text-sm">
              <BioRow label="Naissance">{birthLine}</BioRow>
              <BioRow label="Décès">{deathLine}</BioRow>
              <BioRow label="Genre">{entity.gender}</BioRow>
              <BioRow label="Nationalité">{join(entity.nationalities)}</BioRow>
              <BioRow label="Occupation">{join(entity.occupations)}</BioRow>
              <BioRow label="Employeur">{entity.employer}</BioRow>
              <BioRow label="Parti">{join(entity.political_party)}</BioRow>
              <BioRow label="Fonctions">{join(entity.positions_held)}</BioRow>
              <BioRow label="Distinctions">{join(entity.awards)}</BioRow>
              <BioRow label="Œuvres">{join(entity.notable_works)}</BioRow>
              {hasSensitive && (
                <div className="pt-2 mt-2 border-t divider">
                  <div
                    className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-1.5"
                    title="Données sensibles RGPD art. 9 — affichées par décision explicite du propriétaire (2026-05-30)."
                  >
                    ⚠ Données sensibles (Wikidata)
                  </div>
                  <BioRow label="Religion">{join(entity.religion)}</BioRow>
                  <BioRow label="Origine">{join(entity.ethnic_group)}</BioRow>
                  <BioRow label="Orientation">{entity.sexual_orientation}</BioRow>
                  <BioRow label="Santé">{join(entity.medical_condition)}</BioRow>
                </div>
              )}
            </div>
          )}
          <CooccurrencePartners slug={entity.slug} />
          <BehavioralProfile slug={entity.slug} />
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
