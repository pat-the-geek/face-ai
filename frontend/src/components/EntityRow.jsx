import { memo } from "react";
import { useNavigate } from "react-router-dom";
import { getDisplayName } from "../hooks/useSortMode";
import DeferredImg from "./DeferredImg";
import FavoriteToggle from "./FavoriteToggle";

/**
 * Memoizé : à 847 rows, sans memo, tout re-render à chaque changement de
 * route (`/sam-altman` → `/musk-elon` re-render les 847 rows). Avec memo,
 * seules les 2 rows dont `active` change re-rendent (l'ancienne et la
 * nouvelle).
 *
 * `active` est calculé par EntityList — sinon `useParams()` dans chaque row
 * forcerait le re-render à chaque navigation, et la memo ne tiendrait pas.
 * Le bool passé en prop est shallow-comparé : 845 rows restent à
 * `false === false`, memo court-circuite, 2 changent et re-rendent.
 */
function EntityRow({ entity, sortMode = "canonical", active = false }) {
  const navigate = useNavigate();
  const displayName = getDisplayName(entity.name, sortMode);
  const initial = displayName.charAt(0).toUpperCase();

  // <div role=button> plutôt que <button> pour autoriser le FavoriteToggle
  // imbriqué (un <button> dans un <button> est HTML invalide). stopPropagation
  // suffit côté événements, mais on évite quand même la nesting structurelle.
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => navigate(`/${entity.slug}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(`/${entity.slug}`);
        }
      }}
      className={`w-full text-left px-4 py-3 border-b divider transition-colors flex items-center gap-3 cursor-pointer ${
        active
          ? "bg-bg-secondary"
          : "hover:bg-bg-secondary"
      }`}
    >
      <div className="shrink-0 w-10 h-10 rounded-full overflow-hidden bg-bg-secondary border divider flex items-center justify-center">
        {entity.wiki_thumbnail_url ? (
          <DeferredImg
            src={entity.wiki_thumbnail_url}
            className="w-full h-full"
            fallback={
              <span className="font-display text-lg text-[var(--text-secondary)]">
                {initial}
              </span>
            }
          />
        ) : (
          <span className="font-display text-lg text-[var(--text-secondary)]">
            {initial}
          </span>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          {/* Pas de truncate : la colonne grid s'étend (cf. fit-content
              dans App.jsx) ; au-delà de 380px, le nom wrappe au lieu
              d'être amputé d'un "…" */}
          <div className="font-display text-xl leading-tight">
            {displayName}
          </div>
          <FavoriteToggle
            slug={entity.slug}
            isFavorite={entity.is_favorite}
            size="sm"
          />
        </div>
        <div className="text-xs font-mono text-[var(--text-secondary)] mt-0.5 flex justify-between">
          <span title={
            entity.unique_image_count !== entity.image_count
              ? `${entity.unique_image_count} uniques sur ${entity.image_count} (${entity.image_count - entity.unique_image_count} doublons détectés)`
              : `${entity.image_count} images`
          }>
            {entity.unique_image_count !== entity.image_count
              ? `${entity.unique_image_count}/${entity.image_count} img`
              : `${entity.image_count} img`}
          </span>
          <span>{entity.article_count} art</span>
        </div>
      </div>
    </div>
  );
}

export default memo(EntityRow);
