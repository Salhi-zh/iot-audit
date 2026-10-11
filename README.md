# iot-audit — projet & infrastructure

**Projet :** Reconnaissance d'objets connectés pour audit de sécurité IoT
**Auteur :** Mohamed Salhi — Polytech Lille / ENSA Kénitra · **Tuteur :** Thomas Vantroys
**Périmètre :** ~4 semaines solo · **CDC 16/09** · **Specs 18/09**
**Racine :** `~/iot-audit/` — tout ce qui suit vit ici, rien en vrac dans `$HOME`.

Photo d'un objet connecté → marque/modèle/catégorie → CPE (NIST) → CVE (NVD local) → rapport PDF signé + journal chaîné HMAC.
Le système fait du **triage produit-level** : il ne dit jamais qu'un exemplaire précis est vulnérable (une photo ne donne pas la version firmware).

---

## Arborescence

```
~/iot-audit/
├── README.md                    ce fichier — index maître
├── .gitignore
├── docs/                        conception du projet (le « quoi » et le « pourquoi »)
│   ├── README.md                index du jeu de plans + registre des décisions + questions ouvertes
│   ├── 01-scope-claims-limits.md      périmètre MVP, registre des affirmations, limites assumées
│   ├── 02-decisions.md                15 décisions argumentées (alternatives rejetées, preuves)
│   ├── 03-architecture.md             couches, contrats d'interface, SPOF, taxonomie d'erreurs
│   ├── 04-data-pipelines.md           pipelines CPE + NVD, volumétrie, versioning, SQL
│   ├── 05-matching-and-confidence.md  matching CPE flou, seuils, formalisation de la confiance
│   ├── 06-corpus-and-metrics.md       photos internet, contamination, puissance statistique
│   ├── 07-verification-plan.md        preuves / tests / benchmarks avec critères d'acceptation
│   └── 08-execution-plan.md           planning, tâches atomiques, chemin critique, risques
├── infra/                       infrastructure du cluster zabeth (3 nœuds RTX 3060)
│   ├── README.md                guide d'utilisation des scripts + faits vérifiés du cluster
│   ├── SPEC-infra-setup.md      **spécification à remettre à l'agent qui met en place l'infra**
│   ├── config/
│   │   ├── cluster.env                    configuration partagée (IP, ports, chemins, seuils)
│   │   ├── ssh_config.workstation.example ProxyJump via portier
│   │   ├── ssh_config.node.example        LAN direct, depuis un nœud
│   │   └── hosts.example                  entrées /etc/hosts optionnelles
│   ├── lib/
│   │   ├── lib_cluster.sh                 helpers ssh, sondes, wait/kill
│   │   └── lib_serve.sh                   lancement/arrêt parallèle
│   ├── scripts/
│   │   ├── bootstrap_ssh.sh               installation de clé (dry-run par défaut)
│   │   ├── cluster_status.sh              tableau de bord (ping, SSH, GPU, ports, disques)
│   │   ├── sync_models.sh                 réplication des artefacts + vérification d'intégrité
│   │   ├── start_qwen_all.sh / stop_qwen_all.sh    vLLM Qwen2.5-VL, port 8000
│   │   ├── start_llama_all.sh / stop_llama_all.sh  llama-server, port 8001
│   │   ├── run_benchmark.sh               pilotage de benchmark_distributed.py
│   │   └── node_*.sh                      scripts exécutés SUR un nœud (noms sur le nœud différents —
│   │                                      ex. node_gpu_bench.sh → ~/gpu-bench-node.sh ; voir infra/README.md)
│   ├── selftest/                harnais hors-ligne (faux ssh/rsync) pour tester sans les machines
│   └── journal/
│       └── 2026-09-14-cluster-tooling.md  journal de la session de conception
└── evidence/                    artefacts d'exécution (logs, mesures, rapports) — gitignored
```

## Où trouver quoi

| Je cherche… | Aller à |
|---|---|
| Ce que le projet promet et ne promet pas | `docs/01-scope-claims-limits.md` |
| Pourquoi tel choix technique (et pas l'autre) | `docs/02-decisions.md` |
| Le plan de preuve : tests, benchmarks, seuils | `docs/07-verification-plan.md` |
| Les dates, tâches, risque de dépassement | `docs/08-execution-plan.md` |
| Comment lancer/arrêter le service, état du cluster | `infra/README.md` |
| **Ce qu'il faut faire pour réparer l'infra** | `infra/SPEC-infra-setup.md` |
| Les faits **vérifiés** sur les machines | `infra/README.md` §« VERIFIED » et `SPEC-infra-setup.md` §3 |

## État actuel — sans enjolivement

| Élément | État |
|---|---|
| `docs/` | **complet** (v1, 2026-09-14) — chiffres marqués `VERIFY` à mesurer avant le CDC |
| Scripts `infra/scripts/` | écrits, `bash -n` OK, validés hors-ligne via `infra/selftest/` ; `node_golden_check.sh` **exécuté contre les vraies machines** les 2026-09-15, 2026-09-16 et **2026-09-17** (ce dernier run : les scripts ont été exécutés *depuis le dépôt*, via le bastion → `infra/README.md` §AMENDMENT 2026-09-17) |
| Cluster zabeth | **3 nœuds sur 3 dorés** — G1–G10 fast *et* deep, 0 FAIL → `evidence/2026-09-16/cluster-golden-recheck/SUMMARY.md` |
| Drivers | **homogènes** : 615.71.09 sur les trois (CUDA 13.4-capable) — `evidence/2026-09-15/SUMMARY.md` |
| Service vLLM | démarré : vLLM 0.29.0 + torch 2.13.0+cu132 sur les 3, port 8000 ; p50 ≈ 1,08 s pour une cible de 10 s. **Re-vérifié le 2026-09-17** par inférence réelle (prompt + schéma du dépôt, images du corpus) : 0,98–2,92 s, JSON conforme |
| Accès SSH | ✅ clé `id_zabeth` installée (bastion + 3 nœuds) le **2026-09-17** ; `ssh zabeth2{1,2,3}` sans mot de passe, **node→node vérifié dans les 6 sens** → `sync_models.sh` copie en direct sur le LAN (`direct rsync (LAN)`), plus de relais par l'orchestrateur |
| Outils par nœud | ✅ `~/golden-check.sh` + `~/vllm-service.sh` **identiques sur les 3 nœuds** (sha256 = fichiers du dépôt, mode 755, shebang en ligne 1), installés le 2026-09-17. Preuve : `golden-check.sh --json` → **17 PASS / 0 FAIL / 2 WARN, NOEUD DORE ×3** ; `$HOME/golden-check.sh` existe partout (ferme le défaut de provenance SPEC §C30) |
| Redémarrage / supervision | ❌ **rien** — vérifié le 2026-09-17 : aucun `crontab`, aucun `init.d`, aucune unité utilisateur, `/etc/boot.d` **vide** sur les 3 nœuds. Le service ne survit pas à un reboot ; il faut relancer à la main |
| Egress | **prouvé bloqué** en test (V12, 3/3 domaines) ; re-vérifié le 2026-09-16 → `evidence/2026-09-16/v12-egress-rerun/` |
| `benchmark_distributed.py` | **absent des machines** — vérifié le 2026-09-17 : pas de `~/benchmark_distributed.py` sur les 3 nœuds (`~/datasets` et `~/bench` vides). `run_benchmark.sh` ne peut donc pas tourner tel quel ; le harnais réellement présent sur le cluster est `~/v11-bench.py` (zabeth22) |
| Phase B (llama.cpp / GGUF) | **non déployée** — vérifié le 2026-09-17 : aucun `~/llama.cpp`, aucun `*.gguf`/`*mmproj*`, port 8001 libre sur les 3 nœuds (`infra/README.md` §AMENDMENT 2026-09-17) |
| Corpus (photos) | **48 objets / 144 images publiables** (+11 orphelines hors périmètre) — `corpus/corpus.sqlite`, `corpus/manual-removals.json` |
| Ingestion CVE | **absente** — c'est le chemin critique restant (`docs/08`) |

> **Le blocage n'est plus l'infrastructure, mais le cœur du sujet.** L'infra est dorée et mesurée ;
> ce qui manque est en aval : **aucune donnée CVE**, pas d'API, pas de PDF, pas de journal HMAC,
> aucun test, et **pas de dépôt Git**. Voir `ETAT-DES-LIEUX-2026-09-15.md` §0.5.
>
> Cette table a été corrigée le 2026-09-17 : elle affirmait encore « 1 nœud sur 3 », des pilotes
> « hétérogènes » et un service « non démarré », faux depuis la session du 2026-09-15.

## Démarrage rapide

```bash
# 1. lire l'état du projet
less docs/README.md

# 2. installer l'accès SSH (dry-run, puis --yes)
cd infra/scripts
./bootstrap_ssh.sh
./bootstrap_ssh.sh --yes

# 3. voir l'état réel du cluster (lecture seule, ne modifie rien)
./cluster_status.sh

# 4. quand l'infra est prête : Phase A puis Phase B
./start_qwen_all.sh
./run_benchmark.sh --model qwen --images ~/datasets/bench --output ~/bench/qwen.json
./stop_qwen_all.sh
```

**Avant tout lancement de serveur :** lire `infra/README.md` §« Before Phase A » — le préflight refuse de démarrer sur un nœud dont le driver ne supporte pas le build torch installé.

## Conventions

* **Aucun secret dans un fichier.** Mot de passe via `$ZABETH_SSH_PASS` ou `~/.zabeth_pass` (chmod 600), jamais en argument de commande (`ps` l'exposerait).
* **Les artefacts d'exécution vont dans `evidence/`**, pas à côté des sources.
* Les documents `docs/` sont en français ; les commentaires de code sont en anglais.
* Toute affirmation chiffrée est étiquetée `PROUVÉ` / `MESURÉ` / `LIMITE` (voir `docs/01`).

## Note : dossier voisin `~/zabeth22-vllm-repair/` vs barème vendored

`~/zabeth22-vllm-repair/` **n'est pas dans cette arborescence**, volontairement.

* Historique 2026-09-14/17 : le dossier était le seul accès fonctionnel au cluster
  depuis un poste sans clé (`remote.sh`, `SSH_ASKPASS_REQUIRE` — voir
  `infra/README.md` §AMENDMENT 2026-09-17) et 8 scripts de `corpus/` y
  chargeaient `audit-grading.py` via `IOT.parent` (blocage documenté jusqu'au
  2026-09-17).
* Depuis 2026-09-29 le **barème est vendored** : `iot_audit/corpus/audit_grading.py`
  (byte-frozen, voir `iot_audit/corpus/VENDORED-audit-grading.md`). Les 8 scripts
  passent désormais par `corpus/_common.py` (`GRADING` dans le dépôt + `load_grading()`
  via `importlib`). `tests/test_grading_vendored.py` verrouille la copie (2 empreintes +
  diff d'une ligne `EV`). Le seul point de couplage restant vers le voisin est le
  fichier `GRADING_SOURCE` dans `_common.py` (utilisé uniquement pour vérifier la
  non-dérive quand le voisin est présent, sinon skippé).
* Un artefact isolé a été absorbé dès 2026-09-17 : `gpu-bench-node.sh` →
  `infra/scripts/node_gpu_bench.sh` (`bfe192a8…` puis `8e774069…` v2, v1 conservée
  dans `evidence/2026-09-17/gpu-bench-instrument/` — règle R7).

`~/zabeth22-vllm-repair/` reste en place comme **référence hors dépôt** pour la
reproductibilité et l'historique de la clé SSH ; il n'est plus requis pour
rejouer les preuves image déjà publiées (`evidence/2026-09-14/*`, `2026-09-15/*`).
