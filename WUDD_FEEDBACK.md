# Retours WUDD.ai — vu depuis l'intégration FACE.ai

> Mis à jour le 11 mai 2026 (révision soir). La version précédente
> considérait les 7 plaintes initiales comme résolues — l'observation en
> production montre que **§A.3 (faux PERSON) reste partiellement
> ouvert** : on continue de capturer pays, prénoms isolés, et
> déterminants embarqués. Ce rapport reclasse ce point et conserve les
> autres §A comme acquis. §B inchangé.
>
> Volume observé à cette date : 720 entités enrichies Wikidata, 376 images
> alignées, ratio flagged ArcFace ~1 % (après vague de confirmations
> manuelles via le bouton ✓ ajouté ce jour). 47 tombstones `not_person`
> dont 12 nouvelles purgées dans la journée (OpenAI, États-Unis, Iran,
> Chine, Lebanon, Maison-Blanche, Donovan, Nancy, Irène, Americans…).

---

## Synthèse

**Côté résolu** (§A) — 6 points sur 7 acquis. §A.3 reclassé en
**partiellement résolu** : voir détails ci-dessous.

**Côté partiellement résolu** :

- **§A.3 — Faux PERSON** : observable côté FACE.ai même après les
  corrections amont. Trois patterns systématiques restent (pays, prénoms
  isolés, déterminants embarqués). Le filtrage est aujourd'hui assuré
  100 % côté FACE.ai via le garde-fou P31 + tombstones — ce qui marche,
  mais duplique l'effort pour tous les consommateurs WUDD.

**Côté ouvert** (§B) — 4 nouvelles observations issues des travaux mai 2026 :

1. Confirmation que `max_articles=2000` est suffisant pour notre volume
2. Garde-fou P31 implémenté côté FACE.ai — proposition de mutualisation
3. Auto-merge par QID Wikidata côté FACE.ai — idem
4. Notification de changement WUDD (changelog / webhook) — souhaitable

---

# A. Points résolus

## A.1. ✅ `GET /api/entities/articles` : ambiguïté `limit` vs `max_articles`

**Statut** : pris en compte. Du côté FACE.ai notre client utilise
explicitement `max_articles=2000` ([wudd_client.py:111-117](backend/wudd_client.py)) et
clamp ensuite côté Python pour respecter la limite demandée par l'appelant.

## A.2. ✅ Canonicalisation insuffisante (Trump/Donald Trump, Zelensky)

**Statut** : pris en compte. Côté FACE.ai on a complété par notre propre
**auto-merge par Wikidata QID** ([entity_merge.py](backend/entity_merge.py)) qui
fusionne les variantes pointant vers le même item Wikidata. Voir §B.3
pour le détail de ce qu'on fait et ce qu'on aimerait que WUDD fasse.

## A.3. ⚠️ Faux positifs PERSON (Anthropic, Atreides, Russie…) — partiellement résolu

**Statut** : **partiellement résolu**. Des correctifs ont été apportés
côté WUDD mais en production on continue d'observer plusieurs catégories
de faux PERSON qui parviennent jusqu'à FACE.ai. Le filtrage final est
aujourd'hui assuré par notre garde-fou P31 (cf. §B.2).

**Observations sur la journée du 11 mai 2026** — 12 nouvelles entités ont
basculé en `not_person` via notre rétro-check Wikidata. Pattern par
catégorie :

| Catégorie | Exemples concrets reçus de WUDD | QID Wikidata | Type Wikidata réel |
|---|---|---|---|
| **Pays / entités géopolitiques** | `Chine`, `Lebanon`, `États-Unis, les`, `L'Iran` | Q148, Q993523, Q30, Q147397 | `Q6256` (pays) |
| **Lieux / bâtiments** | `Maison-Blanche` (mal segmenté de `Blanche, Maison`) | Q1576642 | `Q1968426` (résidence officielle) |
| **Démonymes / pluriels** | `Americans` | Q846570 | `Q43229` (organisation) |
| **Prénoms isolés** | `Donovan`, `Nancy`, `Irène` | Q21446653, Q40898, Q389528 | divers (homonymes) |
| **Entreprises / produits** | `OpenAI`, `ChatGPT` | Q21708200, Q115564437 | `Q4830453` (entreprise), `Q2002016` (chatbot) |

**Patterns observés** :

1. **Déterminants embarqués** — `L'Iran`, `États-Unis, les` (article `L'`
   et `les` non strippés par le NER).
2. **Segmentation des noms composés** — `Maison-Blanche` apparaît comme
   `Blanche, Maison` (le tiret est traité comme un séparateur).
3. **Tokens uniques sans contexte** — `Donovan`, `Nancy` sortent comme
   PERSON quand mentionnés sans patronyme.

**Côté FACE.ai** : le garde-fou §B.2 attrape tous ces cas mais doit être
relancé manuellement via `POST /admin/recheck-not-person` ou via le
panneau Admin (bouton ↻ Recheck N) pour rattraper les entités déjà
enrichies avant l'ajout du garde-fou.

**Recommandation WUDD si réouverture** : la voie la plus efficace est
celle évoquée en §B.2 — résolution P31 à l'ingestion + reclassement
automatique. Si trop coûteux, un filtre minimal côté NER pourrait déjà
couper les déterminants embarqués (regex `^(L'|le |la |les |the |of )`)
et les démonymes plurisl en `-s` ambigus. Mais ça touche le cœur du
NER et n'est pas anodin.

## A.4. ✅ Cache d'images Wikimedia — mauvais matches sur noms ambigus

**Statut** : pris en compte. Côté FACE.ai, le pipeline `§5.4` (purge en
4 paliers) + l'audit ArcFace continuent d'attraper les faux matches qui
passeraient encore (différence de personne révélée par la distance au
centroïde d'identité).

## A.5. ✅ Inconsistance de langue dans les noms d'entités

**Statut** : pris en compte. FACE.ai conserve son fallback FR→EN dans
`wikidata.enrich_entity` ([wikidata.py:34](backend/wikidata.py)) qui est de
toute façon utile pour la résolution Wikidata indépendamment de la
politique de nommage WUDD.

## A.6. ✅ Champ `Images[*].alt` souvent rempli avec le titre d'article

**Statut** : pris en compte. Pour info, sur le corpus actuel ce phénomène
reste l'une des principales causes des associations `flagged` détectées
par notre audit ArcFace — il y aura probablement toujours un résidu lié
à la qualité hétérogène des sources HTML, mais le signalement explicite
par WUDD de la provenance de l'alt nous permettra de tracer.

## A.7. ✅ Pas de mécanisme de delta/cursor pour le pull incrémental

**Statut** : pris en compte. Pour l'instant FACE.ai reste sur un pull
complet idempotent (URLs / slugs uniques). Voir §B.4 pour la proposition
de notification active (changelog / webhook) côté WUDD pour réduire la
fréquence de polling.

---

# B. Nouvelles observations (mai 2026)

## B.1. ℹ️ Confirmation `max_articles=2000` suffisant pour notre volume

Pas une critique — une confirmation utile pour les futurs consommateurs.

À 6300 entités côté WUDD et un cap de 2000 articles par entité, le
volume théorique max est ~12,6 M associations entité↔article. **C'est
largement au-dessus de ce dont nous avons besoin** côté FACE.ai :

- Notre pull batch quotidien priorise les favoris + top mentions, à un
  rythme de ~120 entités/jour (`WUDD_BATCH_ENTITIES_PER_CYCLE=5` × 24h).
- En pratique on tronque à 50–300 articles/entité (paramètre
  `WUDD_PULL_LIMIT`), car au-delà la diversité visuelle plafonne et le
  coût ArcFace augmente sans gain marginal.
- Le cap de 2000 nous laisse une marge confortable même pour les
  personnalités très médiatisées (Trump, Musk, Zelensky ≥ 1000 mentions).

**Recommandation** : pas de demande de changement. Le cap actuel est
bien dimensionné. À reconsidérer si WUDD vise un corpus > 50 000 entités
ou si nous voulons faire de la veille rétroactive sur l'historique
complet — auquel cas un cursor ou un endpoint `/articles/since=<date>`
pourrait être pertinent (§B.4).

## B.2. ℹ️ Garde-fou Wikidata P31 côté FACE.ai — proposition de mutualisation

**Ce qu'on a mis en place le 11 mai 2026** :
[`wikidata.enrich_entity`](backend/wikidata.py) extrait la propriété
**P31** (`instance of`) des entités résolues. Si la liste des QIDs
instance ne contient pas `Q5` (être humain), l'entité est marquée
`wikidata_status='not_person'`, ses images/articles/liens sont purgés,
et un tombstone bloque la recréation au prochain pull WUDD du même nom
([`entity_cleanup.py`](backend/entity_cleanup.py)).

**Premier test live** : injection manuelle de `Park, Apple` → Wikidata
résout en `Q22041180` → P31 = `Q1497375` (complexe de bâtiments) ≠ Q5
→ purge automatique. Le worker fait pareil sur tout faux PERSON qui
serait ré-ingéré depuis WUDD à l'avenir.

**Intérêt pour WUDD** : ce mécanisme pourrait être mutualisé côté amont.
La pipeline WUDD pourrait :
1. Résoudre le QID Wikidata à l'ingestion (déjà fait pour le cache
   `data/images_cache.json`)
2. Vérifier `P31` avant de classer en `PERSON`
3. Reclasser en `ORG`, `LOC`, `FICTIONAL` ou autre selon le P31 trouvé,
   au lieu de propager l'erreur NER

L'avantage : tous les consommateurs WUDD bénéficient de la correction,
pas seulement FACE.ai. L'inconvénient : 1 requête Wikidata par entité
nouvelle. C'est une couche optionnelle (toggle env var ?) — utile pour
les pipelines qui se font confiance sur le type.

**Si WUDD préfère ne pas implémenter** : pas de problème, notre filtre
fonctionne et ne demande rien à WUDD. C'est juste qu'on duplique l'effort
si chaque consommateur refait sa propre validation.

## B.3. ℹ️ Auto-merge par QID Wikidata côté FACE.ai — idem mutualisable

**Ce qu'on a mis en place** :
[`entity_merge.auto_merge_by_qid`](backend/entity_merge.py) tourne dans
le worker (poll 2 min). Dès que deux entités FACE.ai s'enrichissent vers
le même `wikidata_qid`, on les fusionne automatiquement. Cas typiques
attrapés sur le corpus actuel :

| Canonical retenu (image_count max) | Variantes absorbées |
|---|---|
| Zelensky, Volodymyr (Q3874799) | Zelenskyy, Vladimir Zelensky |
| Trump, administration | Trump → encore distinct (QID différent) |
| Netanyahu (Q43723) | Netanyahou, Benyamin / Netanyahou |
| Lula (Q37181) | Silva, Luiz Inacio Lula da |
| Sutcliffe, Stuart (Q204218) | Sutcliffe, Stu |
| Picasso, Pablo (Q5593) | Picasso |
| Araghtchi, Abbas (Q7459020) | Araghchi, Abbas |

**Limites observées** : la fusion par QID ne couvre pas les cas où WUDD
distingue **deux QIDs Wikidata différents pour la même personne**, ex.
`Zuckerberg` (Q21491489 — homonyme/redirect) vs `Zuckerberg, Mark`
(Q36215). Ces cas restent dans notre nouvelle interface manuelle
[`/audit · Doublons probables`](frontend/src/components/DuplicatesPanel.jsx)
pour validation humaine.

**Intérêt pour WUDD** : idem §B.2 — si WUDD pré-canonicalise par QID
à l'ingestion, les consommateurs reçoivent déjà une liste fusionnée.
À pondérer contre la complexité (gestion des redirects Wikidata,
homonymes, sous-types) qui n'est pas triviale.

## B.4. ℹ️ Notification active pour les nouvelles entités / articles

Le pull complet idempotent (§A.7) marche, mais il oblige FACE.ai à
poller régulièrement même si rien ne change. Trois pistes par ordre
d'effort croissant :

1. **Endpoint `/api/changelog`** — liste les entités/articles ajoutés
   depuis un timestamp. Petit, non bloquant pour WUDD. FACE.ai pourrait
   passer de 30 min de poll entités à 5 min sans coût supplémentaire.

2. **Header `Last-Modified` sur `/api/entities/export`** — encore plus
   léger. FACE.ai envoie `If-Modified-Since`, WUDD répond 304 si rien
   n'a bougé. Pas de payload, pas de logique nouvelle, juste un check
   `MAX(updated_at)` côté serveur.

3. **Webhook** — push WUDD → FACE.ai quand un événement (nouvelle PERSON
   du top, nouvel article taggué d'une PERSON existante) survient. Plus
   complexe (gestion erreurs, retry, sécurisation LAN/Tailscale).

**Recommandation** : l'option 2 (header `Last-Modified` + 304) est le
meilleur rapport effort/valeur — 10 lignes côté WUDD, économie réelle
côté tous les consommateurs.

## B.5. ℹ️ Cooccurrence NER plus basse qu'attendue sur paires fortes (Trump/Musk = 2)

**Observation côté FACE.ai (rapport test MCP, 2026-05-12)** : sur le
corpus actuel (1 800 articles, 1 118 entités), le tool MCP
`compare_entities("trump-donald-j", "musk-elon")` remonte une
**cooccurrence de 2 articles** seulement, alors que ces deux figures ont
saturé l'actualité 2025-2026 (alliance puis rupture publique). Le
calcul côté FACE.ai est correct (jointure sur `article_entities`), donc
le signal vient de l'**ingestion amont** :

1. Soit le NER WUDD manque les mentions conjointes dans les articles
   pertinents (Musk cité par pronom, ou via "le patron de Tesla"
   au lieu du nom propre dans des passages où Trump est nommé).
2. Soit la canonicalisation amont sépare des variantes
   (Trump/Donald Trump = 2 entités côté WUDD, cf. §A.2 toujours
   partiellement actif sur la branche Trump) — FACE.ai cale ses
   entités sur ce qui sort de l'export WUDD, donc reflète la
   fragmentation.

**Test inversé pour calibrer** : `compare_entities` sur Altman/Amodei
(deux figures dont la rivalité Anthropic/OpenAI est massivement
couverte) pourrait servir de baseline. Côté FACE.ai on a tout ce qu'il
faut pour fournir une liste de paires à tester si utile.

Pas une demande d'action urgente — plutôt un signal de calibration pour
WUDD : si les "fortes paires" remontent trop bas, c'est probablement le
même signal côté analyses internes WUDD.

---

# C. Points de coordination ponctuels

Pour information uniquement, pas des demandes :

- **Conformité** : FACE.ai reste positionnée comme outil de veille
  interne sur corpus maîtrisé (spec §1.5, posture RGPD art. 6.1.f). Pas
  d'évolution prévue vers un service public — donc pas de pression
  réciproque sur WUDD pour ouvrir l'API publiquement.
- **Volume de pull** : à ~120 entités/jour avec cap de 50 articles
  chacune, on génère ~6000 req `/api/entities/articles` par jour côté
  WUDD. Si c'est trop, on peut baisser `WUDD_BATCH_ENTITIES_PER_CYCLE`
  (variable env). Signaler.

---

# D. Annexe : ce que FACE.ai fait pour rattraper ce qui passe encore

Quelques points où FACE.ai applique des corrections a posteriori, par
réflexe défensif — ça peut intéresser WUDD ou simplement servir de
checkpoint sur la qualité de l'intégration.

| Phénomène | Gestion FACE.ai |
|---|---|
| Faux PERSON (lieux, entreprises, fictions) | Garde-fou Wikidata P31 → purge auto, tombstone bloque recréation (§B.2) |
| Variantes canoniques | Auto-merge par QID (worker) + UI manuelle pour les autres (§B.3) |
| Mauvaise association alt/caption | Audit ArcFace par centroïde d'identité → `association_status='flagged'` → workflow `/audit` (réassocier / supprimer) |
| Faux match Wikimedia (John Ternus → Apple Park) | §5.4 purge si pas de visage humain ; sinon ArcFace flag |
| Signalement humain manuel | Bouton ⚠ Signaler sur chaque image de galerie → bascule en `human_flagged` → même queue audit |
| Mélange FR/EN | Wikidata fallback FR→EN dans la recherche QID |
| Pas de delta WUDD | Pull idempotent par URL + slug uniques |

---

**Contact FACE.ai** : `contact@ok-ia.ch`
