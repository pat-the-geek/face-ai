import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

/**
 * Recherche globale (FTS5 entités + articles + images) avec palette
 * ouverte via `Cmd+K` / `Ctrl+K`. Le bouton dans le header sert de point
 * d'entrée souris ; le raccourci clavier ouvre la même modale partout.
 *
 * Architecture :
 * - Bouton header (always visible) → toggle `open`
 * - Modale plein écran semi-transparente avec input centré
 * - Résultats live (debounce 200 ms) groupés par type
 * - Navigation ↑/↓ pour parcourir, Entrée pour sélectionner, Échap pour fermer
 *
 * Le rendu utilise `dangerouslySetInnerHTML` pour le snippet — celui-ci
 * vient de SQLite FTS5 `snippet()` qui ne produit que `<mark>` / `</mark>`
 * et `…` (échappés par FTS5 côté backend pour le reste). Pas de risque XSS
 * tant que l'API ne sert que notre propre corpus.
 */
export default function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  // Raccourci global Cmd+K / Ctrl+K
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Focus input à l'ouverture
  useEffect(() => {
    if (open) {
      // setTimeout pour laisser le DOM se monter avant focus()
      const id = setTimeout(() => inputRef.current?.focus(), 10);
      return () => clearTimeout(id);
    } else {
      // Reset à la fermeture
      setQuery("");
      setSelectedIdx(0);
    }
  }, [open]);

  // Debounce 200 ms — réseau et FTS sont rapides en LAN, mais ça évite de
  // spammer la DB à chaque frappe sur "physicien quantique".
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(query.trim()), 200);
    return () => clearTimeout(id);
  }, [query]);

  const { data } = useQuery({
    queryKey: ["global-search", debouncedQuery],
    queryFn: () => api.searchGlobal(debouncedQuery, { scope: "all", limit: 8 }),
    enabled: debouncedQuery.length >= 2,
  });

  // Liste plate de tous les résultats pour la nav clavier
  const flat = [
    ...(data?.entities || []).map((e) => ({ kind: "entity", item: e })),
    ...(data?.articles || []).map((a) => ({ kind: "article", item: a })),
    ...(data?.images || []).map((i) => ({ kind: "image", item: i })),
  ];

  // Reset index quand les résultats changent
  useEffect(() => {
    setSelectedIdx(0);
  }, [debouncedQuery]);

  const onActivate = (hit) => {
    if (!hit) return;
    setOpen(false);
    if (hit.kind === "entity") {
      navigate(`/${hit.item.slug}`);
    } else if (hit.kind === "article") {
      if (hit.item.entity_slug) {
        navigate(`/${hit.item.entity_slug}`);
      } else if (hit.item.url) {
        window.open(hit.item.url, "_blank", "noopener,noreferrer");
      }
    } else if (hit.kind === "image" && hit.item.entity_slug) {
      navigate(`/${hit.item.entity_slug}`);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      onActivate(flat[selectedIdx]);
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-2 py-0.5 border divider text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:border-accent hover:text-accent transition-colors"
        title="Recherche globale (Cmd+K)"
      >
        <span>⌕ Rechercher</span>
        <kbd className="text-[9px] opacity-70">⌘K</kbd>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-24"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-2xl mx-4 bg-[var(--bg-primary)] border divider shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="entité, occupation, titre d'article, caption…"
              className="px-4 py-3 bg-transparent border-b divider text-base outline-none placeholder:text-[var(--text-secondary)]"
            />

            <div className="max-h-[60vh] overflow-y-auto">
              {debouncedQuery.length < 2 && (
                <div className="px-4 py-6 text-xs font-mono text-[var(--text-secondary)] text-center">
                  tapez au moins 2 caractères — recherche full-text dans entités,
                  bio Wikipedia, titres d'articles, captions d'images
                </div>
              )}

              {debouncedQuery.length >= 2 && flat.length === 0 && data && (
                <div className="px-4 py-6 text-xs font-mono text-[var(--text-secondary)] text-center">
                  aucun résultat pour "{debouncedQuery}"
                </div>
              )}

              {data?.entities?.length > 0 && (
                <Section title="Entités" total={data.totals.entities}>
                  {data.entities.map((e, i) => {
                    const idx = i;
                    return (
                      <Hit
                        key={`e-${e.slug}`}
                        selected={selectedIdx === idx}
                        onClick={() => onActivate({ kind: "entity", item: e })}
                        onMouseEnter={() => setSelectedIdx(idx)}
                      >
                        <div className="font-display text-base">
                          {e.name}
                        </div>
                        <Snippet html={e.snippet} />
                        <Meta>
                          {e.image_count} img · {e.article_count} articles
                        </Meta>
                      </Hit>
                    );
                  })}
                </Section>
              )}

              {data?.articles?.length > 0 && (
                <Section title="Articles" total={data.totals.articles}>
                  {data.articles.map((a, i) => {
                    const idx = (data.entities?.length || 0) + i;
                    return (
                      <Hit
                        key={`a-${a.article_id}`}
                        selected={selectedIdx === idx}
                        onClick={() => onActivate({ kind: "article", item: a })}
                        onMouseEnter={() => setSelectedIdx(idx)}
                      >
                        <div className="text-sm leading-snug">
                          {a.title || (
                            <span className="italic text-[var(--text-secondary)]">
                              sans titre
                            </span>
                          )}
                        </div>
                        <Snippet html={a.snippet} />
                        <Meta>
                          {a.source_domain || "?"}
                          {a.entity_name && (
                            <>
                              {" · "}
                              <span className="text-[var(--text-primary)]">
                                → {a.entity_name}
                              </span>
                            </>
                          )}
                        </Meta>
                      </Hit>
                    );
                  })}
                </Section>
              )}

              {data?.images?.length > 0 && (
                <Section title="Images" total={data.totals.images}>
                  {data.images.map((img, i) => {
                    const idx =
                      (data.entities?.length || 0) +
                      (data.articles?.length || 0) +
                      i;
                    return (
                      <Hit
                        key={`i-${img.image_id}`}
                        selected={selectedIdx === idx}
                        onClick={() => onActivate({ kind: "image", item: img })}
                        onMouseEnter={() => setSelectedIdx(idx)}
                      >
                        <div className="flex gap-3">
                          {img.aligned_url ? (
                            <img
                              src={img.aligned_url}
                              alt=""
                              className="w-12 h-12 object-cover shrink-0 bg-bg-secondary"
                              loading="lazy"
                            />
                          ) : (
                            <div className="w-12 h-12 bg-bg-secondary shrink-0" />
                          )}
                          <div className="min-w-0 flex-1">
                            <div className="text-sm leading-snug">
                              {img.caption || (
                                <span className="italic text-[var(--text-secondary)]">
                                  sans légende
                                </span>
                              )}
                            </div>
                            <Snippet html={img.snippet} />
                            {img.entity_name && (
                              <Meta>→ {img.entity_name}</Meta>
                            )}
                          </div>
                        </div>
                      </Hit>
                    );
                  })}
                </Section>
              )}
            </div>

            <div className="px-4 py-2 border-t divider text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] flex justify-between">
              <span>↑↓ naviguer · ↵ ouvrir · esc fermer</span>
              <span>FTS5</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Section({ title, total, children }) {
  return (
    <div className="border-b divider last:border-b-0">
      <div className="px-4 py-1.5 text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] bg-bg-secondary flex justify-between">
        <span>{title}</span>
        <span>{total} hit{total > 1 ? "s" : ""}</span>
      </div>
      <ul>{children}</ul>
    </div>
  );
}

function Hit({ selected, onClick, onMouseEnter, children }) {
  return (
    <li
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className={`px-4 py-2 cursor-pointer border-b divider last:border-b-0 ${
        selected ? "bg-bg-secondary" : ""
      }`}
    >
      {children}
    </li>
  );
}

function Snippet({ html }) {
  if (!html) return null;
  return (
    <div
      className="text-xs text-[var(--text-secondary)] leading-snug mt-1 [&_mark]:bg-transparent [&_mark]:text-accent [&_mark]:font-medium"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function Meta({ children }) {
  return (
    <div className="text-[10px] font-mono text-[var(--text-secondary)] mt-1">
      {children}
    </div>
  );
}
