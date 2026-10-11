# Cahiers — index et contrat documentaire

**Projet** : Reconnaissance d'objets connectés pour audit de sécurité IoT  
**Auteur** : Mohamed Salhi — Polytech Lille / ENSA Kénitra · **Tuteur** : Thomas Vantroys  
**Dernière révision de cet index** : 24 septembre 2026 · **Horizon** : 15/09 → 15/12/2026 (13 semaines)

> **Où lire quoi.** `CDC-v3.1-proposition.md` + `CDS-v2.1-proposition.md` sont les **versions de référence** du 24/09 (état réel daté, critères AC1–AC12, contrats alignés sur le code). `CDC-v3.0.md` + `CDS-v2.0.md` sont les **synthèses exécutives** de travail. La revue méthodologique du 24/09 est scellée dans `DUAL_AGENT_REVIEW.md` : cinq failles critiques arbitrées, sept écarts V1→24/09 documentés, aucune porte fermée par une revue.

---

## 1. Index des documents

| Fichier | Rôle | Statut au 24/09 |
|---|---|---|
| **[CDC-v3.1-proposition.md](CDC-v3.1-proposition.md)** | Cahier des charges — référence : périmètre, état réel daté (§3), acquis vs ouverts (§3.5), critères **AC1–AC12** (§7), portes G0–G7 (§6), risques (§9), corrections datées (§14.3) | **référence d'ingénierie** |
| **[CDS-v2.1-proposition.md](CDS-v2.1-proposition.md)** | Spécifications techniques — contrats de `contracts.py` (§3), schéma NVD (§7), moteur `search_cve` (§9), notation et reproductibilité (§15), conformité (§13) | **référence d'ingénierie** |
| **[CDC-v3.0.md](CDC-v3.0.md)** | Synthèse exécutive du contrat — lecture en 5 minutes | synthèse de travail |
| **[CDS-v2.0.md](CDS-v2.0.md)** | Synthèse exécutive des spécifications — pile, contrats, briques suivantes | synthèse de travail |
| **[PLANNING-13-SEMAINES.md](PLANNING-13-SEMAINES.md)** | Calendrier daté : capacité à deux bornes, S1–S13, chemin critique, liste d'arbitrage, questions Q1–Q9 avec valeurs par défaut | vivant |
| **[DUAL_AGENT_REVIEW.md](DUAL_AGENT_REVIEW.md)** | Revue croisée des deux rédactions : 5 failles arbitrées, 7 écarts V1→24/09, 5 actions exécutées | **scellé le 24/09** |
| **[NOTE-CONFORMITE-z23-tailscale.md](NOTE-CONFORMITE-z23-tailscale.md)** | Note d'incident : co-locataire réseau (Tailscale) sur zabeth23, options A/B | incident clos le 24/09 |
| **[CDC-v2.0.md](CDC-v2.0.md)** | Version du 15/09 — **historique**, tronquée au §3.4 | historique |

---

## 2. Les trois choses à dire en premier au tuteur (au 24/09/2026)

1. **L'infrastructure est finie et prouvée** — 3 nœuds RTX 3060, invariants `G1–G10 = 10/10`, confinement egress prouvé sur les trois (3/3 domaines en timeout, inférence exécutée sous blocage), `uv pip check` PASS, latence p50 ≈ 1,08 s pour une cible de 10 s. Le banc 3 nœuds du 24/09 donne un **accord inter-nœuds de 4/4** (mêmes images, mêmes réponses).
2. **Le cœur du sujet a démarré le 24/09** — ingestion NVD 2021–2024 locale (**121 719 CVE / 324 470 critères matériels, 11 s, 154 Mo**), moteur `search_cve` (**p95 = 3,48 ms** pour une cible de 50 ms ; **40/40 tests**), dépôt Git initialisé (commits `f36ca41` → `fb6d06d` + revue). **Reste à fermer** : rejeu ×2 sans doublon + oracle 60 cas (G1), index FTS5 (G2), chaîne E2E + HMAC/Ed25519 + PDF (G3/G4).
3. **La limite est structurelle et assumée** — le système fait du **triage produit-level** : il ne dit jamais qu'un exemplaire est vulnérable, parce qu'une photo ne porte pas de version de firmware. Ce n'est pas une réserve de rédaction, c'est la conception du produit (`triage_scope='product'`, écrit dans la base et dans le rapport).

Et trois questions qui ne sont pas techniques (valeurs par défaut dans `PLANNING-13-SEMAINES.md` §7) :

- **Q3 — arm « conditions propres »** : irréalisable depuis Wikimedia Commons (3 images sur 144) ; décision de collecte (photographier 5–8 objets réels, une séance, repli 50–60 €) ou retrait du critère **avec son motif** ;
- **Q8 — FCC ID** : l'énoncé le propose « pour constituer une première version de la base » ; aujourd'hui **zéro code, zéro donnée**, et il n'existe aucun mapping CPE ↔ FCC ID — l'adopter crée un second spine de données. Recommandation : le **mesurer** sur une strate « étiquette » (~30 images) avant de trancher. Deux FCC ID sont déjà lus correctement par l'OCR en place sur 2 des 144 images.
- **Q9 — nouveau cap tuteur (05/10)** : directive « IoT ou non, catégorie sans marque » — protocole de corpus mixte proposé au §22.3 de `docs/06` (60 objets, 120 photos, coût 0 €) et cibles proposées (rappel IoT ≥ 95 %, catégorie sans texte bornée ≥ 70 %) à valider par le tuteur avant inscription de AC13 dans le CDC (D16).

---

## 3. Comment ces documents restent vivants

| Situation | Règle |
|---|---|
| Un chiffre change | il change **dans la ligne AC correspondante du CDC-v3.1 §7** (avec son artefact) **et** dans `CDS-v2.1` § concerné — pas dans un fil de discussion |
| Une décision est prise | elle est ajoutée à `docs/02` (numérotée D16, D17…) **et** référencée depuis le CDS ou le CDC |
| Une exigence est satisfaite | sa ligne passe de ❌/🟡 à ✅/📝 **avec le chemin de l'artefact** |
| Un paramètre a un effet publié | il se **fige avant le run** (règle M6) et sa valeur va dans le manifeste |
| Un document de preuve doit être corrigé | **ajout daté** ; jamais de réécriture (règle R7) |
| Une rédaction en remplace une autre | l'ancienne est **annulée explicitement** (CDC §14.4), jamais laissée à circuler |

**Règle anti-divergence.** Le CDS **ne recopie pas** le corps de code de `docs/03` à `docs/07` : il fixe les contrats et **renvoie**. Recopier un algorithme dans deux documents crée deux sources de vérité qui divergent — le défaut que `docs/03` §3 dénonce sous le nom de couplage C1/C2.

---

## 4. Historique des annulations (pourquoi v2, puis v3.1)

La **v1 (13/09/2026)** a été rédigée pour un horizon de 4 semaines et contient au moins quatre éléments **factuellement faux** aujourd'hui — dont un pin de version **qui ne s'installe pas** :

| v1 | Réalité mesurée |
|---|---|
| « vLLM 0.29.0 + torch 2.6.0+cu124 » | mutuellement exclusif : 0.29.0 épingle `torch 2.13.0` ; `--torch-backend=cu124` ⇒ échec de résolution |
| « Serveur d'inférence : Ollama » | **vLLM 0.29.0** est déployé et prouvé sur les 3 nœuds |
| « NVD ≈ 200 Go » | 154 Mo utiles, ingérés en 11 s (mesuré le 24/09) |
| « Précision terrain ≥ 50 % » | aucune photo de terrain ; **3 images** « propres » sur 144 |
| « 8–10 objets » | **48 objets, 144 images publiables** |
| « Reproductibilité : résultat identique » | intenable avec le *continuous batching* ⇒ requalifiée en propriété **mesurable** |

La **v3.1-proposition** (24/09) succède à la v3.0 du même jour après la revue croisée ; l'analyse complète des écarts vit dans `DUAL_AGENT_REVIEW.md` §4.

---

## 5. Deux défauts trouvés en interrogeant la base, pas en relisant un document

1. **Le corpus ne fait pas 155 images mais 144.** **11 images orphelines** — aucun objet de vérité terrain, jamais océrisées, jamais prédites, inertes — étaient **comptées dans les figures publiées**. L'instrument était correct (il filtre `object_id IS NOT NULL`) ; c'est **la requête de comptage** qui était fausse. Effet : le corpus publiable est de **144**, et la strate `forum` passe de **23 à 12**. Corrigé : inscrites dans `corpus/manual-removals.json`, sauvegarde `corpus.sqlite.pre-orphan-fix`.
2. **Le canal FCC ID n'a jamais été évalué** alors que l'énoncé le propose explicitement (voir Q8 ci-dessus). Le laisser hors des décisions numérotées est le défaut — pas de l'avoir écarté.
