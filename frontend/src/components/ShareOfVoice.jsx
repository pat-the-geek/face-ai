import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

/**
 * Part de présence (share of voice, v030) — page pleine largeur `/tendances`.
 *
 * Classement des entités les plus présentes dans la presse sur une fenêtre
 * glissante (7/30/90 j), avec leur part (% des mentions) et la tendance vs la
 * fenêtre précédente. Barres horizontales façon « media intelligence ».
 */
const WINDOWS = [
  { days: 7, label: "7 jours" },
  { days: 30, label: "30 jours" },
  { days: 90, label: "90 jours" },
];

function Trend({ trend, delta }) {
  if (trend === "new") {
    return <span className="text-accent" title="Nouvelle présence sur la période">✦ nouv.</span>;
  }
  if (trend === "up") {
    return <span className="text-[#2e9e5b]" title={`+${delta}% vs période précédente`}>▲ {delta}%</span>;
  }
  if (trend === "down") {
    return <span className="text-accent" title={`${delta}% vs période précédente`}>▼ {delta}%</span>;
  }
  return <span className="text-[var(--text-secondary)]" title="Stable">→</span>;
}

export default function ShareOfVoice() {
  const [windowDays, setWindowDays] = useState(30);
  const { data, isLoading, error } = useQuery({
    queryKey: ["share-of-voice", windowDays],
    queryFn: () => api.shareOfVoice({ windowDays, limit: 30 }),
  });

  const entities = data?.entities || [];
  const maxShare = entities[0]?.share_pct || 1;

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-baseline justify-between flex-wrap gap-4 mb-2">
          <h1 className="font-display text-4xl">Part de présence</h1>
          <div className="flex items-center gap-1 text-xs font-mono">
            {WINDOWS.map((w) => (
              <button
                key={w.days}
                onClick={() => setWindowDays(w.days)}
                className={`px-3 py-1 border transition-colors uppercase tracking-wider ${
                  windowDays === w.days
                    ? "border-accent text-accent"
                    : "divider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs font-mono text-[var(--text-secondary)] mb-6">
          Articles distincts par personnalité · share of voice ={" "}
          {data ? `${data.total_mentions} mentions` : "…"} sur la fenêtre · tendance vs
          période précédente
        </p>

        {isLoading && (
          <div className="font-mono text-sm text-[var(--text-secondary)]">chargement…</div>
        )}
        {error && (
          <div className="font-mono text-sm text-accent">erreur : {error.message}</div>
        )}
        {!isLoading && !error && entities.length === 0 && (
          <div className="font-mono text-sm text-[var(--text-secondary)]">
            aucune activité presse sur cette fenêtre
          </div>
        )}

        <ol className="space-y-2">
          {entities.map((e, i) => (
            <li key={e.slug} className="flex items-center gap-3">
              <span className="w-6 text-right font-mono text-xs text-[var(--text-secondary)] shrink-0">
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-2">
                  <Link
                    to={`/${e.slug}`}
                    className="font-display text-lg hover:text-accent transition-colors truncate"
                  >
                    {e.is_favorite ? "★ " : ""}
                    {e.name}
                  </Link>
                  <div className="flex items-center gap-3 font-mono text-xs shrink-0">
                    <span className="text-[var(--text-secondary)]">{e.articles} art</span>
                    <span className="tabular-nums">{e.share_pct}%</span>
                    <span className="w-16 text-right">
                      <Trend trend={e.trend} delta={e.delta_pct} />
                    </span>
                  </div>
                </div>
                <div className="mt-1 h-2 bg-bg-secondary border divider overflow-hidden">
                  <div
                    className="h-full bg-accent"
                    style={{ width: `${Math.max(2, (e.share_pct / maxShare) * 100)}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
