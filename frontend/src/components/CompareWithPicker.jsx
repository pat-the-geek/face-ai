import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

/**
 * Picker pour démarrer une comparaison côte-à-côte (spec §11.5).
 *
 * Bouton compact 1-state qui révèle un input search au clic.
 * À la sélection d'une entité cible, navigue vers `/compare/:slugA/:slugB`.
 */
export default function CompareWithPicker({ currentSlug }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q),
    enabled: open && q.length >= 2,
  });

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors"
        title="Comparer cette entité avec une autre côte-à-côte"
      >
        ⊞ Comparer à…
      </button>
    );
  }

  const results = (data?.results || []).filter((e) => e.slug !== currentSlug);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="entité à comparer…"
          className="px-2 py-1 border divider text-xs font-mono bg-transparent outline-none focus:border-accent w-64"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              setQ("");
            }
          }}
        />
        <button
          onClick={() => {
            setOpen(false);
            setQ("");
          }}
          className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          annuler
        </button>
      </div>
      {results.length > 0 && (
        <ul className="border divider w-80 absolute bg-[var(--bg-primary)] z-10 mt-8">
          {results.slice(0, 6).map((e) => (
            <li key={e.id}>
              <button
                onClick={() => {
                  navigate(`/compare/${currentSlug}/${e.slug}`);
                }}
                className="w-full text-left px-2 py-1 text-sm font-display hover:bg-bg-secondary transition-colors flex justify-between items-baseline"
              >
                <span>{e.name}</span>
                <span className="text-xs font-mono text-[var(--text-secondary)]">
                  {e.unique_image_count} img
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
