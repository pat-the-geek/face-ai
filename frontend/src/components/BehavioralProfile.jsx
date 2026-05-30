import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

// Définitions affichées dans le bloc dépliable « ⓘ comment lire ce profil ».
const METRIC_HELP = [
  ["Réseau", "Centralité de degré : nombre d'entités distinctes co-citées avec cette personne dans au moins 2 articles."],
  ["Volatilité", "Écart-type ÷ moyenne du nombre d'images par mois. ≥ 0,6 = présence en pics événementiels ; ≤ 0,3 = présence régulière."],
  ["Pic", "Mois le plus actif en nombre d'images."],
  ["Mois actifs", "Nombre de mois distincts comptant au moins une image."],
  ["Attrib. suspectes", "Part d'images flaggées (audit ArcFace > 0,55 au centroïde d'identité, ou signalement manuel). Bas = attribution fiable."],
  ["Sources dominantes", "Les 3 domaines de presse qui couvrent le plus la personne, comptés en images distinctes."],
];

/**
 * Profil comportemental (B4) — signaux dérivés du SEUL corpus FACE.ai/WUDD
 * (aucune source externe) : centralité réseau, volatilité de visibilité, mois
 * de pic, ratio d'attributions suspectes, sources éditoriales dominantes.
 * Affiché dans le panneau « Infos & activité » sous les partenaires.
 */
function Metric({ label, value, title }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex flex-col" title={title}>
      <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]">
        {label}
      </span>
      <span className="text-sm tabular-nums">{value}</span>
    </div>
  );
}

export default function BehavioralProfile({ slug }) {
  const [helpOpen, setHelpOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ["behavioral-profile", slug],
    queryFn: () => api.entityBehavioralProfile(slug),
    enabled: !!slug,
    // 404 possible (entité sans données) → pas de retry agressif.
    retry: false,
  });

  if (!data || data.network_degree === undefined) return null;

  const vol = data.visibility_volatility;
  const volLabel =
    vol == null
      ? null
      : `${vol.toFixed(2)} ${vol >= 0.6 ? "(pics)" : vol <= 0.3 ? "(régulier)" : ""}`.trim();
  const flagged =
    data.flagged_ratio == null
      ? null
      : `${(data.flagged_ratio * 100).toFixed(1)} %`;
  const sources = data.dominant_sources || [];

  return (
    <div className="pt-3 mt-3 border-t divider">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-2 flex items-center gap-2">
        <span>
          ⊚ Profil comportemental
          <span className="ml-1 normal-case opacity-60" title={data.interpretation_note}>
            (corpus seul)
          </span>
        </span>
        <button
          type="button"
          onClick={() => setHelpOpen((v) => !v)}
          className="normal-case hover:text-accent transition-colors"
          title="Comment lire ce profil ?"
          aria-expanded={helpOpen}
        >
          {helpOpen ? "▾" : "▸"} ⓘ
        </button>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <Metric
          label="Réseau"
          value={`${data.network_degree} partenaire${data.network_degree > 1 ? "s" : ""}`}
          title="Centralité de degré : nombre d'entités co-citées dans au moins 2 articles."
        />
        <Metric
          label="Volatilité"
          value={volLabel}
          title="Écart-type / moyenne des images mensuelles. Élevé (≥0.6) = présence en pics événementiels ; bas (≤0.3) = présence régulière."
        />
        <Metric
          label="Pic"
          value={data.peak_month}
          title="Mois le plus actif en nombre d'images."
        />
        <Metric
          label="Mois actifs"
          value={data.active_months}
          title="Nombre de mois distincts avec au moins une image."
        />
        <Metric
          label="Attrib. suspectes"
          value={flagged}
          title="Part d'images flaggées (ArcFace ou humain) — qualité d'attribution."
        />
      </div>
      {sources.length > 0 && (
        <div className="mt-2 text-xs">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mr-2">
            Sources dominantes
          </span>
          {sources.map((s, i) => (
            <span key={s.domain} className="text-[var(--text-secondary)]">
              {i > 0 ? " · " : ""}
              <span className="text-[var(--text-primary)]">{s.domain}</span> ({s.images})
            </span>
          ))}
        </div>
      )}

      {helpOpen && (
        <dl className="mt-3 pt-3 border-t divider text-xs space-y-1.5">
          {METRIC_HELP.map(([term, def]) => (
            <div key={term} className="flex gap-3">
              <dt className="w-32 shrink-0 font-mono text-[10px] uppercase tracking-wider text-[var(--text-secondary)] pt-0.5">
                {term}
              </dt>
              <dd className="flex-1 text-[var(--text-secondary)]">{def}</dd>
            </div>
          ))}
          <div className="flex gap-3 pt-1">
            <dt className="w-32 shrink-0 font-mono text-[10px] uppercase tracking-wider text-[var(--text-secondary)] pt-0.5">
              Corpus seul
            </dt>
            <dd className="flex-1 text-[var(--text-secondary)]">
              Tous ces signaux sont dérivés uniquement du corpus FACE.ai/WUDD —
              aucune source externe, aucun scoring de personnalité.
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}
