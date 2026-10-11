# Revue croisée et confrontation critique — Double regard

**Date d'arbitrage** : 24 septembre 2026  
**Postures méthodologiques tenues simultanément** :  
1. *Tuteur académique / Chercheur senior* (Vérification épistémologique, rigueur métrologique, refus absolu des sur-promesses).  
2. *Architecte système / Ingénieur lead* (Faisabilité opérationnelle, robustesse logicielle, élimination de la dette et résilience infrastructure).

---

## 1. Cartographie des deux approches en présence

Deux approches de rédaction coexistent actuellement dans l'historique du projet :

- **Approche A (Synthèse exécutive directe — `CDC-v3.0.md` / `CDS-v2.0.md`)** :  
  - *Forces* : Écriture sobre, sans jargon superflu, va droit au but opérationnel.  
  - *Faiblesses* : Trop allégée ; elle élague les détails métrologiques indispensables (protocoles exacts des bancs OCR, barème multivarié à 4 bandes, traçabilité des numéros d'articles historiques du CDC).
- **Approche B (Spécification exhaustive de recherche — `CDC-v3.1-proposition.md` / `CDS-v2.1-proposition.md`)** :  
  - *Forces* : Exhaustive, cite rigoureusement les intervalles de Wilson pour chaque mesure, traque chaque micro-dérive (ex: rectification de l'IC de 79/144 à `[0,467 ; 0,628]`), cartographie toutes les références croisées.  
  - *Faiblesses* : Peut paraître dense et spéculative sur les jalons lointains si elle ne distingue pas nettement ce qui est **prouvé aujourd'hui** de ce qui est **planifié**.

---

## 2. Détection des 5 failles critiques & Arbitrages formels

### Faille 1 : Le calcul et l'unité de l'intervalle de confiance (Règle d'or Wilson)
- **Le problème** : L'approche naïve calcule l'intervalle de Wilson sur les 144 images traitées comme des tirages indépendants.
- **La critique du tuteur** : Les clichés d'un même objet partagent le même boîtier, souvent le même éclairage ou le même capteur. Traiter $N=144$ comme des variables i.i.d. est une faute statistique qui sous-estime artificiellement la variance.
- **Arbitrage retenu** : L'unité de preuve statistique pour l'exactitude globale est impérativement l'**objet ($N=48$)**. Les chiffres par image sont rapportés à titre descriptif d'ingénierie, mais aucun claim d'exactitude opposable n'est validé sans Wilson calculé au niveau objet.

### Faille 2 : L'amalgame entre le résultat du modèle et le résultat de l'OCR
- **Le problème** : Confusion fréquente dans la prose : « le modèle lit l'étiquette ».
- **La critique de l'architecte** : Il faut découpler l'OCR (instrument auxiliaire local RapidOCR/OnnxTR qui peuple `visible_text`) et la capacité de perception propre du VLM. Le benchmark COCO-Text a prouvé que l'OCR complet de bout en bout ne dépasse pas 10 % de rappel sur scène complexe.
- **Arbitrage retenu** : Le canal OCR est un *indice* fourni au système, jamais la source de vérité terrain. Le contrat v3 pénalise formellement le VLM s'il prétend s'appuyer sur un label absent (`visible_text` vide).

### Faille 3 : Traitement du mythe des « 200 Go » de données NVD
- **Le problème** : L'ancienne v1 affirmait que l'ingestion NVD représentait 200 Go et constituait un risque bloquant.
- **La critique de l'architecte** : Un flux annuel NVD JSON 2.0 pèse ~25 Mo compressé. L'espace utile ne concerne que le matériel (`part='h'`).
- **Preuve établie le 24/09** : L'ingestion réelle des 4 flux 2021-2024 a pris **11 secondes** pour 324 470 critères et 121 719 CVEs dans SQLite (154 Mo). Le risque est formellement clos et relégué au rang de simple tâche batch.

### Faille 4 : Statut réel du parallélisme GPU et gestion de cluster
- **Le problème** : Spéculer sur un cluster 3 nœuds toujours parfait.
- **La réalité mesurée le 24/09** : `zabeth23` a été squatté par un grand modèle tiers et pollué par un VPN Tailscale. Même si l'éviction a restauré les 3 nœuds pour notre test de validation, l'incident prouve qu'un environnement universitaire partagé est hostile.
- **Arbitrage retenu (Principe P8)** : Le pipeline est conçu pour être **souverain en mono-machine**. Les 3 nœuds zabeth sont un accélérateur de banc de test, jamais une dépendance liante d'audit.

### Faille 5 : Gestion des versions firmware & absence de CVE
- **Le problème** : La tentation d'afficher un verdict binaire « sécurisé » ou « vulnérable ».
- **Arbitrage retenu (Triage produit strict)** : Interdiction absolue d'affirmer la vulnérabilité d'un exemplaire physique. Obligation contractuelle du code `E_NO_CVE` avec message explicite : *« Aucune CVE connue au niveau modèle matériel n'implique une absence de vulnérabilité logicielle »*.

---

## 3. Décision d'Alignement des Documents

Pour clore le débat entre concision et rigueur scientifique :
1. **`CDC-v3.1-proposition.md`** et **`CDS-v2.1-proposition.md`** constituent la référence d'ingénierie et de recherche exhaustive (à soumettre pour validation officielle).
2. **`CDC-v3.0.md`** et **`CDS-v2.0.md`** restent les versions synthétiques exécutives de travail au quotidien.
3. Le présent document scelle l'accord méthodologique entre les deux approches.

---

## 4. Confrontation factuelle : rédaction du 13/09 (V1) → état du 24/09

Le document initial (`01_CAHIER_DES_CHARGES.md` / `02_CAHIER_DES_SPECIFICATIONS.md`, 13/09) a été confronté aux preuves recueillies sur le matériel réel. **Sept écarts**, tous résolus par une mesure — aucun par un argument d'autorité :

| Axe | Rédaction V1 (13/09) | État prouvé (24/09) | Preuve du renversement |
|---|---|---|---|
| **Modèle de vision** | `Qwen2-VL-7B-AWQ` | **`Qwen2.5-VL-7B-Instruct-GPTQ-Int4`** | banc apparié 144 images : 79 vs 53 exactitudes, IC disjoints avec Qwen3-VL ; Llama-3.2 écarté sur 21/144 JSON invalides (`evidence/2026-09-16/zabeth22/head2head/SUMMARY.md`) |
| **Serveur d'inférence** | **Ollama** | **vLLM 0.29.0** + Guided Decoding | Ollama n'existe sur aucun nœud ; vLLM sert 144/144 JSON strict, p50 ≈ 1,1 s (`evidence/2026-09-15/RESULT.json`) |
| **Volumétrie NVD** | « ≈ 200 Go » (risque majeur) | **324 470 critères `part='h'` / 121 719 CVE, 154 Mo, 11 s** | ingestion réelle en streaming (`evidence/2026-09-24/nvd-ingest.log`) |
| **Recherche CVE** | non spécifiée | **`search_cve`** : pré-filtre SQL + plages en Python | 40/40 tests, p50 1,54 ms / p95 3,48 ms sur la base réelle (`evidence/2026-09-24/`) |
| **Matching CPE** | tout-embeddings (`all-MiniLM-L6-v2`) | **lexical d'abord** (FTS5 prévu, `token_set_ratio` mesuré), sémantique en repli | les identifiants produit sont lexicaux ; `docs/02` D3, levier mesuré `docs/06` §11.1 |
| **Corpus** | « 8–10 objets », « ≥ 50 % terrain » | **48 objets / 144 images publiables** (11 orphelines exclues) + strate terrain honnête : 3 images `official` | `corpus/corpus.sqlite`, `manual-removals.json` |
| **Reproductibilité** | « résultat identique à chaque exécution » | **accord de décision mesuré** : catégorie 100 %, tuple ≥ 95 %, dérive publiée | promesse bit-exact intenable (continuous batching) ⇒ requalifiée, `docs/02` D8 |

**Trois leçons méthodologiques conservées au dossier :**

1. **Promesse firmware** : la V1 mentionnait la limite sans la graver ; elle est aujourd'hui un champ de schéma (`triage_scope='product'`) et une mention obligatoire du PDF.
2. **Promesse bit-exact** : une promesse de reproductibilité qu'aucun batching continu ne peut tenir a été remplacée par une propriété **mesurable** — plus forte devant un jury, pas plus faible.
3. **Opposabilité** : le HMAC seul prouve l'intégrité *sous le détenteur de la clé* ; l'ajout d'Ed25519 sur la tête de chaîne (D11) rend la vérification tierce possible sans partage de secret.

---

## 5. Actions exécutées au titre de cette revue (24/09, après `fb6d06d`)

| # | Action | Statut |
|---|---|---|
| 1 | Unité objet (n = 48) actée comme seule base d'une affirmation d'exactitude — reportée dans `CDC-v3.1-proposition.md` §3.1/AC1 et `CDS-v2.1-proposition.md` §15.2 | ✅ |
| 2 | Séparation formelle acquis / jalons ouverts — `CDC-v3.1-proposition.md` §3.5 | ✅ |
| 3 | `.gitignore` : exclusions `corpus/nvd.sqlite` et `corpus/nvd-feeds/` (les deux propositions les promettaient, la règle manquait) | ✅ |
| 4 | Fusion de l'analyse V1→24/09 dans le présent document ; `CHALLENGE_REVIEW_V1_VS_V3.md` retiré (source unique de revue) | ✅ |
| 5 | `README.md` réécrit : index à jour, message au tuteur actualisé (l'ancien affirmait encore « aucune ingestion NVD, aucun test, aucun dépôt Git » — faux depuis le 24/09) | ✅ |

**Ce que cette revue ne fait pas** : elle ne ferme aucune porte (G1–G7). Les critères en échec (AC1 : 0,549 < 0,70 · AC10 : 0,368 < 0,80 · AC12 : 0/20 codes) restent publiés en échec, avec leur levier de correction identifié.

