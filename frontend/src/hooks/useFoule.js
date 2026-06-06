import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { computeGrid, cellRect, sameLayout } from "../foule/gridLayout";
import { createBitmapCache, bitmapKey, sizeBucket } from "../foule/imageCache";
import { diagonalOrder, pulseDue, easeInOut, rgbaIndex } from "../foule/effects";
import {
  SPEEDS,
  TARGET_FRAME_MS,
  MAX_SWAP_RATE,
  desiredSwapRate,
  governorStep,
  roundRobinIndices,
} from "../foule/scheduler";

const PAGE_LIMIT = 500;
const LOOKAHEAD = 40;
const PRELOAD_WINDOW = 12;
const FETCH_CONCURRENCY = 4;
const MAX_SWAPS_PER_FRAME = 24;
const MAX_DPR = 2;
const UI_SYNC_MS = 250;
const SKIP_GUARD = 64;

// Effets
const TRAIL_MS = 380; // durée du fondu par cellule (trainées spectrales)
const PULSE_MS = 800; // fondu Galton synchronisé
const PULSE_INTERVAL_MS = 9000; // période de la pulsation
const MAX_PULSE_CELLS = 1200; // borne anti-pic CPU de la pulsation
const MOSAIC_ALPHA = 0.5; // intensité de la teinte mosaïque

const BG = "#080808";

const DEFAULT_EFFECTS = { wave: false, trails: false, pulse: false, mosaic: false };

/**
 * Moteur de la « Foule » (cf. plan iridescent-beaming-cloud).
 *
 * Grille qui se subdivise d'un carré par personne (activité décroissante),
 * chaque carré faisant défiler les photos alignées. Rendu canvas unique,
 * repeinture des seules cellules sales, gouverneur adaptatif (CPU), et ajout
 * différé anti carré-noir (une cellule n'apparaît que photo 1 décodée).
 *
 * Quatre effets visuels superposables :
 *  - **onde** : les swaps balaient la grille en front diagonal (réordonnancement).
 *  - **trainées** : chaque changement de photo est un fondu par cellule.
 *  - **pulsation Galton** : fondu synchronisé de toute la foule, périodique.
 *  - **mosaïque** : les tuiles sont teintées pour composer le portrait de la
 *    personne la plus active — grille passée en **plein cadre** (sans bord noir).
 */
export function useFoule({ canvasRef }) {
  const [fps, setFps] = useState(4);
  const [paused, setPaused] = useState(false);
  const [effects, setEffects] = useState(DEFAULT_EFFECTS);
  const [ui, setUi] = useState({
    shown: 0,
    total: 0,
    loadingMore: true,
    swapRate: 0,
    throttled: false,
    ready: false,
  });

  const fpsRef = useRef(fps);
  const pausedRef = useRef(paused);
  const effectsRef = useRef(effects);
  useEffect(() => {
    fpsRef.current = fps;
  }, [fps]);
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);
  useEffect(() => {
    effectsRef.current = effects;
  }, [effects]);

  // Candidats
  const peopleRef = useRef([]);
  const urlsRef = useRef([]);
  const fetchingRef = useRef(new Set());
  const allPeopleLoadedRef = useRef(false);
  const scanRef = useRef(0);

  // Cellules affichées
  const personOfRef = useRef([]);
  const imgIdxRef = useRef([]);
  const lastBmRef = useRef([]);
  const shownRef = useRef(0);

  // Rendu
  const gridRef = useRef(null);
  const zoneRef = useRef({ w: 0, h: 0, dpr: 1 });
  const dirtyRef = useRef(new Set());
  const fullRepaintRef = useRef(true);

  // Onde
  const waveRef = useRef(null); // ordre diagonal des cellules
  const waveColsRef = useRef(0);
  const waveRowsRef = useRef(0);

  // Fondus par cellule (trainées + pulsation) : c → {from,to,t0,dur}
  const animRef = useRef(new Map());
  const lastPulseRef = useRef(0);

  // Mosaïque
  const targetImgRef = useRef(null);
  const mosaicCanvasRef = useRef(null);
  const mosaicRef = useRef(null); // {data, cols, rows}

  const cursorRef = useRef(0);
  const governedRef = useRef(MAX_SWAP_RATE);
  const growthAccRef = useRef(0);
  const swapAccRef = useRef(0);
  const lastTsRef = useRef(0);
  const avgWorkRef = useRef(0);
  const avgDtRef = useRef(TARGET_FRAME_MS);
  const baseDtRef = useRef(TARGET_FRAME_MS);
  const lastUiSyncRef = useRef(0);

  const cacheRef = useRef(null);
  const rafRef = useRef(0);
  const aliveRef = useRef(true);

  // ---- Données -----------------------------------------------------------

  const ensureImages = useCallback((p) => {
    if (p < 0 || p >= peopleRef.current.length) return;
    if (urlsRef.current[p] !== undefined) return;
    if (fetchingRef.current.has(p)) return;
    if (fetchingRef.current.size >= FETCH_CONCURRENCY) return;
    fetchingRef.current.add(p);
    const person = peopleRef.current[p];
    api
      .entityImages(person.slug)
      .then((data) => {
        urlsRef.current[p] = (data.images || [])
          .map((im) => im.aligned_url)
          .filter(Boolean);
      })
      .catch(() => {
        urlsRef.current[p] = [];
      })
      .finally(() => {
        fetchingRef.current.delete(p);
      });
  }, []);

  const prospective = useCallback((nCells) => {
    const { w, h, dpr } = zoneRef.current;
    const grid = computeGrid(nCells, w, h, { fill: effectsRef.current.mosaic });
    const bucket = sizeBucket(Math.ceil(Math.max(grid.cellW, grid.cellH) * dpr));
    return { grid, bucket };
  }, []);

  const preloadFirst = useCallback((p, bucket) => {
    const urls = urlsRef.current[p];
    if (!urls || urls.length === 0) return;
    const url = urls[0];
    const key = bitmapKey(url, bucket);
    if (cacheRef.current.getSync(key)) return;
    cacheRef.current.load(key, url, bucket).catch(() => {
      const arr = urlsRef.current[p];
      if (arr && arr.length) urlsRef.current[p] = arr.filter((u) => u !== url);
    });
  }, []);

  const readiness = useCallback(
    (p) => {
      const urls = urlsRef.current[p];
      if (urls === undefined) {
        ensureImages(p);
        return "wait";
      }
      if (urls.length === 0) return "skip";
      const { bucket } = prospective(shownRef.current + 1);
      if (cacheRef.current.getSync(bitmapKey(urls[0], bucket))) return "ready";
      preloadFirst(p, bucket);
      return "wait";
    },
    [ensureImages, prospective, preloadFirst],
  );

  const pumpImages = useCallback(() => {
    const start = scanRef.current;
    const end = Math.min(peopleRef.current.length, start + LOOKAHEAD);
    const { bucket } = prospective(shownRef.current + 1);
    for (let p = start; p < end; p++) {
      const urls = urlsRef.current[p];
      if (urls === undefined) {
        ensureImages(p);
        continue;
      }
      if (urls.length === 0) continue;
      if (p < start + PRELOAD_WINDOW) preloadFirst(p, bucket);
    }
    // Précharge l'image cible de la mosaïque (la personne la plus active).
    if (!targetImgRef.current && urlsRef.current[0] && urlsRef.current[0].length) {
      const img = new Image();
      img.onload = () => resampleMosaic();
      img.src = urlsRef.current[0][0];
      targetImgRef.current = img;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ensureImages, prospective, preloadFirst]);

  const loadPeoplePages = useCallback(async () => {
    let offset = 0;
    while (aliveRef.current) {
      let data;
      try {
        data = await api.entities({ sortBy: "activity", limit: PAGE_LIMIT, offset });
      } catch {
        break;
      }
      const batch = (data.entities || []).filter((e) => e.image_count > 0);
      for (const e of batch) {
        peopleRef.current.push({ slug: e.slug, name: e.name });
        urlsRef.current.push(undefined);
      }
      const got = data.entities?.length || 0;
      offset += got;
      if (got < PAGE_LIMIT || offset >= (data.total || 0)) break;
    }
    allPeopleLoadedRef.current = true;
  }, []);

  // ---- Mosaïque : échantillonnage de la couleur cible par cellule --------

  const resampleMosaic = useCallback(() => {
    const img = targetImgRef.current;
    const grid = gridRef.current;
    if (!img || !img.complete || !img.naturalWidth) return;
    if (!grid || grid.cols <= 0) return;
    const cols = grid.cols;
    const rows = grid.rows;
    let cnv = mosaicCanvasRef.current;
    if (!cnv) {
      cnv = document.createElement("canvas");
      mosaicCanvasRef.current = cnv;
    }
    cnv.width = cols;
    cnv.height = rows;
    const cx = cnv.getContext("2d");
    try {
      cx.drawImage(img, 0, 0, cols, rows);
      mosaicRef.current = {
        data: cx.getImageData(0, 0, cols, rows).data,
        cols,
        rows,
      };
    } catch {
      mosaicRef.current = null;
    }
  }, []);

  const applyMosaic = useCallback((ctx, rect, c) => {
    if (!effectsRef.current.mosaic) return;
    const m = mosaicRef.current;
    const grid = gridRef.current;
    if (!m || !grid || m.cols !== grid.cols) return;
    const col = c % grid.cols;
    const row = Math.floor(c / grid.cols);
    const i = rgbaIndex(col, row, m.cols);
    const d = m.data;
    ctx.fillStyle = `rgba(${d[i]},${d[i + 1]},${d[i + 2]},${MOSAIC_ALPHA})`;
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  }, []);

  // ---- Peinture ----------------------------------------------------------

  const fillRect = useCallback((ctx, rect, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  }, []);

  const drawBitmap = useCallback((ctx, rect, bm) => {
    try {
      ctx.drawImage(bm, rect.x, rect.y, rect.w, rect.h);
      return true;
    } catch {
      return false;
    }
  }, []);

  const paintCell = useCallback(
    (ctx, c) => {
      const grid = gridRef.current;
      if (!grid || grid.cellW <= 0) return;
      const rect = cellRect(c, grid);
      const p = personOfRef.current[c];
      const urls = urlsRef.current[p];
      const url = urls && urls.length ? urls[imgIdxRef.current[c]] : null;
      if (!url) {
        const fb = lastBmRef.current[c];
        if (!(fb && drawBitmap(ctx, rect, fb))) fillRect(ctx, rect, BG);
        applyMosaic(ctx, rect, c);
        return;
      }
      const { dpr } = zoneRef.current;
      const targetPx = sizeBucket(Math.ceil(Math.max(rect.w, rect.h) * dpr));
      const key = bitmapKey(url, targetPx);
      const cache = cacheRef.current;
      const exact = cache.getSync(key);
      const bm = exact || lastBmRef.current[c];
      if (!(bm && drawBitmap(ctx, rect, bm))) fillRect(ctx, rect, BG);
      if (exact) lastBmRef.current[c] = exact;
      applyMosaic(ctx, rect, c);
      if (!exact) {
        cache
          .load(key, url, targetPx)
          .then((b) => {
            lastBmRef.current[c] = b;
            if (c < shownRef.current) dirtyRef.current.add(c);
          })
          .catch(() => {});
      }
    },
    [fillRect, drawBitmap, applyMosaic],
  );

  // Peinture d'une cellule en cours de fondu (trainées / pulsation).
  const paintAnim = useCallback(
    (ctx, c, a, now) => {
      const grid = gridRef.current;
      if (!grid || grid.cellW <= 0) return true;
      const rect = cellRect(c, grid);
      const prog = easeInOut((now - a.t0) / a.dur);
      fillRect(ctx, rect, BG);
      if (a.from) {
        ctx.globalAlpha = 1 - prog;
        drawBitmap(ctx, rect, a.from);
      }
      ctx.globalAlpha = prog;
      if (a.to) drawBitmap(ctx, rect, a.to);
      ctx.globalAlpha = 1;
      applyMosaic(ctx, rect, c);
      if (prog >= 1) {
        lastBmRef.current[c] = a.to;
        return true; // terminé
      }
      return false;
    },
    [fillRect, drawBitmap, applyMosaic],
  );

  const repaint = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { w, h } = zoneRef.current;
    if (fullRepaintRef.current) {
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, w, h);
      for (let c = 0; c < shownRef.current; c++) paintCell(ctx, c);
      fullRepaintRef.current = false;
      dirtyRef.current.clear();
    } else if (dirtyRef.current.size) {
      for (const c of dirtyRef.current) paintCell(ctx, c);
      dirtyRef.current.clear();
    }
    // Fondus en cours (par-dessus la peinture dure).
    const anims = animRef.current;
    if (anims.size) {
      const now = performance.now();
      for (const [c, a] of anims) {
        if (c >= shownRef.current) {
          anims.delete(c);
          continue;
        }
        if (paintAnim(ctx, c, a, now)) anims.delete(c);
      }
    }
  }, [canvasRef, paintCell, paintAnim]);

  // ---- Onde --------------------------------------------------------------

  const ensureWaveOrder = useCallback(() => {
    const grid = gridRef.current;
    if (!grid) return;
    if (
      !waveRef.current ||
      waveColsRef.current !== grid.cols ||
      waveRowsRef.current !== grid.rows ||
      waveRef.current.length !== shownRef.current
    ) {
      waveRef.current = diagonalOrder(grid.cols, grid.rows, shownRef.current);
      waveColsRef.current = grid.cols;
      waveRowsRef.current = grid.rows;
    }
  }, []);

  // ---- Ajout de cellule --------------------------------------------------

  const addCellIfReady = useCallback(() => {
    let guard = 0;
    while (scanRef.current < peopleRef.current.length && guard < SKIP_GUARD) {
      guard++;
      const p = scanRef.current;
      const st = readiness(p);
      if (st === "skip") {
        scanRef.current += 1;
        continue;
      }
      if (st === "wait") return "wait";
      const c = personOfRef.current.length;
      const { grid, bucket } = prospective(c + 1);
      personOfRef.current.push(p);
      imgIdxRef.current.push(0);
      lastBmRef.current.push(
        cacheRef.current.getSync(bitmapKey(urlsRef.current[p][0], bucket)) || null,
      );
      scanRef.current += 1;
      shownRef.current = personOfRef.current.length;
      const changed = !sameLayout(grid, gridRef.current);
      gridRef.current = grid;
      if (changed) {
        fullRepaintRef.current = true;
        waveRef.current = null; // forcer reconstruction de l'onde
        if (effectsRef.current.mosaic) resampleMosaic();
      } else {
        dirtyRef.current.add(c);
        if (waveRef.current) waveRef.current.push(c);
      }
      return "added";
    }
    if (scanRef.current >= peopleRef.current.length && allPeopleLoadedRef.current)
      return "exhausted";
    return "wait";
  }, [readiness, prospective, resampleMosaic]);

  // ---- Swap d'une photo --------------------------------------------------

  const commitSwap = useCallback((c, next, toBm) => {
    imgIdxRef.current[c] = next;
    const from = lastBmRef.current[c];
    if (effectsRef.current.trails && from && from !== toBm) {
      animRef.current.set(c, { from, to: toBm, t0: performance.now(), dur: TRAIL_MS });
    } else {
      lastBmRef.current[c] = toBm;
      dirtyRef.current.add(c);
    }
  }, []);

  const swapCell = useCallback(
    (c) => {
      const p = personOfRef.current[c];
      const urls = urlsRef.current[p];
      if (!urls || urls.length < 2) return;
      const grid = gridRef.current;
      if (!grid || grid.cellW <= 0) return;
      const next = (imgIdxRef.current[c] + 1) % urls.length;
      const url = urls[next];
      const { dpr } = zoneRef.current;
      const rect = cellRect(c, grid);
      const targetPx = sizeBucket(Math.ceil(Math.max(rect.w, rect.h) * dpr));
      const key = bitmapKey(url, targetPx);
      const cache = cacheRef.current;
      const ready = cache.getSync(key);
      if (ready) {
        commitSwap(c, next, ready);
      } else {
        cache
          .load(key, url, targetPx)
          .then((b) => {
            if (c < shownRef.current) commitSwap(c, next, b);
          })
          .catch(() => {});
      }
    },
    [commitSwap],
  );

  // ---- Pulsation Galton (fondu synchronisé périodique) -------------------

  const triggerPulse = useCallback(() => {
    const shown = shownRef.current;
    const grid = gridRef.current;
    if (!grid || shown < 2) return;
    const { dpr } = zoneRef.current;
    const now = performance.now();
    const limit = Math.min(shown, MAX_PULSE_CELLS);
    for (let c = 0; c < limit; c++) {
      const p = personOfRef.current[c];
      const urls = urlsRef.current[p];
      if (!urls || urls.length < 2) continue;
      const next = (imgIdxRef.current[c] + 1) % urls.length;
      const rect = cellRect(c, grid);
      const targetPx = sizeBucket(Math.ceil(Math.max(rect.w, rect.h) * dpr));
      const toBm = cacheRef.current.getSync(bitmapKey(urls[next], targetPx));
      if (!toBm) continue; // pas de décodage forcé (anti rafale)
      imgIdxRef.current[c] = next;
      const from = lastBmRef.current[c];
      if (from && from !== toBm) {
        animRef.current.set(c, { from, to: toBm, t0: now, dur: PULSE_MS });
      } else {
        lastBmRef.current[c] = toBm;
        dirtyRef.current.add(c);
      }
    }
  }, []);

  // ---- Boucle rAF --------------------------------------------------------

  const frame = useCallback(
    (ts) => {
      if (!aliveRef.current) return;
      if (pausedRef.current) {
        lastTsRef.current = ts;
        rafRef.current = requestAnimationFrame(frame);
        return;
      }
      const prev = lastTsRef.current || ts;
      let dt = ts - prev;
      lastTsRef.current = ts;
      if (dt > 100) dt = 100;
      if (dt <= 0) {
        rafRef.current = requestAnimationFrame(frame);
        return;
      }

      avgDtRef.current = avgDtRef.current * 0.9 + dt * 0.1;
      baseDtRef.current = Math.min(baseDtRef.current, Math.max(8, avgDtRef.current));
      const fpsNow = fpsRef.current;
      const fx = effectsRef.current;

      const t0 = performance.now();

      // Croissance
      growthAccRef.current += (fpsNow * dt) / 1000;
      if (growthAccRef.current >= 1) {
        const res = addCellIfReady();
        if (res === "added") growthAccRef.current -= 1;
        else if (res === "exhausted") growthAccRef.current = 0;
        else growthAccRef.current = Math.min(growthAccRef.current, 1);
      }

      // Pulsation Galton
      if (fx.pulse && shownRef.current > 1) {
        if (!lastPulseRef.current) lastPulseRef.current = ts;
        else if (pulseDue(ts, lastPulseRef.current, PULSE_INTERVAL_MS)) {
          lastPulseRef.current = ts;
          triggerPulse();
        }
      }

      // Swaps (onde diagonale si activée)
      const desired = desiredSwapRate(fpsNow, shownRef.current);
      const effective = Math.min(desired, governedRef.current);
      swapAccRef.current += (effective * dt) / 1000;
      let swaps = Math.min(MAX_SWAPS_PER_FRAME, Math.floor(swapAccRef.current));
      if (swaps > 0 && shownRef.current > 0) {
        swapAccRef.current -= swaps;
        const { indices, cursor } = roundRobinIndices(
          cursorRef.current,
          swaps,
          shownRef.current,
        );
        cursorRef.current = cursor;
        if (fx.wave) {
          ensureWaveOrder();
          const order = waveRef.current;
          for (const k of indices) swapCell(order && k < order.length ? order[k] : k);
        } else {
          for (const k of indices) swapCell(k);
        }
      } else {
        swapAccRef.current -= Math.floor(swapAccRef.current);
      }

      repaint();

      const workMs = performance.now() - t0;
      avgWorkRef.current = avgWorkRef.current * 0.8 + workMs * 0.2;
      const jankWork = avgWorkRef.current / 6;
      const jankFrame = avgDtRef.current / (baseDtRef.current * 1.6);
      const jank = Math.max(jankWork, jankFrame);
      governedRef.current = governorStep(governedRef.current, { jankRatio: jank });

      if (ts - lastUiSyncRef.current > UI_SYNC_MS) {
        lastUiSyncRef.current = ts;
        setUi({
          shown: shownRef.current,
          total: peopleRef.current.length,
          loadingMore: !allPeopleLoadedRef.current,
          swapRate: Math.round(Math.min(desired, governedRef.current)),
          throttled: desired > governedRef.current + 0.5,
          ready: shownRef.current > 0,
        });
      }

      rafRef.current = requestAnimationFrame(frame);
    },
    [addCellIfReady, triggerPulse, ensureWaveOrder, swapCell, repaint],
  );

  // ---- Cycle de vie ------------------------------------------------------

  const resize = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w <= 0 || h <= 0) return;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    zoneRef.current = { w, h, dpr };
    if (shownRef.current > 0) {
      gridRef.current = computeGrid(shownRef.current, w, h, {
        fill: effectsRef.current.mosaic,
      });
    }
    waveRef.current = null;
    if (effectsRef.current.mosaic) resampleMosaic();
    fullRepaintRef.current = true;
  }, [canvasRef, resampleMosaic]);

  useEffect(() => {
    aliveRef.current = true;
    cacheRef.current = createBitmapCache();
    resize();
    loadPeoplePages();
    const pump = setInterval(pumpImages, 150);
    rafRef.current = requestAnimationFrame(frame);
    const ro = new ResizeObserver(resize);
    if (canvasRef.current) ro.observe(canvasRef.current);
    window.addEventListener("resize", resize);
    return () => {
      aliveRef.current = false;
      cancelAnimationFrame(rafRef.current);
      clearInterval(pump);
      ro.disconnect();
      window.removeEventListener("resize", resize);
      cacheRef.current?.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reprise après pause → on finalise les fondus et on repeint tout.
  useEffect(() => {
    if (!paused) {
      for (const [c, a] of animRef.current) {
        if (c < shownRef.current && a.to) lastBmRef.current[c] = a.to;
      }
      animRef.current.clear();
      fullRepaintRef.current = true;
    }
  }, [paused]);

  // Bascule mosaïque → la grille change de mode (plein cadre ↔ carré).
  useEffect(() => {
    const { w, h } = zoneRef.current;
    if (shownRef.current > 0 && w > 0) {
      gridRef.current = computeGrid(shownRef.current, w, h, {
        fill: effects.mosaic,
      });
    }
    waveRef.current = null;
    animRef.current.clear();
    if (effects.mosaic) resampleMosaic();
    fullRepaintRef.current = true;
  }, [effects.mosaic, resampleMosaic]);

  const togglePause = useCallback(() => setPaused((pp) => !pp), []);
  const toggleEffect = useCallback(
    (k) => setEffects((e) => ({ ...e, [k]: !e[k] })),
    [],
  );

  return {
    fps,
    setFps,
    speeds: SPEEDS,
    paused,
    togglePause,
    effects,
    toggleEffect,
    shown: ui.shown,
    total: ui.total,
    loadingMore: ui.loadingMore,
    swapRate: ui.swapRate,
    throttled: ui.throttled,
    ready: ui.ready,
  };
}
