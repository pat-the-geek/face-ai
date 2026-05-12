import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Heatmap calendrier-style (inspirée GitHub contributions) — densité
 * d'articles par jour sur 365 jours glissants.
 *
 * Grille SVG : 53 colonnes (semaines) × 7 lignes (jours dimanche → samedi).
 * Couleur graduée selon `count` rapporté à `max_count` de la fenêtre :
 * 5 paliers en niveaux de var(--accent).
 *
 * Pic visible = événement médiatique de la personne (sortie, scandale,
 * actualité). Tooltip natif au survol affiche `date · N article(s)`.
 */
const CELL_SIZE = 11;
const CELL_GAP = 2;

export default function EntityTimeline({ slug, selectedDate, onSelectDate }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["entity-timeline", slug],
    queryFn: () => api.entityTimeline(slug),
    enabled: Boolean(slug),
  });

  const grid = useMemo(() => buildGrid(data), [data]);

  if (isLoading) {
    return (
      <div className="text-xs font-mono text-[var(--text-secondary)] py-2">
        timeline…
      </div>
    );
  }
  if (error || !data || !grid) return null;
  if (data.total_articles === 0) {
    return (
      <div className="text-xs font-mono text-[var(--text-secondary)] py-2">
        pas d'article daté sur les 365 derniers jours
      </div>
    );
  }

  const totalWidth = grid.weeks.length * (CELL_SIZE + CELL_GAP);
  const totalHeight = 7 * (CELL_SIZE + CELL_GAP);
  const maxCount = data.max_count || 1;

  return (
    <section className="my-6">
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)]">
          activité presse · 365 derniers jours
        </div>
        <div className="text-[10px] font-mono text-[var(--text-secondary)]">
          {data.total_articles} article{data.total_articles > 1 ? "s" : ""} ·
          {" "}{data.total_days} jour{data.total_days > 1 ? "s" : ""} ·
          {" "}pic {data.max_count}
        </div>
      </div>
      <svg
        viewBox={`0 0 ${totalWidth} ${totalHeight}`}
        width="100%"
        style={{ maxWidth: totalWidth, height: "auto" }}
        aria-label={`Timeline ${slug}`}
      >
        {grid.weeks.map((week, wi) =>
          week.map((cell, di) => {
            if (!cell) return null;
            const x = wi * (CELL_SIZE + CELL_GAP);
            const y = di * (CELL_SIZE + CELL_GAP);
            const intensity = cell.count / maxCount; // 0..1
            const isSelected = selectedDate === cell.date;
            const clickable = cell.count > 0 && onSelectDate;
            return (
              <rect
                key={`${wi}-${di}`}
                x={x}
                y={y}
                width={CELL_SIZE}
                height={CELL_SIZE}
                fill={fillForIntensity(intensity, cell.count > 0)}
                rx="1"
                style={{
                  cursor: clickable ? "pointer" : "default",
                  stroke: isSelected ? "var(--accent)" : "transparent",
                  strokeWidth: isSelected ? 1.5 : 0,
                }}
                onClick={
                  clickable
                    ? () =>
                        onSelectDate(
                          // Toggle : si déjà sélectionné, désélectionne.
                          isSelected ? null : cell.date,
                        )
                    : undefined
                }
              >
                <title>
                  {cell.date} · {cell.count} article{cell.count > 1 ? "s" : ""}
                  {clickable ? " · clic pour filtrer la galerie" : ""}
                </title>
              </rect>
            );
          }),
        )}
      </svg>
      <div className="mt-2 flex items-center gap-1 text-[10px] font-mono text-[var(--text-secondary)]">
        <span>faible</span>
        {[0.0, 0.25, 0.5, 0.75, 1.0].map((i, idx) => (
          <span
            key={idx}
            style={{
              width: CELL_SIZE,
              height: CELL_SIZE,
              background: fillForIntensity(i, i > 0),
              borderRadius: "1px",
              display: "inline-block",
            }}
          />
        ))}
        <span>pic</span>
      </div>
    </section>
  );
}

/**
 * Construit une grille [semaine][jour] sur 365 jours glissants
 * (lundi → dimanche ISO). Cellules sans data → `null`, cellules
 * avec data → `{ date, count }`.
 */
function buildGrid(data) {
  if (!data) return null;
  const from = new Date(data.from);
  const to = new Date(data.to);

  // Index par date ISO pour lookup O(1)
  const counts = new Map();
  (data.days || []).forEach((d) => counts.set(d.date, d.count));

  // Aligner sur le lundi précédent `from` pour démarrer la 1re colonne
  // (ISO week-start = lundi). `getDay()` : 0=dim, 1=lun, …, 6=sam.
  const start = new Date(from);
  const dayOfWeek = (start.getDay() + 6) % 7; // lundi=0
  start.setDate(start.getDate() - dayOfWeek);

  const weeks = [];
  let cursor = new Date(start);
  const endStamp = to.getTime();

  while (cursor.getTime() <= endStamp + 6 * 86400000) {
    const week = [];
    for (let d = 0; d < 7; d++) {
      const iso = cursor.toISOString().slice(0, 10);
      const inRange = cursor >= from && cursor <= to;
      week.push(
        inRange
          ? { date: iso, count: counts.get(iso) || 0 }
          : null,
      );
      cursor = new Date(cursor.getTime() + 86400000);
    }
    weeks.push(week);
  }
  return { weeks };
}

function fillForIntensity(i, hasActivity) {
  if (!hasActivity) return "var(--bg-secondary)";
  // 5 paliers : 0.2 / 0.4 / 0.6 / 0.8 / 1.0 d'opacité de var(--accent)
  // sur le fond. On utilise rgba pour pas devoir résoudre var.
  // Lecture du couleur accent : on bake juste l'opacité.
  const opacity = Math.max(0.18, Math.min(1, i));
  return `rgb(200 16 46 / ${opacity})`; // --accent = #c8102e
}
