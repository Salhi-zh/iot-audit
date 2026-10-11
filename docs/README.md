# IoT / CPE / CVE — plan set

**Projet :** Reconnaissance d'objets connectés pour audit de sécurité IoT
**Auteur :** Mohamed Salhi — Polytech Lille / ENSA Kénitra
**Tuteur :** Thomas Vantroys
**Started :** 2026-09-14 · **Cahiers v2 :** 15/09 · **Horizon :** 13 semaines (→ 15/12/2026) · solo

> **Contrat de référence :** [`../cahiers/CDC-v2.0.md`](../cahiers/CDC-v2.0.md) et
> [`../cahiers/CDS-v2.0.md`](../cahiers/CDS-v2.0.md) (**v2.0, 15/09/2026** — annulent la v1 du
> 13/09). **Ce plan set `docs/01..08` est l'échelon d'ingénierie** : décisions, algorithmes,
> corps de code, protocoles. État d'exécution vérifié :
> [`../evidence/2026-09-15/`](../evidence/2026-09-15/) et
> [`../ETAT-DES-LIEUX-2026-09-15.md`](../ETAT-DES-LIEUX-2026-09-15.md).

Photo d'un objet connecté → marque/modèle/catégorie → CPE (NIST) → CVE (NVD local) → rapport PDF signé, journal chaîné HMAC.

> **Cadrage en une phrase.** Le projet fait du **triage produit-level** : il dit « cet objet est un *TP-Link Archer C7*, et *ce produit* a des CVE connues ». Il ne dit **jamais** « cet exemplaire est vulnérable », parce qu'une photo ne donne pas la version firmware. Tout le plan est construit pour ne pas laisser dériver cette distinction.

---

## Comment lire ce plan

| Doc | Contenu | Pour qui |
|---|---|---|
| `01-scope-claims-limits.md` | Périmètre MVP, **registre des affirmations** (ce qui est prouvé / mesuré / limite assumée) | jury, tuteur |
| `02-decisions.md` | **15 décisions** argumentées : alternatives considérées, pourquoi rejetées, conséquence, comment on prouve | jury, toi |
| `03-architecture.md` | Couches, **contrats d'interface (dataclasses)**, SPOF, taxonomie d'erreurs, delta de schéma SQLite | toi |
| `04-data-pipelines.md` | CPE + NVD : volumétrie, parsing streaming, versioning, SQL, **reprise sur erreur** | toi |
| `05-matching-and-confidence.md` | Algorithme de normalisation + matching CPE, seuils, **formalisation de la confiance** | toi, jury |
| `06-corpus-and-metrics.md` | Photos internet : contamination, stratification, **puissance statistique**, plan de mesure | toi, jury |
| `07-verification-plan.md` | **Preuves / tests / benchmarks** avec critères d'acceptation chiffrés | jury, tuteur |
| `08-execution-plan.md` | Semaines, tâches atomiques 2-4 h, chemin critique, **3 risques de dépassement** | toi |
| `../cahiers/CDC-v2.0.md` | **Le contrat** : périmètre, EF/ENF, critères d'acceptation, jalons et portes, risques, matrice de traçabilité | tuteur, jury |
| `../cahiers/CDS-v2.0.md` | **La référence d'ingénierie** : architecture, contrats, modèle de données, **protocole de mesure**, plan de vérification | toi, jury |

**Ordre de lecture conseillé :** CDC v2 → ce README → 01 → 02 → ensuite au besoin.

---

## État du projet

*État au **15/09/2026**, vérifié sur les nœuds et dans les preuves — voir `../cahiers/CDC-v2.0.md` §3.3 et §3.4 pour le détail complet.*

| Élément | État |
|---|---|
| Contrats et outillage corpus | ✅ `iot_audit/contracts.py` (228 l., dataclasses gelées + 4 protocoles) et `iot_audit/corpus/` (collecte, identité, OCR, mesure) |
| Modules métier (pipeline, resolve, search_cve, confidence, report, API) | ❌ **n'existent pas** — c'est le chantier des phases P1–P5 |
| Corpus | ✅ **48 objets / 155 images**, 5/5 catégories, licence + URL + sha256 par image |
| Plateforme d'inférence (zabeth ×3, vLLM, Qwen2.5-VL) | ✅ **dorée** : `vllm 0.29.0` + `torch 2.13.0+cu132`, driver `615.71.09` sur les 3, **G1–G10 = 10/10**, `uv pip check` PASS, p50 ≈ 1,08 s |
| Dictionnaire CPE | ✅ **1 838 235 entrées** versionnées (h 64 842), ingestion 27 s |
| **Chaîne CVE (le sujet)** | ❌ **aucune** ingestion NVD, aucune table CVE, aucun `search_cve` |
| Journal d'intégrité, PDF, API | ❌ aucun |
| Tests, dépôt Git, lockfile | ❌ **0 test, aucun dépôt, aucun lockfile** |
| Cahiers | ✅ **v2.0** (`../cahiers/`) — horizon 13 semaines, chiffres mesurés |
| Ce plan | `docs/01..08` — échelon d'ingénierie, cohérent avec la v2 |

---

## Registre des décisions (résumé)

Chaque décision est argumentée en détail dans `02-decisions.md`.

| # | Décision | Raison courte |
|---|---|---|
| D1 | Le CDC **ne fige aucun pin vLLM** ; version fixée à l'intégration et enregistrée dans la provenance | le pin actuel du CDC est **auto-contradictoire** (vLLM 0.29.0 + torch 2.6.0+cu124) |
| D2 | Les **deux modèles tournent sous vLLM** (pas de llama.cpp) | sinon on compare un *modèle* à un *moteur* : résultat inexploitable |
| D3 | Récupération CPE **lexicale d'abord** (FTS5 + vendor exact), embeddings en second | les identifiants produit sont lexicaux, pas sémantiques ; et lexical = déterministe (ENF5) |
| D4 | Si embeddings : on indexe une **chaîne naturelle synthétisée** par entrée CPE, jamais le token CPE brut | `all-MiniLM-L6-v2` est entraîné sur du langage naturel, pas sur `tp-link:archer_c7:2.0` |
| D5 | Matching CVE par **(vendor, product) dénormalisé + logique de version NVD**, jamais par `LIKE` sur wildcard | un wildcard SQL est incorrect et explose en lignes |
| D6 | Dictionnaire CPE et flux NVD **immuables et versionnés** ; chaque run référence la version utilisée | sinon une MAJ NIST casse les runs passés et ENF5 |
| D7 | Confiance = **deux axes** : accord inter-photos (A) × résolvabilité CPE (R) | l'accord seul mesure la *cohérence*, pas la *justesse* : 8 hallucinations identiques donnent A = 1.0 |
| D8 | ENF5 requalifié : **complétude de provenance + accord de rejeu mesuré**, pas bit-exact | bit-exact impossible avec continuous batching + DP |
| D9 | Pipeline **complète sur une seule machine** ; le DP est un accélérateur, jamais une dépendance | 7B Int4 tient sur une 3060 ; la panne d'un nœud ne doit pas bloquer un run |
| D10 | Corpus **stratifié par risque de contamination** ; champs de provenance dans le schéma | photos web = risque de mémorisation + biais « photo produit publicitaire » |
| D11 | **Ed25519 sur la tête de chaîne** + horodatage RFC 3161, en plus du HMAC | le HMAC symétrique interdit toute vérification par un tiers |
| D12 | Catégorie via **mapping curé** mot-clé → catégorie sur les CPE hardware filtrés, avec seuil de précision mesuré | la catégorie n'existe pas dans le CPE ; c'est un livrable data avec une barre qualité |
| D13 | **sha256 du snapshot NVD** enregistré dans chaque run | une CVE trouvée n'est pas reproductible si la base NVD change |
| D14 | Taxonomie d'erreurs **étendue + comportement + message + trace journal** par code | exigé par EF5, ENF4 et le HITL |
| D15 | Schéma SQLite étendu : `feed_versions`, `dictionary_versions`, `cve_cpe_criteria`, provenance corpus, `corrections` | le schéma actuel ne permet ni versioning, ni HITL traçable |
| D16 | Le cap devient **« IoT ou non, catégorie sans marque »** : premier filtre = objet connecté + catégorie, la marque restant une action de l'auditeur | sans texte, la marque tombe à 0,161 quand la catégorie tient 0,581 (objets, run v4 gelé) — voir `06` §22 |

---

## Questions ouvertes (à trancher avec le tuteur)

1. **Pin de version dans le CDC** — un pin est-il exigé, ou « compatible driver ≥ X, figé à l'intégration » suffit-il ? (bloque D1)
2. **Métrique « terrain »** — sans photos terrain réelles, accepte-t-on de la redéfinir comme *proxy* (photos d'avis utilisateurs) ? Sinon, la retirer du CDC. (voir `06`)
3. **DP sur 3 machines** — est-ce une exigence d'évaluation, ou un choix d'implémentation ? Avec ~400 images, une machine suffit ; il faut pouvoir le justifier.
4. **Périmètre du HITL** — validation à chaque étape ou au résultat final ? Impacte le schéma `corrections` (D15).
5. **Publication du corpus** — les photos web peuvent-elles être redistribuées avec le rapport/dépôt, ou seulement citées par URL ?
6. **Nouveau cap « IoT ou non »** — valider le protocole du corpus mixte (30 objets connectés + 30 objets du quotidien, 2 conditions de texte) et les cibles (rappel IoT ≥ 95 %, catégorie sans texte bornée ≥ 70 %). (voir `06` §22, D16)

## Chiffres autrefois marqués VERIFY — **clos le 15/09/2026**

Ces trois chiffres devaient être mesurés au jour 1 (`08` §0.3). C'est fait ; ils sont retirés du CDC v1 et remplacés par les valeurs du CDC v2 §7.

| Chiffre annoncé | Statut | Résolution |
|---|---|---|
| NVD complet ≈ **200 GB** | ✅ **clos** | chiffre non filtré et non compressé ; remplacé par une **méthode de mesure** (CDC v2 §7.1) — le volume utile est celui des critères `part=h`, ordre 10³–10⁴ CVE |
| CPE XML ≈ **500 MB** | ✅ **clos** | le chiffre qui compte est celui des entrées : **1 838 235** au total, **64 842** `part=h`, ingestion **27 s**. Les embeddings ne sont donc **pas** un goulot d'étranglement |
| Driver CUDA **12.4** | ✅ **clos** | les drivers étaient **hétérogènes** (550.163.01 sur z21/z23 vs 615.71.09 sur z22) ; **alignés** sur `615.71.09`. Aucun pin vLLM n'est figé dans le contrat (D1, CDC v2 §1.3) |
