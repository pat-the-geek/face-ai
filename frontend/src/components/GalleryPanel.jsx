import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useEntityImages } from "../hooks/useEntities";
import { useAmbientColor } from "../hooks/useAmbientColor";
import { useColorMode } from "../hooks/useColorMode";
import { useFlipbook } from "../hooks/useFlipbook";
import EntityTimeline from "./EntityTimeline";
import GalleryHeader from "./GalleryHeader";
import FaceCard from "./FaceCard";
import FlipbookOverlay from "./FlipbookOverlay";

/**
 * @param {{ slug?: string }} props - Quand `slug` est fourni en prop (mode
 *   split-screen), il a la priorité sur le param d'URL. Sinon on lit l'URL.
 */
export default function GalleryPanel({ slug: propSlug }) {
  const params = useParams();
  const slug = propSlug ?? params.slug;
  const [pose, setPose] = useState(null);
  const [uniqueOnly, setUniqueOnly] = useState(true);
  // Filtre date posé par clic sur une cellule de la heatmap (`date` =
  // ISO "YYYY-MM-DD" ou null). On envoie `date_from=date_to=date` au
  // backend qui supporte déjà ce param.
  const [dateFilter, setDateFilter] = useState(null);
  // Sélection multi-FaceCard pour le composite Galton interactif.
  // Set vide = "Galton sur tout" (comportement historique). Non vide
  // = Galton sur le sous-ensemble choisi.
  const [galtonSelection, setGaltonSelection] = useState(() => new Set());

  const { data, isLoading, error } = useEntityImages(slug, {
    pose: pose || undefined,
    unique: uniqueOnly || undefined,
    date_from: dateFilter || undefined,
    date_to: dateFilter || undefined,
  });

  const images = useMemo(() => data?.images || [], [data]);
  // Le Flipbook ne gère que les images avec aligned_url disponible —
  // sinon le mode comparaison serait incohérent (tailles différentes).
  const flipbookImages = useMemo(
    () => images.filter((i) => i.aligned_url),
    [images],
  );
  const flipbook = useFlipbook(flipbookImages);

  // Couleur ambiante : image courante du Flipbook si ouvert,
  // sinon première image alignée disponible.
  const ambientSource =
    flipbook.isOpen && flipbook.current
      ? flipbook.current.aligned_url || flipbook.current.source_url
      : flipbookImages[0]?.aligned_url || images[0]?.source_url || null;

  // Mode dark inhibe l'extraction ambient — la palette dark fixe gagne.
  const { mode: colorMode } = useColorMode();
  useAmbientColor(ambientSource, { enabled: colorMode !== "dark" });

  useEffect(() => {
    flipbook.close();
  }, [slug, pose, dateFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset le filtre date quand on change d'entité.
  useEffect(() => {
    setDateFilter(null);
  }, [slug]);

  // Reset la sélection Galton quand le contexte d'images change
  // significativement (entité, filtre pose/date/dedup) — sinon des IDs
  // "fantômes" persistent et brouillent le compteur affiché.
  useEffect(() => {
    setGaltonSelection(new Set());
  }, [slug, pose, dateFilter, uniqueOnly]);

  const toggleGaltonSelect = (id) => {
    setGaltonSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const clearGaltonSelection = () => setGaltonSelection(new Set());

  // Sous-ensemble effectif passé à Galton : si sélection non vide, on
  // filtre ; sinon, comportement historique (toutes les images alignées).
  const galtonImages = useMemo(() => {
    if (galtonSelection.size === 0) return flipbookImages;
    return flipbookImages.filter((i) => galtonSelection.has(i.id));
  }, [flipbookImages, galtonSelection]);

  if (!slug) {
    return (
      <div className="h-full flex items-center justify-center font-display text-3xl text-[var(--text-secondary)]">
        sélectionnez une entité
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-8 font-mono text-sm text-[var(--text-secondary)]">
        chargement…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 font-mono text-sm text-accent">
        erreur : {error.message}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <GalleryHeader
        entity={data?.entity}
        pose={pose}
        onPoseChange={setPose}
        total={data?.total || 0}
        filtered={data?.filtered || 0}
        onOpenFlipbook={() => flipbook.open(0)}
        flipbookDisabled={flipbookImages.length === 0}
        uniqueOnly={uniqueOnly}
        onToggleUnique={() => setUniqueOnly((v) => !v)}
        images={flipbookImages}
        galtonImages={galtonImages}
        galtonSelectionCount={galtonSelection.size}
        onClearGaltonSelection={clearGaltonSelection}
      />
      <div className="flex-1 overflow-y-auto p-8">
        <EntityTimeline
          slug={slug}
          selectedDate={dateFilter}
          onSelectDate={setDateFilter}
        />
        {dateFilter && (
          <div className="mb-4 px-3 py-2 border border-accent flex items-center justify-between text-xs font-mono">
            <span>
              filtre actif : articles du{" "}
              <strong className="text-accent">{dateFilter}</strong>
              {data?.filtered !== undefined && (
                <span className="text-[var(--text-secondary)] ml-2">
                  ({data.filtered} image{data.filtered > 1 ? "s" : ""})
                </span>
              )}
            </span>
            <button
              onClick={() => setDateFilter(null)}
              className="uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
            >
              ✕ retirer
            </button>
          </div>
        )}
        {images.length ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {images.map((img) => {
              const flipIdx = flipbookImages.indexOf(img);
              const canGalton = Boolean(img.aligned_url);
              return (
                <FaceCard
                  key={img.id}
                  image={img}
                  onActivate={
                    flipIdx >= 0 ? () => flipbook.open(flipIdx) : undefined
                  }
                  galtonSelectable={canGalton}
                  galtonSelected={galtonSelection.has(img.id)}
                  onToggleGaltonSelect={
                    canGalton ? () => toggleGaltonSelect(img.id) : undefined
                  }
                />
              );
            })}
          </div>
        ) : (
          <div className="text-sm font-mono text-[var(--text-secondary)]">
            aucune image pour ce filtre
          </div>
        )}
      </div>
      <FlipbookOverlay controller={flipbook} />
    </div>
  );
}
