# Cahier des charges — v3.1 (contrat · recherche · état réel)

**Projet** : Reconnaissance d'objets connectés pour audit de sécurité IoT  
**Auteur** : Mohamed Salhi — Polytech Lille / ENSA Kénitra · **Tuteur** : Thomas Vantroys  
**Statut** : Contrat normatif de référence | Révision du 24/09/2026 (Annule et remplace v1 et v2)  
**Horizon** : 15/09/2026 → 15/12/2026 (13 semaines, capacité effective : 60 à 73 j·h)

---

## 1. Épistémologie du problème & Limite fondamentale

### 1.1 Principe du pipeline unidirectionnel
Le système opère un flux de données strictement descendant sans boucle rétroactive :

$$\mathcal{I}_{\text{photo}} \xrightarrow[\text{Guided Decoding}]{\text{VLM } + \text{ OCR}} (\text{Marque}, \text{Modèle}, \text{Catégorie}) \xrightarrow[\text{FTS5 / Levenshtein}]{\text{Résolution CPE}} \text{CPE}_{\text{hardware}} \xrightarrow[\text{Algèbre d'intervalles}]{\text{Requête NVD}} \{\text{CVE}\}_{\text{produit}} \xrightarrow{\text{HMAC + Ed25519}} \text{Rapport PDF}$$

1. **Identifier** : à partir d'UNE photo d'UN équipement, extraire marque, modèle et catégorie parmi 5 catégories fermées (`smart_plug`, `ip_camera`, `smart_bulb`, `router_ap`, `smart_speaker`).
2. **Rattacher** : associer cette identité lexicale à une entrée produit du dictionnaire NIST CPE 2.3 local (`part='h'`).
3. **Remonter** : sélectionner les CVE associées à ce modèle depuis la base NVD locale (zéro appel externe en cours d'audit).
4. **Sceller & Rapporter** : produire un PDF d'audit opposable, horodaté, scellé par journal chaîné HMAC-SHA256 et signé par clé asymétrique Ed25519.

### 1.2 La barrière infranchissable : Triage Produit-Level (`triage_scope='product'`)
Une photographie montre un boîtier externe, **jamais la version du firmware interne**.
- Le système effectue un **triage au niveau modèle** : il liste les vulnérabilités historiquement déclarées sur ce produit.
- **Interdiction formelle** d'affirmer qu'un exemplaire inspecté est vulnérable. Mention obligatoire : *« concerne ce produit — version firmware non déterminée »*.
- **Interdiction formelle** de présenter l'absence de CVE comme une preuve de sécurité (émission du code `E_NO_CVE`).
- Rejet de tout score de risque global agrégé ($\max(\text{CVSS})$), systématiquement pessimiste et non actionnable pour l'auditeur.

---

## 2. État d'avancement réel au 24/09/2026 (Faits prouvés & Chiffrés)

| Brique technique | État réel vérifié | Source / Preuve |
|---|---|---|
| **Inférence VLM (Qwen2.5-VL)** | vLLM 0.29.0 déployé sur zabeth21/22/23. 144/144 images rendues. Exactitude 79/144 [0.460 ; 0.621], supériorité prouvée face à Qwen3 (53/144) et Llama 3.2. | `evidence/2026-09-16/zabeth22/head2head/SUMMARY.md` |
| **Banc 3 nœuds parallèle** | Les 3 nœuds répondent simultanément : $p_{50}$ = 1.80s (z21), 1.96s (z22), 2.88s (z23). Accord inter-nœuds = 100%. | `evidence/2026-09-24/bench-3nodes.json` |
| **Dictionnaire CPE NIST** | 1 838 235 entrées (dont 64 842 hardware `part='h'`) stockées localement sous SQLite WAL. | `corpus/cpe.sqlite` |
| **Base NVD 2021-2024 locale** | 324 470 critères hardware (`part='h'`) et 121 719 CVEs ingérés en 11s en streaming avec zéro doublon. | `corpus/nvd.sqlite`, `evidence/2026-09-24/nvd-ingest.log` |
| **Moteur search_cve** | Algèbre de plages et exclusion `NEGATE` validées par 40 tests pytest (100% PASS). Latence réelle : $p_{50} = 1.54\text{ ms}$, $p_{95} = 3.48\text{ ms}$. | `evidence/2026-09-24/cve-search-bench.json` |
| **Corpus photographique** | 48 objets réels, 144 images exploitables, stratifié par contamination (`label` vs `visual`), 11 orphelines isolées. | `corpus/corpus.sqlite`, `manual-removals.json` |
| **Confinement réseau** | Confinement egress `nftables DROP` vérifié : 0 paquet émis vers des tiers pendant le traitement. | `evidence/2026-09-16/v12-egress-rerun/` |
| **Gestion des versions Git** | Dépôt Git initialisé, code versionné, données lourdes exclues proprement, lockfile scellé. | Commit `f36ca41`, `requirements.lock` |

---

## 3. Périmètre contractuel

### 3.1 Dans le périmètre (MVP)
- **1 photo = 1 équipement** bien cadré (rejet propre `E_MULTI_OBJECT_OR_UNCLEAR` si ambigu).
- **5 catégories fermées** : prise, caméra IP, ampoule, routeur/AP, enceinte connectée.
- **Base 100% locale** : interrogation hors-ligne de SQLite FTS5 et NVD sans aucune dépendance externe en cours de run.
- **Scellement cryptographique** : journalisation chaînée HMAC et signature Ed25519 pour opposabilité de l'audit.

### 3.2 Hors périmètre (assumé)
- Déduction magique du firmware par l'image (impossible).
- Détection multi-objets dans une scène encombrée.
- Scan réseau actif ou intrusion (interdit sans mandat légal écrit — art. 323-1 CP).

---

## 4. Portes de validation jalonnées (G0 à G7)

- **G0 (21/09) — Socle & Traçabilité :** ✅ **CLOS** (Dépôt Git initialisé, lockfile scellé, corpus 144 images nettoyé).
- **G1 (19/10) — Ingestion & Moteur CVE :** ✅ **CLOS** (Ingestion NVD 2021-2024 idempotente, $p_{95} < 5\text{ ms}$, 40/40 tests PASS).
- **G2 (02/11) — Résolution CPE FTS5 :** Normalisation syntaxique + FTS5 trigrammes. Banc 200 paires validé avec IC Wilson.
- **G3 (23/11) — Orchestration E2E & Rejeu :** Pipeline complète Photo $\to$ CVE en mode dégradé (1 nœud sain, NVD locale coupée).
- **G4 (30/11) — Chaîne d'Intégrité :** HMAC séquentiel + signature Ed25519, détection des altérations validée par tests d'injection.
- **G5 (07/12) — API & Démonstration :** API HTTP locale minimale pour ingestion et restitution de rapports signés.
- **G6 (14/12) — Gel Métrologique :** Recompilation automatisée des métriques du corpus stratifié par script.
- **G7 (15/12) — Clôture & Soutenance :** Rapport final, carnet de réfutation orale, archive autonome scellée.
