# Tester le serveur MCP FACE.ai — 10 prompts

> Une fois `claude mcp add --transport sse --scope local face-ai http://127.0.0.1:8011/sse`
> exécuté et `/mcp` ouvert dans Claude Code, tu peux soumettre les prompts ci-dessous.
> L'ordre va du plus simple au plus complexe — chaînage de plusieurs outils
> et analyse éditoriale en fin de liste.

---

## Niveau 1 — un seul outil, requête directe

### 1. État global du corpus
```
Donne-moi un aperçu général du corpus FACE.ai.
```
**Outil attendu** : `get_corpus_stats`
**Vérification** : tu dois voir totaux (entités/images/articles), top 10 entités par volume, distribution des poses (front/left/right), taux d'alignement.

---

### 2. Recherche par nom partiel
```
Y a-t-il dans la base des personnes dont le nom contient "altm" ?
```
**Outil attendu** : `search_entities` (préfixe FTS5)
**Vérification** : doit retrouver Sam Altman avec son slug, ses compteurs et son score de diversité.

---

### 3. Profil enrichi
```
Quel est le profil complet d'Emmanuel Macron dans FACE.ai ?
```
**Outil attendu** : `get_entity_profile`
**Vérification** : bio Wikidata (date de naissance, lieu, occupations, employer Rothschild & Cie), distribution des poses, sources médias, plage temporelle, nombre de doublons.

---

### 4. Images avec filtre
```
Montre-moi les portraits de Sam Altman au profil gauche, hors doublons.
```
**Outils attendus** : `get_entity_images` avec `pose=left`, `unique_only=true`
**Vérification** : liste d'images avec aligned_url, caption, distance ArcFace, lien article.

---

## Niveau 2 — comparaison ou agrégation

### 5. Comparaison de deux personnalités
```
Compare la couverture médiatique de Sam Altman et Elon Musk dans FACE.ai. 
Combien d'articles partagés ?
```
**Outil attendu** : `compare_entities`
**Vérification** : volumes d'images/articles côté à côte + `cooccurrence_articles` (nombre d'articles citant les deux).

---

### 6. Pic de visibilité dans le temps
```
Trace l'évolution mensuelle des mentions de Donald Trump. 
Y a-t-il des pics suspects ?
```
**Outil attendu** : `get_media_timeline` avec `granularity=month`
**Vérification** : buckets `[{period: "2024-MM", count: N}, ...]`. Claude devrait commenter les pics éventuels.

---

## Niveau 3 — chaînage et analyse éditoriale

### 7. Synthèse pour brief
```
Prépare une note de brief de 5 lignes max sur Yoshua Bengio à partir de FACE.ai.
```
**Outils attendus** : `get_entity_profile` (pour la bio + stats)
**Vérification** : Claude doit synthétiser bio + couverture sans inventer (les chiffres viennent du MCP, pas de sa connaissance générale).

---

### 8. Détection d'anomalie
```
Pour Sam Altman, dis-moi s'il y a des associations d'images douteuses 
qui mériteraient un audit manuel.
```
**Outils attendus** : `get_entity_images` (sans `unique_only`)
**Vérification** : Claude doit lire `identity_match_score` et `association_status` de chaque image, signaler celles `flagged` ou avec `score > 0.4`. Bonus : il peut suggérer d'aller dans l'UI `/audit`.

---

### 9. Comparaison statistique multi-outils
```
Qui de Trump, Musk ou Macron a la plus grande diversité visuelle 
dans FACE.ai, et pourquoi ? Donne-moi des chiffres.
```
**Outils attendus** : `get_entity_profile` × 3 (un par personne) ou `compare_entities` × N
**Vérification** : Claude doit appeler 3 fois (ou 3 comparaisons) puis ranger par `diversity_score` desc et expliquer (variété d'images, sources, poses).

---

### 10. Analyse éditoriale complète (le plus exigeant)
```
Fais-moi une analyse de la couverture médiatique de Sam Altman dans le 
corpus FACE.ai : volume relatif, sources principales, évolution dans le 
temps, qualité des associations, et trois angles d'analyse possibles 
pour un papier de fond.
```
**Outils attendus** : `analyze_visibility_pattern` (qui combine déjà profil + timeline + titres + instructions LLM), éventuellement complété par `get_corpus_stats` pour le contexte relatif.
**Vérification** : Claude doit produire une analyse structurée avec **chiffres tirés du MCP** (pas de connaissance générale plaquée), nommer les sources dominantes, identifier les pics chronologiques et proposer des angles concrets (ex. "concentration de couverture sur 3 sources US, sous-représentation de la presse asiatique").

---

## Bonus — tester les cas limites

### A. Entité inexistante
```
Donne-moi le profil de "Yoshua Inexistant".
```
**Comportement attendu** : `get_entity_profile` retourne `{"error": "entité 'yoshua-inexistant' introuvable"}`. Claude doit le signaler proprement, ne pas halluciner.

### B. Comparaison entre 2 inconnus
```
Compare Marcel Duchamp et André Breton dans FACE.ai.
```
**Comportement attendu** : si les deux sont absents, message d'erreur clair. Claude peut **proposer** d'ajouter une entité via WUDD si elle existe là-bas (mais ce n'est pas un outil exposé — il devra dire "ces personnes ne sont pas dans le corpus actuel").

### C. Recherche multi-mots
```
Cherche "elon musk" dans la base.
```
**Comportement attendu** : FTS5 traite "elon musk" comme deux tokens, doit ramener Elon Musk par le préfixe `elon* musk*`.

---

## Critère général de qualité

Pour chaque réponse Claude, vérifier :

1. **Aucune invention** : tous les chiffres et faits doivent venir d'un appel MCP, pas de la connaissance générale du modèle.
2. **Citation des sources outils** : Claude devrait être transparent sur les outils qu'il a appelés.
3. **Limites assumées** : si une donnée n'est pas dans le corpus, le dire clairement (pas de placeholder).
4. **Reformulation FR cohérente** : le serveur retourne du JSON anglais/français mélangé (ex. `wikipedia_summary` en FR, mais `pose: "front"`). Claude doit produire une sortie 100 % française.

---

## Pour aller plus loin

Après ces 10 tests, des cas d'usage qui valent la peine :
- "Liste les 5 personnalités les plus mentionnées que je n'ai pas marquées favorites" → mix MCP + connaissance des favoris (Claude doit demander si le corpus expose `is_favorite` — pour l'instant non exposé en MCP, à ajouter si utile).
- "Quels patterns de pose émergent chez les CEOs tech vs hommes politiques ?" → analyse cross-entités, exigeant.
- "Si je veux faire un papier sur la concentration de la presse tech autour d'OpenAI, quelles entités prioriser ?" → recommandation éditoriale basée sur `compare_entities` + `get_media_timeline`.
