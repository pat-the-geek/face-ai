import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useFoule } from "../hooks/useFoule";

// --- Helpers API Fullscreen (avec repli vendor WebKit/Safari) -------------
function fsElement() {
  return document.fullscreenElement || document.webkitFullscreenElement || null;
}
function requestFs(el) {
  const fn = el && (el.requestFullscreen || el.webkitRequestFullscreen);
  if (!fn) return;
  try {
    const p = fn.call(el);
    if (p && p.catch) p.catch(() => {});
  } catch {
    /* refusé hors geste utilisateur : on reste en overlay fenêtré */
  }
}
function exitFs() {
  const fn = document.exitFullscreen || document.webkitExitFullscreen;
  if (!fn) return;
  try {
    const p = fn.call(document);
    if (p && p.catch) p.catch(() => {});
  } catch {
    /* ignore */
  }
}

// Durée écoulée formatée m:ss.mmm (précision milliseconde).
function formatMs(ms) {
  const total = Math.max(0, Math.floor(ms));
  const m = Math.floor(total / 60000);
  const s = Math.floor((total % 60000) / 1000);
  const millis = total % 1000;
  return `${m}:${String(s).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

// Style « verre dépoli » partagé (HUD bas + groupes de contrôles du haut).
const PILL = {
  background: "rgba(0,0,0,0.66)",
  border: "1px solid rgba(255,255,255,0.22)",
  backdropFilter: "blur(6px)",
  WebkitBackdropFilter: "blur(6px)",
  textShadow: "0 1px 4px rgba(0,0,0,0.85)",
};

/**
 * « Foule » — affichage plein écran génératif (plan iridescent-beaming-cloud).
 *
 * Vrai plein écran via l'API Fullscreen (masque le chrome du navigateur).
 * Démarre sur la personne la plus active (1 carré plein cadre) puis subdivise
 * l'écran d'un carré à chaque personne ajoutée, chaque carré faisant défiler
 * ses photos. Un seul curseur de vitesse (0.5/1/2/4 fps) pilote à la fois la
 * croissance et le défilement ; un gouverneur adaptatif protège le CPU.
 *
 * Échap (ou sortie du plein écran) ferme. Rendu dans un <canvas> unique.
 */
export default function FoulePanel() {
  const navigate = useNavigate();
  const panelRef = useRef(null);
  const canvasRef = useRef(null);
  const closingRef = useRef(false);
  const foule = useFoule({ canvasRef });
  const [controlsVisible, setControlsVisible] = useState(true);
  const [isFs, setIsFs] = useState(false);
  const hideTimer = useRef(null);

  // Chrono à la milliseconde — mis à jour via rAF dans le DOM (pas de re-render
  // React) ; démarre au 1er visage, se met en pause avec la lecture.
  const timerRef = useRef(null);
  const accumRef = useRef(0);
  const lastTickRef = useRef(0);
  const startedRef = useRef(false);
  const pausedDisplayRef = useRef(false);

  useEffect(() => {
    pausedDisplayRef.current = foule.paused;
  }, [foule.paused]);

  useEffect(() => {
    if (foule.ready && !startedRef.current) {
      startedRef.current = true;
      lastTickRef.current = performance.now();
    }
  }, [foule.ready]);

  useEffect(() => {
    let raf;
    const tick = () => {
      const now = performance.now();
      if (startedRef.current && !pausedDisplayRef.current) {
        accumRef.current += now - lastTickRef.current;
      }
      lastTickRef.current = now;
      if (timerRef.current) timerRef.current.textContent = formatMs(accumRef.current);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const close = useCallback(() => {
    if (closingRef.current) return; // idempotent (ESC + fullscreenchange)
    closingRef.current = true;
    if (fsElement()) exitFs();
    if (window.history.length > 1) navigate(-1);
    else navigate("/");
  }, [navigate]);

  // Le plein écran est normalement déjà demandé par le clic sur « Foule »
  // (geste utilisateur, comme le mode immersif de WUDD). Tentative de repli au
  // montage pour le cas où l'on arrive ici par un autre geste.
  useEffect(() => {
    requestFs(document.documentElement);
  }, []);

  // Sortie du plein écran (Échap natif ou autre) → on ferme le panneau.
  useEffect(() => {
    const onFs = () => {
      setIsFs(Boolean(fsElement()));
      if (!fsElement() && !closingRef.current) close();
    };
    document.addEventListener("fullscreenchange", onFs);
    document.addEventListener("webkitfullscreenchange", onFs);
    return () => {
      document.removeEventListener("fullscreenchange", onFs);
      document.removeEventListener("webkitfullscreenchange", onFs);
    };
  }, [close]);

  // Échap ferme (cas fenêtré où le plein écran a été refusé) ; espace = pause.
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === " ") {
        e.preventDefault();
        foule.togglePause();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [foule.togglePause, close]);

  // Contrôles auto-masqués : réapparaissent au mouvement, disparaissent après 2,5 s.
  useEffect(() => {
    const wake = () => {
      setControlsVisible(true);
      if (hideTimer.current) clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setControlsVisible(false), 2500);
    };
    wake();
    window.addEventListener("mousemove", wake);
    return () => {
      window.removeEventListener("mousemove", wake);
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, []);

  return createPortal(
    <div
      ref={panelRef}
      className="fixed inset-0 z-50 select-none"
      style={{ background: "var(--immersive-bg)", color: "var(--immersive-text-primary)" }}
    >
      <canvas
        ref={canvasRef}
        onClick={() => {
          // Clic sur l'image → plein écran (geste utilisateur propre, comme le
          // mode immersif de WUDD). Repli WebKit géré par requestFs.
          if (!fsElement()) requestFs(document.documentElement);
        }}
        className="absolute inset-0 w-full h-full cursor-pointer"
        style={{ display: "block" }}
      />

      {/* Barre de contrôles */}
      <div
        className="absolute top-0 left-0 right-0 flex items-start justify-between gap-4 px-6 py-6 font-mono text-xl transition-opacity duration-500"
        style={{
          opacity: controlsVisible ? 1 : 0,
          pointerEvents: controlsVisible ? "auto" : "none",
        }}
      >
        <div
          className="flex items-center gap-3 px-6 py-3 rounded-2xl"
          style={PILL}
        >
          <button
            onClick={close}
            className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
            aria-label="Fermer la Foule (Échap)"
          >
            ✕ Échap
          </button>
          {!isFs && (
            <button
              onClick={() => requestFs(document.documentElement)}
              className="text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
              title="Passer en vrai plein écran"
            >
              ⛶ Plein écran
            </button>
          )}
        </div>

        <div
          className="flex items-center gap-3 px-6 py-3 rounded-2xl flex-wrap justify-center"
          style={PILL}
        >
          <button
            onClick={foule.togglePause}
            className={
              foule.paused
                ? "text-accent"
                : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
            }
            title="Lecture / pause (Espace)"
          >
            {foule.paused ? "▶ Lecture" : "❚❚ Pause"}
          </button>
          <span className="text-[var(--immersive-separator)]">|</span>
          {foule.speeds.map((s) => (
            <button
              key={s}
              onClick={() => foule.setFps(s)}
              className={
                foule.fps === s
                  ? "text-[var(--immersive-text-primary)]"
                  : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
              }
            >
              {s} fps
            </button>
          ))}
          <span className="text-[var(--immersive-separator)]">|</span>
          {[
            { k: "wave", label: "〰 Onde" },
            { k: "pulse", label: "✦ Galton" },
            { k: "trails", label: "👻 Trainées" },
            { k: "mosaic", label: "▦ Mosaïque" },
          ].map(({ k, label }) => (
            <button
              key={k}
              onClick={() => foule.toggleEffect(k)}
              className={
                foule.effects[k]
                  ? "text-accent"
                  : "text-[var(--immersive-text-muted)] hover:text-[var(--immersive-text-primary)] transition-colors"
              }
              title={`Effet ${label}`}
            >
              {label}
            </button>
          ))}
        </div>

        <div
          className="flex items-center gap-3 px-6 py-3 rounded-2xl"
          style={{ ...PILL, color: "#ffffff" }}
        >
          {foule.throttled && (
            <span
              style={{ color: "#f5b13d" }}
              title="Le gouverneur a réduit le débit pour ménager le CPU"
            >
              ↓ ralenti
            </span>
          )}
          <span title="visages cyclés par seconde (toutes cellules confondues)">
            ≈ {foule.swapRate} img/s
          </span>
        </div>
      </div>

      {/* Légende d'amorçage tant que rien n'est prêt */}
      {!foule.ready && (
        <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-[var(--immersive-text-muted)] pointer-events-none">
          chargement de la foule…
        </div>
      )}

      {/* HUD bas : personnes · vitesse · chrono (toujours visible). */}
      <div className="absolute bottom-6 left-1/2 -translate-x-1/2 pointer-events-none">
        <div
          className="px-10 py-4 rounded-2xl font-mono text-3xl flex items-center gap-8"
          style={{
            background: "rgba(0,0,0,0.66)",
            border: "1px solid rgba(255,255,255,0.22)",
            backdropFilter: "blur(6px)",
            WebkitBackdropFilter: "blur(6px)",
            textShadow: "0 1px 4px rgba(0,0,0,0.85)",
          }}
        >
          <span style={{ color: "#ffffff" }}>
            <span className="text-accent font-semibold">
              {foule.shown.toLocaleString("fr-FR")}
            </span>
            {" / "}
            {foule.total.toLocaleString("fr-FR")}
            {foule.loadingMore ? "+" : ""} personnes
          </span>
          <span style={{ color: "rgba(255,255,255,0.4)" }}>·</span>
          <span style={{ color: "#ffffff" }}>{foule.fps} fps</span>
          <span style={{ color: "rgba(255,255,255,0.4)" }}>·</span>
          <span
            ref={timerRef}
            className="tabular-nums"
            style={{ color: "#ffffff" }}
          />
        </div>
      </div>

      {/* Invite plein écran tant qu'on n'y est pas (clic = geste utilisateur). */}
      {!isFs && (
        <button
          onClick={() => requestFs(document.documentElement)}
          className="absolute bottom-24 left-1/2 -translate-x-1/2 font-mono text-xs px-4 py-2 rounded-full transition-opacity"
          style={{
            background: "rgba(0,0,0,0.55)",
            color: "var(--immersive-text-primary)",
            border: "1px solid var(--immersive-separator)",
            opacity: controlsVisible ? 1 : 0,
            pointerEvents: controlsVisible ? "auto" : "none",
          }}
        >
          ⛶ Cliquer pour le plein écran
        </button>
      )}
    </div>,
    document.body,
  );
}
