import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Superposition de deux timelines d'activité presse (visualisation de
 * cooccurrence). Placé sous l'EntityTimeline dans le panneau « Infos &
 * activité ». Un picker « + comparer l'activité… » choisit une 2e entité,
 * puis on superpose les deux courbes mensuelles (12 mois) sur le même axe
 * et on affiche le nombre d'articles partagés sur la fenêtre.
 *
 * Choix graphique : la heatmap calendrier d'EntityTimeline ne se superpose
 * pas lisiblement à 2 couleurs → on agrège par mois et on trace deux aires
 * semi-transparentes (entité courante = accent, comparée = bleu acier).
 */
const COLOR_A = "var(--accent)";
const COLOR_B = "#3b82c4";
const W = 640;
const H = 120;
const PAD = 4;

export default function TimelineCompare({ slug }) {
  const [other, setOther] = useState(null); // {slug, name}
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");

  const { data: search } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q),
    enabled: open && q.length >= 2,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["timeline-compare", slug, other?.slug],
    queryFn: () => api.timelineCompare(slug, other.slug),
    enabled: Boolean(other?.slug),
  });

  const chart = useMemo(() => (data ? buildMonthly(data) : null), [data]);

  if (!other) {
    if (!open) {
      return (
        <button
          onClick={() => setOpen(true)}
          className="mt-1 text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent transition-colors"
          title="Superposer l'activité presse d'une autre entité"
        >
          + comparer l'activité…
        </button>
      );
    }
    const results = (search?.results || []).filter((e) => e.slug !== slug);
    return (
      <div className="mt-2 relative">
        <div className="flex items-center gap-2">
          <input
            type="text"
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="entité à superposer…"
            className="px-2 py-1 border divider text-xs font-mono bg-transparent outline-none focus:border-accent w-56"
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
            className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            annuler
          </button>
        </div>
        {results.length > 0 && (
          <ul className="border divider w-72 absolute bg-[var(--bg-primary)] z-10 mt-1">
            {results.slice(0, 6).map((e) => (
              <li key={e.id}>
                <button
                  onClick={() => {
                    setOther({ slug: e.slug, name: e.name });
                    setOpen(false);
                    setQ("");
                  }}
                  className="w-full text-left px-2 py-1 text-sm font-display hover:bg-bg-secondary transition-colors"
                >
                  {e.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <section className="mt-3">
      <div className="flex items-baseline justify-between mb-1">
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="flex items-center gap-1">
            <Swatch color={COLOR_A} /> {shortName(data?.a?.name || slug)}
          </span>
          <span className="flex items-center gap-1">
            <Swatch color={COLOR_B} /> {shortName(other.name)}
          </span>
        </div>
        <button
          onClick={() => setOther(null)}
          className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
        >
          ✕ retirer
        </button>
      </div>

      {isLoading && (
        <div className="text-[10px] font-mono text-[var(--text-secondary)] py-3">
          superposition…
        </div>
      )}

      {chart && (
        <>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            width="100%"
            style={{ height: "auto" }}
            aria-label="Superposition des activités presse"
          >
            <Area points={chart.aPts} color={COLOR_A} />
            <Area points={chart.bPts} color={COLOR_B} />
          </svg>
          <div className="mt-1 flex justify-between text-[10px] font-mono text-[var(--text-secondary)]">
            <span>{chart.firstLabel}</span>
            <span className="text-accent">
              {data.shared_articles} article{data.shared_articles > 1 ? "s" : ""}{" "}
              partagé{data.shared_articles > 1 ? "s" : ""}
            </span>
            <span>{chart.lastLabel}</span>
          </div>
        </>
      )}
    </section>
  );
}

function Swatch({ color }) {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        background: color,
        borderRadius: 1,
        display: "inline-block",
      }}
    />
  );
}

function shortName(name) {
  // "Last, First" → "First Last", tronqué
  const s = name?.includes(",")
    ? name.split(",").map((p) => p.trim()).reverse().join(" ")
    : name || "";
  return s.length > 22 ? s.slice(0, 21) + "…" : s;
}

/**
 * Agrège les deux séries journalières en 12 mois glissants et calcule les
 * points polyligne (aire) pour chacune, sur une échelle Y commune.
 */
function buildMonthly(data) {
  const from = new Date(data.from);
  const to = new Date(data.to);

  const months = [];
  const cursor = new Date(from.getFullYear(), from.getMonth(), 1);
  while (cursor <= to) {
    months.push(
      `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}`,
    );
    cursor.setMonth(cursor.getMonth() + 1);
  }
  const idx = new Map(months.map((m, i) => [m, i]));

  const bucket = (days) => {
    const arr = new Array(months.length).fill(0);
    (days || []).forEach((d) => {
      const key = d.date.slice(0, 7);
      if (idx.has(key)) arr[idx.get(key)] += d.count;
    });
    return arr;
  };
  const aVals = bucket(data.a?.days);
  const bVals = bucket(data.b?.days);
  const max = Math.max(1, ...aVals, ...bVals);

  const toPts = (vals) => {
    const n = vals.length;
    const step = n > 1 ? (W - 2 * PAD) / (n - 1) : 0;
    const inner = vals
      .map((v, i) => {
        const x = PAD + i * step;
        const y = H - PAD - (v / max) * (H - 2 * PAD);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
    // Ferme l'aire vers le bas
    const x0 = PAD;
    const x1 = PAD + (n - 1) * step;
    return `${x0},${H - PAD} ${inner} ${x1},${H - PAD}`;
  };

  const label = (m) => {
    const [y, mo] = m.split("-");
    return `${mo}/${y.slice(2)}`;
  };

  return {
    aPts: toPts(aVals),
    bPts: toPts(bVals),
    firstLabel: months.length ? label(months[0]) : "",
    lastLabel: months.length ? label(months[months.length - 1]) : "",
  };
}

function Area({ points, color }) {
  return (
    <>
      <polygon
        points={points}
        fill={color}
        fillOpacity="0.18"
        stroke="none"
      />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </>
  );
}
