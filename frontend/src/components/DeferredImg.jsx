import { useEffect, useState } from "react";

/**
 * Image avec lazy load via IntersectionObserver.
 *
 * Le `loading="lazy"` natif charge l'image quand le navigateur estime
 * qu'elle est proche du viewport — utile, mais le node `<img>` est
 * quand même créé immédiatement, ce qui pèse à 847 rows. Ici on ne crée
 * le `<img>` qu'une fois l'élément observé comme proche du viewport
 * (rootMargin 200px). Avant ça, on rend un simple `<div>` placeholder
 * de la même taille — quasi-gratuit.
 *
 * Après le premier `intersecting`, on garde l'image montée même si elle
 * sort du viewport (pour ne pas la re-charger en allers-retours).
 */
export default function DeferredImg({
  src,
  alt = "",
  className = "",
  fallback = null,
  rootMargin = "200px",
}) {
  const [el, setEl] = useState(null);
  const [shown, setShown] = useState(false);
  // Bascule à `true` si l'image plante (404, CORS, format) — on
  // affiche alors le fallback à la place du carré cassé natif
  // (point ouvert spec §19 "placeholder image manquante").
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    if (!el || shown) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [el, shown, rootMargin]);

  // Reset l'erreur si la src change (nouvelle image potentiellement valide)
  useEffect(() => {
    setErrored(false);
  }, [src]);

  return (
    <div ref={setEl} className={className}>
      {shown && !errored ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="w-full h-full object-cover"
          onError={() => setErrored(true)}
        />
      ) : (
        fallback
      )}
    </div>
  );
}
