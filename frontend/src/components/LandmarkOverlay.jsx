import { useEffect, useState } from "react";
import { api } from "../api/client";

/**
 * Overlay landmarks faciaux (spec §10).
 *
 * Deux modes :
 * - **Mesh 478 points** (v024+) : si `face.has_full_mesh`, on charge le
 *   mesh complet via `GET /images/{id}/landmarks` et on rend des
 *   filets fins reliant les contours principaux du visage. Esthétique
 *   forensique avec densité de points qui rappelle une analyse
 *   anthropométrique.
 * - **3 points** (fallback) : pour les images analysées avant v024
 *   ou dont l'extraction mesh a échoué, on rend juste yeux + nez +
 *   reliures (comportement historique).
 *
 * Filets gris clair fins, `mixBlendMode: screen` pour rester lisible
 * sur tout fond. Toggle via touche `L` côté FlipbookOverlay parent.
 */
export default function LandmarkOverlay({ face, imageId, visible }) {
  const [mesh, setMesh] = useState(null);
  const [meshLoading, setMeshLoading] = useState(false);

  // Charge le mesh à la demande quand l'overlay s'active sur une image
  // avec mesh disponible. Cache simple par imageId.
  useEffect(() => {
    if (!visible) return;
    if (!face?.has_full_mesh) return;
    if (!imageId) return;
    setMeshLoading(true);
    let alive = true;
    api.imageLandmarks(imageId).then(
      (data) => {
        if (!alive) return;
        setMesh(data.points || null);
        setMeshLoading(false);
      },
      () => {
        if (!alive) return;
        setMesh(null);
        setMeshLoading(false);
      },
    );
    return () => {
      alive = false;
    };
  }, [visible, face, imageId]);

  if (!visible || !face) return null;

  const stroke = "rgba(232, 228, 222, 0.55)";
  const strokeFine = "rgba(232, 228, 222, 0.25)";

  // Coordonnées 3 points (fallback) — en pixels sur l'image source
  const { left_eye_x: lx, left_eye_y: ly } = face;
  const { right_eye_x: rx, right_eye_y: ry } = face;
  const { nose_x: nx, nose_y: ny } = face;

  // Décide quel mesh afficher
  if (mesh) {
    return (
      <svg
        viewBox="0 0 1 1"
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 w-full h-full pointer-events-none"
        style={{ mixBlendMode: "screen" }}
      >
        {/* Mesh dense : 478 points en cercles fins. On utilise un
            <g> avec un style commun pour réduire le poids DOM. */}
        <g fill="none" stroke={stroke} strokeWidth="0.003">
          {mesh.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="0.0025" />
          ))}
        </g>
        {/* Contours stratégiques : ovale visage (indices 10, 338,
            297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397,
            365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
            172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109)
            — version simplifiée : on dessine la chaîne ovale FACE_OVAL
            de MediaPipe pour suggérer le contour. */}
        <path
          d={faceOvalPath(mesh)}
          fill="none"
          stroke={strokeFine}
          strokeWidth="0.0035"
        />
      </svg>
    );
  }

  // Fallback 3 points si pas de mesh ou loading
  if (lx == null || ly == null || rx == null || ry == null) return null;

  return (
    <svg
      viewBox="0 0 300 300"
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ mixBlendMode: "screen" }}
    >
      <line x1={lx} y1={ly} x2={rx} y2={ry} stroke={strokeFine} strokeWidth="0.6" />
      <circle cx={lx} cy={ly} r="3" stroke={stroke} strokeWidth="0.8" fill="none" />
      <circle cx={lx} cy={ly} r="0.7" fill={stroke} />
      <circle cx={rx} cy={ry} r="3" stroke={stroke} strokeWidth="0.8" fill="none" />
      <circle cx={rx} cy={ry} r="0.7" fill={stroke} />
      {nx != null && ny != null && (
        <>
          <line
            x1={(lx + rx) / 2}
            y1={(ly + ry) / 2}
            x2={nx}
            y2={ny}
            stroke={strokeFine}
            strokeWidth="0.6"
            strokeDasharray="2 2"
          />
          <circle cx={nx} cy={ny} r="2.2" stroke={stroke} strokeWidth="0.8" fill="none" />
        </>
      )}
      <text
        x={(lx + rx) / 2}
        y={Math.min(ly, ry) - 6}
        fill={stroke}
        fontSize="6"
        fontFamily="monospace"
        textAnchor="middle"
      >
        ed {Math.round(Math.hypot(rx - lx, ry - ly))}
        {meshLoading && " · loading mesh…"}
      </text>
    </svg>
  );
}

// Indices MediaPipe pour le contour ovale du visage (FACEMESH_FACE_OVAL).
// Source : https://github.com/google/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py
const FACE_OVAL_INDICES = [
  10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
  397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
  172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10,
];

function faceOvalPath(mesh) {
  if (!mesh || !mesh.length) return "";
  const pts = FACE_OVAL_INDICES.map((i) => mesh[i]).filter(Boolean);
  if (pts.length === 0) return "";
  return pts
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x} ${y}`)
    .join(" ");
}
