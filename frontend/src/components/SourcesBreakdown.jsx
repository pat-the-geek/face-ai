import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Cartographie des sources d'une entité (v030) — ventilation des images par
 * agence photo et par domaine de presse. Affichée dans le panneau « Infos &
 * activité » sous le profil comportemental. Barres horizontales.
 */
function Bars({ title, rows, keyName, total }) {
  if (!rows?.length) return null;
  const max = rows[0].count || 1;
  return (
    <div className="mt-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-1.5">
        {title}
      </div>
      <div className="space-y-1">
        {rows.slice(0, 8).map((r) => (
          <div key={r[keyName]} className="flex items-center gap-2 text-xs">
            <span className="w-40 shrink-0 truncate" title={r[keyName]}>
              {r[keyName]}
            </span>
            <div className="flex-1 h-2 bg-bg-secondary border divider overflow-hidden">
              <div
                className="h-full bg-accent"
                style={{ width: `${Math.max(3, (r.count / max) * 100)}%` }}
              />
            </div>
            <span className="w-20 text-right font-mono text-[var(--text-secondary)] tabular-nums shrink-0">
              {r.count} · {r.pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SourcesBreakdown({ slug }) {
  const { data } = useQuery({
    queryKey: ["entity-sources", slug],
    queryFn: () => api.entitySources(slug),
    enabled: !!slug,
    retry: false,
  });

  if (!data || !data.total_images) return null;

  return (
    <div className="pt-3 mt-3 border-t divider">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-1">
        🗞 Sources & agences
        <span className="ml-2 normal-case opacity-60">
          {data.credited_images}/{data.total_images} images créditées
        </span>
      </div>
      <Bars title="Agences photo" rows={data.agencies} keyName="agency" total={data.total_images} />
      <Bars title="Domaines de presse" rows={data.domains} keyName="domain" total={data.total_images} />
    </div>
  );
}
