import { useCallback, useEffect, useMemo, useState } from "react";

const SPEEDS = [0.5, 1, 2, 4];

/**
 * Tri chronologique des images par date de publication de l'article
 * (ancien → récent). Les images sans date passent en fin. Copie stable —
 * ne mute pas le tableau source.
 */
function orderImages(images, chrono) {
  const list = images || [];
  if (!chrono) return list;
  return [...list].sort((a, b) => {
    const da = a.article?.published_at || "";
    const db = b.article?.published_at || "";
    if (!da && !db) return 0;
    if (!da) return 1;
    if (!db) return -1;
    return da.localeCompare(db);
  });
}

/**
 * Contrôle du mode Flipbook (spec §7.5).
 *
 * État : index courant, ouverture, lecture auto, vitesse, mode composite,
 * tri chronologique. Navigation : ←/→ clavier, espace pour pause, Échap.
 * Boucle : prev sur le premier renvoie au dernier, et vice-versa.
 *
 * Mode chrono : réordonne les images par date d'article (ancien → récent),
 * utile pour observer l'évolution d'apparence dans le temps. Le basculement
 * préserve l'image courante (remap de l'index sur la nouvelle liste).
 */
export function useFlipbook(images) {
  const [chrono, setChrono] = useState(false);
  const ordered = useMemo(() => orderImages(images, chrono), [images, chrono]);
  const total = ordered.length;
  const [currentIdx, setCurrentIdx] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [fps, setFps] = useState(2);
  const [composite, setComposite] = useState(false);

  // Bascule le tri chrono en gardant l'image courante à l'écran.
  const toggleChrono = useCallback(() => {
    setChrono((prev) => {
      const next = !prev;
      const curId = ordered[currentIdx]?.id;
      if (curId != null) {
        const idx = orderImages(images, next).findIndex((im) => im.id === curId);
        if (idx >= 0) setCurrentIdx(idx);
      }
      return next;
    });
  }, [images, ordered, currentIdx]);

  // Si la liste change (changement de filtre, d'entité), on borne l'index
  useEffect(() => {
    if (currentIdx >= total) setCurrentIdx(0);
  }, [total, currentIdx]);

  const open = useCallback(
    (idx = 0) => {
      if (total === 0) return;
      setCurrentIdx(Math.max(0, Math.min(total - 1, idx)));
      setIsOpen(true);
    },
    [total],
  );

  const close = useCallback(() => {
    setIsOpen(false);
    setAutoPlay(false);
  }, []);

  const next = useCallback(() => {
    if (total === 0) return;
    setCurrentIdx((i) => (i + 1) % total);
  }, [total]);

  const prev = useCallback(() => {
    if (total === 0) return;
    setCurrentIdx((i) => (i - 1 + total) % total);
  }, [total]);

  const goTo = useCallback(
    (idx) => {
      if (idx >= 0 && idx < total) setCurrentIdx(idx);
    },
    [total],
  );

  // Clavier global tant que l'overlay est ouvert
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (e.key === "ArrowRight") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === " ") {
        e.preventDefault();
        setAutoPlay((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, next, prev, close]);

  // Lecture auto — interval reset à chaque changement de fps
  useEffect(() => {
    if (!isOpen || !autoPlay || total < 2) return;
    const intervalMs = Math.max(50, 1000 / fps);
    const timer = setInterval(next, intervalMs);
    return () => clearInterval(timer);
  }, [isOpen, autoPlay, fps, next, total]);

  return {
    images: ordered,
    current: ordered[currentIdx] ?? null,
    currentIdx,
    total,
    isOpen,
    open,
    close,
    next,
    prev,
    goTo,
    autoPlay,
    setAutoPlay,
    fps,
    setFps,
    composite,
    setComposite,
    chrono,
    toggleChrono,
    speeds: SPEEDS,
  };
}
