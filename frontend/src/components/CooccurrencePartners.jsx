import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

/**
 * Liste compacte des partenaires de cooccurrence éditoriale d'une entité
 * (graphe matérialisé, A5). Affichée dans le panneau « Infos & activité ».
 * Lien cliquable vers chaque partenaire ; compteur = nombre d'articles
 * partagés.
 */
export default function CooccurrencePartners({ slug }) {
  const { data } = useQuery({
    queryKey: ["cooccurrences", slug],
    queryFn: () => api.entityCooccurrences(slug, 10),
    enabled: !!slug,
  });

  const partners = data?.partners || [];
  if (!partners.length) return null;

  return (
    <div className="pt-3 mt-3 border-t divider">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-2">
        ⇄ Partenaires éditoriaux
      </div>
      <div className="flex flex-wrap gap-2">
        {partners.map((p) => (
          <Link
            key={p.slug}
            to={`/${p.slug}`}
            className="px-2 py-1 border divider text-xs hover:border-accent hover:text-accent transition-colors"
            title={`${p.shared_articles} article(s) en commun`}
          >
            {p.is_favorite ? "★ " : ""}
            {p.name}
            <span className="ml-1.5 font-mono text-[10px] text-[var(--text-secondary)]">
              {p.shared_articles}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
