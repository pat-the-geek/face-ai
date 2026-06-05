# Conformité — enrichissement OSINT (v030)

Document de référence pour la couche de veille OSINT ajoutée en v030. À lire
avant tout élargissement du périmètre OU toute diffusion hors LAN.

## 1. Cadre de la décision (2026-06-05, propriétaire Patrick Ostertag)

FACE.ai croise son corpus avec des sources **open data** externes. Cadre
**contraignant** fixé par le propriétaire :

- **Uniquement des données open source** (gratuites, publiques).
- **Uniquement des personnes publiques déjà présentes dans le corpus** (issues
  de WUDD.ai). Aucun ciblage d'inconnus, aucune découverte.
- **Aucune inférence, aucune source privée.** On ne reprend que ce que la
  source publie telle quelle.

Ce cadre prolonge la posture §1.5 (cf. CLAUDE.md) sur le **périmètre des
personnes**. Il s'en écarte en revanche sur les **catégories de données** pour
deux sources (voir §2).

## 2. Catégories de données et base légale

| Source | Donnée | Catégorie RGPD | Base / posture |
|---|---|---|---|
| Wikidata P27→P297 | pays (`country_code`) | ordinaire | intérêt légitime (art. 6.1.f) |
| Wikimedia Commons | portraits libres | ordinaire | intérêt légitime |
| parlament.ch | mandat parlementaire | ordinaire (fonction publique) | OGD suisse |
| GDELT | couverture médiatique agrégée | ordinaire | intérêt légitime |
| Wayback | portraits archivés | ordinaire | intérêt légitime |
| GLEIF | organisations légales | ordinaire | registre public |
| **OpenSanctions** | **statut PEP / sanctions / criminel** | **art. 9 + art. 10** | **dérogation tracée** |
| **ICIJ Offshore Leaks** | **présence dans fuites offshore** | **art. 9/10 + présomption d'innocence** | **dérogation tracée** |

Les deux dernières lignes **sortent du régime d'intérêt légitime**. Le
propriétaire a choisi de les **stocker et exposer en LAN** en connaissance de
cause. Atténuations : personnes publiques uniquement + données déjà publiques
reprises sans inférence (proche de l'art. 9.2.e « manifestement rendues
publiques », sans l'établir automatiquement).

> **Action recommandée** : revue de conformité art. 9/10 (fondement 9.2.e
> et/ou 9.2.j recherche/archivage) **avant toute diffusion élargie** ou mise
> en ligne hors LAN.

## 3. Frontière LAN — invariant technique

**Les données OSINT sensibles (OpenSanctions/PEP, ICIJ) ne franchissent JAMAIS
la frontière réseau.** Elles sont consultables uniquement en LAN (API/MCP/UI
Tailscale, ports liés à `100.72.122.51`, jamais `0.0.0.0`).

Surfaces **hors LAN** et leur traitement :

| Surface | Sortie | Données sensibles ? |
|---|---|---|
| Notifications Discord (`notifications.py`) | hors LAN | **exclues** — scénarios E/F/G non sensibles uniquement |
| Export Markdown (`/entities/{slug}/export.md`) | copiable | **exclues** (`bibliography.py`, art. 9 déjà exclu) |
| Export JPG (`/entities/{slug}/export.jpg`) | image diffusable | **exclues** (`export.py` ne référence aucun champ sensible) |
| Fiche de veille Discord (`synthesis_card.py`) | hors LAN | **exclues** (faits publics + signaux corpus seulement) |

Garde-fou automatisé : `tests/test_osint.py::test_markdown_export_excludes_sensitive_osint`
échoue si une régression fait fuiter `sanction`/`ofac`/`panama`/`icij`/`pep`
dans l'export Markdown. Étendre ce test si un nouvel exporter hors LAN est créé.

## 4. Checklist avant tout nouveau chantier OSINT

- [ ] La source est-elle **open data** et la donnée **publique** ? Sinon : stop.
- [ ] Le traitement reste-t-il borné aux **personnes publiques du corpus** ?
- [ ] Y a-t-il une **inférence** (déduire un attribut depuis le visage/texte) ?
      Si oui : **nouvelle décision séparée** (sort du cadre §1, cf. CLAUDE.md).
- [ ] La donnée est-elle de **catégorie art. 9/10** ? Si oui : la cantonner au
      LAN, l'exclure de toutes les surfaces du §3, et l'inscrire dans ce tableau.
- [ ] Mise en ligne **hors LAN** envisagée ? Si oui : revue de conformité
      art. 9/10 obligatoire **avant**.

## 5. Effacement / rectification

Les champs OSINT sont des colonnes nullables sur `entities` (+ table
`entity_gdelt_coverage`). Pour purger une donnée sensible d'une entité :
`UPDATE entities SET sanctions_status=NULL, sanctions_detail=NULL,
icij_match=0, icij_detail=NULL WHERE slug='…';`. Les scripts d'ingestion sont
idempotents et réécrivent au prochain run — pour exclure durablement une
personne, retirer sa correspondance source ou la sortir du corpus.
