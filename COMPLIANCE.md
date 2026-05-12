# FACE.ai — Compliance RGPD / nLPD CH

> Document de conformité interne pour FACE.ai. Couvre les obligations
> RGPD (UE) art. 30 (registre des activités de traitement) et nLPD
> Suisse art. 12 (registre du responsable de traitement).
>
> **Version** : 1.0 — mai 2026
> **Responsable** : Patrick Ostertag (mono-utilisateur)
> **Statut juridique** : intérêt légitime (RGPD art. 6.1.f / nLPD art. 31 al. 2 lettre c)
>
> ⚠ Ce document est un **registre de bonne foi**, pas un avis juridique.
> Pour toute évolution du périmètre (cf. §6 *Conditions de maintien*),
> faire valider par un juriste avant déploiement.

---

## 1. Identité du responsable de traitement

| Champ | Valeur |
|---|---|
| Responsable | Patrick Ostertag |
| Adresse mail | contact@ok-ia.ch |
| Pays de résidence | Suisse (canton Vaud) |
| Statut | Personne physique, projet personnel non commercial |
| Sous-traitants externes | Aucun (infrastructure locale Mac mini M4 Pro + Tailscale privé) |
| Représentant UE | Non requis (responsable établi en CH, traitement non-commercial à petite échelle, pas de ciblage de personnes UE en tant que tel) |

**Co-traitement WUDD.ai.** WUDD.ai est un projet du même responsable
opéré sur la même infrastructure. Il n'y a pas de transfert de données
entre responsables distincts. Le pipeline WUDD → FACE.ai est interne
à un même responsable, considéré comme une opération unique pour
l'analyse RGPD.

---

## 2. Finalités du traitement

| Finalité | Détail |
|---|---|
| **Veille médiatique interne** | Suivi visuel des personnalités publiques apparaissant dans la presse francophone et anglophone analysée par WUDD.ai |
| **Constitution d'un corpus artistique** | Esthétique forensique-musée assumée : Flipbook, composite Galton, archive systématique. Références : Bertillon, Galton, Sander, Simon, Henner |
| **Recherche personnelle** | Exploration des dynamiques de visibilité médiatique (qui apparaît, quand, dans quel contexte) |

**Ce que le traitement n'est PAS** :
- Pas un projet de recherche académique généraliste sur la reconnaissance faciale
- Pas un outil de surveillance de masse ni de tracking d'individus inconnus
- Pas un SaaS multi-tenant — pas d'inscription, pas de partage public, pas d'API ouverte
- Pas un système d'identification temps réel à partir de flux vidéo ou de photos personnelles fournies par un tiers

---

## 3. Base légale invoquée

**RGPD art. 6.1.f — Intérêt légitime** (et le pendant nLPD art. 31 al.
2 lettre c).

### 3.1 Test des trois étapes (RGPD)

**Étape 1 — Identification de l'intérêt légitime poursuivi.**

Veille médiatique sur des personnalités publiques apparaissant nommément
dans des articles de presse déjà publiés et indexés par WUDD.ai.
L'analyse géométrique d'alignement (MediaPipe + OpenCV) produit une
représentation comparable qui sert l'analyse documentaire et la
production artistique (composite Galton, Flipbook).

**Étape 2 — Nécessité du traitement.**

Pas d'autre moyen réaliste d'agréger les portraits d'une même personne
issus de sources hétérogènes que de les aligner géométriquement. Le
volume restreint (~16 000 entités cibles, ~500 actuellement) reste
proportionné à un usage individuel de veille.

**Étape 3 — Mise en balance avec les droits des personnes concernées.**

Trois facteurs qui penchent côté intérêt légitime :

- **Personnalités publiques** : les personnes concernées sont identifiées
  nommément dans la presse, ont accepté de fait une visibilité
  médiatique. Le traitement ne révèle rien que la presse n'ait déjà publié.
- **Pas de diffusion** : LAN/Tailscale seulement, accès limité au
  responsable. Pas d'exposition publique, pas d'API ouverte.
- **Pas de croisement comportemental** : aucun enrichissement avec
  données de géolocalisation, opinions politiques inférées, profilage
  publicitaire. Les seules données ajoutées (Wikidata) sont des
  identifiants publics et des biographies factuelles.

Facteur défavorable mitigé : la **reconnaissance faciale** (ArcFace) est
identifiée comme catégorie sensible par certaines autorités (CNIL,
EDPB). Atténuation : pas d'identification de personnes inconnues — on
**vérifie** seulement l'attribution texte→image fournie par la presse
elle-même. Le système ne cherche pas qui est sur une image, il vérifie
qu'une image légendée « Sam Altman » montre bien la même personne que
les autres images légendées Sam Altman.

### 3.2 Conditions de maintien du régime

Si l'un des éléments suivants change, l'analyse juridique est à refaire :

- Élargissement du corpus à des **personnes privées non publiques**
- **Exposition publique** de la galerie ou de l'API (au-delà LAN/Tailscale)
- Croisement avec des **données comportementales** (géolocalisation,
  opinions politiques inférées, données de santé)
- **Mise à disposition de tiers**, même gratuite (sauf demande
  d'opposition cf. §7)

---

## 4. Catégories de personnes concernées et de données

### 4.1 Personnes concernées

| Catégorie | Estimation volume |
|---|---|
| Personnalités publiques (politiques, dirigeants, artistes, sportifs) apparaissant nommément dans des articles indexés par WUDD.ai | ~1 067 actuellement, ~16 000 à terme |

**Exclus** : enfants mineurs (filtrage indirect par le NER de WUDD.ai
qui privilégie les personnalités citées dans la presse adulte), personnes
privées non publiques.

### 4.2 Catégories de données

| Catégorie | Source | Lieu de stockage | Sensible (art. 9 RGPD / art. 5 nLPD) ? |
|---|---|---|---|
| Nom canonique, aliases | WUDD.ai (NER) | `entities`, `entity_aliases` | Non |
| Date/lieu de naissance et décès | Wikidata | `entities` | Non (donnée publique) |
| Nationalité, occupation, employeur | Wikidata | `entities` | Non |
| Résumé biographique | Wikipédia FR/EN | `entities.wiki_summary` | Non |
| URL article source | WUDD.ai | `articles` | Non |
| Images de visage (originales) | URLs sources presse / Wikimedia Commons | `static/originals/` (binding-mount disque) | **Biométrique** au sens art. 9.1 RGPD si traité pour identifier (cf. §4.3) |
| Images alignées (300×300) | Calcul local | `static/aligned/` | **Biométrique** idem |
| Embeddings faciaux ArcFace 512-dim | Calcul local InsightFace | `images.identity_embedding`, `entities.identity_centroid` (BLOB SQLite) | **Biométrique** art. 9.1 RGPD |
| Embeddings pHash 64 bits | Calcul local OpenCV | `images.embedding` | Non (signature perceptive, pas biométrique) |
| Landmarks faciaux (468 points) | MediaPipe local | `face_analysis.landmarks_blob` | **Biométrique** idem |

### 4.3 Sur la qualification "donnée biométrique"

L'art. 4.14 RGPD définit la donnée biométrique comme « les données à
caractère personnel résultant d'un traitement technique spécifique […]
qui permettent ou confirment l'identification unique d'une personne
physique ». La nLPD (art. 5 let. c ch. 4) reprend le même critère.

**Notre cas** : on **confirme** une identification déjà fournie par la
presse (caption → entité), on n'identifie pas une personne inconnue.
L'EDPB (lignes directrices 3/2019) considère que la reconnaissance
faciale au sens strict implique une **identification active** d'une
personne inconnue. Notre usage est **vérification d'attribution** sur
des personnalités publiques nommément citées dans la presse.

Position adoptée : on traite ces données **comme si** elles étaient
biométriques au sens strict (haute exigence de sécurité), mais on
n'invoque pas la base légale art. 9.2.a (consentement explicite) ni
9.2.e (manifestement rendues publiques) — on reste sur l'intérêt
légitime art. 6.1.f, en cohérence avec la doctrine majoritaire pour
les analyses de vérification non identifiantes.

Si cette position devait être contestée par une autorité (CNIL, PFPDT
suisse), le repli serait d'invoquer l'art. 9.2.e RGPD (« rendues
manifestement publiques par la personne concernée ») pour les
personnalités publiques apparaissant nommément en presse.

---

## 5. Destinataires et transferts

| Destinataire | Type | Données partagées |
|---|---|---|
| Responsable du traitement (Patrick Ostertag) | Personne physique unique | Toutes (accès local Mac mini) |
| WUDD.ai | Système amont du même responsable | Pas de transfert sortant — c'est WUDD qui fournit l'amont |
| Wikidata / Wikipedia / Wikimedia Commons | API publiques | Requête sortante : nom de l'entité, QID Wikidata. Pas de transfert de données personnelles **vers** ces services (lecture seulement) |
| DuckDuckGo Images | API publique (gated `FACE_AI_ENABLE_DDG`) | Requête sortante : nom de l'entité. Idem, lecture seulement |
| Tailscale (réseau privé) | Hébergement réseau | Transit chiffré, pas de stockage côté Tailscale |

**Transferts hors UE/EEE** :
- Suisse (CH) : pays bénéficiant d'une **décision d'adéquation** de la
  Commission européenne (depuis 2000). Pas de garantie supplémentaire
  requise pour les transferts UE → CH.
- US (DuckDuckGo, certains miroirs Wikimedia) : transferts vers des
  serveurs potentiellement situés aux US dans le cadre de **requêtes
  publiques anonymisées** (User-Agent générique, pas d'identifiants
  personnels du responsable transmis). Risque évalué bas : on consomme
  des APIs publiques en lecture seule, les serveurs ne reçoivent que
  des noms de personnes déjà rendues publiques.

---

## 6. Durée de conservation

| Donnée | Durée | Justification |
|---|---|---|
| Images, embeddings, métadonnées d'entités présentes | Tant qu'au moins un article WUDD.ai actif référence l'entité | Cohérence avec le périmètre de veille |
| Tombstones `not_person` | Permanent (pour empêcher la recréation par re-pull WUDD) | Hygiène pipeline |
| Tombstones après `DELETE /entities/{slug}` (droit d'opposition) | Permanent (entrée vide avec slug + status) | Empêcher la recréation accidentelle après demande d'effacement |
| Logs HTTP FastAPI | 30 jours via rotation Docker (configurable) | Diagnostic technique uniquement, pas d'identifiant personnel utilisateur (mono-utilisateur) |
| Backups SQLite | 7 daily + 4 weekly + 12 monthly (rotation automatique) | Récupération en cas de corruption ; les backups héritent du périmètre du moment où ils ont été pris |
| `worker_events` | 7 jours (rotation probabiliste dans `worker_metrics`) | Observabilité technique uniquement |

**Réévaluation** : annuelle, par le responsable. La proposition
actuelle de « tant que référencé par WUDD » est dynamique — quand WUDD
purge un article, FACE.ai a vocation à suivre. Une revue manuelle
annuelle vérifie l'absence d'entités orphelines.

---

## 7. Droits des personnes concernées

Même si l'application n'est pas exposée publiquement, **un canal de
demande doit exister** (doctrine PFPDT + CNIL).

| Droit | Comment l'exercer |
|---|---|
| **Accès** (art. 15 RGPD / art. 25 nLPD) | Email à `contact@ok-ia.ch` avec le nom canonique de l'entité. Le responsable vérifie l'identité du demandeur (pièce officielle ou attestation publiable) avant de répondre. Réponse sous 30 jours : extraction `GET /entities/{slug}` + `GET /entities/{slug}/images` + `GET /entities/{slug}/timeline` sous forme JSON ou PDF |
| **Rectification** (art. 16 RGPD / art. 32 nLPD) | Idem : email avec correction demandée. Si correction d'une métadonnée Wikidata, redirigée vers Wikidata directement (responsable n'a pas autorité sur la source) |
| **Effacement / opposition** (art. 17, 21 RGPD / art. 32 nLPD) | Endpoint `DELETE /entities/{slug}` purge en cascade : aliases, images (DB + fichiers disque), face_analysis, article_entities. Conserve un tombstone vide pour empêcher la recréation par re-pull WUDD. Backups antérieurs gardent la donnée jusqu'à expiration de leur rotation (max 1 an) |
| **Portabilité** (art. 20 RGPD) | Pas pertinent : les données ne sont pas fournies par la personne concernée, elles sont collectées indirectement via la presse |
| **Limitation** (art. 18 RGPD / art. 30 nLPD) | Email à `contact@ok-ia.ch`. Le responsable peut marquer une entité en `is_favorite=false` et la masquer côté UI sans la supprimer, le temps d'instruire une demande contestée |

**Mention obligatoire** : ce canal `contact@ok-ia.ch` doit être
indiqué dans toute interface publique-facing de WUDD.ai et FACE.ai si
elles sont jamais exposées. Pour l'instant (LAN/Tailscale only), la
mention reste interne à ce document.

---

## 8. Mesures techniques et organisationnelles

| Catégorie | Mesure |
|---|---|
| **Confidentialité — réseau** | Bind 127.0.0.1 ou interface Tailscale uniquement. Aucun port exposé sur 0.0.0.0. Pas d'authentification applicative car le réseau est le périmètre (cf. CLAUDE.md §13.9) |
| **Confidentialité — disque** | Volumes Docker bind-mount sur disque local. Backups SQLite gzippés sur le même disque. Pas de stockage cloud |
| **Confidentialité — secrets** | `.env` et `data/` dans `.gitignore`. Pas de clés API stockées en clair dans le code (Wikidata/Wikipedia ne demandent pas de clé) |
| **Intégrité — DB** | Backup auto quotidien + rotation (7 daily / 4 weekly / 12 monthly). UI restore avec snapshot pré-restauration. Migrations Alembic versionnées (24 migrations, ordre déterministe) |
| **Intégrité — pipeline** | Garde-fou anti-fusion catastrophique (incident 2026-05-11 → §11). Garde-fou P31=Q5 sur les faux PERSON. `MIN_IMAGES_PER_SIDE=5` sur fusion par centroïde |
| **Disponibilité** | Pas d'engagement de disponibilité (mono-utilisateur). Healthcheck Docker. Observabilité `/admin/worker-status` + `/metrics` Prometheus |
| **Auditabilité** | Table `worker_events` retient 7 jours de cycles + événements rares. UI Audit P9 trace les corrections manuelles |
| **Mises à jour** | Image Python `python:3.12-slim` rebuilt avec `pip install --upgrade` à chaque release majeure. Dépendances pinned dans `requirements.txt` |

---

## 9. Analyse d'impact relative à la protection des données (AIPD / DPIA)

### 9.1 Faut-il un DPIA art. 35 RGPD ?

Critères de déclenchement (art. 35.3) :

- ✗ Évaluation systématique d'aspects personnels par décision automatisée
  → pas le cas, FACE.ai n'évalue pas les personnes, il aligne des images
- ✗ Traitement à **grande échelle** de catégories particulières (art. 9)
  → 1 067 personnes, ~500 images, ne qualifie pas comme « grande échelle »
  (le seuil EDPB suggère > 5 000 personnes pour la qualification)
- ✗ **Surveillance systématique** à grande échelle d'une zone accessible
  au public → non applicable
- ✗ Décisions juridiques sur la base de la donnée → non
- ✗ Données biométriques de personnes vulnérables → non, personnalités
  publiques adultes

**Verdict** : DPIA non obligatoire au sens art. 35 RGPD. La présente
section 9 sert quand même de **mini-DPIA** documentaire, par prudence.

### 9.2 Risques identifiés et atténuation

| Risque | Probabilité | Gravité | Atténuation |
|---|---|---|---|
| Faux match ArcFace → image attribuée à la mauvaise personne (atteinte à la réputation) | Moyenne (observé sur Mark Hamill ↔ Trump pendant un audit) | Modérée (visible côté UI uniquement, pas de diffusion) | Garde-fou `MIN_IMAGES_PER_SIDE=5` + workflow `/audit` qui flag les associations douteuses + correction manuelle disponible |
| Fusion catastrophique d'entités (incident 2026-05-11) | Faible depuis garde-fou anti-fusion | Élevée si non détecté (3 entités fusionnées en une) | Garde-fou `MERGE_MAX_GROWTH_RATIO=1.5` + score Wikidata ≥ 1.0 obligatoire + endpoint `/admin/merge-conflicts` qui surface les blocages |
| Faux PERSON (lieu, entreprise, prénom isolé) | Élevée (WUDD envoie 47+ faux PERSON purgés à date) | Faible | Garde-fou P31=Q5 + tombstones empêchent la recréation |
| Élargissement involontaire du périmètre via DDG picker | Faible (gated par env var) | Élevée si activé sans valider individuellement | DDG désactivé par défaut, picker manuel obligatoire (pas d'ingestion auto), badge `source_provider='ddg'` visible dans `/audit` pour audit renforcé |
| Fuite de données par compromission du Mac mini | Faible (LAN/Tailscale) | Élevée si exfiltration complète | Pas d'auth app mais réseau privé. Backups locaux non-cloud. Disque chiffré FileVault (à vérifier côté responsable) |
| Pérennité au-delà de la durée de vie du projet | Existe (responsable mortel) | Modérée | Backups SQLite portables (~10 Mo), reproductibles depuis le code source. Pas de dépendance à un service cloud propriétaire |

---

## 10. Notification de violation

En cas d'incident de sécurité au sens art. 33 RGPD (notification à
l'autorité dans les 72h) ou art. 24 nLPD (notification au PFPDT dans
les meilleurs délais) :

1. **Détection** : monitoring `/admin/worker-status` + alertes manuelles
2. **Évaluation** : nature, volume, conséquences pour les personnes
   concernées
3. **Notification autorité** : CNIL France (si responsable FR) ou PFPDT
   CH dans les délais légaux. **Le responsable étant en CH avec
   traitement non-commercial à petite échelle, l'autorité de référence
   est le PFPDT** (https://www.edoeb.admin.ch)
4. **Notification personnes concernées** : seulement si « risque élevé
   pour les droits et libertés » (art. 34 RGPD / art. 24 al. 5 nLPD)
5. **Documentation** : journal interne avec date, nature, mesures
   prises

Compte tenu du périmètre LAN-only, le scénario le plus probable est
le **vol physique du Mac mini**. En tel cas, la notification dépendra
de l'état d'avancement du disque (FileVault chiffré → notification
allégée, sinon notification standard).

---

## 11. Incident historique pour mémoire

**11 mai 2026 — Fusion catastrophique de QID Wikidata**.

Un bug d'enrichissement (cause racine non identifiée, logs perdus) a
attribué le QID `Q7407093` (Sam Altman) à trois autres entités
(Elon Musk, Mark Zuckerberg, Paul McCartney). Le mécanisme
`auto_merge_by_qid` a alors fusionné les 4 entités → Altman a accumulé
85 images au lieu de 30, les 3 autres ont disparu côté UI.

**Détection** : audit manuel utilisateur (~15 min après l'incident).

**Impact** : aucune donnée perdue (la fusion regroupe sans supprimer).
Restauration complète en 1 heure via démerge ciblé. ArcFace a
correctement flag les 48 images mal attribuées (sa fonction d'audit
visuel a fait son travail malgré la corruption QID).

**Mesures correctives** :
- Garde-fou `MERGE_MAX_GROWTH_RATIO=1.5` (refuse une fusion qui ferait
  grossir le canonical de plus de 50%)
- Garde-fou `MERGE_MIN_WIKIDATA_SCORE=1.0` (refuse une fusion si label
  Wikidata pas exact)
- Endpoint `/admin/merge-conflicts` pour visibilité des blocages
- Backup auto quotidien (`backup_loop`) — ajouté en réaction directe
- Table `worker_events` pour observabilité worker
- Tests `TestAutoMergeSafeguards` qui reproduisent le scénario

**Notifications faites** : aucune. Aucune donnée personnelle n'a fuité
au-delà du périmètre (LAN/Tailscale), aucune personne concernée n'a
été affectée hors-application. L'incident est documenté ici par
transparence et pour traçabilité interne.

---

## 12. Revue et mise à jour de ce document

| Échéance | Action |
|---|---|
| Annuelle | Revue complète du présent registre par le responsable |
| Sur changement de périmètre (§3.2) | Refonte de l'analyse, validation juridique externe si exposition publique |
| Sur incident notifiable | Ajout d'une entrée dans §11 |
| Sur ajout de nouvelle source de données | Ajout dans §4.2 et §5 |

**Prochaine revue prévue** : mai 2027.

---

## Annexe — Mention légale interne

Tant que FACE.ai reste sur LAN/Tailscale et mono-utilisateur, aucune
mention publique n'est requise. Si l'application devait être exposée à
des tiers (collègues, collaborateurs, démonstration publique), la
mention suivante doit être ajoutée en pied de page de l'UI :

> *FACE.ai est un outil de veille interne traitant des images de
> personnalités publiques apparaissant dans la presse, dans le cadre
> de l'intérêt légitime (RGPD art. 6.1.f, nLPD art. 31). Pour exercer
> vos droits d'accès, de rectification ou d'opposition :
> contact@ok-ia.ch.*

---

*Fin du document de conformité v1.0*
