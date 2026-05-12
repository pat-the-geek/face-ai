import { useCallback, useEffect, useState } from "react";

const SPEEDS = [0.5, 1, 2, 4];

/**
 * Mode Flipbook comparaison (spec §11.5) — un seul controller pour 2 listes.
 *
 * Touche ← / → → avance simultanément les 2 portraits.
 * Total = min(|A|, |B|) : on ne compare que les paires existantes.
 * Si l'une des listes est vide, l'overlay refuse simplement de s'ouvrir.
 */
export function useSplitFlipbook(imagesA, imagesB) {
  const lenA = imagesA?.length || 0;
  const lenB = imagesB?.length || 0;
  const total = Math.min(lenA, lenB);

  const [currentIdx, setCurrentIdx] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [fps, setFps] = useState(2);

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

  useEffect(() => {
    if (!isOpen || !autoPlay || total < 2) return;
    const intervalMs = Math.max(50, 1000 / fps);
    const timer = setInterval(next, intervalMs);
    return () => clearInterval(timer);
  }, [isOpen, autoPlay, fps, next, total]);

  return {
    currentA: imagesA?.[currentIdx] ?? null,
    currentB: imagesB?.[currentIdx] ?? null,
    currentIdx,
    total,
    lenA,
    lenB,
    isOpen,
    open,
    close,
    next,
    prev,
    autoPlay,
    setAutoPlay,
    fps,
    setFps,
    speeds: SPEEDS,
  };
}
