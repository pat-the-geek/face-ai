import { describe, expect, it, vi } from "vitest";
import { createBitmapCache, bitmapKey, sizeBucket } from "./imageCache";

// Faux bitmap : taille fixe → octets prévisibles (w*h*4).
function fakeBitmap(px) {
  return { width: px, height: px, close: vi.fn() };
}

describe("bitmapKey / sizeBucket", () => {
  it("clé = url@taille", () => {
    expect(bitmapKey("http://x/a.jpg", 96)).toBe("http://x/a.jpg@96");
  });
  it("arrondit au bucket supérieur", () => {
    expect(sizeBucket(40)).toBe(96);
    expect(sizeBucket(96)).toBe(96);
    expect(sizeBucket(150)).toBe(192);
    expect(sizeBucket(300)).toBe(384);
    expect(sizeBucket(999)).toBe(512);
  });
});

describe("createBitmapCache", () => {
  it("charge puis sert depuis le cache (1 seul décodage)", async () => {
    const decoder = vi.fn(async (_url, px) => fakeBitmap(px));
    const cache = createBitmapCache({ decoder, maxBytes: 10 * 1024 * 1024 });
    const k = bitmapKey("a", 96);
    const bm = await cache.load(k, "a", 96);
    expect(bm.width).toBe(96);
    expect(cache.getSync(k)).toBe(bm);
    await cache.load(k, "a", 96);
    expect(decoder).toHaveBeenCalledTimes(1);
  });

  it("déduplique les requêtes concurrentes", async () => {
    const decoder = vi.fn(
      (_url, px) => new Promise((r) => setTimeout(() => r(fakeBitmap(px)), 5)),
    );
    const cache = createBitmapCache({ decoder });
    const k = bitmapKey("a", 96);
    const [a, b] = await Promise.all([
      cache.load(k, "a", 96),
      cache.load(k, "a", 96),
    ]);
    expect(a).toBe(b);
    expect(decoder).toHaveBeenCalledTimes(1);
  });

  it("évince les entrées les moins récentes au-delà du budget", async () => {
    const px = 100; // 100*100*4 = 40 000 octets / entrée
    const decoder = async (_u, p) => fakeBitmap(p);
    const cache = createBitmapCache({ decoder, maxBytes: 100_000 }); // ~2 entrées
    const b0 = await cache.load(bitmapKey("u0", px), "u0", px);
    await cache.load(bitmapKey("u1", px), "u1", px);
    await cache.load(bitmapKey("u2", px), "u2", px); // dépasse → évince u0
    expect(cache.getSync(bitmapKey("u0", px))).toBeNull();
    expect(cache.getSync(bitmapKey("u1", px))).not.toBeNull();
    expect(cache.getSync(bitmapKey("u2", px))).not.toBeNull();
    expect(b0.close).toHaveBeenCalled(); // bitmap évincé libéré
  });

  it("getSync rafraîchit la récence (protège de l'éviction)", async () => {
    const px = 100;
    const decoder = async (_u, p) => fakeBitmap(p);
    const cache = createBitmapCache({ decoder, maxBytes: 100_000 });
    await cache.load(bitmapKey("u0", px), "u0", px);
    await cache.load(bitmapKey("u1", px), "u1", px);
    cache.getSync(bitmapKey("u0", px)); // u0 redevient le plus récent
    await cache.load(bitmapKey("u2", px), "u2", px); // évince le plus ancien = u1
    expect(cache.getSync(bitmapKey("u0", px))).not.toBeNull();
    expect(cache.getSync(bitmapKey("u1", px))).toBeNull();
  });

  it("clear ferme tout et remet à zéro", async () => {
    const cache = createBitmapCache({ decoder: async (_u, p) => fakeBitmap(p) });
    await cache.load(bitmapKey("a", 96), "a", 96);
    cache.clear();
    expect(cache.size).toBe(0);
    expect(cache.bytes).toBe(0);
  });
});
