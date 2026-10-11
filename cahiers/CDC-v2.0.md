# Cahier des charges — v2.0

**Projet** : Reconnaissance d'objets connectés pour audit de sécurité IoT
**Auteur** : Mohamed Salhi 
**Tuteur** : Thomas Vantroys
**Date de rédaction** : 15 septembre 2026
**Horizon** : 13 semaines (15/09/2026 → 15/12/2026), **en capacité effective ≈ 60 j·h** (§9)

## §1 · Contexte et besoin

### 1.1 Le besoin opérationnel

Lors d'un audit de sécurité en environnement réel, l'auditeur fait face à un parc d'objets connectés dont il ne connaît ni la marque, ni le modèle, ni les vulnérabilités connues. L'identification manuelle est lente et son exhaustivité dépend de la mémoire de l'auditeur. Le système visé **accélère la phase de reconnaissance** : d'une photographie, il déduit l'identité produit de l'objet, la rattache au référentiel NIST (CPE) et remonte les vulnérabilités connues (CVE) du produit depuis une base **locale**, puis produit un rapport d'audit traçable.

### 1.2 Le périmètre réel : **triage au niveau produit**

Le système est un outil de **triage produit-level**. Il répond à la question comme ça :

> « *Cet objet est un TP-Link Archer C7, et **ce produit** a des CVE connues.* »

Il ne répond **jamais** à :

> « *Cet exemplaire précis est vulnérable.* »

La distinction n'est pas une nuance de rédaction : une photographie identifie un **modèle**, jamais une **version de firmware**, et les CVE sont rattachées à des versions de firmware ou à des plages de versions. L'intervalle est structurel et **infranchissable** au sein de ce projet (§2).

### 1.3 Infrastructure

**Conséquence de méthode** : la ressource rare n'est plus le temps calendaire, c'est l'**attention disponible** (§9). Le planning est donc bâti sur des **portes démontrables en une séance** (§9.3), pas sur des dates.

---

## §2 · La limite structurelle (non négociable)

```
photo ──► (marque, modèle) ──► identifiant CPE « produit » ──► CVE du produit
  │              │                        │                          │
  │              │                        │                          └─ vraie pour CERTAINES
  │              │                        │                             versions de firmware
  │              │                        └─ identifie un MODÈLE, pas un exemplaire
  │              └─ probabiliste : mesure d'accord, jamais une certitude
  └─ ne contient AUCUNE information de version
```

`cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*` désigne une **révision matérielle**, pas le firmware. La distance entre « voici les CVE de ce produit » et « cet exemplaire est vulnérable » est un intervalle **que le système ne franchit pas**.

**Conséquences d'ingénierie, pas seulement de rédaction :**

1. le rapport **ne présente jamais** de score de risque agrégé (`« l'objet est à 7,5/10 »`). Un CVSS agrégé pour un produit est un maximum sur toutes les versions : systématiquement pessimiste et non actionnable ;
2. chaque CVE affichée porte la mention **« concerne ce produit — version firmware non déterminée »** ;
3. le champ `triage_scope = 'product'` est écrit **dans la base**, pas seulement dans le PDF ;
4. l'absence de CVE **n'est jamais** présentée comme une absence de vulnérabilité (code `E_NO_CVE`, message non rassurant).

### 2.1 Les deux affirmations interdites

| Interdit | Motif |
|---|---|
| « Ces CVE concernent l'exemplaire audité » | la photo ne porte aucune information de version |
| « L'objet est sûr s'il n'y a pas de CVE » | l'absence de CVE référencée ≠ absence de vulnérabilité |

**Ce qu'il ne faut pas dire** : « détecte les vulnérabilités », « score de risque de l'appareil », « 90 % de précision » (sans `n` ni intervalle), « signé donc non répudiable ».
**Ce qu'il faut dire** : « triage produit-level », « identifie le produit, pas la version », « la confiance mesure l'accord, pas la justesse », « le HMAC prouve l'intégrité **sous le détenteur de la clé** ».

---

## §3 · Périmètre et état d'avancement réel

### 3.1 Dans le périmètre

| # | Élément | Sortie attendue | État 15/09 |
|---|---|---|---|
| P1 | Une photo = **un objet** cadré | sinon `E_MULTI_OBJECT_OR_UNCLEAR` (rejet, aucune tentative) | 🟡 |
| P2 | **5 catégories** : prise, caméra IP, ampoule, routeur/AP, enceinte | mapping catégorie validé sur échantillon étiqueté | ✅ 48 objets, 5/5 |
| P3 | Corpus photos internet, stratifié par risque de contamination, provenance complète | corpus gelé + vérité terrain | ✅ 48 objets / **144 images** |
| P4 | Inférence **100 % locale** | test d'absence d'egress | 📐 V12 les 3 nœuds |

### 3.2 Hors périmètre (assumé)

| Élément | Statut |
|---|---|
| Version de firmware déduite d'une photo | **impossible** — c'est la limite du §2 |
| Détection multi-objets dans une scène | bonus, ⛔ hors MVP |
| Fingerprinting réseau actif (banner grabbing, mDNS/UPnP) | ⛔ **exclu** : exigerait une autorisation écrite du propriétaire (art. 323-1 et suivants du Code pénal) |
| Appels API NVD en temps réel pendant un run | ⛔ interdit par conception (ENF4) |
| Exploitation, PoC, scan de vulnérabilité | ⛔ hors projet |
| Application mobile native | ⛔ hors périmètre (web responsive) |
| Multi-tenant, authentification forte | ⛔ hors MVP |

### 3.3 Ce qui est déjà vrai le 15/09/2026 (artefacts de preuve)

| Domaine | État vérifié | Où |
|---|---|---|
| Cluster | 3 nœuds, Devuan 6, i9-13900, 62 Go, RTX 3060 12 Go | `../evidence/2026-09-15/SUMMARY.md` |
| Pile | `vllm 0.29.0`, `torch 2.13.0+cu132`, driver `615.71.09` sur les 3, `torch.version.cuda = 13.2` | idem, `ENV_STATUS.md` ×3 |
| Intégrité des paquets | `uv pip check` PASS — 208 / 215 / 208 paquets | `RESULT.json` |
| Recette nœud | `20 PASS / 0 FAIL / 1 WARN` (palier profond, 3 nœuds) | `zabeth2*/golden-check-deep.log` |
| Invariants | **G1–G10 = 10/10** sur les 3 nœuds | `SUMMARY.md` §2 |
| Egress | `output drop` ⇒ nvd/huggingface/pypi `timeout` 3/3, DNS+LAN intacts, **inférence réelle exécutée sous blocage**, ruleset restauré | `V12-EGRESS.md` |
| Latence | p50 = **1,085 / 1,082 / 1,084 s**, p95 = 1,878 / 1,091 / 1,861 s (n=12) | `RESULT.json` |
| Poids | `sha256` identiques sur les 3 nœuds (`25aab8ca…`, `d380b110…`) | `RESULT.json` |
| Corpus | 48 objets, **144 images publiables**, 5/5 catégories, licence + URL + sha256 par image — **+ 11 orphelines exclues** (§3.6) | `corpus/corpus.sqlite` |
| Dictionnaire CPE | **1 838 235 entrées** (h 64 842 / a 1 625 996 / o 147 397), ingestion 27 s, versionné | zabeth22 `~/cpe.sqlite` |
| Contrats | `iot_audit/contracts.py` — 228 l., dataclasses gelées + 4 protocoles | dépôt |
| Mesure | drapeau `text_visible`, deux moteurs OCR comparés, capture–recapture, réplication hors échantillon | `21-FLAG-SWAP.md`, `docs/06` §13 |

### 3.4 Ce qui n'existe pas encore (et qui est le sujet)

| Manque | Impact |
|---|---|
| **Aucune ingestion NVD, aucune table CVE, aucun `search_cve`** | ❌ **le cœur du sujet** est absent |
| Aucun index **FTS5** sur le dictionnaire CPE | la résolution lexicale planifiée n'a pas de support |
| Aucun `confidence.py` | la formalisation A×R n'est pas implémentée |
| Aucun journal HMAC, aucune signature, aucun PDF | opposabilité nulle |
| Aucun test, aucune CI | couverture **0 %** |
| **Aucun dépôt Git**, aucun `requirements.txt` / lockfile | livrable de la v1 non satisfait |
| Aucun artefact RGPD (rétention, minimisation écrite) | conformité non documentée |
| **11 images orphelines** (aucun objet rattaché) étaient **comptées dans les figures publiées** | le corpus publiable est de **144**, pas 155 ; la strate `forum` est de **12**, pas 23 (§3.6) |
| **Aucun objet du corpus ne porte de champ FCC ID**, aucune exploitation du FCC ID (proposé par l'énoncé) | opportunité d'identification non évaluée (§3.5) |


