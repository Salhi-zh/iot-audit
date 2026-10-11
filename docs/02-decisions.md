# 02 — Décisions techniques argumentées

Format : **Décision · Alternatives rejetées · Argument · Conséquence · Preuve.**
Une décision sans « Preuve » est une opinion : il n'y en a pas ici.

---

## D1 — Le CDC ne fige aucun pin vLLM

**Décision.** Le cahier des charges spécifie une **interface** (« serveur d'inférence local, API OpenAI-compatible, port 8000, modèles servis localement ») et non un numéro de version. La version est fixée **à l'intégration**, puis enregistrée dans la provenance de chaque run.

**Alternatives rejetées.**
- *Pin `vllm==0.29.0`* — c'est ce que dit le CDC actuel, **et c'est ininstallable** sur ce matériel : 0.29.0 épingle `torch==2.13.0`, qui n'existe qu'en `cu130`. Prouvé par `uv pip compile --torch-backend=cu124` → **exit 1**.
- *Pin `vllm==0.8.5.post1` + `torch==2.6.0+cu124`* — cohérent, mais fige une version qui n'est peut-être pas nécessaire si le driver est récent.

**Argument.** Le CDC contient aujourd'hui **deux affirmations mutuellement exclusives dans la même liste de pile** :

```
- vLLM 0.29.0 + Qwen2.5-VL-7B-Instruct-GPTQ-Int4
- PyTorch 2.6.0+cu124          ← incompatible : 0.29.0 exige torch 2.13.0
```

Un CDC est un contrat lu par un tuteur. Y écrire une pile qui ne s'installe pas, c'est un défaut factuel corrigible en 5 minutes aujourd'hui et embarrassant le 16/09. Par ailleurs, **aucune exigence du projet ne dépend du pin** : ni les 5 catégories, ni le seuil des 10 s, ni le journal HMAC. Le pin est un détail de déploiement, pas une exigence — le figer dans le CDC ne gagne rien et crée un risque.

**Conséquence.** Le tableau de bord d'installation (`install_vllm.sh --profile <X> --apply`) reste agnostique, piloté par `TARGET_VLLM`. Le CDC gagne une ligne : *« version d'inférence figée et tracée à l'intégration (§provenance) »*.

**Preuve.** Les deux profils sont déjà **prouvés par résolution** : `uv pip compile --torch-backend=cu130` → `torch==2.13.0+cu130` (196 paquets) ; `--torch-backend=cu124` → `torch==2.6.0+cu124` (156 paquets). Le choix effectif se fait par lecture du driver réel (`nvidia-smi --query-gpu=driver_version`), pas par déduction. **Règle : le pin suit le driver, pas la doc.**

**Mise à jour 2026-09-14 16:38 — D1 n'est pas une précaution, c'est une nécessité.**
Les machines ont été interrogées :

| Nœud | Driver | CUDA annoncé | Wheels cu13 ? |
|---|---|---|---|
| zabeth21 | **550.163.01** | 12.4 | non |
| zabeth22 | **615.71.09** | 13.4 | oui |
| zabeth23 | **550.163.01** | 12.4 | non |

Le postulat « 3 machines identiques, driver aligné » est **faux**. Un `~/vllm-env`
construit en `cu13x` fonctionne sur z22 et **échoue sur z21/z23** : un venv unique
répliqué à l'identique est donc impossible, et **aucun pin unique ne peut être
correct pour le cluster**. Deux sorties : aligner les drivers, ou bâtir z21/z23 en
`cu12.x`. Dans les deux cas le CDC ne doit contenir **aucun** pin — sinon il
décrit un système qui n'existe pas.

---

## D2 — Les deux modèles tournent sous vLLM (pas de llama.cpp)

**Décision.** Le benchmark compare Qwen2.5-VL-7B (GPTQ-Int4) et Llama-3.2-11B-Vision (W4A16) **sur le même moteur d'inférence** (vLLM, deux serveurs, ports 8000/8001).

**Alternatives rejetées.**
- *Qwen sous vLLM vs Llama sous llama.cpp (GGUF)* — plan envisagé dans une session antérieure. Rejeté.

**Argument.** C'est un **biais de confusion** classique : si on change modèle **et** moteur en même temps, un écart de résultat n'est attribuable à aucun des deux. Or le projet utilise ce benchmark pour **justifier le choix de Qwen**. Si Qwen gagne, un jury demandera : *est-ce le modèle, ou le continuous batching / Guided Decoding / PagedAttention de vLLM ?* La réponse honnête serait « on ne sait pas » — ce qui vide l'expérience de son sens.

Fait décisif : **les deux modèles sont déjà au format vLLM**. GPTQ-Int4 (GPTQ) et W4A16 (compressed-tensors) sont tous deux supportés par vLLM. Le détour llama.cpp n'apporte rien et coûte l'attribution causale.

**Conséquence.** Deux serveurs vLLM sur la même machine (7B Int4 ≈ 6.9 GB + 11B W4A16 ≈ 8.5 GB ne tiennent **pas** ensemble sur 12 GB → benchmark en deux passes séquentielles, ou répartition sur 2 nœuds, ou quantification plus agressive). À trancher en semaine 2 (`08`).

**Preuve.** Protocole de benchmark **contrôlé** : mêmes images, même prompt, `temperature=0`, mêmes paramètres d'échantillonnage, même version de moteur ; on ne fait varier **que** les poids. Rapport avec intervalles de confiance (voir `06`).

---

## D3 — Récupération CPE : lexical d'abord, embeddings en second

**Décision.** La recherche du CPE candidat utilise **en premier** un index lexical (`SQLite FTS5` trigram + correspondance exacte sur le *vendor* normalisé). Les embeddings ne servent qu'à **départager** / rattraper les cas où le lexical ne sort rien au-dessus du seuil.

**Alternatives rejetées.**
- *Embeddings seuls, top-3 cosinus* (plan initial du CDC) — rejeté comme **mécanisme principal**.
- *Supprimer totalement les embeddings* — rejeté : ils gardent une valeur sur les cas paraphrasés (« borne wifi »).

**Argument (trois raisons, dont deux nouvelles par rapport au CDC).**
1. **Mismatch de domaine.** `all-MiniLM-L6-v2` est entraîné sur du langage naturel. `tp-link:archer_c7:2.0` n'est pas du langage naturel. Embedder le token brut revient à demander à un modèle de paraphrase de comparer des chaînes sans sémantique.
2. **Conflation sémantique = exactement le risque déjà identifié.** Un modèle d'embeddings fort rapproche « Archer C7 » de « routeur TP-Link » — et donc *tous* les routeurs TP-Link entre eux. Or le risque n°1 du projet est la **confusion entre produits** (white-label, gammes voisines). On aurait donc un système dont le composant de récupération *augmente* le risque principal. Le lexical, lui, discrimine précisément `archer_c7` vs `archer_c9`.
3. **ENF5.** Un composant appris est un artefact versionné supplémentaire, non déterministe face à une mise à jour de modèle d'embeddings. Le lexical est déterministe par construction.

**Conséquence.** Le CDC garde `sentence-transformers` (pas de relitige sans raison : elle existe), mais son **rôle passe en secondaire**, et on **mesure** les trois stratégies (lexical / sémantique / hybride) sur le jeu étiqueté. C'est un résultat publiable dans le rapport, pas une perte.

**Preuve.** Benchmark sur ≥ 200 paires (requête VLM simulée → CPE attendu), top-1 et top-3 pour chacune des 3 stratégies. Le choix final se fait sur les chiffres, et le rapport présente le tableau comparatif.

---

## D4 — Si embeddings : indexer une chaîne naturelle synthétisée

**Décision.** Chaque entrée CPE est indexée sous forme de **phrase synthétisée**, par exemple :
`"TP-Link Archer C7 2.0 wireless router"` — construite depuis `vendor` + `product` (underscores → espaces) + catégorie mappée.

**Alternatives rejetées.** Embedder `vendor:product` brut, ou `vendor + description NIST` seule.

**Argument.** Un modèle d'embeddings ne peut exprimer une similarité que sur ce qu'on lui donne. `tp-link:archer_c7` privé de séparateurs naturels et de contexte de catégorie produit un vecteur dominé par le vendor → tous les produits du même vendor se ressemblent. Ajouter le **nom d'affichage désérialisé + la catégorie** est ce qui permet ensuite de distinguer une caméra d'un routeur *du même vendor*.

**Conséquence.** Une colonne `embed_text` (ou un générateur déterministe) dans `cpe_entries`, et un test unitaire vérifiant la stabilité du texte généré (ENF5 : le texte doit être dérivé, pas retapé).

**Preuve.** Test unitaire : pour 20 entrées, `embed_text` est déterministe et contient vendor + product désérialisés. Benchmark : comparer embeddings-de-chaîne-naturelle vs embeddings-de-token-brut sur le jeu étiqueté.

---

## D5 — Matching CVE : (vendor, product) dénormalisé, jamais `LIKE` sur wildcard

**Décision.** Les critères de correspondance CPE du NVD sont stockés **dénormalisés en lignes** (`cve_cpe_criteria`) avec index `(part, vendor, product)`, et l'appartenance se calcule par **pré-filtrage SQL puis évaluation explicite de la logique de version** — pas par résolution de wildcard en SQL.

**Alternatives rejetées.**
- *`WHERE cpe_pattern LIKE 'cpe:2.3:h:tp-link:*'`* — rejeté : incorrect **et** lent.
- *Exploser tous les wildcards en lignes* — rejeté : explosion combinatoire (`vendor:*` × toutes versions) ingérable.

**Argument.** Une entrée NVD n'est pas un motif plat, c'est un **arbre booléen** (`AND` / `OR` / `NEGATE`) dont les feuilles sont des critères CPE avec des **plages de versions** (`versionStartIncluding`, `versionEndExcluding`). Réduire ça à un `LIKE` perd la sémantique (un `NEGATE` devient un faux positif) et le pré-filtre `(vendor, product)` est ce qui rend la requête rapide **sans** perdre la correction. C'est le seul design qui satisfait à la fois « < 50 ms » et « réponse correcte ».

**Conséquence.** Le matching devient du **code testable** (évaluation d'arbre + comparaison de versions), donc des tests unitaires — au lieu d'une requête SQL non testable.

**Preuve.** (a) benchmark : p95 < 50 ms sur le jeu filtré ; (b) tests unitaires sur 12 arbres synthétiques (AND imbriqué, OR, NEGATE, plage ouverte) ; (c) test de non-régression sur 60 CVE annotées à la main.

---

## D6 — Dictionnaire CPE et NVD immuables et versionnés

**Décision.** `cpe_entries` est **versionné** (`dictionary_version_id`), les flux NVD sont enregistrés dans `feed_versions` (nom, sha256, date de publication, date d'ingestion). Aucune mise à jour **ne supprime** : les entrées dépréciées sont marquées `deprecated = 1`. Chaque `analysis_run` référence les versions utilisées.

**Alternatives rejetées.** *Upsert destructif du dictionnaire* (simple, mais rend les runs passés ininterprétables).

**Argument.** Question posée par le CDC : « comment gérer une mise à jour NIST sans casser les runs précédents ? ». La réponse n'est pas une astuce d'implémentation, c'est un choix de modèle de données : **une analyse est un fait daté qui référence le monde tel qu'il était**. Si le dictionnaire est muté en place, un rapport de septembre devient non reproductible en octobre — et ENF5 meurt silencieusement. Le coût du versioning est un entier par ligne ; le coût de son absence est de voir un rapport contesté qu'on ne peut plus reproduire.

**Conséquence.** `cpe_entries` grossit à chaque rafraîchissement (acceptable : volumétrie faible, cf. `04`). Requêtes par défaut filtrées sur la version « courante ».

**Preuve.** Test : ingérer le dictionnaire v1 → produire un run R1 → ingérer v2 (avec une entrée modifiée) → vérifier que R1 resélectionne toujours la v1 et donne le même top-1. Test d'idempotence : ingérer deux fois la même version ne crée pas de doublons.

---

## D7 — Confiance = deux axes (accord A × résolvabilité R)

**Décision.** Le score de confiance affiché combine **A** (accord inter-photos) et **R** (résolvabilité CPE : score du meilleur candidat après matching). Les deux sont reportés, et la décision (identifié / réserve / non identifié) dépend du **couple**.

**Alternatives rejetées.**
- *`confidence` auto-déclarée par le VLM* — déjà écartée par le CDC, à raison (scores non calibrés).
- *Accord seul (moyenne ou mode)* — rejeté : insuffisant, voir argument.

**Argument.** L'accord mesure la **cohérence**, pas la **justesse**. Contre-exemple décisif : le VLM se trompe **systématiquement** en lisant « D-Link » comme « TP-Link » sur les 8 photos d'un même objet (même angle, même éclairage). A = 1.0. Résultat : unanimité sur une **fausse** identification. L'accord seul donne donc une confiance maximale à une erreur systématique — exactement la pire sortie possible pour un outil d'audit.

Le second axe répare ça : si le tuple consensuel « TP-Link » a une **résolvabilité faible** (aucun produit proche dans le dictionnaire), c'est le signal que le consensus est halluciné. Deux axes indépendants → quatre quadrants exploitables (§`05`).

**Conséquence.** Le CDC gagne une notion : *l'accord et la résolvabilité sont deux mesures distinctes, aucune ne vaut justesse.* L'UI (module 2) affiche le quadrant, pas un pourcentage unique.

**Preuve.** (a) test synthétique : 8 réponses identiques + résolvabilité nulle → le système doit **refuser** d'identifier ; (b) test : 8 réponses différentes → `E_LOW_CONFIDENCE` ; (c) sur corpus, mesurer la corrélation entre A et justesse (attendu : positive mais imparfaite — ce résultat est un livrable).

---

## D8 — ENF5 requalifié : provenance + accord de rejeu

**Décision.** ENF5 devient : *provenance complète et vérifiable* + *accord de rejeu mesuré*. La formulation « résultat identique » est retirée du CDC.

**Alternatives rejetées.** *Garder « bit-exact »* — intenable : `continuous batching` + DP + noyaux non associatifs ⇒ les logits varient avec la composition du lot, même à `temperature=0`.

**Argument.** Une exigence intenable se traduit par une non-conformité en soutenance. La version requalifiée est **plus forte** : elle ne promet pas moins, elle promet quelque chose de **prouvable**. Et elle ajoute un livrable (le taux de dérive) que les autres projets n'ont pas.

**Conséquence.** `analysis_runs` porte : `model_revision`, `weights_sha256`, `prompt_sha256`, `schema_version`, `vllm_version`, `torch_version`, `nvd_snapshot_sha256`, `cpe_dict_version_id`, `sampling_params_json`. Une contrainte SQL empêche un run sans provenance.

**État au 2026-10-06.** Cette phrase était une promesse : `analysis_runs` n'existait dans **aucun** schéma du dépôt (`iot_audit/vuln/schema.sql` porte quatre tables côté CVE, `iot_audit/corpus/schema.sql` sept tables de mesure). La table est désormais écrite par `iot_audit/storage/runs.py` — colonnes `NOT NULL` + `CHECK (length(...) > 0)`, `cpe_dict_version_id > 0`, `sampling_params_json` contraint à du JSON **objet** — et `record_analysis_run` refuse un run dont la provenance est incomplète avec le **même** verdict que le scellement (`ProvenanceIncompleteError`), calculé par le même prédicat. Deux jeux de règles pour la même garantie auraient fini par diverger.

**Preuve.** Test de rejeu : 100 images × 2 runs → **100 %** d'accord catégorie, **≥ 95 %** d'accord tuple, drift publié. Test de schéma : `INSERT` sans provenance → rejet.

---

## D9 — Pipeline complète sur une seule machine

**Décision.** Le pipeline complet (ingestion → inférence → CPE → CVE → rapport) doit tourner **sur un seul nœud**. Le Data Parallelism sur 3 machines est un **accélérateur**, jamais un prérequis de correction.

**Alternatives rejetées.** *Architecture où les 3 nœuds sont nécessaires* (sharding d'état, coordinateur unique obligatoire).

**Argument.**
1. **Le modèle tient sur une carte.** 7B en GPTQ-Int4 ≈ 6.9 GB sur 12 GB. Le Tensor Parallelism n'a donc **aucune** justification technique ici — il servirait à répartir un modèle qui n'a pas besoin d'être réparti, au prix de NCCL sur Ethernet. Le CDC tranche TP/DP ; l'argument à ajouter est que **le TP n'est pas seulement « moins bien », il est inutile** : on ne parallélise pas ce qui tient déjà.
2. **La charge ne le justifie pas.** ~400 images × ~1–10 s ≈ moins d'une heure de GPU. Le DP apporte du **débit**, pas de la faisabilité.
3. **Résilience.** Si un nœud tombe, un run doit se terminer en mode dégradé (un seul nœud) plutôt que d'échouer — ce qui donne gratuitement une réponse solide à « mode dégradé » (ENF4) au-delà du seul NVD.

**Conséquence.** Le client d'inférence est un pool d'URLs avec bascule sur échec, jamais un ensemble de participants obligatoires. Un run enregistre `nodes_used`.

**Preuve.** Test de panne : couper le serveur du nœud 2 en pleine exécution → le run se termine, `nodes_used` reflète la bascule, aucune perte d'image.

---

## D10 — Corpus stratifié par risque de contamination

**Décision.** Le corpus est constitué de photos internet, **explicitement stratifiées par risque de contamination et de facilité**. La métrique « terrain » est soit redéfinie comme *proxy* (photos d'avis utilisateurs), soit retirée du CDC.

**Alternatives rejetées.**
- *Corpus web homogène (« photos d'objets connectés »)* — rejeté : c'est mesurer une précision sur des **photos publicitaires**.
- *Garder « terrain ≥ 50 % » avec des photos web* — rejeté : **la métrique serait fausse**, pas optimiste : ce n'est pas du terrain.

**Argument.** Deux menaces distinctes que le corpus web introduit :
1. **Contamination d'entraînement.** Qwen2.5-VL a vu le web. Les photos produit les plus courantes ont pu être mémorisées ⇒ précision gonflée sans capacité réelle. C'est la menace de validité n°1 du projet, et elle est exactement du type de celles que la mission sécurité demande d'anticiper.
2. **Biais de facilité.** Les visuels marketing sont cadrés, éclairés, mono-objet, marque visible — le contraire du terrain. Les confondre revient à annoncer « 85 % de précision » sans dire « sur des photos de catalogue ».

**Conséquence.** Le schéma gagne des colonnes de corpus : `source_url`, `license`, `retrieved_at`, `stratum`, `text_visible`, `label_source`. Les résultats sont **reportés par strate**, pas en un chiffre unique.

**Preuve.** (a) accuracy par strate (attendu : décroissance officiel → avis → forum : c'est la **preuve de contamination**) ; (b) test de robustesse par perturbation contrôlée (recadrage, rotation, fond, luminosité) ; (c) rapport présentant la courbe, y compris si elle est défavorable.

---

## D11 — Ed25519 sur la tête de chaîne, en plus du HMAC

**Décision.** Le HMAC chaîné reste (intégrité applicative), et on ajoute : signature **Ed25519** de la tête de chaîne + **horodatage RFC 3161**, avec la clé **publique** publiée dans le PDF et un vérificateur tiers.

**Alternatives rejetées.**
- *HMAC seul* (état actuel) — rejeté comme preuve opposable.
- *Chaîne de blocs / Merkle complet* — surdimensionné pour un MVP ; une signature de tête suffit.

**Argument.** Modèle de menace, sans détour : HMAC est **symétrique**. La clé est sur la même machine qui écrit la base. Donc tout acteur qui détient la clé — c'est-à-dire l'auditeur lui-même — peut **reconstruire une chaîne entièrement valide**. Et le trigger SQL vit dans le même fichier SQLite qu'il peut réécrire. Le HMAC protège donc contre : corruption accidentelle, altération par un tiers *sans* la clé, et manipulation par une couche applicative buggée. Il **ne** protège **pas** contre l'auditeur, ni ne permet la vérification par un tiers (le client, un régulateur) — car vérifier exige la clé.

Conséquence directe : sans signature asymétrique, un rapport « signé » n'est pas vérifiable par la partie à qui il est destiné. La décision doit être prise **maintenant** parce qu'elle touche le schéma (`corrections`, `hmac_chain`, métadonnées du PDF), pas en semaine 4.

**Conséquence.** Le rapport porte : clé publique Ed25519, empreinte de la tête de chaîne, horodatage, et une phrase exacte du modèle de menace. `verify_report.py` (outil tiers) ne lit ni la base ni la clé secrète ; il exige en revanche la clé publique **de l'auditeur** (`--pubkey`) pour prononcer un verdict d'authenticité. Une clé lue *dans* le rapport ne prouve rien : un faussaire y met la sienne et le document se vérifie tout seul (verdict distinct `partiel`, code de retour 3).

**Preuve.** (a) test d'altération : modifier une ligne → `verify_chain` échoue **à l'index exact** ; (b) test d'export : modifier le PDF après export → la vérification Ed25519 échoue ; (c) test de forgeage : vérifier qu'un détenteur de clé HMAC **peut** forger ⇒ documenter explicitement la limite (le test prouve la limite au lieu de la cacher).

---

## D12 — Catégorie via mapping curé, avec seuil de précision

**Décision.** La catégorie est dérivée par un **mapping curé** (mots-clés vendor/product → 5 catégories) appliqué aux CPE hardware filtrés. Le mapping est un **livrable versionné** avec une précision mesurée sur échantillon étiqueté.

**Alternatives rejetées.** *Classification par embeddings* (la catégorie est un label grossier, lexique suffisant) ; *laisser le VLM décider la catégorie et s'en servir comme clé de recherche*.

**Argument.** La catégorie **n'existe pas** dans une entrée CPE : il n'y a ni « camera » ni « router » comme champ exploitable de façon fiable. C'est donc un travail de data engineering, pas une lecture. Et il est **structurant** : il sert à filtrer le dictionnaire (D3/D5) et à contraindre la sortie du VLM. Une erreur ici se propage partout — d'où la nécessité d'une barre de qualité mesurée plutôt que d'un mapping « à l'intuition ».

Corollaire : on ne fait **pas** confiance à la catégorie prédite par le VLM comme clé de recherche (elle serait l'entrée d'un raisonnement circulaire). Elle sert de **contrôle de cohérence** : si le CPE retenu est une caméra et que le VLM dit « routeur », c'est un signal d'ambiguïté.

**Conséquence.** `category_rules` versionné ; `cpe_entries.category` dérivée ; test de cohérence croisée VLM/CPE.

**Preuve.** Précision du mapping sur ≥ 200 entrées annotées à la main (cible ≥ 95 % sur les 5 catégories, classe `other` incluse) ; matrice de confusion publiée.

---

## D13 — sha256 du snapshot NVD dans chaque run

**Décision.** `feed_versions` enregistre chaque flux ingéré (nom, sha256, dates). `analysis_runs.nvd_snapshot_sha256` fige l'état vu par le run.

**Alternatives rejetées.** *Enregistrer seulement la date d'ingestion.* Insuffisant : deux ingestions le même jour ne sont pas le même contenu.

**Argument.** Une CVE trouvée en septembre n'est reproductible en octobre que si on sait **contre quelle version de la base** elle a été trouvée. Les CVE sont re-notées, rejetées, modifiées (`modified` feed). Sans empreinte, on ne peut ni rejouer, ni expliquer un écart, ni répondre à « pourquoi ce rapport d'hier liste une CVE qui n'existe plus ? ».

**Conséquence.** Champ obligatoire ; `E_PROVENANCE_INCOMPLETE` si absent.

**Preuve.** Test : deux snapshots NVD différents → deux runs donneront des listes de CVE différentes **mais** chacun reste rejouable et explicable.

---

## D14 — Taxonomie d'erreurs étendue et opérationnalisée

**Décision.** Chaque code d'erreur a : **déclencheur précis**, **comportement système**, **message utilisateur (FR, ton professionnel)**, **trace dans le journal**. Table complète en `03` §5.

**Alternatives rejetées.** *Codes sans comportement associé* (ce qui existe aujourd'hui) : un code sans comportement n'est pas une gestion d'erreur, c'est un nom.

**Argument.** EF5 (« non identifié — vérification manuelle requise, pas de résultat inventé ») et ENF4 (mode dégradé) ne sont pas des phrases : ce sont des **comportements**. Les spécifier un par un est ce qui rend l'exigence testable. Et la trace dans le journal est ce qui rend la chaîne HMAC utile : sans elle, on saurait *qu'il y a eu une erreur* mais pas *laquelle*, donc pas de post-mortem.

**Conséquence.** Un test par code d'erreur. C'est le test le moins coûteux et le plus rentable du projet.

**Preuve.** Suite de tests d'injection de panne : 1 test par code, vérifiant comportement + message + trace.

---

## D15 — Delta de schéma SQLite

**Décision.** Ajouter au schéma existant :

| Table / colonne | Rôle | Décision liée |
|---|---|---|
| `feed_versions` | nom, sha256, published_at, ingested_at | D13 |
| `dictionary_versions` | id, source_sha256, entry_count, loaded_at | D6 |
| `cve_cpe_criteria` | critères CPE dénormalisés `(part, vendor, product, version, start, end, vulnerable)` indexés | D5 |
| `corrections` | corrections HITL : run_id, field, avant, après, acteur, horodatage, hmac | D15/HITL |
| `cpe_entries.dictionary_version_id`, `.deprecated`, `.embed_text`, `.category` | versioning, cycle de vie, embeddings, catégorie | D4, D6, D12 |
| `images.source_url`, `.license`, `.retrieved_at`, `.stratum`, `.text_visible` | provenance et validité du corpus | D10 |
| `analysis_runs.model_revision`, `.weights_sha256`, `.prompt_sha256`, `.vllm_version`, `.torch_version`, `.nvd_snapshot_sha256`, `.cpe_dict_version_id`, `.triage_scope`, `.nodes_used` | provenance, ENF5 requalifié | D8, D9, D13 |
| `analysis_runs.content_sha256` + table `object_identity` | squelette de déduplication entre photos d'un même objet | `06` |

**Argument.** Le schéma actuel est bon sur le cœur métier mais **muet sur la provenance** et **sans place pour le HITL**. Or le HITL est une exigence (EF6) et la provenance est ce qui rend ENF5 défendable. Ajouter ces colonnes maintenant coûte une migration ; en semaine 4, elles coûtent une réécriture des runs.

**Preuve.** Tests de migration ; contrainte `NOT NULL` sur la provenance avec test d'échec d'insertion ; test que `corrections` est bien chaîné au journal.

---

## D16 — Le cap devient « IoT ou non, catégorie sans marque »

**Décision (tuteur, 2026-10-05).** La chaîne n'exige plus la marque en premier : le système
doit dire **(a)** si un objet est connecté et **(b)** sa catégorie, à partir de la seule
apparence ; la lecture de la marque reste une action de l'auditeur, déclenchée par l'alerte
« objet d'intérêt ». M1 reste publié comme mesure de fin de chaîne.

**Argument (mesuré le 2026-10-05 sur le run v4 gelé).** Sans texte lisible, la marque tombe
à `5/31 = 0,161` (objets, règle `conservative`) quand la catégorie tient `18/31 = 0,581`, et
la catégorie reste juste sur `13/26 = 0,500` des objets à marque fausse. La lecture des
marques est un canal **conditionné par la lisibilité** (§19) ; la reconnaissance de forme est
le seul canal qui survit — c'est lui qu'on augmente, et c'est ce que la directive déplace au
premier filtre.

**Preuve / suite.** `evidence/2026-10-05/category-without-brand/` (sonde, sortie, JSON) ;
protocole du corpus mixte au §22.3 de `docs/06` (30 objets connectés + 30 objets du
quotidien, deux conditions de texte, coût 0 €) ; cibles proposées — rappel IoT ≥ 95 %,
catégorie sans texte bornée ≥ 70 % — à arbitrer avec le tuteur (Q9).
