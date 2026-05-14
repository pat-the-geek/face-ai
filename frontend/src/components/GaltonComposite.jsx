import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Composite Galton interactif (spec §1.5 / §11.6) — superpose N
 * portraits alignés avec opacité graduée pour faire émerger un visage
 * "moyen". L'esthétique forensique-musée du projet : on relit le sens
 * statistique du portrait par accumulation.
 *
 * - **Mode auto** : opacité égale (1/N pour chacun) → effet Galton
 *   strict, le composite est la moyenne arithmétique pixel à pixel
 *   (en alpha blending qui approxime).
 * - **Mode gradué** : opacité linéaire décroissante de 1.0 à 0.1 →
 *   met l'accent sur les premiers portraits dans l'ordre.
 *
 * Rendu via `<canvas>` 600×600. Les images alignées (300×300) sont
 * upscalées. Toutes les images doivent avoir `aligned_url`, sinon
 * elles sont ignorées.
 *
 * Export PNG via `canvas.toDataURL('image/png')` — fichier
 * `galton_{slug}_{N}_{timestamp}.png`.
 */
const CANVAS_SIZE = 600;

export default function GaltonComposite({
  images,
  entitySlug,
  onClose,
}) {
  const canvasRef = useRef(null);
  const [mode, setMode] = useState("auto"); // "auto" | "graduated"
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);

  const validImages = images.filter((i) => i.aligned_url);

  useEffect(() => {
    if (!canvasRef.current || validImages.length === 0) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    let cancelled = false;

    async function draw() {
      // Running weighted average via `source-over` standard.
      // À chaque image i (poids w_i), on dessine avec
      //   alpha_i = w_i / sum(w_0..w_i)
      // Démonstration : par récurrence, après l'image i, le canvas
      // contient sum(w_j × src_j, j=0..i) / sum(w_j, j=0..i).
      // À i=N-1 c'est la moyenne pondérée exacte.
      //
      // Avantages vs `lighter` + alpha normalisé :
      // - alpha cumulé du canvas atteint 1.0 (plein opaque) au lieu
      //   de rester semi-transparent → pas de fond CSS qui plombe
      // - pas de risque de clipping sur les hautes valeurs
      // - sémantique mathématique propre : c'est littéralement la
      //   moyenne pondérée de Galton
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

      const weights = computeWeights(validImages.length, mode);
      let cumW = 0;

      for (let i = 0; i < validImages.length; i++) {
        if (cancelled) return;
        const img = validImages[i];
        try {
          const bitmap = await loadImage(img.aligned_url);
          cumW += weights[i];
          ctx.globalAlpha = weights[i] / cumW;
          ctx.drawImage(bitmap, 0, 0, CANVAS_SIZE, CANVAS_SIZE);
          setProgress(i + 1);
        } catch (e) {
          // Image qui ne charge pas (CORS, 404) → on continue ; comme
          // on n'a pas incrémenté cumW, le calcul reste cohérent.
          console.warn("Galton: image skipped", img.aligned_url, e);
        }
      }
      ctx.globalAlpha = 1.0;
    }

    setProgress(0);
    setError(null);
    draw().catch((e) => {
      if (!cancelled) setError(e.message);
    });

    return () => {
      cancelled = true;
    };
  }, [validImages, mode]);

  const onExport = () => {
    if (!canvasRef.current) return;
    const url = canvasRef.current.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = url;
    a.download = `galton_${entitySlug || "composite"}_${validImages.length}_${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-primary)] border divider max-w-3xl w-full p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-baseline justify-between mb-4">
          <div>
            <div className="font-display text-3xl">Composite Galton</div>
            <div className="mt-1 text-xs font-mono text-[var(--text-secondary)]">
              {validImages.length} portraits superposés
              {entitySlug && ` · ${entitySlug}`}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
          >
            ✕ Fermer
          </button>
        </header>

        <div className="flex items-center justify-center bg-black p-4 mb-4">
          <canvas
            ref={canvasRef}
            width={CANVAS_SIZE}
            height={CANVAS_SIZE}
            className="max-w-full h-auto"
            style={{ imageRendering: "smooth" }}
          />
        </div>

        {progress > 0 && progress < validImages.length && (
          <div className="text-xs font-mono text-[var(--text-secondary)] mb-3">
            rendu : {progress} / {validImages.length}
          </div>
        )}

        {error && (
          <div className="text-xs font-mono text-accent mb-3">
            erreur : {error}
          </div>
        )}

        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider">
            <span className="text-[var(--text-secondary)]">opacités :</span>
            <button
              onClick={() => setMode("auto")}
              className={`px-2 py-0.5 border ${
                mode === "auto"
                  ? "border-accent text-accent"
                  : "divider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
              title="1/N — moyenne arithmétique stricte"
            >
              Galton (1/N)
            </button>
            <button
              onClick={() => setMode("graduated")}
              className={`px-2 py-0.5 border ${
                mode === "graduated"
                  ? "border-accent text-accent"
                  : "divider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
              title="Décroissance linéaire 1.0 → 0.1 — accentue les 1ers"
            >
              Gradué
            </button>
          </div>
          <button
            onClick={onExport}
            disabled={progress === 0 || progress < validImages.length}
            className="px-3 py-1 border border-accent text-accent uppercase tracking-wider text-xs disabled:opacity-40"
          >
            ⤓ Exporter PNG
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`image load failed: ${url}`));
    img.src = url;
  });
}

/**
 * Calcule les poids bruts (non normalisés) par image. Le caller fait
 * le running average lui-même via `alpha_i = w_i / cumW_i` avec
 * `globalCompositeOperation="source-over"`.
 *
 * - `auto` : poids égal 1.0 → moyenne arithmétique stricte (Galton)
 * - `graduated` : poids décroissants linéaires 1.0 → 0.1.
 */
function computeWeights(total, mode) {
  if (total === 0) return [];
  const raw = [];
  for (let i = 0; i < total; i++) {
    if (mode === "auto") {
      raw.push(1.0);
    } else {
      const t = total > 1 ? i / (total - 1) : 0;
      raw.push(1.0 - t * 0.9);
    }
  }
  return raw;
}
