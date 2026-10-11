# 08 — Plan d'exécution

**Aujourd'hui :** 2026-09-14 · **CDC :** 16/09 · **Specs :** 18/09 · **Fin :** ~mi-octobre · **Solo**

Principe directeur : **le chemin critique n'est pas l'IA.** C'est la donnée (CPE → CVE) et la preuve. L'inférence est la partie confortable ; elle doit être traitée tôt mais elle n'est pas le risque.

---

## Semaine 0 — 14 → 18/09 : geler le contrat, pas le code

But : le CDC et les specs ne doivent **pas** dépendre de ce qui n'est pas encore résolu.

| # | Tâche | Durée | Dépend de |
|---|---|---|---|
| 0.1 | Trancher la question du driver (lecture `nvidia-smi` sur les 3 machines) | 1 h | accès SSH |
| 0.2 | Réécrire la ligne de pile du CDC : **aucun pin vLLM** (D1) | 1 h | — |
| 0.3 | Mesurer les vrais volumétries NVD + CPE (méthode : `curl -sI`, compteurs) | 2 h | réseau |
| 0.4 | Remplacer « 200 Go » et « terrain ≥ 50 % » par les chiffres mesurés (ou retirer) | 1 h | 0.3 |
| 0.5 | Rédiger le **registre des affirmations** (`01` §3) et le joindre aux specs | 2 h | — |
| 0.6 | Rédiger les métriques révisées (`06` §5) avec `n` et IC | 1 h | 0.5 |
| 0.7 | Figer la **source de vérité** : schéma JSON VLM, taxonomie d'erreurs, provenance | 3 h | — |
| 0.8 | Décider D11 (Ed25519) — impacte le schéma, donc à décider **avant** les specs | 1 h | — |

**Livrable :** CDC + specs cohérents, avec des chiffres vrais et des limites écrites.
**Règle :** si 0.1 est bloqué (accès indisponible), 0.2 reste applicable — c'est précisément l'intérêt de D1.

---

## Semaine 1 — le spine de données (le vrai chantier)

| # | Tâche | Durée | Dépend de |
|---|---|---|---|
| 1.1 | Arborescence du dépôt + `contracts.py` (les dataclasses de `03`) | 3 h | 0.7 |
| 1.2 | Migrations SQLite : D15 complet (provenance, versions, critères, `corrections`) | 3 h | 1.1 |
| 1.3 | Téléchargement CPE + `sha256` → `dictionary_versions` | 2 h | 1.2 |
| 1.4 | `iter_cpe_items` + `INSERT OR IGNORE` versionné + test d'idempotence | 3 h | 1.3 |
| 1.5 | `normalize.py` + **tests des 3 pièges** (`v2`→`2`, `smart switch`, échappements) | 3 h | 1.1 |
| 1.6 | `category_rules` + annotation de 200 entrées (⇒ précision D12) | 4 h | 1.4 |
| 1.7 | Index **FTS5** sur `(vendor, product, display_name)` | 2 h | 1.4 |
| 1.8 | Ingestion NVD : streaming `ijson`, filtre `part=h`, table de critères indexée | 4 h | 1.2 |
| 1.9 | Reprise sur erreur des deux pipelines + `ingest_progress` | 2 h | 1.4, 1.8 |
| 1.10 | **Démarrage collecte corpus** (métadonnées : URL, licence, strate, `text_visible`) | 2 h puis en continu | — |

**Fin de semaine 1, obligatoire :** `parse_cpe` et `ingest_nvd` tournent **deux fois** sans doublon, avec `row_count` cohérent. C'est la preuve d'idempotence et elle débloque tout le reste.

---

## Semaine 2 — inférence et résolution

| # | Tâche | Durée | Dépend de |
|---|---|---|---|
| 2.1 | Serveur vLLM opérationnel (profil retenu en 0.1) + prompt versionné | 3 h | 0.1 |
| 2.2 | Schéma JSON + Guided Decoding, **échec provoqué** → `E_VLM_INVALID_JSON` | 3 h | 2.1 |
| 2.3 | Client `VLMRunner` : timeout, retry/backoff, bascule de nœud, latences mesurées | 4 h | 2.1 |
| 2.4 | Module Ingest : validation, `sha256`, détection multi-objet | 2 h | 1.1 |
| 2.5 | `resolve_cpe` étages 1-2 (portail vendeur + FTS5) + **200 paires** (`06` §4.2) | 4 h | 1.7, 1.5 |
| 2.6 | Étage 3 sémantique + **benchmark des 3 stratégies** (B3) | 3 h | 2.5 |
| 2.7 | Calibration des seuils (`T_ACCEPT`, `T_MARGIN`) sur les 200 paires | 2 h | 2.5 |
| 2.8 | **Corpus : annotation terminée** (objets → vérité terrain + CPE) | 4-6 h | 1.10 |
| 2.9 | `confidence.py` : A, R, par-champ, matrice de décision + tests du §4.5 de `05` | 3 h | 2.5 |

**Fin de semaine 2, obligatoire :** les 200 paires existent et le top-1 est mesuré. Sans elles, aucune métrique du rapport n'existe.

---

## Semaine 3 — CVE, intégrité, rapport

| # | Tâche | Durée | Dépend de |
|---|---|---|---|
| 3.1 | `search_cve` : requête pré-filtre + logique de plages + `match_basis` | 4 h | 1.8 |
| 3.2 | Benchmark CVE (B2, p95 < 50 ms) + 60 cas annotés (A3) | 3 h | 3.1 |
| 3.3 | Journal HMAC + trigger append-only + `verify_chain` + **6 tests d'altération** | 3 h | 1.2 |
| 3.4 | Ed25519 sur la tête + RFC 3161 + `verify_report.py` tiers | 4 h | 3.3 |
| 3.5 | Orchestrateur : provenance, journal, bascule nœud, `E_PARTIAL_RUN` | 3 h | 2.3, 3.3 |
| 3.6 | Les 20 codes d'erreur : comportement + message FR + trace (1 test chacun) | 4 h | 3.5 |
| 3.7 | Rapport PDF : structure, mention produit-level, clé publique, vérif | 5 h | 3.4 |
| 3.8 | HITL : correction tracée dans `corrections` + chaînée au journal | 3 h | 3.7, 3.3 |
| 3.9 | API Django Ninja : upload, run, statut, PDF, vérif | 4 h | 3.5, 3.7 |

---

## Semaine 4 — preuves, robustesse, rédaction

| # | Tâche | Durée | Dépend de |
|---|---|---|---|
| 4.1 | Benchmark corpus complet → M1-M3, M7, IC de Wilson | 3 h | 2.8, 2.9 |
| 4.2 | Benchmark robustesse (B7) + `confusable` (M5) | 3 h | 4.1 |
| 4.3 | Benchmark reproductibilité (B9) : 2 runs, accord publié | 2 h | 3.5 |
| 4.4 | Test d'absence d'egress (A5) sous nftables | 2 h | 3.9 |
| 4.5 | Tests adversariaux (`07` §5) dont `label_injection.jpg` | 3 h | 2.2, 3.6 |
| 4.6 | Mode dégradé : NVD coupé, puis 1 nœud tué | 2 h | 3.5, 3.9 |
| 4.7 | `benchmarks/results.md` régénéré par script (citable) | 2 h | 4.1-4.3 |
| 4.8 | Rédaction du rapport : registre des affirmations → résultats | 8 h | 4.7 |
| 4.9 | **Répétition de soutenance** + les 5 questions du jury (`01` §4) | 3 h | 4.8 |
| 4.10 | Gel : tag du dépôt, archive des artefacts (DB + snapshots + résultats) | 2 h | tout |

---

## Chemin critique

```
0.1 driver ─► 2.1 vLLM ─► 2.3 client ─► 3.5 orchestrateur ─► 4.3 rejeu
                                              │
1.2 schéma ─► 1.4 dict CPE ─► 1.7 FTS5 ─► 2.5 resolve ─► 2.9 confiance ─► 3.1 CVE
                                                                              │
                                                    3.3 HMAC ─► 3.4 Ed25519 ─► 3.7 PDF ─► 4.8 rapport
```

**Le chemin critique ne passe pas par le VLM.** Il passe par : schéma → dictionnaire CPE → FTS5 → résolution → confiance → CVE → intégrité → PDF → rapport. Un retard sur le VLM coûte une journée ; un retard sur le dictionnaire CPE coûte une semaine.

---

## Les 3 tâches à plus fort risque de dépassement

| Rang | Tâche | Pourquoi ça dérape | Mitigation |
|---|---|---|---|
| **1** | **1.8 + 3.1 — pipeline NVD et matching CVE** | la sémantique NVD (arbres booléens, `NEGATE`, plages de versions) est plus subtile qu'elle n'en a l'air ; les deux missions la traitent en une ligne | commencer semaine 1 ; **livrer d'abord le pré-filtre + `match_basis`** et documenter l'arbre complet comme limite ; ne jamais viser l'exactitude NVD complète au MVP |
| **2** | **2.8 + 1.10 — annotation du corpus** | travail **manuel**, hors chemin critique ⇒ toujours repoussé ⇒ **toutes** les métriques manquent en semaine 4 | démarrer en semaine 1, 1 h/jour, pas « en fin de projet » ; compte minimal 50 objets |
| **3** | **3.7 + 3.9 — rapport PDF et API** | c'est ce que le jury voit ; génération PDF et HITL toujours sous-estimés | maquette PDF dès la semaine 2 (données factices), puis remplissage |

**Risque transversal (externe) :** la plateforme d'inférence (venv vLLM cassé, driver non tranché) — dépend d'un travail qui n'est pas le tien. D'où 0.1 et D1 : **rendre le CDC indifférent à ce blocage**. Si le driver s'avère insuffisant, le profil `0.8.5.post1 / cu124` est prouvé et installable aujourd'hui.

---

## Définition de « terminé »

- [ ] CDC + specs déposés, **sans chiffre non mesuré** et **sans pin vLLM contradictoire**
- [ ] `parse_cpe` et `ingest_nvd` **idempotents** (rejoués deux fois, aucun doublon)
- [ ] Corpus ≥ 50 objets, ≥ 400 images, stratifié, provenance complète
- [ ] M1-M9 produites avec `n` et IC, dans `benchmarks/results.md` régénéré
- [ ] 20 codes d'erreur testés (comportement + message + trace)
- [ ] Altération HMAC détectée **et** limite de forgeage documentée par un test
- [ ] Export PDF vérifiable par un tiers **sans** la clé HMAC
- [ ] Test d'absence d'egress réussi
- [ ] Mode dégradé validé (NVD coupé ; 1 nœud tué)
- [ ] 5 limites de `07` §8 écrites dans le rapport
- [ ] Répétition générale faite, dépôt taggé, artefacts archivés
