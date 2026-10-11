# 01 — Périmètre, registre des affirmations, limites

Ce document existe pour une raison unique : **empêcher la sur-promesse**. Un jury sécurité attaque d'abord les affirmations mal bornées. Ici, chaque affirmation est étiquetée.

---

## 1. La limite structurelle, formalisée

La chaîne de preuve du système est :

```
photo ──► (marque, modèle) ──► identifiant CPE « produit » ──► CVE du produit
  │              │                        │                          │
  │              │                        │                          └─ la CVE est vraie pour
  │              │                        │                             CERTAINES versions
  │              │                        └─ identifie un MODÈLE, pas un exemplaire
  │              └─ probabiliste : mesure d'accord, jamais une certitude
  └─ ne contient AUCUNE information de version
```

**Le trou est irréparable :** `cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*` désigne une *version matérielle* (`2.0`) mais pas le **firmware**. Or une CVE est rattachée à une version de firmware ou à une plage de versions. Donc la distance entre « voici les CVE de ce produit » et « cet exemplaire est vulnérable » n'est pas un détail d'implémentation : c'est un intervalle que le projet **ne peut pas franchir**.

**Conséquence de conception, pas seulement de rédaction :**

- le rapport ne présente **jamais** de score de risque agrégé (« l'objet est à 7.5/10 »). Un CVSS agrégé pour un produit est un *max sur toutes les versions*, donc systématiquement pessimiste et non actionnable ;
- chaque CVE affichée porte la mention **« concerne ce produit, version firmware non déterminée »** ;
- le champ `triage_scope = 'product'` est écrit **dans la base**, pas seulement dans le PDF (voir D15) ;
- l'absence de CVE n'est **jamais** présentée comme une absence de vulnérabilité (voir `03` §taxonomie, `E_NO_CVE`).

---

## 2. Périmètre MVP

### Dans le périmètre

| # | Élément | Critère de sortie |
|---|---|---|
| P1 | Une photo = **un objet** cadré et isolé | sinon `E_MULTI_OBJECT_OR_UNCLEAR` (rejet, pas de tentative) |
| P2 | **5 catégories** : prise connectée, caméra IP, ampoule connectée, routeur/AP, enceinte connectée | mapping catégorie validé sur échantillon étiqueté |
| P3 | Corpus **photos internet**, ≥ 50 objets, ≥ 8 photos/objet, stratifié (voir `06`) | corpus gelé avec ground truth + provenance |
| P4 | Inférence **100 % locale** | test d'absence d'egress réseau |
| P5 | Identification → CPE (top 3) → CVE → PDF | chaîne complète reproductible sur ≥ 1 objet |
| P6 | Journal chaîné HMAC append-only | test d'altération détectée |
| P7 | HITL avant export final | correction tracée dans le journal |

### Hors périmètre (assumé)

| Élément | Statut |
|---|---|
| Détection multi-objets | **bonus**, hors MVP |
| Version firmware depuis la photo | **impossible** — c'est toute la limite du §1 |
| Exploitation, PoC, scan actif | hors projet |
| Fingerprinting réseau (extension initialement évoquée) | **hors périmètre** : nécessiterait une autorisation écrite du client (art. 323-1 et suivants du Code pénal) |
| Appels API NVD en temps réel | interdit par conception (ENF4) |
| App mobile native | hors périmètre (web responsive) |
| Multi-tenant, authentification forte | hors MVP |

---

## 3. Registre des affirmations

Trois étiquettes, et **une seule règle** : une affirmation étiquetée `LIMITE` ne peut pas être présentée au jury comme un résultat.

- **PROUVÉ** — propriété vérifiée par un test déterministe, reproductible à la demande.
- **MESURÉ** — grandeur empirique, avec corpus, n, et intervalle de confiance.
- **LIMITE** — propriété qu'on **assume** et documente, à énoncer comme telle.

| # | Affirmation | Étiquette | Preuve / méthode | Critère d'acceptation |
|---|---|---|---|---|
| A1 | « Identifie marque + modèle + catégorie depuis une photo » | MESURÉ | accuracy objet-level sur corpus stratifié | ≥ 70 % strate studio-proxy ; voir `06` pour les vraies cibles |
| A2 | « Associe l'objet à un CPE (NIST) » | MESURÉ | top-1 / top-3 sur ≥ 200 paires étiquetées | top-1 ≥ 80 %, top-3 ≥ 92 % |
| A3 | « Retrouve les CVE connues du produit » | **PROUVÉ** | comparaison à un échantillon annoté à la main (60 cas) + logique de version testée unitairement | 0 faux négatif sur l'échantillon, faux positifs documentés |
| A4 | « < 10 s par image » | MESURÉ | latence p50/p95 par étape | p95 end-to-end < 10 s |
| A5 | « Aucune photo ne sort du réseau local » | **PROUVÉ** | test d'egress : run complet avec règles nftables bloquant toute sortie, + capture | 0 paquet sortant vers une IP non locale |
| A6 | « Reproductibilité stricte » | **LIMITE, requalifiée** | provenance complète (prouvée) + **accord de rejeu mesuré** | 100 % accord catégorie, ≥ 95 % accord tuple, dérive publiée |
| A7 | « Journal infalsifiable » | **LIMITE** | test d'altération détecté ; **modèle de menace explicite** | détection d'altération = 100 % ; forgeage par détenteur de clé = documenté |
| A8 | « Fonctionne sans réseau externe » | MESURÉ | run avec NVD/ internet coupés | pipeline complet, `cache_status` renseigné |
| A9 | « Ces CVE concernent l'exemplaire audité » | **INTERDIT** | — | n'est **jamais** affirmé ; cf. §1 |
| A10 | « L'objet est sûr s'il n'y a pas de CVE » | **INTERDIT** | — | n'est **jamais** affirmé ; cf. `E_NO_CVE` |

**Ce qu'il ne faut pas dire en soutenance :** « détecte les vulnérabilités », « score de risque de l'appareil », « 90 % de précision » (sans le n et l'IC), « signé donc non répudiable ».

**Ce qu'il faut dire :** « triage produit-level », « identifie le *produit*, pas la version », « la confiance mesure l'accord, pas la justesse », « le HMAC prouve l'intégrité sous le détenteur de la clé ».

---

## 4. Transparence sur les affirmations A6 et A7

Ces deux-là sont les plus attaquables, donc elles sont traitées en décisions (D8, D11) plutôt qu'en promesses.

**A6 — ENF5.** Le CDC actuel dit « même image + même version modèle = résultat identique ». C'est faux sur cette pile : le *continuous batching* de vLLM fait varier la composition des lots, donc l'ordre des réductions flottantes, donc les logits. Même à `temperature=0`. La version honnête et **encore plus forte** :

> *Tout run enregistre la provenance complète (révision modèle + sha256 des poids, hash du prompt, version du schéma, versions vLLM/torch, sha256 du snapshot NVD, sha256 du dictionnaire CPE). Rejouer un run sur le même déploiement reproduit la même **décision** (catégorie, tuple identifié, ensemble de candidats CPE) — la dérive observée est mesurée et publiée.*

On remplace une promesse intenable par une propriété **mesurée** : c'est plus fort devant un jury, pas plus faible.

**A7 — HMAC.** Un HMAC symétrique avec la clé sur la machine qui écrit la base ne protège **pas** contre le détenteur de la clé. Le trigger SQL append-only est une protection applicative, pas une protection contre un auditeur qui possède le fichier SQLite. Voir D11 pour la version opposable (Ed25519 + RFC 3161) et la formulation exacte du modèle de menace.
