import { useEffect } from "react";
import { createPortal } from "react-dom";

/**
 * Visualisation plein écran de l'image **source** (URL d'origine, pleine
 * résolution, sans le crop d'alignement). Complément naturel de la vue
 * alignée 300×300 du Flipbook : permet de vérifier le contexte de la photo,
 * de voir le visage sans recadrage, ou de juger la qualité d'origine.
 *
 * Déclencheurs (cf. FaceCard / FlipbookOverlay) :
 * - Bouton 🔍 en survol d'une `FaceCard` dans la galerie
 * - Touche `S` dans le Flipbook (bascule alignée ↔ source)
 *
 * Touche `Échap` ou clic sur le fond pour fermer.
 */
export default function SourceLightbox({ image, onClose }) {
  useEffect(() => {
    if (!image) return;
    const handler = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [image, onClose]);

  if (!image) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex flex-col select-none"
      style={{ background: "var(--immersive-bg)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-8 py-3 font-mono text-xs">
        <button
          onClick={onClose}
          className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
        >
          ✕ Échap
        </button>
        <span className="text-[var(--immersive-text-muted)] uppercase tracking-wider">
          image source · pleine résolution
        </span>
        <a
          href={image.source_url}
          target="_blank"
          rel="noreferrer"
          className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
          onClick={(e) => e.stopPropagation()}
        >
          ↗ ouvrir l'URL
        </a>
      </div>

      {/* Image */}
      <div
        className="flex-1 flex items-center justify-center min-h-0 px-4"
        onClick={onClose}
      >
        <img
          src={image.source_url}
          alt={image.caption || ""}
          referrerPolicy="no-referrer"
          className="max-w-full max-h-full object-contain"
          onClick={(e) => {
            // Clic sur l'image elle-même ferme aussi (ergonomie naturelle)
            e.stopPropagation();
            onClose();
          }}
        />
      </div>

      {/* Méta basse */}
      <div className="px-8 py-3 font-mono text-xs space-y-1 max-h-32 overflow-y-auto">
        {image.caption && (
          <p className="text-[var(--immersive-text-primary)]">{image.caption}</p>
        )}
        {image.copyright && (
          <p className="text-[var(--immersive-text-muted)]">{image.copyright}</p>
        )}
        {image.article && (
          <p className="text-[var(--immersive-text-muted)]">
            article :{" "}
            <a
              href={image.article.url}
              target="_blank"
              rel="noreferrer"
              className="hover:text-[var(--immersive-text-primary)] transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              {image.article.title || image.article.url}
            </a>
          </p>
        )}
        <p className="text-[var(--immersive-separator)] truncate">{image.source_url}</p>
      </div>
    </div>,
    document.body,
  );
}
