import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * Surface UI pour les outils d'admin (workflow d'observabilité, ajouté
 * après l'incident 2026-05-11). Quatre sections en lecture, un bouton
 * d'action pour le backup manuel.
 */
export default function AdminPanel() {
  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto">
      <header className="mb-8">
        <div className="font-display text-4xl">Admin · observabilité</div>
        <p className="mt-2 text-sm text-[var(--text-secondary)] max-w-2xl">
          État du worker, des backups, des conflits de fusion en attente, et de
          l'ingestion WUDD. Tout est en lecture seule sauf le bouton de backup
          manuel.
        </p>
      </header>

      <div className="space-y-10">
        <WorkerSection />
        <MergeConflictsSection />
        <RecheckSection />
        <BackupsSection />
        <WuddSection />
      </div>
    </div>
  );
}

function Section({ title, subtitle, children }) {
  return (
    <section>
      <div className="mb-3 pb-2 border-b divider">
        <div className="font-display text-2xl">{title}</div>
        {subtitle && (
          <p className="mt-1 text-xs text-[var(--text-secondary)]">{subtitle}</p>
        )}
      </div>
      {children}
    </section>
  );
}

function StaleAt({ iso }) {
  if (!iso) return <span className="text-[var(--text-secondary)]">—</span>;
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  const label =
    minutes < 1
      ? "à l'instant"
      : minutes < 60
        ? `il y a ${minutes} min`
        : minutes < 1440
          ? `il y a ${Math.round(minutes / 60)} h`
          : `il y a ${Math.round(minutes / 1440)} j`;
  const stale = minutes > 10;
  return (
    <span
      className={
        stale
          ? "text-accent"
          : "text-[var(--text-secondary)]"
      }
      title={iso}
    >
      {label}
    </span>
  );
}

function WorkerSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["worker-status"],
    queryFn: api.workerStatus,
    refetchInterval: 30_000,
  });

  if (isLoading) return <Section title="Worker · cycles"><Loading /></Section>;
  if (error) return <Section title="Worker · cycles"><ErrorLine err={error} /></Section>;

  const loops = data?.loops || {};
  const events = data?.events_24h || {};
  const db = data?.db || {};

  return (
    <Section
      title="Worker · cycles"
      subtitle="Chaque boucle worker pousse un événement par cycle. Une boucle silencieuse > 10 min apparaît en accent."
    >
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-[var(--text-secondary)] uppercase tracking-wider">
            <th className="text-left py-1">boucle</th>
            <th className="text-right py-1">dernier OK</th>
            <th className="text-right py-1">dernière erreur</th>
            <th className="text-right py-1">OK/24h</th>
            <th className="text-right py-1">err/24h</th>
            <th className="text-right py-1">dernier cycle</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(loops)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([name, info]) => (
              <tr key={name} className="border-t divider">
                <td className="py-1.5">{name}</td>
                <td className="text-right py-1.5">
                  <StaleAt iso={info.last_success_at} />
                </td>
                <td className="text-right py-1.5">
                  {info.last_error_at ? (
                    <span className="text-accent">
                      <StaleAt iso={info.last_error_at} />
                    </span>
                  ) : (
                    <span className="text-[var(--text-secondary)]">—</span>
                  )}
                </td>
                <td className="text-right py-1.5">{info.successes_24h}</td>
                <td className="text-right py-1.5">
                  {info.errors_24h > 0 ? (
                    <span className="text-accent">{info.errors_24h}</span>
                  ) : (
                    info.errors_24h
                  )}
                </td>
                <td className="text-right py-1.5 max-w-xs truncate text-[var(--text-secondary)]">
                  {info.last_summary ? JSON.stringify(info.last_summary) : "—"}
                </td>
              </tr>
            ))}
        </tbody>
      </table>

      <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
        <Stat label="images" value={db.total_images} />
        <Stat
          label="flagged"
          value={db.flagged_images}
          accent={db.flagged_ratio > 0.1}
        />
        <Stat
          label="ratio flagged"
          value={
            db.flagged_ratio !== undefined
              ? (db.flagged_ratio * 100).toFixed(1) + " %"
              : "—"
          }
          accent={db.flagged_ratio > 0.1}
        />
        <Stat
          label="événements 24h"
          value={
            Object.entries(events).length === 0
              ? "—"
              : Object.entries(events)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(" / ")
          }
        />
      </div>
    </Section>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="border divider px-3 py-2">
      <div className="uppercase tracking-wider text-[10px] text-[var(--text-secondary)]">
        {label}
      </div>
      <div
        className={`mt-1 text-sm ${
          accent ? "text-accent" : "text-[var(--text-primary)]"
        }`}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

function MergeConflictsSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["merge-conflicts"],
    queryFn: api.mergeConflicts,
    refetchInterval: 60_000,
  });

  if (isLoading) return <Section title="Fusions · conflits"><Loading /></Section>;
  if (error) return <Section title="Fusions · conflits"><ErrorLine err={error} /></Section>;

  const conflicts = data?.conflicts || [];

  return (
    <Section
      title="Fusions · conflits"
      subtitle="Paires d'entités au même QID que le garde-fou refuse de fusionner. Aucune ligne = aucun conflit en attente."
    >
      {conflicts.length === 0 ? (
        <div className="text-xs font-mono text-[var(--text-secondary)] py-4">
          ✓ aucun conflit
        </div>
      ) : (
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-[var(--text-secondary)] uppercase tracking-wider">
              <th className="text-left py-1">canonical</th>
              <th className="text-left py-1">duplicate</th>
              <th className="text-left py-1">raison du blocage</th>
            </tr>
          </thead>
          <tbody>
            {conflicts.map((c, i) => (
              <tr key={i} className="border-t divider">
                <td className="py-1.5">
                  {c.canonical.slug}
                  <span className="ml-2 text-[var(--text-secondary)]">
                    ({c.canonical.image_count} img)
                  </span>
                </td>
                <td className="py-1.5">
                  {c.duplicate.slug}
                  <span className="ml-2 text-[var(--text-secondary)]">
                    ({c.duplicate.image_count} img)
                  </span>
                </td>
                <td className="py-1.5 text-accent">{c.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function RecheckSection() {
  const queryClient = useQueryClient();
  const [lastSummary, setLastSummary] = useState(null);

  const recheckMut = useMutation({
    mutationFn: (limit) => api.recheckNotPerson(limit),
    onSuccess: (data) => {
      setLastSummary(data);
      queryClient.invalidateQueries({ queryKey: ["worker-status"] });
      queryClient.invalidateQueries({ queryKey: ["letters"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
    },
  });

  return (
    <Section
      title="Rétro-check type=PERSON"
      subtitle="Rétro-applique le garde-fou Wikidata P31 aux entités déjà 'done' enrichies avant v014. Purge ChatGPT, OpenAI, pays, organisations restés taggés PERSON par WUDD."
    >
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <button
          onClick={() => recheckMut.mutate(50)}
          disabled={recheckMut.isPending}
          className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors disabled:opacity-50"
        >
          {recheckMut.isPending ? "recheck 50…" : "↻ Recheck 50"}
        </button>
        <button
          onClick={() => recheckMut.mutate(200)}
          disabled={recheckMut.isPending}
          className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors disabled:opacity-50"
        >
          {recheckMut.isPending ? "recheck 200…" : "↻ Recheck 200"}
        </button>
        <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-secondary)]">
          ~1 s/entité, politesse Wikidata
        </span>
      </div>

      {lastSummary && (
        <div className="border divider px-3 py-2 text-xs font-mono">
          <div className="text-[var(--text-secondary)] uppercase tracking-wider mb-1">
            dernier batch
          </div>
          <div>
            <span className="text-[var(--text-primary)]">{lastSummary.checked}</span>{" "}
            vérifiées ·{" "}
            <span className={lastSummary.purged ? "text-accent" : ""}>
              {lastSummary.purged} purgées
            </span>{" "}
            ·{" "}
            <span className="text-[var(--text-secondary)]">
              {lastSummary.still_person} valides
            </span>
            {lastSummary.errors > 0 && (
              <span className="text-accent ml-2">
                · {lastSummary.errors} erreurs
              </span>
            )}
          </div>
          {(lastSummary.details || []).length > 0 && (
            <ul className="mt-2 space-y-0.5 max-h-40 overflow-y-auto">
              {lastSummary.details.map((d, i) => (
                <li key={i} className="text-[var(--text-secondary)]">
                  · {d}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Section>
  );
}

function BackupsSection() {
  const queryClient = useQueryClient();
  const [confirmingRestore, setConfirmingRestore] = useState(null);
  // Conserve l'info de succès au-delà de la fermeture du dialog —
  // affiche l'avis "restart requis" tant qu'on n'a pas explicitement
  // fermé.
  const [restoreSuccess, setRestoreSuccess] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["backups"],
    queryFn: api.backups,
  });
  const backupMut = useMutation({
    mutationFn: api.backupNow,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["backups"] }),
  });
  const restoreMut = useMutation({
    mutationFn: (filename) => api.restoreBackup(filename),
    onSuccess: (data, filename) => {
      setConfirmingRestore(null);
      setRestoreSuccess({ ...data, filename });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });

  return (
    <Section
      title="Backups SQLite"
      subtitle="Snapshot quotidien automatique avec rotation (7 daily / 4 weekly / 12 monthly)."
    >
      <div className="mb-3">
        <button
          onClick={() => backupMut.mutate()}
          disabled={backupMut.isPending}
          className="px-3 py-1 border divider text-xs font-mono uppercase tracking-wider hover:border-accent hover:text-accent transition-colors disabled:opacity-50"
        >
          {backupMut.isPending ? "snapshot…" : "↻ Backup maintenant"}
        </button>
        {backupMut.isSuccess && (
          <span className="ml-3 text-xs font-mono text-[var(--text-secondary)]">
            ✓ {backupMut.data.created.length} fichier(s) créé(s)
          </span>
        )}
      </div>

      {isLoading ? (
        <Loading />
      ) : error ? (
        <ErrorLine err={error} />
      ) : (
        <div className="grid grid-cols-3 gap-4 text-xs font-mono">
          {["daily", "weekly", "monthly"].map((kind) => (
            <div key={kind} className="border divider px-3 py-2">
              <div className="uppercase tracking-wider text-[10px] text-[var(--text-secondary)] mb-2">
                {kind} ({data?.[kind]?.length || 0})
              </div>
              {(data?.[kind] || []).length === 0 ? (
                <div className="text-[var(--text-secondary)]">—</div>
              ) : (
                <ul className="space-y-0.5">
                  {data[kind].slice(0, 6).map((b) => {
                    const filename = b.path.split("/").pop();
                    return (
                      <li key={b.date} className="flex justify-between gap-2 items-center" title={b.path}>
                        <span>{b.date}</span>
                        <span className="text-[var(--text-secondary)]">
                          {(b.size / 1024 / 1024).toFixed(1)} Mo
                        </span>
                        <button
                          onClick={() => setConfirmingRestore(filename)}
                          className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
                          title="Restaurer ce snapshot"
                        >
                          ↺
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {restoreSuccess && (
        <RestoreSuccessBanner
          info={restoreSuccess}
          onDismiss={() => setRestoreSuccess(null)}
        />
      )}

      {confirmingRestore && (
        <div className="mt-4 border border-accent px-4 py-3 text-xs font-mono">
          <div className="text-accent uppercase tracking-wider mb-2">
            ⚠ Restauration de {confirmingRestore}
          </div>
          <p className="text-[var(--text-primary)] mb-3 leading-snug">
            Le contenu actuel de <code>face_ai.db</code> sera remplacé. Un
            snapshot <code>pre-restore-…</code> de l'état courant est créé
            avant. <strong>Tu devras ensuite redémarrer api + worker
            manuellement</strong> (<code>docker compose restart api worker</code>)
            pour que l'engine SQLAlchemy recharge la nouvelle DB.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => restoreMut.mutate(confirmingRestore)}
              disabled={restoreMut.isPending}
              className="px-3 py-1 border border-accent text-accent uppercase tracking-wider animate-pulse disabled:animate-none"
            >
              {restoreMut.isPending ? "restauration…" : "Confirmer restauration"}
            </button>
            <button
              onClick={() => setConfirmingRestore(null)}
              className="px-3 py-1 text-[var(--text-secondary)] uppercase tracking-wider hover:text-[var(--text-primary)]"
            >
              Annuler
            </button>
          </div>
          {restoreMut.isSuccess && (
            <div className="mt-3 text-[var(--text-primary)]">
              ✓ Restauré. Redémarre maintenant :{" "}
              <code>docker compose restart api worker</code>
            </div>
          )}
          {restoreMut.isError && (
            <div className="mt-3 text-accent">
              erreur : {restoreMut.error?.message}
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

function RestoreSuccessBanner({ info, onDismiss }) {
  // Bannière persistante post-restore : tant que l'admin n'a pas
  // explicitement fermé, on rappelle qu'API + worker doivent être
  // redémarrés pour que l'engine SQLAlchemy recharge la nouvelle DB.
  // Sans ce restart, l'app continue de servir l'ancien état en cache
  // (la DB sur disque est nouvelle, mais SQLAlchemy garde son pool
  // de connexions ouvertes sur l'ancien handle de fichier).
  const cmd = "docker compose restart api worker";
  return (
    <div className="mt-4 border-2 border-accent bg-accent/10 px-4 py-3 text-xs font-mono">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="text-accent uppercase tracking-wider mb-1 text-sm">
            ⚠ Restauration terminée — RESTART REQUIS
          </div>
          <p className="text-[var(--text-primary)] leading-snug">
            <strong>{info.filename}</strong> a été restauré sur{" "}
            <code>face_ai.db</code>.
            <br />
            Snapshot de l'état précédent :{" "}
            <code>{(info.pre_restore_snapshot || "").split("/").pop()}</code>
            {" "}({((info.pre_restore_size || 0) / 1024 / 1024).toFixed(1)} Mo)
          </p>
          <div className="mt-3 px-3 py-2 bg-[var(--bg-primary)] border divider">
            <div className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] mb-1">
              à exécuter dans le terminal du serveur
            </div>
            <code className="block text-[var(--text-primary)]">{cmd}</code>
            <button
              onClick={() => navigator.clipboard?.writeText(cmd)}
              className="mt-1 text-[10px] uppercase tracking-wider text-[var(--text-secondary)] hover:text-accent"
            >
              copier
            </button>
          </div>
          <p className="mt-3 text-[var(--text-secondary)] leading-snug">
            Sans ce redémarrage, l'app continue de servir l'ancien état en
            cache (SQLAlchemy garde son pool de connexions ouvertes sur
            l'ancien handle de fichier). Pour annuler une restauration, le
            snapshot <code>pre-restore-…</code> est restaurable de la même
            façon depuis la liste des backups.
          </p>
        </div>
        <button
          onClick={onDismiss}
          className="text-[var(--text-secondary)] hover:text-accent text-base shrink-0"
          aria-label="Fermer"
        >
          ✕
        </button>
      </div>
    </div>
  );
}


function WuddSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["wudd-status"],
    queryFn: api.wuddStatus,
    refetchInterval: 60_000,
  });

  if (isLoading) return <Section title="WUDD · ingestion"><Loading /></Section>;
  if (error) return <Section title="WUDD · ingestion"><ErrorLine err={error} /></Section>;

  const pct =
    data?.total_entities > 0
      ? Math.round((data.ever_synced / data.total_entities) * 100)
      : 0;

  return (
    <Section
      title="WUDD · ingestion"
      subtitle="Progression du pull batch articles WUDD (favoris d'abord, puis top mentions)."
    >
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono mb-4">
        <Stat label="entités totales" value={data?.total_entities} />
        <Stat
          label="déjà sync"
          value={`${data?.ever_synced} (${pct} %)`}
        />
        <Stat label="jamais sync" value={data?.never_synced} />
        <Stat
          label="favoris à refresh"
          value={data?.favorites_to_refresh}
          accent={data?.favorites_to_refresh > 0}
        />
      </div>

      <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider">
        config : {data?.config?.entities_per_cycle} entités/cycle ·{" "}
        {data?.config?.articles_per_entity} articles/entité ·{" "}
        refresh favoris {data?.config?.favorites_refresh_days} j /{" "}
        autres {data?.config?.refresh_days} j
      </div>
    </Section>
  );
}

function Loading() {
  return <div className="text-xs font-mono text-[var(--text-secondary)] py-2">chargement…</div>;
}

function ErrorLine({ err }) {
  return (
    <div className="text-xs font-mono text-accent py-2">
      erreur : {err.message}
    </div>
  );
}
