import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Panneau OSINT d'une entité (v030) — affiché dans « Infos & activité ».
 *
 * Ne montre que les sections renseignées (l'API omet les vides). Les sections
 * RGPD art. 9/10 (statut OpenSanctions/PEP, ICIJ Offshore Leaks) sont
 * regroupées sous un libellé « ⚠ Données sensibles (LAN) » et **ne sortent
 * jamais du LAN** (exclues des notifications Discord et des exports). Source :
 * données OPEN SOURCE sur personnes publiques, cf. CLAUDE.md.
 */
function Section({ title, children }) {
  return (
    <div className="mt-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-1.5">
        {title}
      </div>
      {children}
    </div>
  );
}

function SanctionBadge({ status }) {
  const map = {
    sanctioned: { label: "Sanctionné", cls: "bg-accent text-white" },
    pep: { label: "PEP", cls: "border border-accent text-accent" },
  };
  const m = map[status];
  if (!m) return null;
  return (
    <span className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider ${m.cls}`}>
      {m.label}
    </span>
  );
}

/**
 * Niveau de corroboration anti-homonymie (garde-fou OpenSanctions) : le match
 * est-il confirmé par la naissance/le pays, ou seulement par le nom ?
 */
function VerificationTag({ verification }) {
  const map = {
    birthdate: { label: "✓ naissance", cls: "text-[var(--text-secondary)]" },
    country: { label: "✓ pays", cls: "text-[var(--text-secondary)]" },
    unverified: {
      label: "⚠ non vérifié",
      cls: "text-[#b8860b] font-semibold",
      title: "Match par nom non corroboré (ni naissance ni pays) — à auditer.",
    },
  };
  const m = map[verification];
  if (!m) return null;
  return (
    <span
      className={`text-[10px] font-mono ${m.cls}`}
      title={m.title || "Match corroboré par la donnée biographique."}
    >
      {m.label}
    </span>
  );
}

export default function OsintPanel({ slug }) {
  const { data } = useQuery({
    queryKey: ["entity-osint", slug],
    queryFn: () => api.entityOsint(slug),
    enabled: !!slug,
    retry: false,
  });

  if (!data) return null;
  const {
    country,
    media_coverage: mc,
    portrait_history: ph,
    corporate,
    sanctions,
    parliament,
    offshore,
  } = data;

  const hasAny =
    country || mc || ph || corporate || sanctions || parliament || offshore;
  if (!hasAny) return null;

  const sensitive = sanctions || offshore;

  return (
    <div className="pt-3 mt-3 border-t divider">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-1">
        🛰 Veille OSINT (open data)
      </div>

      {country && (
        <div className="mt-2 text-sm">
          <span className="mr-1.5">{country.flag}</span>
          {country.name}
          <span className="ml-2 text-xs font-mono text-[var(--text-secondary)]">
            {country.code}
          </span>
        </div>
      )}

      {parliament && (
        <Section title="🏛 Parlement suisse">
          <div className="text-sm">
            {[parliament.party, parliament.canton, parliament.council]
              .filter(Boolean)
              .join(" · ") || "Membre de l'Assemblée fédérale"}
            {parliament.active === false && (
              <span className="ml-2 text-xs text-[var(--text-secondary)]">
                (mandat inactif)
              </span>
            )}
          </div>
        </Section>
      )}

      {mc && (
        <Section title="🌍 Couverture médiatique mondiale (GDELT)">
          <div className="text-sm flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>{mc.article_count} articles</span>
            {mc.avg_tone != null && (
              <span
                className={mc.avg_tone < 0 ? "text-accent" : "text-[var(--text-secondary)]"}
                title="Tonalité moyenne (négatif = couverture défavorable)"
              >
                ton {mc.avg_tone.toFixed(1)}
              </span>
            )}
            {mc.top_countries?.length > 0 && (
              <span className="text-xs font-mono text-[var(--text-secondary)]">
                {mc.top_countries.slice(0, 4).map((c) => c.country).join(" · ")}
              </span>
            )}
          </div>
          {mc.top_themes?.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {mc.top_themes.slice(0, 8).map((t) => (
                <span
                  key={t.theme}
                  className="px-2 py-0.5 text-[10px] font-mono border divider text-[var(--text-secondary)]"
                >
                  {t.theme}
                </span>
              ))}
            </div>
          )}
        </Section>
      )}

      {ph && (
        <Section title="🕰 Évolution du portrait (Wayback)">
          <div className="flex gap-3 overflow-x-auto pb-1">
            {ph.results.map((p, i) => (
              <div key={i} className="shrink-0 text-center">
                {p.aligned_url ? (
                  <img
                    src={p.aligned_url}
                    alt={String(p.year)}
                    className="w-16 h-16 object-cover border divider"
                  />
                ) : (
                  <div className="w-16 h-16 border divider bg-bg-secondary" />
                )}
                <div className="mt-1 text-[10px] font-mono text-[var(--text-secondary)]">
                  {p.year}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {corporate && (
        <Section title="🏢 Organisations légales (GLEIF)">
          <ul className="space-y-1 text-sm">
            {corporate.results.slice(0, 6).map((c) => (
              <li key={c.lei} className="flex items-baseline gap-2">
                <span>{c.legalName}</span>
                <span className="text-xs font-mono text-[var(--text-secondary)]">
                  {c.lei} {c.country ? `· ${c.country}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {sensitive && (
        <div className="pt-2 mt-3 border-t divider">
          <div
            className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mb-1.5"
            title="Données RGPD art. 9/10 (open data publiques). Consultables en LAN uniquement — jamais envoyées sur Discord ni exportées."
          >
            ⚠ Données sensibles (LAN uniquement)
          </div>

          {sanctions && (
            <div className="mt-1 text-sm flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]">
                OpenSanctions
              </span>
              <SanctionBadge status={sanctions.sanctions_status} />
              <VerificationTag verification={sanctions.verification} />
              {sanctions.topics?.length > 0 && (
                <span className="text-xs font-mono text-[var(--text-secondary)]">
                  {sanctions.topics.join(" · ")}
                </span>
              )}
            </div>
          )}

          {offshore && (
            <div className="mt-2 text-sm">
              <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] mr-2">
                ICIJ Offshore Leaks
              </span>
              <span>{offshore.count} connexion{offshore.count > 1 ? "s" : ""}</span>
              <ul className="mt-1 space-y-0.5 text-xs font-mono text-[var(--text-secondary)]">
                {offshore.results.slice(0, 5).map((o, i) => (
                  <li key={i}>
                    {o.name}
                    {o.dataset ? ` · ${o.dataset}` : ""}
                    {o.jurisdiction ? ` · ${o.jurisdiction}` : ""}
                  </li>
                ))}
              </ul>
              <div className="mt-1 text-[10px] italic text-[var(--text-secondary)]">
                Présence factuelle dans une base publique — ne vaut pas accusation.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
