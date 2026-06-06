import os
from pathlib import Path

DB_PATH = Path(os.getenv("FACE_AI_DB", "./data/face_ai.db"))
STATIC_DIR = Path(os.getenv("FACE_AI_STATIC", "./static"))
ENV = os.getenv("ENV", "development")

DATABASE_URL = f"sqlite:///{DB_PATH}"

EYE_DISTANCE_TARGET = 80
CROP_SIZE = 300
CROP_OFFSET_Y = 0.35

# Intégration WUDD.ai (spec §8, mode pull)
WUDD_BASE_URL = os.getenv("WUDD_BASE_URL", "http://100.72.122.51:5050")
WUDD_PULL_LIMIT = int(os.getenv("WUDD_PULL_LIMIT", "200"))
WUDD_USER_AGENT = "FACE.ai/1.0 (contact@ok-ia.ch)"

# Pull articles WUDD par batch (roadmap court terme)
# Avec ces valeurs, ~120 entités traitées par jour (5 × 24 cycles).
# Refresh d'une entité au plus tôt après 30 jours pour entretien.
WUDD_BATCH_ENTITIES_PER_CYCLE = int(os.getenv("WUDD_BATCH_ENTITIES_PER_CYCLE", "5"))
WUDD_BATCH_CYCLE_MINUTES = int(os.getenv("WUDD_BATCH_CYCLE_MINUTES", "60"))
WUDD_BATCH_ARTICLES_PER_ENTITY = int(os.getenv("WUDD_BATCH_ARTICLES_PER_ENTITY", "50"))
WUDD_BATCH_REFRESH_DAYS = int(os.getenv("WUDD_BATCH_REFRESH_DAYS", "30"))
WUDD_BATCH_FAVORITES_REFRESH_DAYS = int(
    os.getenv("WUDD_BATCH_FAVORITES_REFRESH_DAYS", "7")
)

# Garde-fous auto_merge_by_qid (incident 2026-05-11 : 3 entités absorbées dans
# Altman via QID corrompu). Le canonical ne peut grossir au-delà de ce ratio
# sans confirmation humaine ; et tout score Wikidata < ce seuil refuse la
# fusion auto (un label inexact = trop d'incertitude pour une opération
# irréversible). Les conflits refusés restent visibles via
# `GET /admin/merge-conflicts`.
MERGE_MAX_GROWTH_RATIO = float(os.getenv("MERGE_MAX_GROWTH_RATIO", "1.5"))
MERGE_MIN_WIKIDATA_SCORE = float(os.getenv("MERGE_MIN_WIKIDATA_SCORE", "1.0"))

# DDG picker — élargissement de périmètre vs spec §1.5 (corpus maîtrisé WUDD).
# Désactivé par défaut. Activer explicitement via env `FACE_AI_ENABLE_DDG=true`
# si on accepte d'ingérer des images hors-corpus avec validation manuelle.
# Cf. CLAUDE.md sur la posture éthique du projet.
ENABLE_DDG = os.getenv("FACE_AI_ENABLE_DDG", "false").lower() == "true"
DDG_RATE_LIMIT_HOURS = int(os.getenv("DDG_RATE_LIMIT_HOURS", "24"))

# Fusion par centroïde ArcFace — exige un nombre minimum d'images des
# DEUX côtés pour que le centroïde soit considéré comme fiable. À 1
# image, le centroïde est juste l'image elle-même ; un faux match
# (Mark Hamill avec 1 photo de Trump dans une publication) peut
# matcher accidentellement avec un autre centroïde. Le seuil 5 (~1
# semaine de présence média typique) est calibré empiriquement.
# Seuil auto-merge resserré à 0.20 (de 0.30) : plus strict pour
# éviter les faux positifs sur frères/sosies/vieillissement.
CENTROID_MIN_IMAGES = int(os.getenv("CENTROID_MIN_IMAGES", "5"))
CENTROID_AUTO_DISTANCE = float(os.getenv("CENTROID_AUTO_DISTANCE", "0.20"))
CENTROID_SUGGEST_DISTANCE = float(os.getenv("CENTROID_SUGGEST_DISTANCE", "0.45"))

# Graphe de cooccurrence matérialisé (v029, A5). On ne stocke que les paires
# d'entités partageant au moins ce nombre d'articles — borne la table
# (sinon ~tout couple co-cité une fois, bruit + volume). 2 = au moins deux
# co-occurrences éditoriales pour considérer un lien.
COOCCURRENCE_MIN_SHARED = int(os.getenv("COOCCURRENCE_MIN_SHARED", "2"))

# Part de présence (share of voice, v030). Fenêtre glissante par défaut pour
# le classement « qui domine la presse en ce moment » + comparaison à la
# fenêtre précédente pour la tendance.
SHARE_OF_VOICE_WINDOW_DAYS = int(os.getenv("SHARE_OF_VOICE_WINDOW_DAYS", "30"))

# Cleanup des entités orphelines (v031). Une entité `wikidata_status='not_found'`
# (aucun QID Wikidata) ET sans aucune image après ce délai est du poids mort :
# soit un faux PERSON du NER WUDD (concept, lieu, entreprise non reconnu par le
# garde-fou P31 car même pas trouvé sur Wikidata), soit une personne trop
# obscure sans portrait — inutilisable dans une galerie de visages. On ne purge
# QUE manuellement (endpoint /admin, pas de loop worker) : opération
# destructive, on veut un humain dans la boucle. Délai mesuré depuis
# `wikidata_synced_at` (instant où le not_found a été confirmé), pas first_seen.
CLEANUP_ORPHAN_AFTER_DAYS = int(os.getenv("CLEANUP_ORPHAN_AFTER_DAYS", "30"))

# ── Notifications Discord (veille proactive, v030) ──────────────────────
# Webhook réutilisé de WUDD.ai (sortie réseau assumée, cf. CLAUDE.md §1.5).
# Vide → notifications désactivées (le worker n'émet rien). On ne logge
# jamais l'URL en clair.
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
NOTIFY_ENABLED = (
    os.getenv("FACE_AI_NOTIFY_ENABLED", "true").lower() == "true"
    and bool(DISCORD_WEBHOOK_URL)
)
# Cadence du notify_loop. 10 min : assez réactif pour de la veille, sans
# spammer (les pics se mesurent en jours, les flagged arrivent par l'ingestion).
NOTIFY_POLL_SECONDS = int(os.getenv("FACE_AI_NOTIFY_POLL_SECONDS", "600"))
# Scénario A « pic de visibilité » : fenêtre courante vs précédente.
# On alerte si la fenêtre courante compte ≥ MIN articles ET ≥ RATIO × la
# précédente (évite le bruit des petites entités à 1→3 articles).
NOTIFY_SPIKE_WINDOW_DAYS = int(os.getenv("NOTIFY_SPIKE_WINDOW_DAYS", "7"))
NOTIFY_SPIKE_MIN_ARTICLES = int(os.getenv("NOTIFY_SPIKE_MIN_ARTICLES", "5"))
NOTIFY_SPIKE_RATIO = float(os.getenv("NOTIFY_SPIKE_RATIO", "3.0"))
NOTIFY_SPIKE_MAX_PER_CYCLE = int(os.getenv("NOTIFY_SPIKE_MAX_PER_CYCLE", "5"))
# Scénario B « photo inhabituelle » : images flaggées récemment ingérées.
NOTIFY_FLAGGED_LOOKBACK_HOURS = int(os.getenv("NOTIFY_FLAGGED_LOOKBACK_HOURS", "24"))
NOTIFY_FLAGGED_MAX_PER_CYCLE = int(os.getenv("NOTIFY_FLAGGED_MAX_PER_CYCLE", "8"))
# Scénario C « nouvelle personne » : entité PERSON fraîchement créée
# (first_seen récent) AYANT déjà au moins un portrait aligné (« il faut une
# photo »). On notifie une fois par entité. Lookback large car le portrait
# arrive en asynchrone après la création de l'entité.
NOTIFY_NEW_PERSON_LOOKBACK_HOURS = int(
    os.getenv("NOTIFY_NEW_PERSON_LOOKBACK_HOURS", "48")
)
NOTIFY_NEW_PERSON_MAX_PER_CYCLE = int(
    os.getenv("NOTIFY_NEW_PERSON_MAX_PER_CYCLE", "8")
)

# Scénario D « palier corpus » : notification chaque fois que le nombre de
# personnalités gérées franchit un bloc (50 par défaut → prochain à 3050).
# Dédup persistante via un fichier d'état (worker_events est purgé à 7 j).
NOTIFY_MILESTONE_BLOCK = int(os.getenv("NOTIFY_MILESTONE_BLOCK", "50"))

# ── Notifications OSINT non sensibles (v030) ────────────────────────────
# IMPORTANT : ces alertes sortent HORS LAN (Discord). On ne notifie donc QUE
# des signaux factuels publics non sensibles. Les statuts OpenSanctions/PEP et
# les correspondances ICIJ (RGPD art. 9/10) sont VOLONTAIREMENT exclus du
# webhook — ils restent consultables en LAN (API/MCP/UI). Cf. CLAUDE.md.

# Scénario E « crise médiatique mondiale » (GDELT) : un snapshot récent de
# couverture mondiale présente une tonalité moyenne fortement négative sur un
# volume d'articles significatif. Signal de veille pur (agrégat public).
NOTIFY_GDELT_TONE_THRESHOLD = float(os.getenv("NOTIFY_GDELT_TONE_THRESHOLD", "-5.0"))
NOTIFY_GDELT_MIN_ARTICLES = int(os.getenv("NOTIFY_GDELT_MIN_ARTICLES", "20"))
NOTIFY_GDELT_LOOKBACK_HOURS = int(os.getenv("NOTIFY_GDELT_LOOKBACK_HOURS", "48"))
NOTIFY_GDELT_MAX_PER_CYCLE = int(os.getenv("NOTIFY_GDELT_MAX_PER_CYCLE", "5"))

# Scénario F « nouveau parlementaire suisse » : une entité vient d'être
# appariée à un·e élu·e de l'Assemblée fédérale (parlament.ch, donnée publique).
NOTIFY_PARLIAMENT_MAX_PER_CYCLE = int(os.getenv("NOTIFY_PARLIAMENT_MAX_PER_CYCLE", "5"))

# Scénario G « nouveau pays représenté » : le corpus accueille sa 1re
# personnalité d'un pays jamais vu (expansion géographique). Dédup persistante
# (notify_state.json) pour ne notifier chaque pays qu'une fois. Init silencieuse.
NOTIFY_COUNTRY_ENABLED = (
    os.getenv("FACE_AI_NOTIFY_COUNTRY", "true").lower() == "true"
)
NOTIFY_COUNTRY_MAX_PER_CYCLE = int(os.getenv("NOTIFY_COUNTRY_MAX_PER_CYCLE", "6"))

# ── Digest hebdomadaire (v031) ──────────────────────────────────────────
# Synthèse récurrente dérivée du share of voice (qui domine la presse cette
# semaine, tendances, nouveaux entrants), en complément des alertes unitaires.
# Désactivé par défaut (les alertes A–D suffisent à beaucoup d'usages) ;
# activer explicitement. Requiert aussi un webhook (cf. NOTIFY_ENABLED).
# Jour : `weekday()` Python (0 = lundi). Heure : UTC. Le worker vérifie à
# chaque heure et n'émet qu'une fois par semaine ISO (dédup notify_state.json).
NOTIFY_DIGEST_ENABLED = (
    os.getenv("FACE_AI_NOTIFY_DIGEST_ENABLED", "false").lower() == "true"
    and bool(DISCORD_WEBHOOK_URL)
)
NOTIFY_DIGEST_DAY = int(os.getenv("NOTIFY_DIGEST_DAY", "1"))  # mardi par défaut
NOTIFY_DIGEST_HOUR = int(os.getenv("NOTIFY_DIGEST_HOUR", "8"))  # 08:00 UTC
NOTIFY_DIGEST_WINDOW_DAYS = int(os.getenv("NOTIFY_DIGEST_WINDOW_DAYS", "7"))
NOTIFY_DIGEST_TOP = int(os.getenv("NOTIFY_DIGEST_TOP", "10"))

# ── Synthèse par IA locale Ollama (v030) ────────────────────────────────
# La synthèse jointe aux notifications est rédigée par un LLM local (Ollama,
# OpenAI-compatible :11434), même instance que WUDD.ai. Repli déterministe
# (champs bruts) si Ollama est injoignable. L'hôte est résolu dans llm.py
# (host.docker.internal en conteneur, localhost sinon ; surchargé par
# OLLAMA_HOST_DOCKER / OLLAMA_HOST_LOCAL / OLLAMA_HOST).
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_SYNTHESIS_ENABLED = (
    os.getenv("FACE_AI_OLLAMA_SYNTHESIS", "true").lower() == "true"
)

# ── Enrichissement OSINT open data (v030) ───────────────────────────────
# DÉCISION PÉRIMÈTRE 2026-06-05 (Patrick Ostertag) : enrichissement OSINT
# strictement borné à des DONNÉES OPEN SOURCE concernant des PERSONNES
# PUBLIQUES déjà dans le corpus. Aucune inférence, aucune source privée.
# Cf. CLAUDE.md. Toutes les sources ci-dessous sont gratuites/ouvertes.

# Seuil de fuzzy matching nom corpus ↔ source externe (rapidfuzz,
# token_sort_ratio 0..100). 90 = quasi-identique tolérant à l'ordre/accents.
# Au-dessus du seuil → on considère que c'est la même personne.
OSINT_FUZZY_THRESHOLD = int(os.getenv("OSINT_FUZZY_THRESHOLD", "90"))
# Répertoire des logs d'ingestion (logs/ingest_{source}_{date}.log).
OSINT_LOG_DIR = Path(os.getenv("OSINT_LOG_DIR", "./logs"))

# OpenSanctions (P1A). Bulk download du dataset fusionné `default` (JSON Lines).
OPENSANCTIONS_URL = os.getenv(
    "OPENSANCTIONS_URL",
    "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json",
)
# Garde-fou anti-homonymie (le matching par nom seul confond les homonymes,
# ex. Tim Burton réalisateur vs un PEP du même nom). Après le match par nom, on
# CORROBORE avec l'année de naissance (±tolérance) et/ou le pays de l'entité
# (déjà enrichis via Wikidata). Conflit explicite de naissance/pays → match
# REJETÉ (homonyme). Sans donnée pour corroborer → marqué `unverified` (écrit
# mais signalé), ou ignoré si REQUIRE_CORROBORATION=true (mode strict).
OSINT_SANCTIONS_BIRTHYEAR_TOLERANCE = int(
    os.getenv("OSINT_SANCTIONS_BIRTHYEAR_TOLERANCE", "1")
)
OSINT_SANCTIONS_REQUIRE_CORROBORATION = (
    os.getenv("FACE_AI_SANCTIONS_REQUIRE_CORROBORATION", "false").lower() == "true"
)
OSINT_SANCTIONS_MAX_CANDIDATES = int(
    os.getenv("OSINT_SANCTIONS_MAX_CANDIDATES", "8")
)

# Parlement suisse (P1C). API OData officielle.
PARLAMENT_CH_BASE_URL = os.getenv(
    "PARLAMENT_CH_BASE_URL", "https://ws.parlament.ch/odata.svc"
)

# GDELT (P2A). API DOC 2.0 publique, sans auth. Throttle agressif observé
# (429 dès ~1 req/sec en pratique, run témoin 2026-06-05) → délai inter-requête
# prudent par défaut. Baisser via env si l'API se montre tolérante.
GDELT_API_URL = os.getenv(
    "GDELT_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc"
)
GDELT_RATE_LIMIT_SECONDS = float(os.getenv("GDELT_RATE_LIMIT_SECONDS", "5.0"))
GDELT_DEFAULT_DAYS = int(os.getenv("GDELT_DEFAULT_DAYS", "30"))

# User-Agent commun aux requêtes OSINT (politesse + contact, comme Wikimedia).
OSINT_USER_AGENT = os.getenv(
    "OSINT_USER_AGENT", "FACE.ai/1.0 (veille open-data; contact@ok-ia.ch)"
)
