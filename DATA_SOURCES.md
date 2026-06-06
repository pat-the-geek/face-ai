# Catalogue des sources de données — FACE.ai

Inventaire de **toutes** les sources externes consommées par FACE.ai : corpus,
enrichissement, vision, OSINT, carte et veille. Pour le cadre juridique détaillé
de la couche OSINT, voir [COMPLIANCE_OSINT.md](COMPLIANCE_OSINT.md) ; pour la
posture de périmètre, [CLAUDE.md](CLAUDE.md) §1.5.

**Principe directeur** : données **open source** sur des **personnes publiques**
déjà dans le corpus. Aucune inférence, aucune source privée. Les ports
applicatifs sont liés au LAN/Tailscale (`100.72.122.51`), jamais `0.0.0.0`.

> **Note historique (v031, 2026-06-06)** : trois sources OSINT ont été
> **supprimées** après état des lieux car non viables — **GLEIF** (centrée
> organisation, 0 résultat sur des personnes), **ICIJ Offshore Leaks** (API web
> morte, 0 résultat) et **Wayback** (0 capture). Voir le journal de décision.

## Tableau de synthèse (11 sources)

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

⚠ = données RGPD art. 9/10 (statut OpenSanctions/PEP), **consultables en LAN
uniquement**, exclues de Discord et des exports (cf.
[COMPLIANCE_OSINT.md](COMPLIANCE_OSINT.md) §3).

---

## Détail par source

### 1. WUDD.ai — corpus amont (source primaire)
- **Rôle** : satellite de WUDD.ai. Fournit les entités `PERSON` (sortie NER) et
  les articles + images déjà extraites.
- **Endpoints** : `GET /api/entities/export?type=PERSON&images=true` ;
  `GET /api/entities/articles?value=X&type=PERSON&max_articles=N&match_mode=aggregate`. Mode **pull** (jamais push).
- **Base** : `WUDD_BASE_URL` (défaut `http://100.72.122.51:5050`). User-Agent `FACE.ai/1.0 (contact@ok-ia.ch)`. **Param de limite = `max_articles`**.
- **Modules** : `wudd_client.py`, `wudd_sync.py`, `wudd_articles_sync.py`, `wudd_articles_batch.py`.

### 2. Wikidata — enrichissement factuel
- **Rôle** : QID, bio (P569/P570/P19/P20/P27/P106/P108), géo (P625), pays
  (**P27→P297** code ISO), attributs v027 (P21/P102/P39/P166/P800 + sensibles
  P172/P140/P91/P1050).
- **APIs** : Action API (`wbsearchentities`, `wbgetentities&props=labels`) + REST v1 (`statements`). User-Agent obligatoire. ~1 req/s, `Retry-After`. **Licence CC0**.
- **Module** : `wikidata.py` (backfills `--backfill-coordinates|enrichment|countries`).

### 3. Wikipedia — résumé & vignette
- **API** : REST v1 `page/summary` (langues `fr`→`en`). **Licence CC BY-SA**.
  Alimente `wiki_summary`, `wiki_url`, `wiki_thumbnail_url`. **Module** : `wikidata.py`.

### 4. Wikimedia Commons — portraits libres (P1B)
- **API** : `commons.wikimedia.org/w/api.php` — `imageinfo` + `categorymembers` (P373) ; fichiers via **P18**. Licences libres (CC/PD). `source_provider='wikimedia_commons'`.
- **Module** : `scripts/ingest_wikimedia_commons.py`. Idempotent (dédup `source_url` + pHash).

### 5. DuckDuckGo Images — picker manuel (hors-corpus)
- **Lib** : `ddgs` (scrape le JSON privé DDG — **pas d'API officielle**). **Opt-in** `FACE_AI_ENABLE_DDG=true`, validation manuelle. `source_provider='ddg'`. **Module** : `ddg_search.py`.

### 6. OpenStreetMap — tuiles de carte
- **URL** : `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` (Leaflet, navigateur). **Licence ODbL**. **Module** : `frontend/src/components/MapView.jsx`.

### 7. Ollama — LLM local (synthèse de veille)
- **Rôle** : rédige la synthèse des fiches de notification à partir des **seuls
  faits fournis**. Repli déterministe si injoignable. Local `:11434`, `OLLAMA_MODEL` (défaut `qwen2.5:7b`). **Aucune sortie externe**. **Module** : `llm.py`.

### 8. Discord — webhook de notification (sortie hors LAN)
- **Rôle** : alertes de veille (scénarios A–G) + digest hebdo. `DISCORD_WEBHOOK_URL` (`.env`).
- **⚠ Frontière LAN** : seule surface **sortante hors LAN** avec du contenu entité. N'émet **que** des données factuelles publiques + signaux corpus — **jamais** d'attribut sensible art. 9 (v027) ni le statut OpenSanctions. **Modules** : `notifications.py`, `synthesis_card.py`.

### 9. OpenSanctions — PEP & sanctions ⚠ (P1A)
- **Données** : statut `sanctioned`/`pep`/`clean`/`unknown` + datasets/topics + `verification`.
- **Source** : bulk JSON Lines `data.opensanctions.org/.../default/entities.ftm.json` (~3 GB, `OPENSANCTIONS_URL`). Matching `rapidfuzz` (seuil `OSINT_FUZZY_THRESHOLD=90`).
- **Garde-fou anti-homonymie** : après le match par nom, corroboration par **année de naissance** (±tolérance) et **pays** (Wikidata) — conflit → rejet ; sans donnée → `unverified`. Cf. `ingest_opensanctions.py`.
- **Licence CC BY-NC 4.0** (non commercial). **RGPD art. 9 + art. 10**. **LAN uniquement.** **Module** : `scripts/ingest_opensanctions.py`.

### 10. parlament.ch — Parlement suisse (P1C)
- **API** : OData `ws.parlament.ch/odata.svc` — EntitySet **`MemberCouncil`** (⚠ pas `Councillor`), filtre `Language eq 'FR' and Active eq true`.
- **Champs** : `PartyName`, `CantonName`, `CouncilName`, `ParlGroupFunctionText`, `PersonNumber`. Pose `is_swiss_parliament_member`, `parliament_ch_data`, repli `country_code='CH'`. **Licence OGD suisse**. **Module** : `scripts/ingest_parlament_ch.py`.

### 11. GDELT — couverture médiatique mondiale (P2A)
- **API** : `api.gdeltproject.org/api/v2/doc/doc` — `mode=artlist` (volume + pays) + `mode=tonechart` (tonalité).
- **Rate limit** : **throttle agressif** (429 dès ~1 req/s) → `GDELT_RATE_LIMIT_SECONDS=5`.
- **Stockage** : table `entity_gdelt_coverage` (snapshots : volume, tonalité, pays sources). **Module** : `scripts/ingest_gdelt.py`.

---

## Modèles embarqués (pour mémoire — pas des sources de données)
- **InsightFace `buffalo_s`** (RetinaFace + ArcFace MFN, ~120 Mo) : détection + identité + genderage. Modules `identity.py`, `face_attributes.py`.
- **MediaPipe** FaceMesh (478 pts) + FaceDetection : alignement, `face_count`, expression. Module `face_processor.py`.

## Directions réseau (synthèse sécurité)
- **Entrant LAN** : WUDD.ai (pull), API/MCP/UI servis sur Tailscale.
- **Sortant (enrichissement, lecture)** : Wikidata, Wikipedia, Wikimedia Commons, GDELT, OpenSanctions, OSM (navigateur), DDG (opt-in).
- **Sortant (émission de contenu hors LAN)** : **Discord uniquement** — filtré (jamais de donnée sensible). Voir [COMPLIANCE_OSINT.md](COMPLIANCE_OSINT.md) §3.
- **Local** : Ollama (aucune sortie externe).

## Licences — récapitulatif
| Source | Licence | Contrainte |
|--------|---------|-----------|
| Wikidata | CC0 | aucune |
| Wikipedia | CC BY-SA | attribution |
| Wikimedia Commons | CC/PD (par fichier) | selon fichier |
| OpenStreetMap | ODbL | attribution (affichée) |
| OpenSanctions | **CC BY-NC** | **non commercial** |
| parlament.ch | Open Data | attribution |
| GDELT | ouvert | politeness |
| DuckDuckGo | — (scraping) | ToS — opt-in, prudence |

> **Config** : toutes les URLs/seuils/User-Agent sont dans `backend/config.py`
> (préfixes `WUDD_*`, `OSINT_*`, `GDELT_*`, `OPENSANCTIONS_*`, `PARLAMENT_CH_*`,
> `OLLAMA_*`, `DISCORD_WEBHOOK_URL`, `FACE_AI_ENABLE_DDG`). Planification :
> `backend/scripts/osint_crontab.txt`.
