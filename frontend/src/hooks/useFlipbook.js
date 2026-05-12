import { useCallback, useEffect, useState } from "react";

const SPEEDS = [0.5, 1, 2, 4];

/**
 * Contrôle du mode Flipbook (spec §7.5).
 *
 * État : index courant, ouverture, lecture auto, vitesse, mode composite.
 * Navigation : ←/→ clavier, espace pour pause, Échap pour fermer.
 * Boucle : prev sur le premier renvoie au dernier, et vice-versa.
 */
export function useFlipbook(images) {
  const total = images?.length || 0;
  const [currentIdx, setCurrentIdx] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [fps, setFps] = useState(2);
  const [composite, setComposite] = useState(false);

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
    images,
    current: images?.[currentIdx] ?? null,
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
    speeds: SPEEDS,
  };
}
