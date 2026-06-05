# Catalogue des sources de données — FACE.ai

Inventaire de **toutes** les sources externes consommées par FACE.ai : corpus,
enrichissement, vision, OSINT (v030), carte et veille. Pour le cadre juridique
détaillé de la couche OSINT, voir [COMPLIANCE_OSINT.md](COMPLIANCE_OSINT.md) ;
pour la posture de périmètre, [CLAUDE.md](CLAUDE.md) §1.5.

**Principe directeur** : données **open source** sur des **personnes publiques**
déjà dans le corpus. Aucune inférence, aucune source privée. Les ports applicatifs
sont liés au LAN/Tailscale (`100.72.122.51`), jamais `0.0.0.0`.

## Tableau de synthèse

| # | Source | Type | Auth | Direction | Alimente | Module | Activation |
|---|--------|------|------|-----------|----------|--------|------------|
| 1 | **WUDD.ai** | Corpus amont | — (LAN) | LAN ↔ | `entities`, `articles`, `images` | `wudd_*` | toujours |
| 2 | **Wikidata** | Enrichissement | — | ↗ sortant | bio, QID, géo, pays, attributs | `wikidata.py` | auto (worker) |
| 3 | **Wikipedia** | Résumé/portrait | — | ↗ sortant | `wiki_summary/url/thumbnail` | `wikidata.py` | auto (worker) |
| 4 | **Wikimedia Commons** | Portraits libres | — | ↗ sortant | `images` (`wikimedia_commons`) | `scripts/ingest_wikimedia_commons.py` | manuel/cron |
| 5 | **DuckDuckGo Images** | Portraits (picker) | — | ↗ sortant | `images` (`ddg`) | `ddg_search.py` | opt-in env |
| 6 | **OpenStreetMap (tuiles)** | Fond de carte | — | ↗ navigateur | rendu carte `/carte` | `MapView.jsx` | UI carte |
| 7 | **Ollama (LLM local)** | Synthèse veille | — (local) | local | texte des fiches Discord | `llm.py` | env (repli OK) |
| 8 | **Discord (webhook)** | Notifications | webhook | ↘ **sortant LAN→ext** | — (émission) | `notifications.py` | env |
| 9 | **OpenSanctions** | PEP/sanctions ⚠ | — | ↗ sortant | `sanctions_*` | `scripts/ingest_opensanctions.py` | manuel/cron |
| 10 | **parlament.ch** | Parlement CH | — | ↗ sortant | `parliament_ch_*`, `country_code` | `scripts/ingest_parlament_ch.py` | manuel/cron |
| 11 | **GDELT** | Couverture médias | — | ↗ sortant | `entity_gdelt_coverage` | `scripts/ingest_gdelt.py` | manuel/cron |
| 12 | **Wayback Machine** | Portraits archivés | — | ↗ sortant | `images` (`wayback_machine`), `capture_year` | `scripts/ingest_wayback_portraits.py` | manuel/cron |
| 13 | **GLEIF** | Entités légales | — | ↗ sortant | `gleif_data` | `scripts/ingest_gleif.py` | manuel/cron |
| 14 | **ICIJ Offshore Leaks** | Offshore ⚠ | — | ↗ sortant | `icij_match/detail` | `scripts/ingest_icij.py` | manuel/cron |

⚠ = données RGPD art. 9/10, **consultables en LAN uniquement**, exclues de Discord
et des exports (cf. [COMPLIANCE_OSINT.md](COMPLIANCE_OSINT.md) §3).

---

## Détail par source

### 1. WUDD.ai — corpus amont (source primaire)
- **Rôle** : satellite de WUDD.ai. Fournit les entités `PERSON` (sortie NER) et
  les articles + images déjà extraites.
- **Endpoints** : `GET /api/entities/export?type=PERSON&images=true` (liste +
  1 portrait Wikimedia/entité) ; `GET /api/entities/articles?value=X&type=PERSON&max_articles=N&match_mode=aggregate` (articles + images). Mode **pull** (jamais push).
- **Base** : `WUDD_BASE_URL` (défaut `http://100.72.122.51:5050`). User-Agent `FACE.ai/1.0 (contact@ok-ia.ch)`.
- **Licence/accès** : interne (LAN/Tailscale). **Param de limite = `max_articles`** (pas `limit`).
- **Modules** : `wudd_client.py`, `wudd_sync.py`, `wudd_articles_sync.py`, `wudd_articles_batch.py` (loops worker `wudd_sync_loop`, `wudd_articles_batch_loop`).

### 2. Wikidata — enrichissement factuel
- **Rôle** : QID, bio (P569/P570/P19/P20/P27/P106/P108), géo (P625), pays
  (**P27→P297** code ISO), attributs v027 (P21/P102/P39/P166/P800 + sensibles
  P172/P140/P91/P1050).
- **APIs** : Action API (`wbsearchentities`, `wbgetentities&props=labels`) +
  REST v1 (`entities/items/{qid}/statements`). User-Agent obligatoire.
- **Rate limit** : ~1 req/s, respect `Retry-After`. **Licence CC0**.
- **Module** : `wikidata.py` (`enrich_entity`, backfills `--backfill-coordinates|enrichment|countries`).

### 3. Wikipedia — résumé & vignette
- **API** : REST v1 `page/summary` (chaîne de langues `fr` → `en`).
- **Licence** : texte CC BY-SA. Alimente `wiki_summary`, `wiki_url`, `wiki_thumbnail_url`.
- **Module** : `wikidata.py`.

### 4. Wikimedia Commons — portraits libres (v030, P1B)
- **API** : `commons.wikimedia.org/w/api.php` — `imageinfo` (URL directe) +
  `categorymembers` (catégorie P373). Fichiers via **P18** (image) sur l'item Wikidata.
- **Licence** : libres (CC/PD selon fichier). `source_provider='wikimedia_commons'`.
- **Module** : `scripts/ingest_wikimedia_commons.py`. Idempotent (dédup `source_url` + pHash).

### 5. DuckDuckGo Images — picker manuel (hors-corpus)
- **Lib** : `ddgs` (scrape le JSON privé DDG — **pas d'API officielle**, peut casser).
- **Accès** : **opt-in** `FACE_AI_ENABLE_DDG=true`. Validation manuelle obligatoire,
  aucun stockage avant ingestion explicite. `source_provider='ddg'`.
- **Périmètre** : élargit §1.5 → audit `/audit` renforcé. **Module** : `ddg_search.py`.

### 6. OpenStreetMap — tuiles de carte
- **URL** : `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` (Leaflet, côté navigateur).
- **Licence** : **ODbL** (attribution affichée). Sortie réseau assumée comme Wikimedia.
- **Module** : `frontend/src/components/MapView.jsx` (route `/carte`).

### 7. Ollama — LLM local (synthèse de veille)
- **Rôle** : rédige la synthèse des fiches de notification à partir des **seuls
  faits fournis** (jamais d'attribut sensible). Repli déterministe si injoignable.
- **Accès** : local `:11434`, modèle `OLLAMA_MODEL` (défaut `qwen2.5:7b`), hôte
  `host.docker.internal` en conteneur. **Aucune sortie externe** (inférence locale).
- **Module** : `llm.py`. **Mitige** : aucun envoi de données à un tiers LLM cloud.

### 8. Discord — webhook de notification (sortie hors LAN)
- **Rôle** : émission des alertes de veille (scénarios A–G) + digest hebdo.
- **Accès** : `DISCORD_WEBHOOK_URL` (`.env` gitignored), réutilisé de WUDD.ai.
- **⚠ Frontière LAN** : seule surface **sortante hors LAN** avec du contenu entité.
  N'émet **que** des données factuelles publiques + signaux corpus. **Jamais**
  d'attribut sensible art. 9 (v027) ni OSINT sensible (sanctions/ICIJ). **Module** : `notifications.py`, `synthesis_card.py`.

### 9. OpenSanctions — PEP & sanctions ⚠ (v030, P1A)
- **Données** : statut `sanctioned`/`pep`/`clean`/`unknown` + datasets/topics.
- **Source** : bulk JSON Lines `data.opensanctions.org/datasets/latest/default/entities.ftm.json` (`OPENSANCTIONS_URL`). Matching `rapidfuzz` (seuil `OSINT_FUZZY_THRESHOLD=90`).
- **Licence** : **CC BY-NC 4.0** (non commercial). **RGPD art. 9 + art. 10** (casier).
- **Module** : `scripts/ingest_opensanctions.py`. **LAN uniquement.**

### 10. parlament.ch — Parlement suisse (v030, P1C)
- **API** : OData `ws.parlament.ch/odata.svc` — EntitySet **`MemberCouncil`**
  (⚠ pas `Councillor`), lignes **dupliquées par langue** → filtre `Language eq 'FR' and Active eq true`.
- **Champs** : `PartyName`, `CantonName`, `CouncilName`, `ParlGroupFunctionText`, `PersonNumber`. Pose `is_swiss_parliament_member`, `parliament_ch_data`, repli `country_code='CH'`.
- **Licence** : **Open Government Data** suisse. **Module** : `scripts/ingest_parlament_ch.py`.

### 11. GDELT — couverture médiatique mondiale (v030, P2A)
- **API** : `api.gdeltproject.org/api/v2/doc/doc` — `mode=artlist` (volume + pays)
  + `mode=tonechart` (tonalité). Thèmes = mots-clés des titres (dérivés, non GKG).
- **Rate limit** : **throttle agressif** (429 dès ~1 req/s) → `GDELT_RATE_LIMIT_SECONDS=5`.
- **Stockage** : table `entity_gdelt_coverage` (snapshots horodatés). **Module** : `scripts/ingest_gdelt.py`.

### 12. Wayback Machine — portraits archivés (v030, P2B)
- **API** : CDX `web.archive.org/cdx/search/cdx` (captures 200, `collapse=timestamp:4`) + récupération `web/{ts}id_/{url}`. Politeness `WAYBACK_RATE_LIMIT_SECONDS=2`.
- **Seed** : `wiki_thumbnail_url` de l'entité. `source_provider='wayback_machine'`, `images.capture_year`.
- **Module** : `scripts/ingest_wayback_portraits.py`.

### 13. GLEIF — entités légales (v030, P3A)
- **API** : `api.gleif.org/api/v1/lei-records?filter[entity.legalName]=…`.
- **Limite assumée** : GLEIF est **centré organisation** → la plupart des personnes
  n'ont aucun lien (résultat vide = normal). `gleif_data` JSON. **Module** : `scripts/ingest_gleif.py`.

### 14. ICIJ Offshore Leaks — offshore ⚠ (v030, P3B)
- **Données** : présence dans Panama/Pandora/Bahamas/Offshore Leaks (`icij_match`, `icij_detail`).
- **Source** : mode **CSV recommandé** (export officiel data.icij.org, fiable) ;
  mode API web (`offshoreleaks.icij.org/api/v1`) **best-effort** (pas d'API contractuelle).
- **Sensibilité** : **art. 9/10 + présomption d'innocence** — usage journalistique. **LAN uniquement.**
- **Module** : `scripts/ingest_icij.py`.

---

## Modèles embarqués (pour mémoire — pas des sources de données)
- **InsightFace `buffalo_s`** (RetinaFace + ArcFace MFN, ~120 Mo) : détection +
  identité + genderage. Téléchargé au 1er appel dans `/root/.insightface`. Modules `identity.py`, `face_attributes.py`.
- **MediaPipe** FaceMesh (478 pts) + FaceDetection : alignement, `face_count`, expression. Module `face_processor.py`.

## Directions réseau (synthèse sécurité)
- **Entrant LAN** : WUDD.ai (pull), API/MCP/UI servis sur Tailscale.
- **Sortant (enrichissement, lecture)** : Wikidata, Wikipedia, Wikimedia Commons,
  GDELT, Wayback, GLEIF, ICIJ, OpenSanctions, OSM (navigateur), DDG (opt-in).
- **Sortant (émission de contenu hors LAN)** : **Discord uniquement** — filtré
  (jamais de donnée sensible). Voir [COMPLIANCE_OSINT.md](COMPLIANCE_OSINT.md) §3.
- **Local** : Ollama (aucune sortie externe).

## Licences — récapitulatif
| Source | Licence | Contrainte |
|--------|---------|-----------|
| Wikidata | CC0 | aucune |
| Wikipedia | CC BY-SA | attribution |
| Wikimedia Commons | CC/PD (par fichier) | selon fichier |
| OpenStreetMap | ODbL | attribution (affichée) |
| OpenSanctions | **CC BY-NC** | **non commercial** |
| parlament.ch / GLEIF | Open Data | attribution |
| GDELT / Wayback | ouvert | politeness |
| ICIJ | usage restreint | journalistique, sensible |
| DuckDuckGo | — (scraping) | ToS — opt-in, prudence |

> **Config** : toutes les URLs/seuils/User-Agent sont dans `backend/config.py`
> (préfixes `WUDD_*`, `OSINT_*`, `GDELT_*`, `WAYBACK_*`, `GLEIF_*`, `ICIJ_*`,
> `OPENSANCTIONS_*`, `PARLAMENT_CH_*`, `OLLAMA_*`, `DISCORD_WEBHOOK_URL`,
> `FACE_AI_ENABLE_DDG`). Planification : `backend/scripts/osint_crontab.txt`.
