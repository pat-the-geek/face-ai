import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Bouton « 📚 Biblio » + modale plein écran listant tous les articles du
 * corpus mentionnant l'entité (titre, date, source, lien externe, nb
 * d'images de l'entité). Pagination par tranche.
 *
 * Export Markdown : le backend rend un dossier complet (portrait URL
 * publique + bio factuelle SANS attributs sensibles art. 9 + bibliographie)
 * via GET /entities/{slug}/export.md. On propose deux sorties :
 * - télécharger le .md (lien direct, comme l'export JPG) ;
 * - copier le Markdown dans le presse-papier.
 */
export default function BibliographyButton({ slug }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Bibliographie : tous les articles du corpus mentionnant cette personne"
        className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
      >
        📚 Biblio
      </button>
      {open && <Modal slug={slug} onClose={() => setOpen(false)} />}
    </>
  );
}

const PAGE = 50;

function Modal({ slug, onClose }) {
  const [offset, setOffset] = useState(0);
  const [accum, setAccum] = useState([]);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["entityArticles", slug, offset],
    queryFn: () => api.entityArticles(slug, { limit: PAGE, offset }),
    keepPreviousData: true,
  });

  // Accumule les pages au fur et à mesure (chaque offset arrive une fois).
  useEffect(() => {
    if (data?.articles) {
      setAccum((prev) =>
        offset === 0 ? data.articles : [...prev, ...data.articles],
      );
    }
  }, [data, offset]);

  const total = data?.total ?? 0;
  const hasMore = accum.length < total;

  const copyMarkdown = async () => {
    try {
      const res = await fetch(`/api/entities/${slug}/export.md`);
      const md = await res.text();
      await navigator.clipboard.writeText(md);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard indisponible (http non sécurisé) — l'utilisateur a le lien download */
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-12 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl bg-[var(--bg-primary)] border divider shadow-2xl flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-6 py-4 border-b divider flex items-center justify-between gap-4">
          <div>
            <div className="font-display text-2xl">Bibliographie</div>
            <div className="text-xs font-mono text-[var(--text-secondary)] mt-1">
              {total} article{total > 1 ? "s" : ""} dans le corpus
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={copyMarkdown}
              className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
              title="Copier le dossier Markdown (portrait + bio + bibliographie)"
            >
              {copied ? "✓ copié" : "⧉ Copier .md"}
            </button>
            <a
              href={`/api/entities/${slug}/export.md`}
              download={`${slug}.md`}
              className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
              title="Télécharger le dossier Markdown"
            >
              ⤓ .md
            </a>
            <button
              onClick={onClose}
              className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          {isLoading && accum.length === 0 && (
            <div className="py-12 text-center text-xs font-mono text-[var(--text-secondary)]">
              chargement…
            </div>
          )}
          {error && (
            <div className="py-12 text-center text-xs font-mono text-accent">
              erreur : {error.message}
            </div>
          )}
          {!isLoading && total === 0 && (
            <div className="py-12 text-center text-xs font-mono text-[var(--text-secondary)]">
              aucun article dans le corpus
            </div>
          )}

          <ul className="divide-y divide-[var(--divider-color,rgba(0,0,0,0.1))]">
            {accum.map((a) => (
              <li key={a.id} className="px-6 py-3 flex items-baseline gap-3">
                <span className="font-mono text-[10px] text-[var(--text-secondary)] shrink-0 w-24 tabular-nums">
                  {a.published_at || "—"}
                </span>
                <div className="min-w-0 flex-1">
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm hover:text-accent transition-colors break-words"
                  >
                    {a.title || a.url}
                  </a>
                  <div className="text-[10px] font-mono text-[var(--text-secondary)] mt-0.5">
                    {a.source_domain || "source inconnue"}
                    {a.images > 0 && ` · ${a.images} img`}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <footer className="px-6 py-3 border-t divider flex items-center justify-between text-xs font-mono">
          <span className="text-[var(--text-secondary)]">
            {accum.length} / {total} affichés
          </span>
          {hasMore && (
            <button
              onClick={() => setOffset(accum.length)}
              disabled={isFetching}
              className="px-4 py-1.5 border divider uppercase tracking-wider hover:border-accent hover:text-accent disabled:opacity-40"
            >
              {isFetching ? "chargement…" : "charger plus"}
            </button>
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
