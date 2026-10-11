# Planning daté — 13 semaines

**Horizon** : mardi **15/09/2026** → mardi **15/12/2026** (13 semaines, semaines du mardi au lundi)
**Régime** : solo, alternance semaine de cours / semaine de projet + heures creuses et week-ends
**Compagnon de** : `CDC-v2.0.md` §9 · **Statut** : hypothèse de régime à confirmer (**Q1**)

---

## 1. Le calcul de capacité — deux bornes, pas une

Le CDC §9.1 retient **≈ 60 j·h** comme **borne prudente** (rendement 55 %, sans compter les heures creuses). Le planning ci-dessous retient une **borne réaliste de 73 j·h**, en s'appuyant sur la phrase du cahier des charges v1 lui-même : le projet est *« complété par des heures creuses et les week-ends »*.

| Semaine | Charge retenue | Motif |
|---|---|---|
| **de projet** (7 sur 13) | **7 j·h** | journée complète × 1,4 |
| **de cours** (6 sur 13) | **4 j·h** | soirées + week-end |
| **Total** | 7×7 + 6×4 = **73 j·h** | |

| Borne | Valeur | Conséquence |
|---|---|---|
| **Prudente** (CDC §9.1) | **60 j·h** | écart de **13 j·h** ⇒ **liste d'arbitrage** (§6) appliquée |
| **Réaliste** (ce document) | **73 j·h** | le parcours P0–P7 **tient**, à une condition : la rédaction se fait **en continu** (§5) |
| Temps plein | ≈ 130 j·h | le parcours se replie sur **7 semaines** ; S8–S13 deviennent buffer et approfondissement |

> **La contrainte liante n'est pas le calendrier, c'est le rendement.** Le plan ne casse pas par manque de temps disponible : il casse si les 13 j·h d'écart de la borne prudente ne sont pas fermés par arbitrage **explicite** plutôt que par glissement silencieux.

---

## 2. Calendrier daté

*Chaque semaine se termine par un **livrable**, et chaque phase par une **porte démontrable en une séance**.*

| Sem. | Dates | Phase | Livrable de fin de semaine | Porte |
|---|---|---|---|---|
| **S1** | mar 15/09 → lun 21/09 | **P0** | **Comptage corrigé** : 11 orphelines exclues des figures ⇒ **144 images**, strate `forum` **12** (fait le 15/09) · dépôt Git initialisé · lockfile · documents périmés corrigés | **G0** |
| **S2** | 22/09 → 28/09 | P1 | Ingestion NVD 2019–2021 : `feed_versions`, filtre `part=h`, table de critères indexée | — |
| **S3** | 29/09 → 05/10 | P1 | Ingestion 2022–2024 + **idempotence prouvée** (double passe, `row_count` = source) + reprise sur erreur | — |
| **S4** | 06/10 → 12/10 | P1 | `search_cve` : pré-filtre SQL + **logique de plages** + `NEGATE` + tests sur ≥ 12 arbres synthétiques | — |
| **S5** | 13/10 → 19/10 | P1 | **60 cas annotés ⇒ 0 faux négatif** · p95 de recherche mesuré · `match_basis` exposé | **G1** |
| **S6** | 20/10 → 26/10 | P2 | Index **FTS5** · normalisation et canonicalisation de version · tests des 3 pièges | — |
| **S7** | 27/10 → 02/11 | P2 | Résolution **3 étages** · **200 paires** · **tableau de calibration** publié (top-1/top-3 avec `n` et IC) | **G2** |
| **S8** | 03/11 → 09/11 | P2 | `confidence.py` : matrice **A × R** implémentée + tests (8 réponses identiques / R nul ⇒ refus) | — |
| **S9** | 10/11 → 16/11 | P3 | Client `VLMRunner` (timeout, retry, bascule) · orchestrateur · **provenance complète** · schéma du journal | — |
| **S10** | 17/11 → 23/11 | P3 | **Rejeu** (100 % catégorie / ≥ 95 % tuple) · NVD coupé · 1 nœud tué · `nodes_used` | **G3** |
| **S11** | 24/11 → 30/11 | P4 | Journal HMAC + trigger append-only + **6 tests d'altération** · Ed25519 · PDF · `verify_report.py` | **G4** |
| **S12** | 01/12 → 07/12 | P5 | API : upload → run → statut → PDF → vérification, **parcours complet via HTTP** | **G5** |
| **S13** | 08/12 → 14/12 | P6 | Figure stratifiée sous **drapeau réparé** · courbe de robustesse · `benchmarks/results.md` **régénéré par script** | **G6** |
| — | **mar 15/12/2026** | **P7** | **Gel** : dépôt taggé, artefacts archivés, démo hors-ligne + vidéo de secours | **G7** |

### Charge par phase

| Phase | Charge |
|---|---|
| P0 — socle et contrat | **4** |
| P1 — spine CVE | **14** |
| P2 — résolution et confiance | **12** |
| P3 — bout en bout | **11** |
| P4 — intégrité et rapport | **12** |
| P5 — API | **3** |
| P6 — preuves | **7** |
| P7 — rédaction, soutenance, gel | **10** |
| **Total** | **73** = la borne réaliste |

> **Les deux tableaux sont cohérents au total (73 = 73), pas semaine par semaine — et c'est délibéré.** Deux raisons : (a) la **rédaction court en parallèle** à ≈ 1 j·h par semaine (§5), donc une part de la charge hebdomadaire n'est pas affectée à une phase technique ; (b) les phases **se chevauchent aux marges** (la phase dominante d'une semaine laisse un reliquat qui se reporte). Un planning qui prétend répartir les j·h semaine par semaine sur 13 semaines en solo et en alternance sera faux d'ici S3. Ce qui doit tenir, c'est **l'ordre** et les **portes** — pas la répartition. La conséquence pratique est énoncée ci-dessous.

---

## 3. Les portes, sur dates

Une porte n'est **pas** une revue : c'est un critère **démontrable en une séance**. Si elle ne passe pas, la semaine suivante est consommée à la fermer — on ne l'emporte pas en dette.

| Porte | Date | Critère de fermeture | Preuve à produire |
|---|---|---|---|
| **G0** | 21/09 | **0 orpheline comptée** dans toute figure · `git log` non vide · lockfile | requête de contrôle filtrant `object_id IS NOT NULL` · `git log` |
| **G1** | 19/10 | NVD rejouée deux fois ⇒ 0 doublon · 60 cas ⇒ 0 FN · p95 mesuré | `benchmarks/cve.json` |
| **G2** | 02/11 | FTS5 en place · 200 paires avec `n` + IC · tableau de calibration | `benchmarks/cpe.json` |
| **G3** | 23/11 | run complet photo→PDF · provenance complète · rejeu · 2 modes dégradés | `benchmarks/replay.json` |
| **G4** | 30/11 | 6 tests d'altération (index exact) · forgeage = test qui **réussit** · PDF altéré ⇒ refus | `tests/` + `verify_report.py` |
| **G5** | 07/12 | parcours complet via HTTP | `curl` transcript |
| **G6** | 14/12 | toute ligne `MESURÉ` avec `n` + IC · `results.md` régénéré | `benchmarks/results.md` |
| **G7** | 15/12 | rapport · carnet de défense · démo hors-ligne · tag · archive | dépôt taggé |

---

## 4. Chemin critique, daté

```
S1 ─ G0 (drapeau réparé + dépôt)
S2–S3 ─ ingestion NVD ─────────┐
S4    ─ search_cve (plages)    │
S5 ─ G1 ────────────────────────┘        ← LE CHEMIN CRITIQUE
S6    ─ FTS5 + normalisation ──┐
S7 ─ G2 ────────────────────────┘
S8    ─ confidence (A×R) ──────┐
S9–S10 ─ orchestrateur + rejeu ─┘ ─ G3
S11 ─ journal + Ed25519 + PDF ─── G4
S12 ─ API ─────────────────────── G5
S13 ─ preuves régénérées ──────── G6 ─── 15/12 ─ G7
```

**Deux remarques sur ce chemin :**

1. **Il ne passe pas par le VLM.** Le VLM est déjà déployé, mesuré et rapide. C'est une décision de conception, pas une coïncidence : elle rend le planning insensible à la panne d'un nœud.
2. **Aucune phase n'attend une réponse.** Les huit questions du CDC §13 ont toutes une **valeur par défaut** qui permet de continuer (§7). Le planning n'a donc **aucun bloqueur externe**.

---

## 5. La règle qui fait tenir le plan : rédiger en continu

**Le rapport et le carnet de défense s'écrivent 1 j·h par semaine à partir de S2** — soit 10 j·h sur les 11 semaines restantes, exactement la charge de P7.

C'est le point le plus important de ce document. Sur ce type de projet, ce n'est pas le développement qui fait exploser le planning : c'est la **rédaction concentrée en fin de parcours**, qui arrive toujours au moment où la soutenance approche et où les résultats doivent être stabilisés. Écrire à la semaine présente un second effet, décisif ici : **chaque figure est expliquée au moment où elle est produite**, donc la compréhension reste contemporaine du travail — ce qui répond directement à R7 (~95 % du travail produit par un agent).

**Rituel hebdomadaire** (le même chaque semaine) :

1. fermer la porte ou la tâche prévue — **sinon rien d'autre ne commence** ;
2. écrire l'artefact de preuve **le jour même** (jamais « plus tard ») ;
3. écrire 1 page : ce qui a été décidé, pourquoi, et **sa reformulation en langage courant** ;
4. journaliser dans `logs/LOG.md` : ce qui a marché, ce qui a **réfuté** une hypothèse, ce qui reste ouvert.

---

## 6. Liste d'arbitrage — comment fermer les 13 j·h

Si la capacité réelle s'établit à la **borne prudente (60 j·h)**, appliquer les coupes **dans cet ordre**, chacune étant **écrite comme limite assumée** dans le rapport :

| Rang | Coupe | Gain | Coût assumé, écrit dans le rapport |
|---|---|---|---|
| 1 | **RFC 3161 (TSA)** → horodatage par signature Ed25519 seule | 2 j·h | « la borne temporelle est cryptographique, pas externe » |
| 2 | **Interface web** → CLI + endpoints JSON | 3 j·h | la démonstration passe par `curl` et le PDF |
| 3 | **NVD sur 3 ans** au lieu de 5 | 2 j·h | la couverture CVE produit est dominée par les années récentes — à **mesurer**, pas à supposer |
| 4 | **Arbre booléen NVD complet** → déjà hors MVP | 2 j·h | la limite est déjà écrite (§7.7 du CDS) |
| 5 | **200 → 120 paires** de calibration | 2 j·h | seuils calibrés sur moins de points ⇒ **intervalles plus larges** (publiés) |
| 6 | **Strate « étiquette » FCC ID** reportée | 1 j·h | C19 reste ❌ avec son motif (§3.5 du CDC) |
| 7 | **Benchmark DP 3 nœuds** → réutilisation de V11a/V11b | 1 j·h | déjà mesuré : 57,9 req/s, p95 ≈ 0,29 s |
| | **Total** | **13 j·h** | écart fermé |

**Ce qui n'est PAS dans cette liste, parce que non négociable :**

- la **réparation du drapeau** (C18) — sans elle, aucune figure stratifiée n'est publiable ;
- l'**idempotence** des ingestions ;
- les **60 cas annotés ⇒ 0 faux négatif** ;
- le **journal** et la **détection d'altération à l'index exact** ;
- le **test d'egress** ;
- le **PDF vérifiable par un tiers sans la clé HMAC** ;
- le **carnet de défense** et le **rapport** — ce sont les deux seuls livrables que le jury lit vraiment.

---

## 7. Ce dont j'ai besoin de toi — et ce que je fais sans attendre

| # | Question | Vrai bloqueur ? | Valeur par défaut appliquée si pas de réponse |
|---|---|---|---|
| **Q1** | Calendrier d'alternance exact | **non** | 7 j·h/semaine projet, 4 j·h/semaine cours (§1) |
| **Q2** | Dates de remise des cahiers v2 | **non** | proposition : **19/09** |
| **Q3** | Arm « conditions propres » : photographier 5–8 objets réels ? | **change le périmètre** | C1 reste « non estimable — motif : source » |
| **Q4** | HITL : résultat final ou chaque étape ? | **non** | résultat final (schéma `corrections` tel que spécifié) |
| **Q5** | Redistribution des photos (dépôt/rapport ou URL seule) | **non** | URL seule + licence + `sha256` (prudence maximale) |
| **Q6** | DP 3 nœuds : exigence ou choix ? | **non** | choix d'implémentation ; V11a/V11b déjà mesurés |
| **Q7** | Fingerprinting réseau hors périmètre | **non** | confirmé hors périmètre, aucune autorisation requise |
| **Q8** | FCC ID : complémentaire, ou financer une strate étiquette ? | **change le périmètre** | complémentaire non implémenté ; C19 reste ❌ avec son motif |
| **Q9** | Nouveau cap tuteur (05/10) : protocole corpus mixte (« IoT ou non ») et cibles (rappel IoT ≥ 95 %, catégorie sans texte borne basse ≥ 70 %) | **change le périmètre** | protocole §22.3 de `docs/06` (60 objets, 120 photos, coût 0 €) soumis pour arbitrage ; v6 runner prêt ; en attente de validation tuteur avant intégration AC13 au CDC (D16) |

**Aucune de ces réponses n'arrête le travail.** Trois seulement (Q3, Q8, Q9) changent le **périmètre** ; les six autres ont un défaut qui tient. Le planning démarre donc **sans attendre**.

---

## 8. Suivi

*À cocher semaine par semaine. Une case vide en fin de semaine est un signal, pas un détail.*

| Sem. | Dates | Phase | Fait | Porte |
|---|---|---|---|---|
| S1 | 15/09 → 21/09 | P0 | ☐ | ☐ G0 |
| S2 | 22/09 → 28/09 | P1 | ☐ | — |
| S3 | 29/09 → 05/10 | P1 | ☐ | — |
| S4 | 06/10 → 12/10 | P1 | ☐ | — |
| S5 | 13/10 → 19/10 | P1 | ☐ | ☐ G1 |
| S6 | 20/10 → 26/10 | P2 | ☐ | — |
| S7 | 27/10 → 02/11 | P2 | ☐ | ☐ G2 |
| S8 | 03/11 → 09/11 | P2 | ☐ | — |
| S9 | 10/11 → 16/11 | P3 | ☐ | — |
| S10 | 17/11 → 23/11 | P3 | ☐ | ☐ G3 |
| S11 | 24/11 → 30/11 | P4 | ☐ | ☐ G4 |
| S12 | 01/12 → 07/12 | P5 | ☐ | ☐ G5 |
| S13 | 08/12 → 14/12 | P6 | ☐ | ☐ G6 |
| — | 15/12/2026 | P7 | ☐ | ☐ G7 |

**Contrôle de dérive, à chaque porte :** si une porte est fermée avec **plus de 2 j·h** de retard cumulé, appliquer la coupe suivante de la liste d'arbitrage (§6) **le jour même** — pas à la fin.

---

## 9. Deux hypothèses de ce planning, énoncées pour être contestables

1. **Le rendement de 4 j·h par semaine de cours** suppose que les soirées et le week-end restent disponibles. S'ils ne le sont pas, on retombe sur la borne prudente de **60 j·h** et la liste d'arbitrage s'applique intégralement.
2. **La rédaction en continu dès S2** n'est pas une préférence : c'est ce qui rend P7 finançable. Si elle est reportée, **P7 devient impossible à caser** dans l'horizon — c'est le mode de défaillance le plus probable de ce projet, et il est nommé ici pour être surveillé.
