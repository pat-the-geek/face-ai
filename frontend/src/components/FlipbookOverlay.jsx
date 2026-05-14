import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import LandmarkOverlay from "./LandmarkOverlay";
import SourceLightbox from "./SourceLightbox";

/**
 * Mode défilement rapide (spec §7.5).
 *
 * Transitions :
 * - manuel ou auto rapide (≥2 fps) → 0 ms (succession instantanée)
 * - auto lent (≤1 fps) → 400 ms (fondu cinématographique)
 * - composite explicite → 800 ms (effet Galton)
 */
export default function FlipbookOverlay({ controller }) {
  const [showSource, setShowSource] = useState(false);
  const [showLandmarks, setShowLandmarks] = useState(false);

  // Touche `S` ouvre/ferme la vue source ; `L` toggle l'overlay landmarks
  // (spec §10). Écouteur attaché uniquement quand le Flipbook est ouvert.
  useEffect(() => {
    if (!controller.isOpen) return;
    const handler = (e) => {
      if (e.key === "s" || e.key === "S") {
        e.preventDefault();
        setShowSource((v) => !v);
      } else if (e.key === "l" || e.key === "L") {
        e.preventDefault();
        setShowLandmarks((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [controller.isOpen]);

  // Si on change d'image en cours, on ferme la lightbox source pour repartir propre
  useEffect(() => {
    setShowSource(false);
  }, [controller.currentIdx]);

  if (!controller.isOpen || !controller.current) return null;

  const transitionMs = computeTransition(controller);
  const current = controller.current;
  const aligned = current.aligned_url || current.source_url;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center select-none"
      style={{
        background: `radial-gradient(ellipse 80% 60% at 50% 50%,
            hsl(var(--ambient-hue) calc(var(--ambient-sat) * 0.3%) 8%),
            var(--immersive-bg) 70%)`,
        color: "var(--immersive-text-primary)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) controller.close();
      }}
    >
      {/* Compteur */}
      <div className="absolute top-6 right-8 font-mono text-xs text-[var(--immersive-text-muted)]">
        {controller.currentIdx + 1} / {controller.total}
      </div>

      {/* Close */}
      <button
        onClick={controller.close}
        className="absolute top-6 left-8 font-mono text-xs text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
        aria-label="Fermer le Flipbook (Échap)"
      >
        ✕ Échap
      </button>

      {/* Contrôles auto-play + composite */}
      <div className="absolute top-6 left-1/2 -translate-x-1/2 flex items-center gap-3 font-mono text-xs">
        <button
          onClick={() => controller.setAutoPlay(!controller.autoPlay)}
          className={
            controller.autoPlay
              ? "text-accent"
              : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
          }
        >
          {controller.autoPlay ? "❚❚" : "▶"} Auto
        </button>
        {controller.speeds.map((s) => (
          <button
            key={s}
            onClick={() => controller.setFps(s)}
            className={
              controller.fps === s
                ? "text-[var(--immersive-text-primary)]"
                : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
            }
          >
            {s} fps
          </button>
        ))}
        <span className="mx-2 text-[var(--immersive-separator)]">|</span>
        <button
          onClick={() => controller.setComposite(!controller.composite)}
          className={
            controller.composite
              ? "text-[var(--immersive-text-primary)]"
              : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
          }
          title="Crossfade long pour effet composite (Galton)"
        >
          ◉ Composite
        </button>
        <span className="mx-2 text-[var(--immersive-separator)]">|</span>
        <button
          onClick={() => setShowLandmarks((v) => !v)}
          className={
            showLandmarks
              ? "text-[var(--immersive-text-primary)]"
              : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
          }
          title="Overlay landmarks faciaux (touche L)"
        >
          ⊕ Landmarks · L
        </button>
        <span className="mx-2 text-[var(--immersive-separator)]">|</span>
        <button
          onClick={() => setShowSource(true)}
          className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
          title="Voir l'image source pleine résolution (touche S)"
        >
          🔍 Source · S
        </button>
      </div>

      {/* Flèche gauche */}
      <button
        onClick={controller.prev}
        className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] text-6xl font-thin opacity-40 hover:opacity-100 transition-opacity p-6"
        aria-label="Image précédente (←)"
      >
        ‹
      </button>

      {/* Image */}
      <div
        className="relative ambient-halo-dark"
        style={{
          height: "80vh",
          width: "80vh",
          maxWidth: "80vw",
        }}
      >
        <FlipbookImage
          src={aligned}
          alt={current.caption || ""}
          transitionMs={transitionMs}
        />
        <LandmarkOverlay
          face={current.face}
          imageId={current.id}
          visible={showLandmarks}
        />
      </div>

      {/* Flèche droite */}
      <button
        onClick={controller.next}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] text-6xl font-thin opacity-40 hover:opacity-100 transition-opacity p-6"
        aria-label="Image suivante (→)"
      >
        ›
      </button>

      {/* Méta basse */}
      <div
        className="absolute bottom-0 left-0 right-0 px-8 py-4 text-xs font-mono"
        style={{
          background:
            "var(--immersive-bg-meta)",
        }}
      >
        <div className="flex justify-between gap-8 items-start">
          <div className="flex-1 min-w-0">
            {current.caption && (
              <p className="text-[var(--immersive-text-primary)] truncate">{current.caption}</p>
            )}
            {current.copyright && (
              <p className="text-[var(--immersive-text-muted)] mt-1 truncate">
                {current.copyright}
              </p>
            )}
          </div>
          <div className="flex items-start gap-4 shrink-0">
            {current.article && (
              <a
                href={current.article.url}
                target="_blank"
                rel="noreferrer"
                className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
              >
                → article
              </a>
            )}
            <button
              onClick={() => navigator.clipboard?.writeText(current.source_url)}
              className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
            >
              copier URL
            </button>
            <a
              href={current.source_url}
              download
              className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
            >
              dl original
            </a>
            {current.aligned_url && (
              <a
                href={current.aligned_url}
                download
                className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
              >
                dl aligné
              </a>
            )}
          </div>
        </div>
      </div>
      {showSource && (
        <SourceLightbox
          image={current}
          onClose={() => setShowSource(false)}
        />
      )}
    </div>,
    document.body,
  );
}

function computeTransition(controller) {
  if (controller.composite) return 800;
  if (controller.autoPlay && controller.fps <= 1) return 400;
  return 0;
}

function FlipbookImage({ src, alt, transitionMs }) {
  const [layers, setLayers] = useState([{ src, opacity: 1, key: src }]);
  const lastSrc = useRef(src);

  useEffect(() => {
    if (src === lastSrc.current) return;
    lastSrc.current = src;

    if (transitionMs === 0) {
      setLayers([{ src, opacity: 1, key: src + Date.now() }]);
      return;
    }

    const newKey = src + "-" + Date.now();
    // 1. Nouveau layer à opacity 0, anciens fade out
    setLayers((prev) => [
      ...prev.map((l) => ({ ...l, opacity: 0 })),
      { src, opacity: 0, key: newKey },
    ]);

    // 2. Frame suivant : monter le nouveau à 1 (déclenche transition)
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setLayers((prev) =>
          prev.map((l) => (l.key === newKey ? { ...l, opacity: 1 } : l)),
        );
      });
    });

    // 3. Après transition : nettoyer les anciens
    const cleanup = setTimeout(() => {
      setLayers((prev) => prev.filter((l) => l.key === newKey));
    }, transitionMs + 100);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(cleanup);
    };
  }, [src, transitionMs]);

  return (
    <>
      {layers.map((l) => (
        <img
          key={l.key}
          src={l.src}
          alt={alt}
          crossOrigin="anonymous"
          className="absolute inset-0 w-full h-full object-contain"
          style={{
            opacity: l.opacity,
            transition:
              transitionMs > 0
                ? `opacity ${transitionMs}ms ease`
                : "none",
          }}
        />
      ))}
    </>
  );
}
