# État des lieux — 2026-09-15

**Projet** : Reconnaissance d'objets connectés pour audit IoT · **Auteur** : Mohamed Salhi ·
**Tuteur** : Thomas Vantroys · **Méthode** : chaque réponse vient d'un fichier lu ou d'une
commande exécutée le 2026-09-15 (jamais de mémoire).

**Légende** : ✅ fait, prouvé · 🟡 partiel · ❌ non fait · ❓ inconnu

> **À lire avant le reste.** La question la plus importante de ce questionnaire n'est pas
> technique. Le fichier `00_CONTEXTE_ET_PROFIL.md` pose lui-même une exigence :
> *« je dois être capable de reformuler et défendre chaque décision avec mes propres mots,
> sans notes, à l'oral »*. Or **~95 % du travail produit l'a été par un agent IA**. Les
> sections 0.6 et 12 y reviennent. C'est le risque n° 1, avant tout gap technique.

---

## 0 · Méta-projet & agents

| # | Question | Statut | Preuve / réponse |
|---|---|---|---|
| 0.1 | Qui sont les agents ? | ✅ | Un agent de codage (Claude Code / Codebuff) piloté en sessions, **13 sessions** documentées dans `~/zabeth22-vllm-repair/logs/LOG.md` (2026-09-13 → 2026-09-15). Le `CLAUDE.md` du poste décrit un système multi-agents (architect / coder / secops / deployer / re-agent via le gateway `hermes`) — **il n'a pas été utilisé pour ce projet** : tout a été fait par l'agent unique, avec des sous-tâches lancées manuellement. Durée effective : **~3 jours**. |
| 0.2 | Où est le dépôt ? Branche, dernier commit ? | ❌ | **Il n'y a aucun dépôt Git.** `git rev-parse` → `fatal: not a git repository`. C'est un livrable exigé (`01_CAHIER_DES_CHARGES.md` §6.4 : *« Code source documenté et versionné (dépôt Git) »*). **Risque élevé.** |
| 0.3 | Livrables déjà produits | 🟡 | **Design complet** : `docs/01`–`08` + `docs/README.md` (4 346 lignes). **Spec infra** : `infra/SPEC-infra-setup.md` (1 663 l.). **Scripts infra** : 12 dans `infra/scripts/` + 14 dans `~/zabeth22-vllm-repair/`. **Package code** : `iot_audit/` (14 modules). **Données** : corpus 48 objets / 155 images, `cpe.sqlite` 1 838 235 entrées, `inventory.json`. **Preuves** : `evidence/2026-09-14/` + `evidence/2026-09-15/` (36 fichiers dans la seconde). **Rapports** : 23 `*.md` dans `~/zabeth22-vllm-repair/`. **Manquant** : API, PDF, journal HMAC, rapport de projet écrit, support de soutenance. |
| 0.4 | Implémenté vs prototypé vs planifié | ✅ | Voir le tableau §0.4 ci-dessous. |
| 0.5 | Bloqueurs actuels | ✅ | **Aucun blocage de la plateforme d'inférence** (les 3 nœuds sont dorés, G1–G10 = 10/10 au 2026-09-15). Les blocages réels sont **en aval** : (1) **aucune donnée CVE n'existe** — or c'est l'objet du projet ; (2) pas de backend/API/PDF ; (3) pas de dépôt Git ; (4) pas de tests ; (5) matériel IoT physique non confirmé ; (6) calendrier PFE (entretiens imprévisibles). |
| 0.6 | Décisions prises par les agents, non par toi | ✅ | **À relire en priorité** : (a) **source du corpus = Wikimedia Commons** → d'où **98 % de photos de « terrain »** et un bras « propre » à **3 images sur 144** ; (b) **adoption de l'union des deux moteurs OCR** comme drapeau canonique (choix *adverse* au narratif du projet, mais décidé par un agent) ; (c) **reformulation de la métrique `no_text`** en « borne supérieure » ; (d) **non-bascule sur docTR** ; (e) **Option B** (montée de pilote + reboot) — celle-là a bien été validée par toi. Les quatre premières sont des arbitrages scientifiques que tu dois pouvoir défendre. |
| 0.7 | Conflits / incohérences entre modules | ✅ | **4 conflits vérifiés, 2 corrigés** : (1) `README.md` **l. 71–73** affirme encore « **1 nœud sur 3 fonctionnel** », « pilotes **hétérogènes** » et « service non démarré » — **faux** depuis la session 8 (**non corrigé**) ; (2) `SPEC` §3.2/§5.2 affirmaient le pilote 550 — corrigé (**C28**) ; (3) `18-DEPLOIEMENT.md` §4 publiait un test d'inférence que **le log du nœud montre non exécuté** — consigné, historique intact ; (4) **`docs/09` est cité par DEUX fichiers** (`docs/06` l. 1017 et `SPEC` l. 1444 — « §2 of `docs/09` ») **et n'existe pas** : `docs/` s'arrête à `08`. |
| 0.8 | Fichiers de documentation | ✅ | `iot-audit/README.md`, `docs/README.md` + `01`–`08`, `infra/README.md`, `infra/SPEC-infra-setup.md`, `infra/journal/2026-09-14-cluster-tooling.md`, `~/zabeth22-vllm-repair/00`–`23*.md` + `README.md` + `HANDOFF-READ-FIRST.md`. **Absents** : pas de `ARCHITECTURE.md` autonome (il est dans `docs/03`), **pas de `THREAT_MODEL.md`**, **pas de DPIA/AIPD**, pas de registre de traitements. |
| 0.9 | Niveau de maturité | ✅ | **POC**, avec une nuance : le **canal de lecture et le corpus sont mesurés au niveau recherche** (chiffres avec IC, réplication, réfutation d'hypothèses), tandis que **le produit** (API → CVE → PDF) est **au stade « planifié »**. Ce n'est pas un MVP : aucune des EF1–EF6 n'est implémentée. |
| 0.10 | Deadline soutenance / jalons | 🟡 | **CDC 16/09** et **specs 18/09** (confirmés, `docs/08`). **Aucune date de soutenance n'apparaît dans un seul fichier** — `docs/08` raisonne en semaines 0→4 (~mi-octobre). ❓ pour la date officielle, **à obtenir du tuteur**. |

### 0.4 — Implémenté / prototypé / planifié

| Brique | État | Preuve |
|---|---|---|
| Ingestion dictionnaire CPE (NVD API 2.0) | ✅ **implémenté** | `iot_audit/corpus/fetch_cpe.py`, `cpe.py` ; `cpe.sqlite` **1 838 235** entrées sur zabeth22 (484 MB) |
| Collecte corpus + provenance + stratification | ✅ **implémenté** | `commons.py`, `openverse.py`, `annotate.py`, `apply_manual.py`, `fill.py` ; `inventory.json` 1,2 MB |
| Canal OCR + mesure | ✅ **implémenté et mesuré** | `ocrtext.py`, `measure.py`, `metrics.py` |
| Matcher CPE (M4) | 🟡 **prototypé, mesuré, sous la cible** | `corpus/m4_bench_v2.py`, `evidence/2026-09-14/corpus/expanded/m4-v2-results.json` |
| Confiance (D7) | ❌ **planifié** | `docs/05` §4, pas de `confidence.py` |
| **Ingestion CVE (NVD)** | ❌ **rien** | `find -iname '*nvd*'` → vide ; aucune table CVE. **C'est le chemin critique** (`docs/08`) |
| Index **FTS5** CPE | ❌ | seuls des index btree (`ix_cpe_vendor`, `ix_cpe_product`, `ix_cpe_vp`). FTS5 trigram **disponible** (testé par `golden-check.sh`) mais **non construit** |
| 200 paires annotées (`docs/06` §4.2) | ❌ | `cpe_pairs` = **0** lignes |
| Backend Django Ninja / API (EF1) | ❌ | aucun fichier Django |
| Rapport PDF (EF4) | ❌ | — |
| Journal HMAC chaîné (ENF3) | ❌ | — |
| Ed25519 + RFC 3161 (D11) | ❌ | — |
| HITL / table `corrections` (EF6) | ❌ | — |
| 20 codes d'erreur (D14) | ❌ | — |
| Client `VLMRunner` + bascule de nœud | ❌ | — |
| Tests (unitaires / intégration) | ❌ | **aucun `test_*.py` dans le projet** (`docs/07` en exige 5 critiques) |
| Versionnage Git | ❌ | pas de dépôt |
| Infra cluster 3 nœuds | ✅ **implémenté et doré** | `SUMMARY.md`, G1–G10 = 10/10 |

---

## 1 · Architecture & infrastructure

| # | Question | Statut | Preuve |
|---|---|---|---|
| 1.1 | Schéma d'architecture | 🟡 | `docs/03-architecture.md` (couches, contrats d'interface, SPOF). Pas de schéma image. Architecture réelle aujourd'hui = 3 nœuds + 1 poste pilote. |
| 1.2 | Les 3 machines | ✅ | **zabeth21/22/23** — Devuan 6 (sans systemd), Intel i9-13900, **62 GB RAM**, RTX 3060 **12 288 MiB** (compute 8.6), pilote **615.71.09**, disques 221 Go / 221 Go / 889 Go. `evidence/2026-09-15/SUMMARY.md` §2. **Rôles exacts : ❌ non attribués** — aujourd'hui les trois font la même chose (data parallelism du VLM). |
| 1.3 | Déploiement vLLM | ✅ | `vllm 0.29.0` + `torch 2.13.0+cu132`, lancé par `nohup` (pas de systemd), `--host 172.26.145.NN --port 8000 --gpu-memory-utilization 0.90 --max-model-len 8192 --limit-mm-per-prompt {"image": 1}`. **DP = 3 instances indépendantes, pas de load-balancer** (le client doit choisir). Preuve : argv du processus dans `evidence/2026-09-15/*/v12-egress.log`. |
| 1.4 | Backend Django Ninja | ❌ | **rien**. `docs/03` décrit l'API prévue (upload, run, statut, PDF, vérif). |
| 1.5 | SQLite : schéma, migrations, triggers, WAL | 🟡 | Deux bases : `corpus.sqlite` (objects 48, images 155, `image_text_ocr` 144, predictions **0**, cpe_pairs **0**, runs 2) et `cpe.sqlite` (1,8 M). **Aucun trigger**, **aucun `PRAGMA journal_mode=WAL`** (mode par défaut), **aucune migration** — le schéma est créé par `contracts.py`. Le schéma cible (D15 : `corrections`, provenance, versions) est dans `docs/03`, **non implémenté**. |
| 1.6 | Communication entre machines | 🟡 | **SSH par mot de passe**, deux sauts (`postier.polytech-lille.fr:2222` → `172.26.145.NN`), helpers `remote.sh` / `ship-stream.sh` (SSH_ASKPASS). **Pas de mTLS, pas de VPN, pas de clé SSH installée** (les clés du bastion ne sont pas autorisées sur les nœuds internes — `SPEC` §3.1). |
| 1.7 | Port 8000 exposé ? | ✅ | **Bind LAN uniquement** (`172.26.145.x`), jamais `0.0.0.0` (SPEC §12.3). **Aucun jeton d'authentification, aucun rate limiting, pas de mTLS** → quiconque est sur le LAN peut appeler le modèle. |
| 1.8 | Docker / systemd / bare metal | ✅ | **Bare metal + `nohup`**. Pas de Docker, pas de Podman. Devuan 6 n'a **pas** systemd : arrêt par PID/groupe de processus (`vllm-service.sh`). |
| 1.9 | Gestion des secrets | ✅ | Mot de passe **jamais en argv ni en fichier** : `SSH_ASKPASS_REQUIRE=force` + helper lisant l'environnement (`remote.sh`) ; pour `sudo`, canal `env → stdin → env bastion → stdin → sudo -S` (`v12-run.sh`). **Vérifié le 2026-09-15** : 0 occurrence sur 66 518 / 69 088 / 66 512 fichiers par nœud. Pas de Vault, pas de HSM. |
| 1.10 | Reverse proxy | ❌ | Aucun (nginx/traefik/caddy absents). |
| 1.11 | Monitoring | ❌ | Pas de Prometheus/Grafana/Sentry. Seuls des **logs** (`~/logs/qwen_<host>.log`) + `golden-check.sh` (santé à la demande) + `R3-service-robustesse.log`. |
| 1.12 | Topologie réseau | 🟡 | LAN campus `172.26.0.0/16` ; DNS `172.26.188.12`, `193.48.57.48`. **Isolation du réseau étudiant : non vérifiée** — question ouverte. Le contrôle d'egress (V12) **a été prouvé** (3/3 domaines en timeout) mais **n'est pas appliqué en régime permanent**. |
| 1.13 | Si une machine tombe | ✅ | **Mesuré** (`19-V11-CLUSTER.md`) : lot de 2 400 requêtes, un nœud tué en vol → 2 400/2 400 OK, **0 abandonnée**, **522 redistribuées**, latences des survivants inchangées ; débit agrégé 57,9 → **36,1 req/s**. **Mais ce harnais de test n'est pas le produit** : aucun client de production avec bascule n'existe. |
| 1.14 | Reproductibilité de l'environnement | ✅ | `REQUIREMENTS_LOCKED.txt` + 4–6 `REQUIREMENTS_BEFORE_*.txt` par nœud (rollback), `ENV_STATUS.md` par nœud, `uv pip check` PASS (208/215/208). **Pas d'Ansible, pas de Nix, pas de Docker** — la reproductibilité repose sur des scripts idempotents. |

---

## 2 · Pipeline d'ingestion & données

| # | Question | Statut | Preuve |
|---|---|---|---|
| 2.1 | Entrée d'une photo | 🟡 | Aujourd'hui : **collecte par script** (`commons.py`, `openverse.py`) + `annotate.py`. **Aucune API, aucun dossier surveillé** (l'API est planifiée). |
| 2.2 | Formats acceptés | 🟡 | JPEG majoritairement (158 images). **Aucune validation de format** : pas de contrôle HEIC/PNG/RAW. |
| 2.3 | Prétraitement | 🟡 | Redimensionnement côté collecte ; **sha256** calculé (`provenance.json`) ; **pas de suppression EXIF**, **pas de floutage**. |
| 2.4 | Stockage des photos | 🟡 | `~/iot-audit/corpus/images/` (155 localement) **et** `~/iot-audit/corpus/images/` sur zabeth22. **Aucun chiffrement au repos**, permissions par défaut (`drwxrwsr-x`). |
| 2.5 | Durée de conservation | ❌ | **Aucune politique de rétention définie** dans un fichier. |
| 2.6 | Dataset : objets / photos / annotations | ✅ | **48 objets**, **155 images** (dont **144 rattachées**, vérifié : `images`=155, `image_text_ocr`=144), **5 catégories**, vérité terrain par objet dans `inventory.json` + `object-results.json`. |
| 2.7 | Définition des 5 catégories, qui valide | 🟡 | `smart_plug`, `ip_camera`, `smart_bulb`, `router_ap`, `smart_speaker` (+ `other` dans le schéma). Définies par l'agent dans `docs/06`, **validées par toi via le CDC** (`01_CAHIER_DES_CHARGES.md` §2.4 → « 5 minimum : *[À CONFIRMER]* »). |
| 2.8 | Cas multi-objets | ❌ | **Hors MVP**, assumé (`CDC` §2.3 : *« le système traite une photographie d'un objet unique, cadré et isolé »*). EF7 est un bonus non commencé. |
| 2.9 | White-label | ❌ | **Non traité.** Aucune règle, aucun test. C'est pourtant un cas réel (même ODM, marques différentes). |
| 2.10 | OCR | ✅ | **Deux moteurs** : RapidOCR (PP-OCR) et docTR (DBNet+CRNN), dans `ocrtext.py`. Usage : produire le drapeau `text_visible` (l'image contient-elle une identité lisible ?) — pour **exclure** les images où le modèle pourrait « tricher ». Mesuré : rappel 0,351 mot/image réelle (IC [0,322 ; 0,379]). |
| 2.11 | Détection d'étiquettes falsifiées | 🟡 | **Testé** (`11-RESULTATS-ADVERSAIRE.md`) : injection par l'image → **la catégorie suit l'injection** (`router_ap` → `other`) alors que marque/modèle résistent ; injection par le prompt → **détournement total** (`EvilCorp / X999`). **Aucun détecteur en production.** C20 : le schéma garantit la **forme**, pas la véracité. |
| 2.12 | Hash de la photo, journalisé | ✅ | **sha256** dans `provenance.json` / `corpus-snapshot.json`. **Pas de journal chaîné** pour autant (ENF3 ❌). |
| 2.13 | Terrain vs studio, biais | 🟡 | Stratification prévue par `scripts/` dans `contracts.py` (`stratum`, `sub`). Réalité mesurée : **98 % « terrain » (141/144)**, bras « propre » = **3 images** (`docs/06` §12.4). **Biais majeur, chiffré et documenté**, cause structurelle (Commons rejette le contenu promotionnel). |
| 2.14 | Anonymisation / minimisation RGPD | ❌ | **Rien.** Pas de floutage, pas de filtre « pas de personnes », pas de DPIA. Voir §8. |

---

## 3 · Modèle VLM & inférence

| # | Statut | Preuve |
|---|---|---|
| 3.1 | Modèle exact, révision, hash | ✅ **Qwen2.5-VL-7B-Instruct-GPTQ-Int4**, `sha256` des poids `25aab8ca505d…` + `d380b11007431…` (6 928 523 704 octets), **identiques sur les 3 nœuds**. `Llama-3.2-11B-Vision-Instruct-W4A16` présent mais **non servable** par vLLM 0.29.0 (C11). |
| 3.2 | Pourquoi ce modèle, benchmarks | 🟡 | `04-MODEL-SELECTION.md` : comparaison spec (`llama 3.2-vision`) vs cible. **Aucun benchmark comparatif des deux modèles n'a pu être fait** — Llama ne charge pas (C11). Le choix est argumenté, **pas mesuré**. |
| 3.3 | Prompt système / utilisateur, versions | ✅ | Prompts **versionnés et hashés** : v1 `sha256=26599423…`, v2 `sha256=e01e6db2…`, `temperature=0`, graine 1234, 1 image/requête (`14-EXPANSION-PROMPT-M6.md`). Prompt utilisé aujourd'hui : *« Identify the device: brand, model, category. »* |
| 3.4 | Schéma JSON guidé | ✅ | Schéma `{brand, model, category}` avec `enum` des catégories, `additionalProperties: false`, appliqué par `SamplingParams.structured_outputs=StructuredOutputsParams(json=…)`. **Vérifié sur les 3 nœuds le 2026-09-15** : `{"brand":"TP-Link","model":"TL-WR841N","category":"router_ap"}`. **Versionné ?** ❌ — le schéma vit dans le code, **sans numéro de version ni historique**. |
| 3.5 | Paramètres vLLM | ✅ | `temperature=0`, `max_tokens` 96–200 selon le test, `gpu_memory_utilization=0.90`, `max_model_len=8192`. **`top_p` non fixé** (défaut). **Batch size non piloté** (batching continu de vLLM). |
| 3.6 | Data Parallelism, load balancing | 🟡 | 3 instances indépendantes, **aucun load-balancer** (le client choisit). Le harnais `v11-bench.py` fait la répartition, **le produit non**. |
| 3.7 | Latence p50/p95/p99, cible < 10 s | ✅ | **Mesuré le 2026-09-15, n=12/nœud** : p50 **1,085 / 1,082 / 1,084 s**, p95 **1,878 / 1,091 / 1,861 s**. Cible ENF2 (p95 < 10 s) : **PASS, marge 5,3×**. **p99 ❌ non mesuré.** ⚠️ Le p50 publié avant (0,414 s) **n'est pas reproductible** (voir `23-CLOTURE-PHASE0.md`). |
| 3.8 | Taux d'erreur par catégorie, matrice de confusion | 🟡 | Mesuré **au niveau identification** (M9 : critère gelé, exactitude par strate). **Pas de matrice de confusion par catégorie** au sens strict. `06-VLM-ACCEPTANCE.md` + `docs/06` §8–§13. |
| 3.9 | Calcul de la confiance | ❌ | **Rien d'implémenté.** Formalisation dans `docs/05` §4 (deux axes : accord inter-photos **A** × résolvabilité CPE **R**, décision D7). Le score auto-déclaré du modèle n'est **pas** utilisé comme confiance (C21 : un seuil cosinus ne doit pas servir de critère d'identité). |
| 3.10 | Calibration de la confiance | ❌ | Aucune (temperature scaling / Platt / isotonic). |
| 3.11 | Fallback si le VLM échoue | ❌ | Aucun fallback automatique. La **bascule de nœud** est prévue (`docs/03`) mais non codée. EF5 (« non identifié — vérification manuelle requise ») : **spécifié, non implémenté**. |
| 3.12 | Robustesse : lumière, flou, angle, occlusion | 🟡 | **Courbe M6 dose-réponse** sur le flou (v1, 73 images) — `docs/06` §10.5. **Faible lumière, angle, occlusion : non mesurés.** |
| 3.13 | Cache d'inférence, reproductibilité | 🟡 | Reproductibilité du **texte** : **40/40 identiques** (T=0 et T=1,0 graine 1234, lots 1 et 8). **Stabilité des logits : non établie** ; batching hétérogène non testé. `enable_prefix_caching=True` (cache de préfixe) → latence « image répétée » **non représentative du flux réel**. |
| 3.14 | Prompt injection dans les images | 🟡 | **Testé, non mitigé** (voir 2.11). Piste identifiée dans `docs/03` : cohérence croisée entre champs (aurait attrapé l'injection de catégorie **sans modèle**) — **non implémentée**. OCR séparé : oui, mais pas comme filtre de sécurité. |
| 3.15 | Accès Internet du modèle | ✅ | **Non.** **Prouvé le 2026-09-15 sur les trois nœuds** (V12/G9) : nvd.nist.gov, huggingface.co, pypi.org en **timeout 8 s**, DNS campus + LAN OK, **inférence terminée sous confinement**. |
| 3.16 | Intégrité des poids | ✅ | `sha256` calculé et **comparé entre les trois nœuds** (`solidify-04`, V14). Identiques. |

---

## 4 · CPE / NVD / mapping

| # | Statut | Preuve |
|---|---|---|
| 4.1 | Sources exactes | ✅ **NVD API 2.0** pour le **dictionnaire CPE** (`cpeMatchString`), 920 pages, `sha256=f5df2cc8…`. **Aucune source CVE n'a été téléchargée.** |
| 4.2 | Téléchargement : fréquence, rate-limit, cache | 🟡 | Téléchargement **unique et manuel** (`fetch_cpe.py`, `fetch_cpe_standalone.py`), 920 pages. **Aucune planification, aucun rate-limit propre, aucun cache HTTP.** ⚠️ Le rate-limit NVD est un risque listé au CDC §9. |
| 4.3 | Stockage de la base locale | ✅ `cpe.sqlite` — **484 MB, 1 838 235 entrées** `cpe_entries` (part h : 64 842, a : 1 625 996, o : 147 397) **sur zabeth22 uniquement**. La copie locale ne contient que **4 000 entrées** — piège à connaître. |
| 4.4 | Parsing XML CPE | ✅ mais **partiel** : parsing par `iter_cpe_items` (streaming), **edge cases non testés** (`docs/07` §4 les exige). Ingestion 1 838 235 entrées en **27 s**. |
| 4.5 | Mapping marque/modèle → CPE | 🟡 | **Lexical d'abord** (D3) : normalisation + FTS5 + correspondance vendeur exacte ; embeddings en second. Le **matcher M4 v2** existe et est **mesuré** (`m4_bench_v2.py`, `m4-v2-results.json`) — **cibles non atteintes**, cause documentée (`15-M4-CPE-MATCHER.md`). |
| 4.6 | Plusieurs CPE correspondent | ✅ | Codes explicites : `E_CPE_AMBIGUOUS`, `E_NO_CPE_MATCH`, avec **marge de décision**. Correction mesurée en v2 : la marge doit se calculer **par produit**, pas par ligne de version (jusqu'à 19 lignes/version) — bug trouvé par la mesure, pas par relecture. |
| 4.7 | Gestion des versions (firmware inconnu) | ✅ | **C'est le cadrage central du projet** : triage **produit-level**, jamais « cet exemplaire est vulnérable ». `docs/01` + `CDC` §2.2. La décision de version est *explicitement* hors périmètre. |
| 4.8 | Filtrage des CVE | ❌ | **Rien** — aucune donnée CVE. Plan dans `docs/04` (filtre `part=h`, `cve_cpe_criteria`). |
| 4.9 | Score de pertinence | ❌ | Rien. |
| 4.10 | Mise à jour NIST qui casse les mappings | 🟡 | **Conçu** : `dictionary_versions` (URL, `sha256`, date, comptage) + D6 (dictionnaire immuable et versionné). **Implémenté** pour le CPE (`dictionary_versions` = 1 ligne). La politique de reprise sur mise à jour est écrite, pas exercée. |
| 4.11 | Signature / vérification des flux NVD | 🟡 | **`sha256` enregistré** (`dictionary_versions`). **Pas de vérification GPG** des flux NVD. |
| 4.12 | Base locale en lecture seule ? Qui écrit ? | 🟡 | `cpe.sqlite` est écrite par le script d'ingestion (`INSERT OR IGNORE`). **Aucun `chmod` de protection, aucun utilisateur séparé.** |
| 4.13 | Journal des modifications de la base | 🟡 | `dictionary_versions` trace **la version ingérée**, pas les modifications ligne à ligne. |
| 4.14 | NVD indisponible → mode dégradé | ❌ | **Non implémenté** (ENF4). Conçu dans `docs/04` (cache local, `E_NVD_UNAVAILABLE`). **Le mode dégradé « NVD coupé » de `docs/08` tâche 4.6 n'a jamais été exécuté** — il n'y a rien à couper. |
| 4.15 | Qualité du mapping : ground truth | 🟡 | **Banc M4 sur les objets du corpus** (vérité terrain connue) + preuve de concept sur des paires bruitées. **Les 200 paires annotées de `docs/06` §4.2 n'existent pas** (`cpe_pairs` = 0). |

---

## 5 · Journal HMAC & intégrité

| # | Statut | Réponse |
|---|---|---|
| 5.1–5.14 | ❌ **Rien n'est implémenté.** | Aucune table de journal, aucun HMAC, aucun chaînage, aucun trigger append-only, aucune clé, aucun outil de vérification, aucune signature asymétrique (Ed25519), aucun horodatage RFC 3161, aucun Merkle tree, aucune procédure de compromission de clé, aucun export tiers. |

**Ce qui existe** : la **conception** — `docs/03` (taxonomie d'erreurs, schéma), `docs/07` §4.3/§4.4 (le test d'altération **et** la limite de forgeage, à prouver au lieu d'être cachée), D11 et D14 dans `docs/02`. C'est un livrable du **bloc 3** de `docs/08` (semaine 3).

**Point d'honnêteté à porter en soutenance** : `docs/07` §4.4 demande explicitement de **prouver la limite du HMAC** (un HMAC symétrique n'est pas opposable par un tiers, d'où l'Ed25519). C'est un bon signe de conception, mais aujourd'hui **aucune des deux briques n'existe**.

---

## 6 · Rapport PDF & opposabilité

❌ **Rien n'est implémenté** (6.1–6.12) : pas de librairie PDF, pas de signature (HMAC/PAdES/Ed25519), pas de QR code, pas de clé publique publiée, pas de countersignature, pas de révocation, pas de registre public.

**Conçu** : EF4 (`CDC` §3), `docs/03` (sections et champs prévus), `docs/07` §3.4/§3.7, tâche 3.7 de `docs/08` (« Rapport PDF : structure, mention produit-level, clé publique, vérif », **5 h estimées**).

---

## 7 · Sécurité opérationnelle

| # | Question | Statut | Réponse |
|---|---|---|---|
| 7.1 | Isolation du réseau étudiant | ❓ | **Non vérifiée.** `SPEC` §12.3 exige que le port 8000 ne soit pas joignable depuis le réseau étudiant — **non testé**. L'isolation repose sur le bind LAN. |
| 7.2 | Accès du réseau admin école | ❓ | Inconnu. |
| 7.3 | SSH : clés, 2FA, bastion, allowlist, fail2ban | 🟡 | **Bastion** oui (`portier…:2222`) ; **mot de passe** (pas de clé installée sur les nœuds internes) ; **pas de 2FA, pas de fail2ban, pas d'allowlist**. `bootstrap_ssh.sh` existe pour installer une clé, **jamais exécuté en `--yes`**. |
| 7.4 | vLLM : mTLS, token, rate limiting, bind | 🟡 | **Bind LAN ✅** ; mTLS ❌ ; jeton ❌ ; rate limiting ❌. `docs/03` le prévoit. |
| 7.5 | Django : DEBUG, ALLOWED_HOSTS, CSRF, CORS | ❌ | Aucun Django. |
| 7.6 | SQLite : permissions, chiffrement, backups | 🟡 | Permissions par défaut ; **pas de chiffrement** ; **pas de sauvegarde** de la base CPE (484 MB) — elle est re-téléchargeable, `sha256` connu, mais la procédure n'est pas écrite. |
| 7.7 | Containers durcis | ❌ | Pas de containers. |
| 7.8 | Logs : où, rotation, intégrité, accès | 🟡 | `~/logs/qwen_<host>.log` sur les nœuds, `evidence/` sur le poste. **Aucune rotation, aucune intégrité, pas de contrôle d'accès.** |
| 7.9 | Monitoring, alertes, IDS | ❌ | Rien. |
| 7.10 | Réponse à incident | 🟡 | **Une partie existe et est bonne** : une injection de faute (kill -9) a trouvé un **vrai défaut de service** — un enfant reparenté à init, invisible dans `ps`, détenant 8 916 MiB — **corrigé**, avec un `stop` qui **nomme le détenteur** au lieu de refuser vaguement (C23, `R3-service-robustesse.log`). **Aucun playbook écrit pour autant.** |
| 7.11 | Sauvegardes, restauration testée | 🟡 | **Rollback d'environnement ✅** : 4–6 `REQUIREMENTS_BEFORE_*.txt` par nœud + procédure de retour de pilote documentée (`DECISION.md` §6). **Sauvegarde de données ❌.** |
| 7.12 | Gestion des vulnérabilités : scan, patch, CVE | 🟡 | Pilotes patchés (session 8, 4 incidents diagnostiqués). **Aucun scan de vulnérabilités** des nœuds. |
| 7.13 | Plan de reprise | ❌ | Non écrit. |
| 7.14 | Audit de configuration | ✅ **partiel mais réel** | `golden-check.sh` = **19–21 contrôles** par nœud (G1–G10 + 4 invariants infra découverts sur le terrain) : `verified` 17 PASS/0 FAIL/2 WARN (rapide), **20 PASS/0 FAIL/1 WARN (profond)** sur les trois le 2026-09-15. |

---

## 8 · Conformité légale & RGPD

**❌ Aucune de ces 14 questions n'a de réponse dans un fichier.** Pas de base légale écrite, pas de DPIA/AIPD, pas de registre des traitements, pas de durée de conservation, pas de mesures de minimisation, pas de clause sous-traitants, pas de procédure de violation, pas de formation.

**Ce qui existe** : une **intention** — `CDC` §1.3 (« traitement des données compatible avec les contraintes de confidentialité d'un audit réel »), ENF1 (inférence 100 % locale, aucune photo à un tiers) et `docs/01` (registre des affirmations). **La localité du traitement est un vrai argument RGPD** — et il est **prouvé** (V12/G9 : le modèle n'a pas d'accès Internet).

**Deux points à traiter avant tout usage réel** :
1. **§2.14 / §8.5** — les photos du corpus sont des produits, pas des personnes, mais **rien n'empêche une photo de terrain de contenir une personne ou un écran**. Aucune minimisation n'existe.
2. **§8.9 / §8.10 — autorisation écrite pour le fingerprinting réseau** : `CDC` §5 le dit explicitement, et `docs/08` (scope étendu) en fait un pré-requis. **Le scope MVP n'en a pas besoin** — décision à confirmer avec le tuteur pour ne pas laisser la porte ouverte.

---

## 9 · Tests, évaluation, red-teaming

| # | Statut | Preuve |
|---|---|---|
| 9.1 | Tests unitaires, couverture | ❌ **Aucun test** dans le projet (`docs/07` en exige 5 critiques). Zéro couverture mesurable : le seul chiffre honnête est **0 %**. |
| 9.2 | Tests d'intégration | ❌ Aucun (pas de pipeline complet à tester). |
| 9.3 | Tests de performance | ✅ **Mesurés** mais **hors suite** : latence p50/p95 (n=12 ×3 nœuds), débit 57,9 req/s agrégé, V11b. **Aucun test automatisé.** |
| 9.4 | Tests adversariaux | ✅ **8 cas exécutés** (C20) : référence, image dégradée, **instruction imprimée dans l'image**, **instruction hostile dans le prompt**, valeur hors-énum, propriété supplémentaire, image blanche, prompt long bruité. Résultats : **forme 8/8**, **contenu 6/8** (2 échecs). |
| 9.5 | Red-teaming du VLM | 🟡 Idem 9.4 — c'est le red-teaming existant. |
| 9.6 | Red-teaming du système (réseau, API, HMAC) | 🟡 Réseau : **V12 fait** (egress prouvé). API ❌ (n'existe pas). HMAC ❌ (n'existe pas). |
| 9.7 | Précision, rappel, F1, calibration | 🟡 Précision/rappel **par strate** et **par critère gelé** (`docs/06` §8–§13, IC de Wilson/bootstrap). **F1 non calculé. Calibration non faite.** |
| 9.8 | Matrice de confusion par catégorie | ❌ Non produite. |
| 9.9 | Taux de faux positifs / négatifs | 🟡 **Faux négatifs du drapeau `text_visible` : ≥ 15,2 % des identités lisibles** (Chapman, n₁=47/n₂=46/m=39 → 55,4 images légibles estimées, IC95 [52,7 ; 58,1]). C'est une vraie mesure, publiée comme minorant. **Faux positifs : non mesurés.** |
| 9.10 | Accord inter-photos, corrélation avec la vérité | 🟡 Accord **40/40** sur texte (T=0 vs T=1,0 graine fixée). La corrélation accord↔justesse est **précisément ce que D7 refuse de supposer** (8 hallucinations identiques donneraient A = 1,0) — **non mesurée**. |
| 9.11 | Reproductibilité | ✅ **Texte 40/40 identique.** **Logits : non vérifiés** — et c'est écrit comme limite, pas caché. |
| 9.12 | Non-régression (modèle/prompt) | 🟡 **Un cas réel existe** : le passage prompt v1 → v2 a été mesuré (documents avec et sans) — `docs/06` §10.4. **Aucun test automatisé de non-régression.** |
| 9.13 | Jeu de test adversarial public | ❌ Non. |
| 9.14 | Bug bounty interne | ❌ Non. |

**Le point fort réel** : la **méthode de mesure est de niveau recherche**, pas étudiante. Critère **gelé avant comptage**, **réplication hors échantillon** (0,350 vs 0,352 sur deux moitiés disjointes), **bootstrap par grappes** sur les images, **IC**, **contrôle de confusion posé avant lecture du résultat**, **réfutation de ses propres hypothèses** (deux fois : §12.2 bis puis C27), **barème gelé réutilisé et asserté** (8/8 agrégats). C'est ce qui impressionnera un jury sécurité.

---

## 10 · Reproductibilité & versioning

| # | Statut | Réponse |
|---|---|---|
| 10.1 | `model_revision` épinglée | 🟡 `sha256` des poids ✅ ; **révision HuggingFace non épinglée** (`revision=` non passé au chargeur). |
| 10.2 | `prompt_version` | ✅ **v1 / v2**, hashés (`26599423…`, `e01e6db2…`), historique dans `14-EXPANSION-PROMPT-M6.md`. |
| 10.3 | `schema_version` (JSON) | ❌ Le schéma JSON n'a **ni version ni historique** — il vit dans le code. |
| 10.4 | `dataset_version` | 🟡 `corpus-snapshot.json` + `measure-manifest.json` (102 KB) + `inventory.json` ; **pas de hash global unique** du dataset. |
| 10.5 | environment : lockfile, seeds | ✅ `REQUIREMENTS_LOCKED.txt` (208/215), `temperature=0`, **graine 1234**. |
| 10.6 | NVD snapshot : date, hash, signature | 🟡 **CPE** : `dictionary_versions` (URL, sha256, date, comptage) ✅. **CVE : rien.** |
| 10.7 | CPE dictionary : version, hash | ✅ `dictionary_versions` = 1 ligne ; `sha256=f5df2cc8…`, 920 pages. |
| 10.8 | Code : git tag, commit | ❌ **Aucun Git.** |
| 10.9 | Configuration | 🟡 `infra/config/cluster.env` ✅ ; `~/iot-audit/.gitignore` existe mais **il n'y a pas de dépôt** (détail révélateur). |
| 10.10 | Procédure de reproduction documentée et testée | 🟡 **Scripts idempotents** (`deploy-zabeth-node.sh` par phases) + section « Reproduce any cell » de `SUMMARY.md`. **Testée sur les 3 nœuds** ✅ mais pas sous forme de test automatisé. |
| 10.11 | Manifeste de run | 🟡 `measure-manifest.json` (gel du barème) ✅ ; `runs` = 2 lignes dans `corpus.sqlite`. Pas de manifeste de run **produit**. |
| 10.12 | Changements de modèle | ❌ Aucune procédure (le modèle n'a jamais changé). |

---

## 11 · Projet, PFE, soutenance

| # | Statut | Réponse |
|---|---|---|
| 11.1 | Objectifs PFE | 🟡 **Deux choses distinctes, à ne pas confondre** : (a) le **projet scolaire** = sujet 7, Polytech Lille, tuteur Thomas Vantroys, ~4 semaines, solo (`docs/README.md`) ; (b) le **PFE de 7 mois** visé **à partir de janvier 2027** — ce projet **n'est pas** ce stage, il doit seulement rester cohérent avec le positionnement sécurité-IA / offensif (`00_CONTEXTE` §« Ce que je cherche »). |
| 11.2 | Cibles | ✅ Synacktiv, Quarkslab, Amossys, Mistral AI, Wavestone, Giskard (`00_CONTEXTE`). |
| 11.3 | Livrables pour la soutenance | 🟡 Cf. `CDC` §6 (6 livrables). **Produits : 0 sur 6 entièrement** — docs ✅, dataset ✅ (48 objets > cible 8–10), code versionné ❌, rapport PDF ❌, support de soutenance ❌. |
| 11.4 | Démo prévue | ❌ Non définie. `CDC` §6.6 exige un **mode hors-ligne + vidéo de secours** — **rien n'est préparé**. C'est le point qui fait basculer une soutenance. |
| 11.5 | Limites déjà documentées | ✅ **Excellent point** : `docs/01-scope-claims-limits.md` = registre des affirmations ; 15 décisions argumentées (`docs/02`) ; 5 limites dans `docs/07` §8 ; et des limites **mesurées** (98 % terrain, bras propre 3/144, faux négatifs ≥ 15,2 %, M4 sous la cible). |
| 11.6 | Affirmations à ne pas faire | ✅ Clair : **jamais « cet exemplaire est vulnérable »** (pas de version firmware) — c'est le cadrage produit-level, répété dans tous les docs. À ajouter : ne pas dire que `no_text` est « mesuré » (c'est une **borne supérieure**) ; ne pas présenter 0,414 s (non reproductible). |
| 11.7 | Questions de jury anticipées | 🟡 `docs/01` §4 en annonce 5. **Manque une question évidente** : « vous avez 48 objets et 155 photos, quel est votre **intervalle de confiance** sur les métriques ? » — il est déjà calculé, autant l'avoir en tête. |
| 11.8 | Narratif professionnel | ✅ Cohérent : IA appliquée + sécurité, triage produit-level, inférence locale, journal inaltérable. C'est exactement l'axe sécurité-IA. |
| 11.9 | Planning restant | 🟡 `docs/08` : semaines 0→4, ~mi-octobre. **Semaine 0 (geler le contrat) : ✅ faite** ; **semaine 1 (spine de données)** : partiellement (CPE ✅, schéma partiel, **FTS5 ❌, CVE ❌**) ; **semaines 2–3** : presque tout ❌. |
| 11.10 | Risques calendaires | ✅ Identifiés : entretiens PFE imprévisibles (écrit noir sur blanc dans `00_CONTEXTE` et `CDC` §5), annotation manuelle du corpus toujours repoussée (risque n° 2 de `docs/08`), PDF + API sous-estimés (risque n° 3). |

---

## 12 · Questions pour brainstorming — mon avis franc

**1. Le plus fragile aujourd'hui.** Pas la technique : **l'absence de dépôt Git et de tests**, et le fait que **le cœur du sujet — CVE — n'existe pas du tout**. On a une infrastructure dorée et un corpus mesuré, mais le système ne répond pas encore à la question du sujet (« quelles failles pour cet objet ? »). Et **tu dois pouvoir défendre à l'oral chaque décision d'un travail produit à ~95 % par un agent** : c'est le vrai risque de recadrage.

**2. Le plus innovant.** La **démarche de mesure** : critère gelé avant comptage, réplication hors échantillon, réfutation de ses propres hypothèses (deux fois, publiquement), borne supérieure assumée plutôt que chiffre flatteur. Beaucoup de projets étudiants présentent des chiffres ; très peu présentent **les conditions qui les invalideraient**.

**3. Ce que les agents ont fait que tu ne comprends peut-être pas entièrement.** Trois choses, par ordre de danger : (a) **le drapeau `text_visible` et son basculement sur l'union de deux moteurs OCR** — c'est une décision méthodologique subtile ; (b) **la réestimation par capture–recapture (Chapman)** du nombre d'images lisibles et le passage de `no_text` de « mesure » à « borne supérieure » ; (c) **la réfutation de §12.2 bis** (je prédisais que docTR ferait baisser `no_text` ; la mesure a montré l'inverse). Ces trois points, un jury peut les creuser.

**4. À améliorer sans savoir comment.** Le **white-label** (même matériel, marques différentes) n'est pas traité et casserait le matcher. Et le **passage de 144 images à une évaluation défendable par catégorie** : 5 catégories × ~29 images, les IC par catégorie seront larges.

**5. Avec 2 mois de plus.** (i) **Ingestion NVD CVE + FTS5 + résolution** (le chemin critique) ; (ii) **journal HMAC + Ed25519 + PDF vérifiable** (le bloc « opposabilité », très différenciant en entretien) ; (iii) **un vrai jeu de photos de terrain** (le bras « propre » à 3 images est le plus gros défaut du corpus) ; (iv) **matériel IoT physique** — 50–60 € changent la crédibilité de la démo.

**6. À supprimer.** Le **scope étendu « fingerprinting réseau »** : coût légal (autorisation écrite) pour un gain incertain, et il brouille le cadrage produit-level. Le retirer proprement du document plutôt que le laisser en « option ».

**7. Ce qui pourrait te faire recaler.** (i) **Pas de Git** alors que c'est un livrable écrit ; (ii) **pas de démo préparée** ni de mode hors-ligne alors que le CDC l'exige ; (iii) **aucune fonctionnalité CVE**, alors que l'énoncé du sujet est explicite ; (iv) **ne pas savoir défendre** les décisions prises par l'agent ; (v) **sur-affirmer** (parler de « vulnérabilités de cet objet »).

**8. Ce qui impressionnerait un jury sécurité.** Le **journal HMAC dont la limite est prouvée par un test**, l'**Ed25519 sur la tête** pour l'opposabilité tierce, l'**absence d'egress prouvée** (V12, avec restitution propre), la **réfutation documentée de ses propres hypothèses**, et le **test d'injection par l'image** (2 échecs sur 8, publiés).

**9. Ce qui intéresserait un recruteur.** Exactement ton axe : « j'ai fait tourner un VLM en local, sans egress, avec sortie structurée contrainte, sur un cluster de 3 GPU, et je sais ce que ça ne prouve pas ». Plus la **gestion d'incidents réels** (nouveau vs nvidia, header CUDA patché, enfant reparenté détenant la VRAM).

**10. Ce qui manque pour passer de POC à outil utilisable.** Dans l'ordre : **CVE** → **API** → **confiance calibrée** → **journal + PDF vérifiable** → **tests** → **Git** → **HITL**. Tant que les trois premiers manquent, ce n'est pas un outil : c'est un banc de mesure très bien fait.

---

## Ce que je te conseille de faire dans la prochaine heure

1. **`git init` + premier commit** sur `~/iot-audit/`. C'est 10 minutes, c'est un livrable, et son absence est indéfendable.
2. **Trancher avec le tuteur** les 5 questions ouvertes de `docs/README.md` — dont le scope étendu à retirer ou valider.
3. **Décider du périmètre de la soutenance** : à ce stade, un système complet n'est pas atteignable. Le choix honnête est soit **réduire** (identification + CPE + rapport simple, sans HMAC/Ed25519), soit **assumer le banc de mesure** comme livrable principal — dans les deux cas, **c'est une décision à prendre, pas à subir**.

---

*Sources de ce document : `iot-audit/README.md`, `docs/01`–`08`, `docs/README.md`, `infra/SPEC-infra-setup.md`,
`infra/config/cluster.env`, `Downloads/00_CONTEXTE_ET_PROFIL.md`, `Downloads/01_CAHIER_DES_CHARGES.md`,
`~/zabeth22-vllm-repair/{README.md,04,06,11,14,15,18,19,20,21,22,23}*.md`, `logs/LOG.md`,
`evidence/2026-09-14/**`, `evidence/2026-09-15/**`, et des commandes exécutées sur les trois nœuds
le 2026-09-15 (schémas SQLite, comptages, `find`, `grep`).*
