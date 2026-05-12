import { useEffect, useState } from "react";

/**
 * Badge debug en bas à droite — affiche les valeurs réelles des variables
 * CSS `--ambient-*` et les 5 couleurs effectives lues depuis le DOM.
 *
 * Permet de vérifier en 1 coup d'œil que `useAmbientColor` tourne et écrit
 * bien les variables sur `:root`. À retirer du JSX une fois la confiance
 * établie (composant orphelin sans usage = pas embarqué).
 */
export default function AmbientDebug() {
  const [snap, setSnap] = useState(null);

  useEffect(() => {
    const probe = () => {
      const cs = getComputedStyle(document.documentElement);
      setSnap({
        hue: cs.getPropertyValue("--ambient-hue").trim(),
        sat: cs.getPropertyValue("--ambient-sat").trim(),
        bg: cs.getPropertyValue("--bg-primary").trim(),
        bg2: cs.getPropertyValue("--bg-secondary").trim(),
        border: cs.getPropertyValue("--border").trim(),
        tp: cs.getPropertyValue("--text-primary").trim(),
        ts: cs.getPropertyValue("--text-secondary").trim(),
      });
    };
    probe();
    // Re-snapshot périodique — `useAmbientColor` modifie via setProperty,
    // qui ne déclenche pas de mutation observable sans MutationObserver
    // sur les attributs style. Poll léger suffit pour debug.
    const id = setInterval(probe, 500);
    return () => clearInterval(id);
  }, []);

  if (!snap) return null;

  const swatch = (color) => (
    <span
      style={{
        background: color,
        display: "inline-block",
        width: 14,
        height: 14,
        verticalAlign: "middle",
        border: "1px solid rgba(0,0,0,0.2)",
        marginRight: 4,
      }}
    />
  );

  return (
    <div
      style={{
        position: "fixed",
        bottom: 12,
        right: 12,
        zIndex: 9999,
        padding: "8px 10px",
        background: "rgba(0,0,0,0.78)",
        color: "#fff",
        fontFamily: "monospace",
        fontSize: 11,
        lineHeight: 1.5,
        borderRadius: 4,
        pointerEvents: "none",
      }}
    >
      <div style={{ opacity: 0.7, marginBottom: 4 }}>
        ambient h={snap.hue || "—"} s={snap.sat || "—"}
      </div>
      <div>{swatch(snap.bg)}bg {snap.bg}</div>
      <div>{swatch(snap.bg2)}bg2 {snap.bg2}</div>
      <div>{swatch(snap.border)}brd {snap.border}</div>
      <div>{swatch(snap.tp)}txt {snap.tp}</div>
      <div>{swatch(snap.ts)}sec {snap.ts}</div>
    </div>
  );
}
