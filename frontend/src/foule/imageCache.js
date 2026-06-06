/**
 * Cache LRU de bitmaps décodés pour la « Foule ».
 *
 * À 3000+ carrés, on ne peut pas garder tous les visages décodés en mémoire.
 * Ce cache borne l'empreinte (octets) et évince les bitmaps les moins
 * récemment utilisés. Les bitmaps sont décodés/downscalés à la taille réelle
 * de la cellule (bucket), donc une même URL peut exister sous plusieurs tailles
 * pendant la vie d'un carré (grand au début, minuscule à pleine grille).
 *
 * Le décodeur est injectable pour les tests (mock de `createImageBitmap`).
 */

const RESIZE_QUALITY = "medium";

async function defaultDecoder(url, targetPx) {
  const resp = await fetch(url, { mode: "cors" });
  if (!resp.ok) throw new Error(`fetch ${url} → ${resp.status}`);
  const blob = await resp.blob();
  return createImageBitmap(blob, {
    resizeWidth: targetPx,
    resizeHeight: targetPx,
    resizeQuality: RESIZE_QUALITY,
  });
}

/** Clé de cache : une URL à une taille cible donnée. */
export function bitmapKey(url, targetPx) {
  return `${url}@${targetPx}`;
}

/**
 * Buckets de taille de décodage (px CSS × DPR déjà appliqué côté appelant).
 * Évite de re-décoder à chaque pixel de variation de cellule : on arrondit au
 * bucket supérieur. Réduit drastiquement le nombre de variantes décodées.
 */
export function sizeBucket(targetPx) {
  if (targetPx <= 96) return 96;
  if (targetPx <= 192) return 192;
  if (targetPx <= 384) return 384;
  return 512;
}

export function createBitmapCache({
  maxBytes = 180 * 1024 * 1024,
  decoder = defaultDecoder,
} = {}) {
  // Map en ordre d'insertion = ordre LRU. get() ré-insère pour marquer récent.
  const map = new Map(); // key -> { bitmap, bytes }
  const inflight = new Map(); // key -> Promise
  let bytes = 0;

  function evict() {
    while (bytes > maxBytes && map.size > 0) {
      const oldest = map.keys().next().value;
      const entry = map.get(oldest);
      map.delete(oldest);
      bytes -= entry.bytes;
      entry.bitmap.close?.();
    }
  }

  function touch(key, entry) {
    map.delete(key);
    map.set(key, entry);
  }

  return {
    /** Bitmap déjà en cache, ou null. Marque comme récemment utilisé. */
    getSync(key) {
      const entry = map.get(key);
      if (!entry) return null;
      touch(key, entry);
      return entry.bitmap;
    },

    /** Charge (ou retourne) le bitmap. Déduplique les requêtes concurrentes. */
    async load(key, url, targetPx) {
      const entry = map.get(key);
      if (entry) {
        touch(key, entry);
        return entry.bitmap;
      }
      if (inflight.has(key)) return inflight.get(key);
      const p = Promise.resolve(decoder(url, targetPx))
        .then((bitmap) => {
          inflight.delete(key);
          const w = bitmap.width || targetPx;
          const h = bitmap.height || targetPx;
          const b = w * h * 4;
          map.set(key, { bitmap, bytes: b });
          bytes += b;
          evict();
          return bitmap;
        })
        .catch((err) => {
          inflight.delete(key);
          throw err;
        });
      inflight.set(key, p);
      return p;
    },

    get size() {
      return map.size;
    },
    get bytes() {
      return bytes;
    },
    clear() {
      for (const e of map.values()) e.bitmap.close?.();
      map.clear();
      inflight.clear();
      bytes = 0;
    },
  };
}
