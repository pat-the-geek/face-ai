import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import GalleryPanel from "./GalleryPanel";
import SplitFlipbookOverlay from "./SplitFlipbookOverlay";
import { useEntity, useEntityImages } from "../hooks/useEntities";
import { useSplitFlipbook } from "../hooks/useSplitFlipbook";

/**
 * Mode comparaison côte-à-côte (spec §11.5).
 *
 * Deux `GalleryPanel` indépendants pour la galerie + un Flipbook unifié
 * accessible depuis la barre du haut. Le Flipbook unifié charge les
 * images alignées non-doublons des 2 entités (sans tenir compte des
 * filtres pose/dedup actifs côté panneau, qui restent un choix d'affichage
 * local). ←/→ avance les 2 portraits en parallèle, indices bornés au
 * plus court des 2 listes.
 */
export default function SplitScreen() {
  const { slugA, slugB } = useParams();

  const { data: entityA } = useEntity(slugA);
  const { data: entityB } = useEntity(slugB);
  const { data: dataA } = useEntityImages(slugA, { unique: true });
  const { data: dataB } = useEntityImages(slugB, { unique: true });

  // Le Flipbook ne fonctionne que sur les images alignées disponibles
  const flipbookImagesA = useMemo(
    () => (dataA?.images || []).filter((i) => i.aligned_url),
    [dataA],
  );
  const flipbookImagesB = useMemo(
    () => (dataB?.images || []).filter((i) => i.aligned_url),
    [dataB],
  );

  const splitFlipbook = useSplitFlipbook(flipbookImagesA, flipbookImagesB);
  const flipbookDisabled = splitFlipbook.total === 0;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-6 py-2 border-b divider flex items-center justify-between text-xs font-mono gap-4">
        <Link
          to={`/${slugA}`}
          className="text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors uppercase tracking-wider"
          title="Quitter la comparaison"
        >
          ← {slugA}
        </Link>
        <div className="flex items-center gap-3">
          <span className="uppercase tracking-wider text-[var(--text-secondary)]">
            ⊞ comparaison côte-à-côte
          </span>
          <button
            onClick={() => splitFlipbook.open(0)}
            disabled={flipbookDisabled}
            className="px-3 py-1 border divider uppercase tracking-wider transition-colors enabled:hover:border-[var(--accent)] enabled:hover:text-[var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              flipbookDisabled
                ? "Aucune paire d'images alignées à comparer"
                : `Flipbook synchronisé sur ${splitFlipbook.total} paires`
            }
          >
            ⟷ Flipbook comparé
            {!flipbookDisabled && (
              <span className="ml-2 text-[var(--text-secondary)] normal-case tracking-normal">
                ({splitFlipbook.total})
              </span>
            )}
          </button>
        </div>
        <Link
          to={`/${slugB}`}
          className="text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors uppercase tracking-wider"
        >
          {slugB} →
        </Link>
      </div>

      <div className="flex-1 grid grid-cols-2 overflow-hidden">
        <div className="border-r divider overflow-hidden">
          <GalleryPanel slug={slugA} />
        </div>
        <div className="overflow-hidden">
          <GalleryPanel slug={slugB} />
        </div>
      </div>

      <SplitFlipbookOverlay
        controller={splitFlipbook}
        nameA={entityA?.name || slugA}
        nameB={entityB?.name || slugB}
      />
    </div>
  );
}
