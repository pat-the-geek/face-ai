# Plan de migration SQLite → PostgreSQL

> **Statut** : non urgente. Spec §19 fixe le seuil de migration à
> **> 100 000 images**. À ce jour (snapshot mai 2026) : ~500 images,
> 1100 entités, 8 000 articles. Marge confortable. Ce document est un
> plan d'action quand le seuil sera approché, pas un chantier ouvert.
>
> SQLite tient très bien jusqu'à 50-100k images sur un SSD moderne
> (lecture FTS5 sub-ms, writes < 10 ms). Au-delà, deux limites
> émergent :
> 1. **Locking pessimiste sur writer unique** : le worker FACE.ai
>    enchaîne plusieurs cycles concurrents (analyze, enrich, dedup,
>    merge, wudd_sync…) sur la même DB. Avec un volume haut, les
>    timeouts apparaissent.
> 2. **FTS5 dégrade à grand volume** : les requêtes de recherche
>    globale (Cmd+K) deviennent visibles côté UX (> 500 ms).
>
> PostgreSQL bascule en MVCC propre + `tsvector`/GIN/`pg_trgm` qui
> tient au-delà du million de rows. Trade-off : un service de plus à
> opérer.

---

## A. Pré-requis avant migration

### Volume

Critère de bascule (chiffres à mesurer via `/metrics` au moment de la
décision) :

- `face_ai_images_total` > 100 000
- ET (au moins une des deux) :
  - Latence p95 sur `/search?q=…` > 300 ms en mode local
  - Worker `record_error{loop=*}` non nul > 5/jour (indice de
    contention writer)

### Pré-validation

À tester avant de basculer en prod :

```bash
# 1. Dimensionnement : la DB SQLite actuelle compresse à combien ?
ls -lh data/face_ai.db data/backups/daily-*.db.gz | head -5

# 2. Si VACUUM réduit beaucoup, l'index est fragmenté et SQLite vit
#    avec son passé. Mesurer après VACUUM :
sqlite3 data/face_ai.db "VACUUM;"

# 3. EXPLAIN sur les requêtes lentes pour identifier ce qui souffre
sqlite3 data/face_ai.db "EXPLAIN QUERY PLAN SELECT … FROM entities_fts MATCH 'physique';"
```

Si VACUUM + bonnes indexes suffisent, **différer la migration**. Postgres
est un service de plus à opérer (backup, monitoring, upgrades).

---

## B. Architecture cible

### Stack

```
Avant                            Après
─────                            ─────
SQLite + FTS5 + triggers   →    PostgreSQL 16 + tsvector + GIN
sqlite3 (stdlib)            →   psycopg2-binary 2.9.x
                                ou psycopg 3.x (asyncio-ready)

Bind mount /data/face_ai.db →   Service docker `db` (PostgreSQL)
                                Volume nommé `pgdata`

alembic.ini :                   alembic.ini :
sqlalchemy.url = sqlite:///…    sqlalchemy.url = postgresql+psycopg2://…
```

### docker-compose.yml additions

```yaml
db:
  image: postgres:16-alpine
  volumes:
    - pgdata:/var/lib/postgresql/data
  environment:
    - POSTGRES_USER=faceai
    - POSTGRES_PASSWORD=…  # via .env, jamais en clair
    - POSTGRES_DB=faceai
  ports:
    - "127.0.0.1:5432:5432"  # LAN-only, cf. CLAUDE.md §13.9
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U faceai"]
    interval: 5s

volumes:
  pgdata:

api:
  depends_on:
    db:
      condition: service_healthy
  environment:
    - DATABASE_URL=postgresql+psycopg2://faceai:${POSTGRES_PASSWORD}@db:5432/faceai
```

`config.py` :
```python
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
```

---

## C. Mapping SQLite → PostgreSQL

### Types

| SQLite | PostgreSQL | Notes |
|---|---|---|
| `INTEGER PRIMARY KEY` | `SERIAL PRIMARY KEY` ou `BIGINT GENERATED ALWAYS AS IDENTITY` | les 2 fonctionnent |
| `TEXT` | `TEXT` | identique |
| `BLOB` | `BYTEA` | embeddings (pHash, ArcFace 512-dim) |
| `BOOLEAN` ('0'/'1') | `BOOLEAN` (true/false) | SQLAlchemy gère, mais nettoyer les defaults SQL |
| `DATETIME` `CURRENT_TIMESTAMP` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | identique |
| `FLOAT` | `DOUBLE PRECISION` (ou `REAL`) | identique côté SQLAlchemy |

**Attention pHash/ArcFace** : on stocke en `BLOB`/`BYTEA` bytes brutes
(via `serialize()`/`deserialize()`). Postgres a `BYTEA` natif, le port
est neutre. La taille reste 8 octets (pHash) et 2048 octets (ArcFace).

### FTS5 → tsvector + GIN

C'est le gros morceau du port.

**Côté SQLite** (3 tables FTS5) :
- `entities_fts` (v018) : name, aliases, occupations, employer,
  nationalities, birth_place, summary
- `articles_fts` (v019) : title, source_domain
- `images_fts` (v020) : caption, alt_text, copyright_text

**Côté PostgreSQL** : 3 colonnes générées `tsvector` indexées en GIN.

Exemple pour `entities` :
```sql
ALTER TABLE entities
ADD COLUMN search_tsv tsvector
GENERATED ALWAYS AS (
    setweight(to_tsvector('french', coalesce(name, '')), 'A')
 || setweight(to_tsvector('french',
        coalesce((SELECT string_agg(alias, ' ')
                  FROM entity_aliases
                  WHERE entity_id = entities.id), '')), 'B')
 || setweight(to_tsvector('french', coalesce(replace(occupations, '|', ' '), '')), 'C')
 || setweight(to_tsvector('french', coalesce(employer, '')), 'C')
 || setweight(to_tsvector('french', coalesce(replace(nationalities, '|', ' '), '')), 'D')
 || setweight(to_tsvector('french', coalesce(birth_place, '')), 'D')
 || setweight(to_tsvector('french', coalesce(wiki_summary, '')), 'D')
) STORED;

CREATE INDEX entities_search_tsv_idx ON entities USING GIN (search_tsv);
```

**Mais** : `GENERATED ALWAYS AS … STORED` ne peut pas faire de sous-
requête (limitation Postgres). Solution : trigger qui recompute à
chaque modification de `entities` OU `entity_aliases`. Pattern :

```sql
CREATE OR REPLACE FUNCTION entities_search_tsv_update() RETURNS trigger AS $$
BEGIN
    UPDATE entities SET search_tsv = (
        setweight(to_tsvector('french', coalesce(name, '')), 'A')
     || setweight(to_tsvector('french',
            coalesce((SELECT string_agg(alias, ' ') FROM entity_aliases WHERE entity_id = NEW.entity_id), '')), 'B')
     -- … etc.
    ) WHERE id = NEW.entity_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

C'est l'équivalent fonctionnel des triggers `entity_aliases_fts_ai/au/ad`
qu'on a en SQLite (cf. migrations v018, v022).

**Recherche côté Python** :
```python
# SQLite (actuel)
stmt = select(Entity).from_statement(
    text("SELECT e.* FROM entities_fts f JOIN entities e ON e.id = f.rowid "
         "WHERE entities_fts MATCH :q ORDER BY rank LIMIT :limit")
).params(q=fts_query, limit=limit)

# Postgres (cible)
stmt = (
    select(Entity, func.ts_rank(Entity.search_tsv, query).label("rank"))
    .where(Entity.search_tsv.op("@@")(func.websearch_to_tsquery("french", q)))
    .order_by(desc("rank"))
    .limit(limit)
)
```

`websearch_to_tsquery` gère les guillemets, le ET implicite, le `-` pour
exclusion — équivalent au mode FTS5 standard de SQLite.

### Tokenizer / accents

SQLite FTS5 utilise `unicode61 remove_diacritics 2`. Équivalent
PostgreSQL :
- `to_tsvector('french', …)` : Snowball français, gère bien les
  accents et les pluriels
- Pour un comportement plus proche du SQLite (suppression accents
  pure, pas de stemming) : `unaccent(…)` avant `to_tsvector('simple', …)`

Recommandation : essayer `'french'` d'abord, fallback `unaccent` +
`'simple'` si le stemming pose des faux positifs sur les noms propres.

### Triggers à porter

| Migration SQLite | Équivalent Postgres |
|---|---|
| v009-v011 `entities_fts` triggers | trigger PL/pgSQL sur `entities` + `entity_aliases` |
| v018 `entities_fts` étendu (bio) | idem, recompute la colonne `search_tsv` |
| v019 `articles_fts` | trigger sur `articles` |
| v020 `images_fts` | trigger sur `images` |
| v022 `entity_aliases_fts_au_eid` (UPDATE OF entity_id) | trigger Postgres standard `BEFORE UPDATE OF entity_id` |

### Différences sémantiques à surveiller

1. **`PRAGMA foreign_keys=ON`** absent côté SQLite (cf. CLAUDE.md).
   PostgreSQL **active** les FK par défaut → toutes les cascades
   `ondelete="CASCADE"` qui étaient ignorées vont s'activer
   automatiquement. Côté code Python, les DELETE explicites manuels
   deviendront redondants (mais inoffensifs).

2. **`AUTOINCREMENT`** : Postgres `SERIAL` ne réutilise jamais les IDs
   supprimés (alors que SQLite peut). Aucun code FACE.ai ne devrait
   s'appuyer sur la séquentialité des IDs, mais vérifier.

3. **`is_duplicate BOOLEAN server_default='0'`** : la chaîne `'0'` est
   un truc SQLite. Postgres veut `'false'` ou `false`. À nettoyer dans
   tous les `Column(... server_default="0")`. Bonne nouvelle :
   SQLAlchemy converti automatiquement à l'écriture, donc le code
   Python reste inchangé, juste les `server_default` ORM à revoir.

4. **Types `TEXT` sans longueur max** : OK des deux côtés, pas de
   `VARCHAR(N)` requis sous Postgres moderne (TOAST gère).

---

## D. Procédure de migration (1 passe, ~1h)

### Étape 1 — Préparer la cible

```bash
# Démarre uniquement le service db, vide
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d db

# Applique les migrations Alembic sur la cible
docker compose exec api alembic -x dburl=postgresql+psycopg2://… upgrade head
```

Note : il faudra créer des **migrations PostgreSQL-spécifiques**
(v0xx_postgres_fts.py) qui montent les colonnes `tsvector` et les
triggers, en remplacement des migrations v009-v022 FTS5.

### Étape 2 — Dump SQLite → Postgres

Option A : via SQLAlchemy en Python (lent mais sûr) :
```python
# backend/migrate_to_postgres.py
from sqlalchemy import create_engine
from database import Article, ArticleEntity, Entity, EntityAlias, Image, FaceAnalysis, Base

src = create_engine("sqlite:///data/face_ai.db")
dst = create_engine(os.environ["DATABASE_URL"])

with src.connect() as src_conn, dst.begin() as dst_conn:
    # Ordre des tables : FK respectées
    for model in [Article, Entity, EntityAlias, ArticleEntity, Image, FaceAnalysis]:
        rows = src_conn.execute(select(model)).all()
        if not rows:
            continue
        dst_conn.execute(
            model.__table__.insert(),
            [dict(r._mapping) for r in rows],
        )
        # Reset la séquence Postgres pour éviter les collisions
        dst_conn.execute(text(f"SELECT setval('{model.__tablename__}_id_seq', "
                              f"(SELECT MAX(id) FROM {model.__tablename__}))"))
```

Option B : via `pgloader` (outil dédié, plus rapide pour > 1M rows) :
```bash
pgloader sqlite:///data/face_ai.db \
         postgresql://faceai:…@db:5432/faceai
```

`pgloader` convertit aussi les types automatiquement, mais ne porte
PAS les triggers FTS — il faudra les recréer après chargement via les
migrations PostgreSQL-spécifiques.

### Étape 3 — Repopuler les `tsvector`

```sql
-- Force le calcul initial sur toutes les rows (triggers ne se
-- déclenchent qu'au prochain UPDATE)
UPDATE entities SET id = id;
UPDATE articles SET id = id;
UPDATE images SET id = id;
```

### Étape 4 — Tests d'intégrité

```bash
# Compte des rows par table
docker compose exec db psql -U faceai -c \
    "SELECT 'entities', COUNT(*) FROM entities
   UNION ALL SELECT 'articles', COUNT(*) FROM articles
   UNION ALL SELECT 'images', COUNT(*) FROM images;"

# Doit matcher avec :
sqlite3 data/face_ai.db "SELECT 'entities', COUNT(*) FROM entities
                       UNION ALL SELECT 'articles', COUNT(*) FROM articles
                       UNION ALL SELECT 'images',   COUNT(*) FROM images;"

# Test recherche FTS
curl 'http://localhost:8010/search?q=physicien&scope=entities'
```

### Étape 5 — Bascule worker

```bash
# Stop worker SQLite
docker compose stop worker

# Update docker-compose.yml : DATABASE_URL pointe sur postgres
# Restart api + worker
docker compose up -d api worker

# Watch logs : pas d'erreurs SQLAlchemy au démarrage
docker compose logs -f api worker
```

### Étape 6 — Backup SQLite final + cleanup

```bash
cp data/face_ai.db data/face_ai-pre-pg-migration-$(date +%F).db
# Garder pendant 1-2 mois avant suppression
```

---

## E. Choses **à ne pas faire**

- ❌ **Migrer pendant un cycle worker actif** : risque d'incohérence.
  Stopper le worker complètement avant le dump.
- ❌ **Garder les triggers SQLite FTS5 dans Postgres** : `entities_fts`
  n'existe pas en PG, les CREATE TRIGGER se planteraient. Les
  migrations v009-v022 doivent être **conditionnées** sur `dialect ==
  'sqlite'`, et de nouvelles migrations PG-only doivent prendre le
  relais.
- ❌ **Activer la FK cascade Postgres sans relire `entity_cleanup` et
  `entity_merge`** : ces modules font des cascades manuelles
  (`DELETE FROM article_entities WHERE entity_id = …`) qui supposent
  que la cascade DB est inactive. Postgres avec FK actives va
  cascader **deux fois** — pas un bug mais du gaspillage.
  Soit on désactive la FK Postgres (`SET CONSTRAINTS … DEFERRED`),
  soit on simplifie les modules Python.
- ❌ **Faire la migration sans backup pré-restore** : si on découvre
  une mauvaise sémantique 2 semaines plus tard, on veut pouvoir
  revenir.

---

## F. Estimation effort

| Étape | Effort |
|---|---|
| Setup `docker-compose.postgres.yml` | 30 min |
| Migrations Alembic PG-spécifiques (FTS) | 2-3 h |
| Script de dump (option A) ou pgloader (option B) | 1 h |
| Test sur DB de copie + validation requêtes | 2 h |
| Bascule prod | 30 min (worker arrêté ~10 min) |
| **Total** | **6-7 h** |

À 100k images on n'aura pas envie d'un downtime > 30 min. À 500k+ ce
sera obligatoire. Plus on attend, plus le dump prend longtemps : ~1
ligne/ms en mode SQLAlchemy = 500k rows = 8 min, ou 30s avec
`pgloader`. Pas critique.

---

## G. Ce qui devra être réécrit (côté code)

Liste des modifications quand on aura décidé de migrer :

1. **`backend/migrations/versions/`** : marquer v009-v022 comme
   `skip_postgres` (ou créer des doublons PG-spécifiques).
2. **`backend/api.py`** : reformuler les recherches FTS5 (env. 8
   endroits : `/entities/search`, `/search`, `/audit?q=`, autocomplete
   global). Pattern unique via une fonction `text_search(query, scope)`
   à créer.
3. **`backend/face_ai_mcp_server.py`** : idem pour `search_entities`
   MCP tool.
4. **`backend/database.py`** : changer les `server_default="0"` en
   booléens propres.
5. **`backend/tests/conftest.py`** : on garde SQLite pour les tests
   (rapidité), `DATABASE_URL` overridable via env. Les tests ne
   testent pas les triggers FTS spécifiques au moteur (sauf
   `test_global_search.py` qui devra être conditionnel).

---

## H. Quand reconsulter ce doc

- Quand `/metrics` renvoie `face_ai_images_total > 80000` (avant
  l'urgence)
- Si la recherche globale Cmd+K devient visiblement lente (> 500 ms)
- Si on observe des `record_error` worker liés à `OperationalError:
  database is locked` (signe de contention writer)

Sinon : laisser dormir. SQLite est très bien pour notre échelle.
