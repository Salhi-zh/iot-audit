# Annexe — ce qui reste non commité, fichier par fichier (2026-10-06)

Produit après `591bd9b` (provenance, station), `c079209` (provenance, nœud ; l'état fautif intermédiaire, `ef07748`, a été
amendé et n'est pas dans l'histoire) et
`3384549` (épingle de révision). **Mesuré**, pas estimé : `git diff --name-only` + `git diff -U0`.

## Correction d'une estimation que j'avais donnée

Je pensais qu'il restait des corrections de date `2026-10-07 → 2026-10-06` dans une
cinquantaine de fichiers. Mesure : **0 ligne** `2026-10-07` subsiste dans le diff — ces
corrections sont déjà commitées (`591bd9b`, `eb76e68`). Ce qui reste est bien plus petit :
**10 fichiers** de réordonnancement d'imports, et le **travail en attente** du poste
dans 38 fichiers.

## 1. Réordonnancement d'imports seul (10 fichiers) — candidat à un commit unique

`corpus/` n'est **pas** couvert par la porte ruff du dépôt
(`ruff check iot_audit verify_report.py benchmarks tests`) : `ruff check corpus/` rapporte
100 erreurs aujourd'hui dans l'arbre de travail. Ces déplacements ne corrigent donc aucune
porte, et rien ne dépend d'eux. Ils sont neutres sémantiquement (même ensemble d'imports,
ordre différent), ce qui est vérifiable d'un coup d'œil — mais leur **attribution** (passe
automatique de quelle session ?) n'est pas établie par la mesure.

| fichier | lignes déplacées |
|---|---|
| `corpus/compare_nodes.py` | 4 |
| `corpus/fetch_cpe_standalone.py` | 2 |
| `corpus/ocr-validation/evaluate_engine2.py` | 2 |
| `corpus/probe-divergence.py` | 10 |
| `corpus/probe-token-budget.py` | 10 |
| `corpus/publish_by_category.py` | 1 |
| `corpus/runner2-v2.py` | 14 |
| `corpus/runner3-v3.py` | 14 |
| `corpus/runner3b-v3-640.py` | 14 |
| `corpus/runner4-v4-cap640.py` | 14 |

## 2. Travail en attente (38 fichiers) — intact, non touché

Aucun hunk de cette catégorie ne porte de ligne de cette session : c'est le chantier du
poste (mesure VRAM du moment, déplacement du shebang, arrêt par PID, nettoyage des
runners, notes de cahiers). Il n'est pas détaillé ici — le recopier serait recopier un
travail qui n'est pas le mien.

| fichier | lignes touchées |
|---|---|
| `infra/README.md` | 1501 |
| `infra/scripts/node_gpu_bench.sh` | 1151 |
| `cahiers/NOTE-CONFORMITE-z23-tailscale.md` | 239 |
| `corpus/diagnose_identification.py` | 158 |
| `infra/selftest/README.md` | 154 |
| `infra/scripts/cluster_status.sh` | 68 |
| `infra/scripts/node_golden_check.sh` | 52 |
| `infra/lib/lib_cluster.sh` | 39 |
| `README.md` | 35 |
| `corpus/runner-bench-zabeth22.py` | 29 |
| `corpus/run1-prompt-perturb.py` | 25 |
| `infra/scripts/node_write_provenance.sh` | 22 |
| `infra/lib/lib_serve.sh` | 21 |
| `cahiers/CDS-v2.1-proposition.md` | 19 |
| `infra/scripts/start_qwen_all.sh` | 19 |
| `cahiers/CDC-v3.1-proposition.md` | 15 |
| `infra/scripts/bootstrap_ssh.sh` | 13 |
| `corpus/ocr-validation/flag_swap_legibility.py` | 11 |
| `corpus/calibrate_status.py` | 10 |
| `corpus/m4_bench_standalone.py` | 8 |
| `corpus/ocr-validation/corpus_legibility.py` | 8 |
| `infra/scripts/start_llama_all.sh` | 8 |
| `corpus/m4_bench_v2.py` | 6 |
| `infra/scripts/run_benchmark.sh` | 6 |
| `cahiers/README.md` | 5 |
| `corpus/assemble_evidence_v3.py` | 5 |
| `corpus/compare_v4.py` | 5 |
| `corpus/grade_v3.py` | 5 |
| `corpus/ingest_cpe_standalone.py` | 5 |
| `corpus/ocr-validation/evaluate_ocr.py` | 5 |
| `corpus/make_runner_v4.py` | 4 |
| `corpus/ocr-validation/flag_swap_identification.py` | 4 |
| `infra/scripts/node_install_venv_environment.sh` | 4 |
| `cahiers/PLANNING-13-SEMAINES.md` | 3 |
| `corpus/make_runner_v3.py` | 2 |
| `corpus/ocr-validation/fetch_coco_text.py` | 2 |
| `docs/README.md` | 2 |
| `infra/selftest/bin/ssh` | 2 |
