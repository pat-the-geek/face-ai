import { createPortal } from "react-dom";

/**
 * Overlay Flipbook pour mode comparaison (spec §11.5).
 *
 * Affiche en parallèle le portrait courant des deux entités, gérés par un
 * controller unique (`useSplitFlipbook`). Pas de crossfade — la comparaison
 * profite mieux d'une succession instantanée et synchronisée.
 *
 * Le filtre pose et le toggle doublons des sub-panneaux ne s'appliquent pas
 * ici : on prend les images alignées non-doublons brutes (chargées par
 * `SplitScreen` qui passe les listes complètes).
 */
export default function SplitFlipbookOverlay({ controller, nameA, nameB }) {
  if (!controller.isOpen) return null;
  if (!controller.currentA || !controller.currentB) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col select-none"
      style={{
        background:
          "radial-gradient(ellipse 90% 60% at 50% 50%, hsl(var(--ambient-hue) calc(var(--ambient-sat) * 0.3%) 8%), #080808 70%)",
        color: "#e8e4de",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) controller.close();
      }}
    >
      {/* Top bar : noms + close + compteur */}
      <div className="flex items-center justify-between px-8 py-4 font-mono text-xs">
        <button
          onClick={controller.close}
          className="text-[#5a5550] hover:text-[#e8e4de] transition-colors"
          aria-label="Fermer (Échap)"
        >
          ✕ Échap
        </button>
        <div className="text-[#5a5550]">
          {controller.currentIdx + 1} / {controller.total} paires comparées
          {controller.lenA !== controller.lenB && (
            <span className="ml-2 text-[#3a3530]">
              ({controller.lenA} ↔ {controller.lenB})
            </span>
          )}
        </div>
      </div>

      {/* Scène : 2 portraits côte-à-côte, sizing strictement identique */}
      <div className="flex-1 grid grid-cols-2 min-h-0 px-4 pb-4 gap-4">
        <SplitPanel image={controller.currentA} name={nameA} />
        <SplitPanel image={controller.currentB} name={nameB} />
      </div>

      {/* Flèches gauche / droite plein écran */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          controller.prev();
        }}
        className="absolute left-2 top-1/2 -translate-y-1/2 text-[#5a5550] hover:text-[#e8e4de] text-6xl font-thin opacity-40 hover:opacity-100 transition-opacity p-6"
        aria-label="Paire précédente (←)"
      >
        ‹
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          controller.next();
        }}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-[#5a5550] hover:text-[#e8e4de] text-6xl font-thin opacity-40 hover:opacity-100 transition-opacity p-6"
        aria-label="Paire suivante (→)"
      >
        ›
      </button>

      {/* Bottom bar : auto-play + speed */}
      <div className="flex items-center justify-center gap-3 px-8 py-3 font-mono text-xs">
        <button
          onClick={() => controller.setAutoPlay(!controller.autoPlay)}
          className={
            controller.autoPlay
              ? "text-[#c8102e]"
              : "text-[#5a5550] hover:text-[#e8e4de] transition-colors"
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
                ? "text-[#e8e4de]"
                : "text-[#5a5550] hover:text-[#e8e4de] transition-colors"
            }
          >
            {s} fps
          </button>
        ))}
      </div>
    </div>,
    document.body,
  );
}

function SplitPanel({ image, name }) {
  const src = image.aligned_url || image.source_url;
  // Sizing strict : `min(70vh, 100%)` plafonne la largeur sur la plus
  // contraignante (hauteur viewport OU largeur de cellule grid), et
  // `aspectRatio: 1/1` rend le conteneur carré. Les 2 panels reçoivent
  // les mêmes contraintes via grid-cols-2 → tailles rendues identiques,
  // peu importe la dimension du portrait source. `object-contain` adapte
  // sans déformer si l'image n'est pas carrée (cas image non-alignée).
  return (
    <div className="flex flex-col items-center justify-center min-h-0 min-w-0">
      <div
        className="relative ambient-halo-dark"
        style={{
          width: "min(70vh, 100%)",
          aspectRatio: "1 / 1",
        }}
      >
        <img
          src={src}
          alt={image.caption || name}
          crossOrigin="anonymous"
          className="absolute inset-0 w-full h-full object-contain"
        />
      </div>
      <div
        className="mt-3 font-mono text-xs uppercase tracking-wider text-[#8a8278]"
      >
        {name}
      </div>
    </div>
  );
}
