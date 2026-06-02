# FACE.ai — Roadmap

> Snapshot au 1er juin 2026. Le projet est en **phase post-MVP stable**.
> Pipeline opérationnel : 1067 entités, ~500 images, pull WUDD continu,
> garde-fous en place (anti-fusion, P31, backup, restore). 404 tests
> backend + 34 tests frontend (Vitest/RTL), 29 migrations Alembic. La
> quasi-totalité du ROADMAP initial a été consommée ; v030 ajoute une
> couche **veille** (part de présence, sources, notifications Discord).

---

## ✅ Livré (synthèse)

Plus de 20 chantiers majeurs entre P0 et la session du 12 mai. Pour
mémoire, par grandes catégories :

**Pipeline data**
- Scraper §5.4 (purge silencieuse 4 paliers : download / cv2 /
  MediaPipe + eye_distance / RetinaFace humain)
- Alignement MediaPipe (300×300 JPEG, cache singleton thread-local)
- pHash 64 bits + dedup cosine, score de diversité
- ArcFace 512-dim (buffalo_s) + audit centroïde 3 paliers
- Enrichissement Wikidata (QID + summary + bio) avec garde-fou P31
- Auto-merge par QID + **garde-fou anti-fusion catastrophique**
  (incident 2026-05-11 résolu)
- **Fusion par centroïde ArcFace** (homonymes Wikidata, durcie avec
  `MIN_IMAGES=5` et `AUTO_DISTANCE=0.20`)

**Intégration WUDD**
- Pull entités PERSON (`wudd_sync_loop`, 30 min)
- Pull articles batch prioritisé (favoris → top mentions → refresh
  30j, ~120 entités/jour)
- Bouton `↧ Collecter` manuel par entité
- **Bouton `🦆 DDG`** picker manuel hors corpus (gated `FACE_AI_ENABLE_DDG`)

**UI**
- Galerie alphabétique avec **tri par prénom** (toggle ↕)
- **Pagination UI progressive** (200 puis +200 via IntersectionObserver)
- **Heatmap timeline d'entité** + drill-down clic → filtre date galerie
- **Mode dark** toggle ☀/🌙 indépendant
- LandmarkOverlay touche L (3 points actuellement — yeux + nez)
- Flipbook + Flipbook comparé synchronisé + Composite Galton via
  crossfade 800ms
- Audit P9 avec filtre `source_provider` (wudd / ddg / manual)
- Bouton ✓ Confirmer pour sortir une image d'audit
- DdgPicker modale avec grille de candidats

**Opérationnel**
- **Backup auto quotidien** + rotation 7/4/12 + UI restore avec
  bannière "RESTART REQUIS"
- **Observabilité worker** (`worker_events`, `/admin/worker-status`,
  `/metrics` Prometheus)
- **AdminPanel UI** unifié (worker / merge-conflicts / backups /
  recheck-not-person / wudd-status)
- ErrorBoundary global, FontScaler, sort persisté en localStorage
- 13 endpoints `/admin/*`

**MCP**
- 7 outils MCP (search, profile, images, compare, timeline, stats,
  visibility_pattern)
- **3 ressources** (`face://stats`, `face://entities`, `face://entity/{slug}`)
- **3 prompts** (portrait_editorial, media_comparison, visibility_anomaly_report)

**Doc & API** (session 12 mai)
- **COMPLIANCE.md** RGPD/nLPD : registre traitements, base légale
  intérêt légitime (test 3 étapes), DPIA, droits personnes,
  incident 2026-05-11 documenté
- Endpoints `GET /articles` (filtres source/date/entity_slug + pagination)
  et `GET /articles/{id}` (détail entités+images)
- Suite test frontend Vitest + RTL + jsdom : 34 tests sur hooks
  (useSortMode, useColorMode) et composants (DeferredImg, ColorModeToggle,
  EntityTimeline, FaceCard)
- **Composite Galton interactif** : sélection multi-FaceCard (toggle
  ●/◯ par carte) + bouton header "Galton (N)" + sous-ensemble passé
  au composite. Les 2 modes (auto 1/N et gradué) et l'export PNG
  existaient déjà.

**Veille v030** (session 1er juin)
- **Part de présence (share of voice)** : `presence.compute_share_of_voice`
  — classement par articles distincts sur fenêtre glissante + part (%)
  + tendance (`up`/`down`/`flat`/`new`) vs période précédente. API
  `GET /corpus/share-of-voice`, page UI `/tendances` (`ShareOfVoice`),
  tool MCP `get_share_of_voice`.
- **Cartographie des sources par entité** : `presence.entity_sources`
  — ventilation complète par agence (`photo_agency`) + domaine de
  presse. API `GET /entities/{slug}/sources`, composant
  `SourcesBreakdown`, tool MCP `get_entity_sources`.
- **Flipbook chronologique** : toggle `⏱ Chrono` (`useFlipbook` tri par
  date d'article, préserve l'image courante au basculement).
- **Notifications Discord (veille proactive)** : `notifications.py` +
  worker `notify_loop` (10 min). 4 scénarios (pic de visibilité, photo
  inhabituelle flaggée ArcFace, nouvelle personne, palier corpus /50).
  Fiche typographiée jointe (`synthesis_card.py`) : portrait + landmarks,
  synthèse **IA locale Ollama** (`llm.py`, repli déterministe), repères
  factuels, corpus & médias, heatmap. Dédup `worker_events` + palier
  persistant `data/notify_state.json`. Endpoints `/admin/notify-test`,
  `/admin/notify-run`. **Synthèse limitée aux données factuelles
  publiques** (art. 9 exclu de la diffusion hors LAN).
- **Infra** : `.dockerignore` (le contexte tarait `data/static/models`
  + course sur le journal SQLite) ; env Discord/Ollama dans
  `docker-compose.prod.yml`.

**v031** (session 2 juin) — bump **v1.0.0**.
- **Cleanup entités orphelines** (manuel) : `entity_cleanup.cleanup_orphan_entities`
  purge les entités `not_found` Wikidata + 0 image après `CLEANUP_ORPHAN_AFTER_DAYS`
  (30 j). Endpoint `POST /admin/cleanup-orphans?dry_run=` + section AdminPanel
  (prévisualiser → confirmer). Suppression complète (pas de tombstone).
- **Digest Discord hebdomadaire** : `notifications.send_weekly_digest` /
  `maybe_send_digest` (dérivé de `compute_share_of_voice`, synthèse Ollama
  optionnelle), worker `digest_loop` (check horaire, créneau `NOTIFY_DIGEST_DAY/HOUR`,
  dédup semaine ISO via `notify_state.json`). Endpoint `POST /admin/digest-test`
  + bouton AdminPanel. Opt-in `FACE_AI_NOTIFY_DIGEST_ENABLED`.
- **Superposition de 2 timelines** : `GET /entities/{slug}/timeline-compare?other=`
  (2 séries jour + articles partagés fenêtrés). Composant `TimelineCompare`
  (courbes mensuelles bi-couleur) sous l'EntityTimeline du panneau Infos & activité.
- **Bibliographie par entité** : `bibliography.py` — `GET /entities/{slug}/articles`
  (liste paginée) + `GET /entities/{slug}/export.md` (**dossier Markdown** : portrait
  URL publique + bio factuelle **sans art. 9** + bibliographie avec citations).
  Bouton `📚 Biblio` → modale plein écran + copier/télécharger le .md.
- **Incident isolation tests** : un `import` métier top-level dans un test a wipe la
  DB prod (restaurée depuis backup). Garde-fous ajoutés dans `conftest.py`
  (env au niveau module + `_assert_test_db`). Cf. CLAUDE.md.

---

## 🎯 Court terme — soldé (session 1er juin)

Audit de l'existant : les 3 items « court terme » étaient en fait
déjà livrés ou faits dans cette session. Détail :

| Item | État |
|---|---|
| LandmarkOverlay **468 points MediaPipe** | ✅ **Déjà livré v024**. Colonne `face_analysis.landmarks_blob`, extraction inline dans `process_image`, endpoint `GET /images/{id}/landmarks`, backfill `POST /admin/backfill-landmarks`, rendu mesh + FACE_OVAL dans `LandmarkOverlay`. Couverture **99,4 %** (1524/1533) ; les 9 restants ne re-détectent pas de mesh sur l'aligné (pose/qualité extrêmes) → fallback 3 points propre. *L'item ROADMAP était périmé.* |
| Mode dark cohérent dans le Flipbook | ✅ **Déjà fait**. Le Flipbook a été migré aux tokens `--immersive-*` (`tokens.css`), plus de hex hardcodé dans le JSX. Palette **volontairement toujours sombre** (choix de design CLAUDE.md, pas un bug) → ne suit pas le toggle light/dark par conception. Docstring `useColorMode` corrigé. |
| Drill batch dans `/audit` | ✅ **Livré cette session**. Sélection multi-images (cases + « tout sélectionner ») + barre sticky « ✓ Confirmer la sélection (N) ». Endpoint `POST /images/confirm-batch` (tolérant : `not_found`/`already_manual`, dédup, 1 commit). 5 tests. |

---

## 🔭 Restant — moyen terme (différé)

| Item | Seuil de déclenchement |
|---|---|
| **Migration PostgreSQL** | > 100k images (snapshot mai 2026 : 500) — plan en place dans [MIGRATION_POSTGRES.md](MIGRATION_POSTGRES.md), ~6-7h le jour J |
| **Refonte layout shell** pour vraie virtualization | UX dégradée sur "Tous" — actuellement pagination UI progressive en remplacement |
| **Resync Wikidata cron hebdo** | ⚠ **BLOQUÉ** tant que la cause racine de l'incident 2026-05-11 (QID corrompu) n'est pas identifiée |

---

## 🔍 Investigation toujours ouverte

**Incident 2026-05-11** — QID `Q7407093` (Altman) attribué par erreur à
Musk / Zuckerberg / McCartney → fusion catastrophique. Restauration
faite, garde-fou anti-fusion en place. **Cause racine non identifiée**
(logs Wikidata enrichment perdus au redémarrage). Conséquence : les
garde-fous bloquent désormais le résultat catastrophique, donc plus
d'urgence, mais le bug d'enrichissement sous-jacent peut toujours se
représenter.

Si on observe à nouveau un cas (`merge_blocked` qui ressort dans
`/admin/worker-status`), lancer immédiatement `docker compose logs
worker --since 30m` pour capturer la trace.

---

## 🌐 Améliorations UX possibles (non urgentes)

| Item | Effort | Valeur |
|---|---|---|
| ~~`entity_cleanup` purge des `not_found`~~ | — | ✅ **livré v031** (manuel) |
| ~~Superposer 2 timelines pour visualiser cooccurrences~~ | — | ✅ **livré v031** (`TimelineCompare`) |
| Sync clavier entre 2 Flipbook individuels en split-screen (∼ ROADMAP horizon moyen, en partie résolu par SplitFlipbookOverlay) | ~1h | confort split-screen |
| Cleanup orphelines **auto** (loop worker) — actuellement manuel | ~30 min | si le bruit `not_found` s'accumule |

---

## 🌌 Horizon long (à mesure que le projet mûrit)

Liste minimale, à reconsulter si le contexte du projet change :

- ~~Notification active~~ — **livré v030** côté FACE.ai (veille Discord
  proactive sur le corpus). Reste éventuellement un canal *push amont*
  depuis WUDD (changelog / webhook), qui dépend de WUDD côté amont.
- Métriques exposées dans une vraie dashboard (Grafana consommant `/metrics`)
- ~~Bibliographie automatique par entité (liste des articles + citations)~~ — **livré v031** (bouton `📚 Biblio` + export Markdown)
- Multi-utilisateurs (RGPD + auth — explicitement hors périmètre v1, cf. CLAUDE.md)

---

## ⚖️ Recommandation actuelle

Le projet est dans un bon état pour **vivre 2-4 semaines en usage
réel** avant nouveau chantier. Les frictions UX identifiées par
l'usage valent plus qu'un nouveau item ajouté maintenant.

Les 3 items « court terme » historiques sont soldés (cf. section
dédiée plus haut). Si tu veux quand même bouger, les prochains candidats
sont dans **🌐 Améliorations UX** et les **extensions v030** :

1. **entity_cleanup auto** (~30 min) — purge des `not_found` après N jours,
   hygiène DB.
2. **Digest périodique Discord** — résumé hebdo dérivé de `share_of_voice`
   en complément des alertes unitaires v030.
3. **Heatmap : superposer 2 timelines** (~2h) — visualiser une cooccurrence.

Le reste peut attendre. La vraie priorité reste **laisser tourner la
veille v030 quelques jours et ajuster les seuils selon le bruit réel.**
