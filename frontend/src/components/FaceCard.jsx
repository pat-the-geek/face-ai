import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import SourceLightbox from "./SourceLightbox";

const POSE_LABEL = {
  front: "FACE",
  left: "PROFIL G.",
  right: "PROFIL D.",
};

// Trois paliers de confiance ArcFace par rapport au centroïde de l'entité.
// Le palier "douteux" (orange) entre 0.4 et 0.55 attire l'attention sur
// les images proches du seuil — le binaire confirmed/flagged manquait
// le cas "techniquement sous le seuil mais probablement faux positif".
const SUSPECT_THRESHOLD = 0.4;
const FLAG_THRESHOLD = 0.55;

function IdentityBadge({ image }) {
  const status = image.association_status;
  const isHumanFlagged = status === "human_flagged";
  const isArcFlagged = status === "flagged";

  // Signalement manuel : pas d'autorité ArcFace à afficher, juste la
  // décision humaine. Le score est null la plupart du temps mais on
  // l'affiche s'il existe (cas où ArcFace l'avait évaluée sous le seuil).
  if (isHumanFlagged) {
    return (
      <span
        className="text-[var(--accent)]"
        title="Signalée manuellement comme ne correspondant pas à cette personne"
      >
        ⚠ signalée
      </span>
    );
  }

  if (image.identity_match_score === null || image.identity_match_score === undefined) {
    return (
      <span className="text-[var(--text-secondary)]">
        {image.aligned_url ? "aligné" : "brut"}
      </span>
    );
  }
  const score = image.identity_match_score;
  const isSuspect = !isArcFlagged && score > SUSPECT_THRESHOLD;
  const tip = `Distance ArcFace au centroïde : ${score.toFixed(2)} · seuils 0.40 (douteux) / 0.55 (flagged)`;

  if (isArcFlagged) {
    return (
      <span className="text-[var(--accent)]" title={tip}>
        ⚠ flagged {score.toFixed(2)}
      </span>
    );
  }
  if (isSuspect) {
    return (
      <span style={{ color: "#d97706" }} title={tip}>
        ? douteux {score.toFixed(2)}
      </span>
    );
  }
  return (
    <span className="text-[var(--text-primary)]" title={tip}>
      ✓ identité {score.toFixed(2)}
    </span>
  );
}

export default function FaceCard({
  image,
  onActivate,
  galtonSelectable = false,
  galtonSelected = false,
  onToggleGaltonSelect,
}) {
  const [showSource, setShowSource] = useState(false);
  const [confirmingFlag, setConfirmingFlag] = useState(false);
  const queryClient = useQueryClient();
  const face = image.face;
  const aligned = image.aligned_url;
  const display = aligned || image.source_url;
  const score = image.identity_match_score;
  const status = image.association_status;
  const isFlagged = status === "flagged";
  const isHumanFlagged = status === "human_flagged";
  const isAnyFlagged = isFlagged || isHumanFlagged;
  const isSuspect =
    !isAnyFlagged &&
    score !== null &&
    score !== undefined &&
    score > SUSPECT_THRESHOLD;
  const cardBorder = isAnyFlagged
    ? { borderColor: "var(--accent)", borderWidth: 2 }
    : isSuspect
      ? { borderColor: "#d97706", borderWidth: 2 }
      : undefined;

  const flagMut = useMutation({
    mutationFn: () => api.flagImage(image.id),
    onSuccess: () => {
      setConfirmingFlag(false);
      // Recharger la galerie et la liste flagged — l'image change de statut
      // côté DB et doit refléter le ⚠ signalée sur la card + apparaître
      // dans /audit.
      queryClient.invalidateQueries({ queryKey: ["entityImages"] });
      queryClient.invalidateQueries({ queryKey: ["flagged"] });
    },
  });

  return (
    <article
      className="border divider bg-[var(--bg-primary)] flex flex-col group"
      style={cardBorder}
    >
      <div className="relative aspect-square">
        <button
          onClick={() => onActivate?.(image)}
          className="block w-full h-full overflow-hidden bg-[var(--bg-secondary)] ambient-halo"
        >
          <FaceImage src={display} alt={image.caption || ""} />
        </button>
        {galtonSelectable && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleGaltonSelect?.();
            }}
            aria-pressed={galtonSelected}
            aria-label={galtonSelected ? "Désélectionner pour Galton" : "Sélectionner pour Galton"}
            title={galtonSelected ? "Retirer du composite Galton" : "Ajouter au composite Galton"}
            className={`absolute top-2 left-2 w-7 h-7 rounded-full border flex items-center justify-center text-sm font-mono transition-all ${
              galtonSelected
                ? "bg-[var(--accent)] text-white border-[var(--accent)] opacity-100"
                : "bg-black/60 text-white border-white/40 opacity-0 group-hover:opacity-100 hover:bg-black/80"
            }`}
          >
            {galtonSelected ? "●" : "◯"}
          </button>
        )}
        <div className="absolute top-2 right-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowSource(true);
            }}
            className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded bg-black/60 text-white hover:bg-black/80"
            title="Voir l'image source en plein écran (touche S dans le Flipbook)"
          >
            🔍 Source
          </button>
          {!isAnyFlagged && !confirmingFlag && !flagMut.isPending && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setConfirmingFlag(true);
              }}
              className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded bg-black/60 text-white hover:bg-[var(--accent)]"
              title="Signaler : cette image ne correspond pas à la personne attribuée"
            >
              ⚠ Signaler
            </button>
          )}
          {confirmingFlag && !flagMut.isPending && (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  flagMut.mutate();
                }}
                className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded bg-[var(--accent)] text-white animate-pulse"
                title="Confirmer le signalement — bascule l'image dans /audit"
              >
                ⚠ Confirmer
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmingFlag(false);
                }}
                className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded bg-black/60 text-white hover:bg-black/80"
              >
                annuler
              </button>
            </>
          )}
          {flagMut.isPending && (
            <span className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded bg-black/60 text-white">
              signalement…
            </span>
          )}
        </div>
      </div>

      <div className="px-3 py-2 border-t divider flex items-center justify-between text-[10px] font-mono uppercase tracking-wider">
        {face?.pose ? (
          <span className="text-[var(--text-primary)]">
            {POSE_LABEL[face.pose] || face.pose}
            {face.yaw !== null && face.yaw !== undefined && (
              <span className="text-[var(--text-secondary)] ml-2">
                {face.yaw >= 0 ? "+" : ""}
                {face.yaw.toFixed(1)}°
              </span>
            )}
          </span>
        ) : (
          <span className="text-[var(--text-secondary)]">non analysée</span>
        )}
        <IdentityBadge image={image} />
      </div>

      {(image.caption || image.copyright) && (
        <div className="px-3 py-2 text-xs leading-snug">
          {image.caption && <p>{image.caption}</p>}
          {image.copyright && (
            <p className="text-[var(--text-secondary)] mt-1">
              {image.copyright}
            </p>
          )}
        </div>
      )}

      <div className="px-3 py-2 border-t divider flex items-center justify-between text-[10px] font-mono">
        {image.article ? (
          <a
            href={image.article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--text-secondary)] hover:text-[var(--accent)] truncate"
            title={image.article.title}
          >
            → {image.article.source_domain}
          </a>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <button
            onClick={() => navigator.clipboard?.writeText(image.source_url)}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            title="Copier l'URL d'origine"
          >
            URL
          </button>
          <a
            href={image.source_url}
            download
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            DL
          </a>
          {aligned && (
            <a
              href={aligned}
              download
              className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              DL aligné
            </a>
          )}
        </div>
      </div>
      {showSource && (
        <SourceLightbox image={image} onClose={() => setShowSource(false)} />
      )}
    </article>
  );
}

/**
 * Image avec fallback placeholder si chargement échoue (URL morte,
 * CORS bloqué, format non supporté). Évite le carré cassé natif du
 * navigateur (cf. spec §19 "Images manquantes").
 */
function FaceImage({ src, alt }) {
  const [errored, setErrored] = useState(false);
  useEffect(() => {
    setErrored(false);
  }, [src]);

  if (errored || !src) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-[var(--bg-secondary)]">
        <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--text-secondary)]">
          ⌧ image indisponible
        </span>
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      crossOrigin="anonymous"
      className="w-full h-full object-cover"
      onError={() => setErrored(true)}
    />
  );
}
