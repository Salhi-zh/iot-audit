# Cahier des charges — v3.1

**Projet** : Reconnaissance d'objets connectés pour audit de sécurité IoT  
**Auteur** : Mohamed Salhi — Polytech Lille / ENSA Kénitra · **Tuteur** : Thomas Vantroys  
**Période** : 15/09/2026 → 15/12/2026 (13 semaines, environ 60 à 73 journées de travail réparties sur le semestre)  
**Version** : 24/09/2026 · **Statut** : version de référence — remplace toutes les versions antérieures.

> **Comment lire ce document.** Il est écrit pour se lire **sans prérequis technique** : les termes nécessaires sont expliqués au passage, et un lexique est disponible en fin de document (§15). Trois principes : (1) chaque chiffre vient d'une **mesure datée** ; (2) statuts : ✅ fait et prouvé · 📝 commencé mais incomplet · ⏳ pas commencé ; (3) les résultats négatifs sont **publiés tels quels**, jamais maquillés.

---

## 1. Le projet, simplement

Lors d'un audit de sécurité, l'auditeur tombe sur des objets connectés (box internet, caméras, prises, enceintes…) dont il ne connaît ni la marque, ni le modèle, ni les failles connues. Les chercher un par un à la main est long et dépend de la mémoire de l'auditeur.

Le projet construit un outil qui va vite, en 4 étapes :

1. **Reconnaître** : à partir d'une photo d'**un seul** objet, l'outil devine la marque, le modèle et le type d'objet, grâce à un modèle d'intelligence artificiel qui tourne **localement** (aucune photo n'est envoyée sur internet).
2. **Retrouver la fiche officielle** : chaque produit commercialisé possède un code officiel dans la nomenclature de la NIST (l'agence américaine des normes informatiques) — appelé **CPE**. L'outil rattache l'objet à ce code.
3. **Lister les failles connues** : la base officielle des failles de sécurité (appelée **NVD**) associe des identifiants publics de failles (**CVE**) aux codes CPE. Cette base est **copiée en local** : pendant un audit, aucune requête ne part vers internet.
4. **Rédiger un rapport** : un PDF lisible, accompagné d'un journal de bord scellé (chaque ligne scelle la précédente) et d'une signature numérique, pour qu'un tiers puisse prouver plus tard que le rapport n'a pas été modifié.

---

## 2. La limite qu'aucune technique ne peut franchir

**Une photo montre le boîtier de l'objet, jamais le logiciel interne (le « firmware ») qui tourne dedans.** Or, une faille CVE concerne une **version précise** de logiciel.

Exemple concret : le code `cpe:2.3:h:tp-link:archer_c7:2.0:…` désigne la **révision matérielle 2.0** d'un routeur — pas la version de son logiciel interne.

**En clair** : le système peut dire *« cet objet est un modèle X, et ce modèle X a connu des failles dans le passé »*. Il ne dira **jamais** : *« cet exemplaire précis est vulnérable »*.

Découlent quatre règles inscrites dans le logiciel, pas seulement dans le texte :

1. aucun **score de risque** en pourcentage ou sur 10 n'est affiché : additionner les failles de toutes les versions à la fois donnerait un chiffre excessivement pessimiste et inutilisable ;
2. chaque faille affichée porte la mention écrite « concerne ce produit — version du logiciel interne non déterminée » ;
3. si aucune faille n'est trouvée, le message dit explicitement **« aucune faille répertoriée ≠ objet sûr »** (et non un « aucun problème » rassurant qui serait faux) ;
4. si la photo est floue ou contient plusieurs objets, l'outil **refuse de répondre** plutôt que d'inventer.

Les cinq phrases que le système n'a **jamais le droit** d'écrire sont listées au §11.1.

---

## 3. Ce qui est déjà fait et mesuré (état au 24/09/2026)

### 3.1 Quel modèle d'IA choisir : comparaison à armes égales

Trois modèles de vision ont été testés **sur les mêmes 144 photos, avec la même consigne**, puis notés à la main contre la vérité :

| Modèle testé | Réponses au format attendu | Bonnes réponses /144 | Marge d'erreur (95 %) | Temps de réponse médian / dégradé |
|---|---|---|---|---|
| **Qwen2.5-VL-7B** *(retenu)* | **144/144** | **79** | [0,467 ; 0,628] | 1,1 s / 1,9 s |
| Qwen3-VL-8B | 144/144 | 53 | [0,294 ; 0,449] | 2,4 s / 4,2 s |
| Llama-3.2-11B-Vision | 123/144 (21 réponses hors format) | 72 | [0,419 ; 0,581] | 2,0 s / 4,3 s |

*Lecture* : la « marge d'erreur » est la fourchette dans laquelle se situe vraisemblablement le vrai résultat ; deux fourchettes qui ne se **recouvrent pas** signifient un écart réel, pas du bruit.

**Pourquoi ce choix, en trois phrases :**

1. Le modèle retenu fait **nettement mieux** que le modèle de nouvelle génération (79 contre 53, fourchettes séparées : l'écart est réel). La version la plus récente se trompe surtout sur les noms précis (elle écrit « Amazon Echo » au lieu d'« Echo Dot »).
2. Le modèle Llama est écarté parce qu'il **respecte mal le format de réponse** (21 réponses sur 144 hors format, et 54 fois il déclare avoir lu une étiquette alors qu'il n'a rien lu du tout). Son taux de réussite à lui n'est pas statistiquement inférieur — on ne le dit jamais « moins bon » sur ce point, il est juste moins **fiable**.
3. Toutes les mesures utilisent la même consigne, la même température de 0 (pour que le modèle ne varie pas au hasard) et le même plafond de 640 mots par réponse — **figés avant les tests** pour qu'on ne puisse pas régler le modèle après avoir vu les résultats.

**Correction datée (24/09)** : la fourchette initialement publiée pour 79/144 ([0,460 ; 0,621]) appartenait en réalité au résultat 78/144 ; la valeur exacte est **[0,467 ; 0,628]**. La conclusion du §3.1 ne change pas.

### 3.2 Les photos de test, et la lecture automatique du texte

**Le jeu de photos**

- 48 objets différents ont été photographiés, ce qui donne **144 photos exploitables** : 50 portent un texte lisible (étiquette, référence imprimée), 94 non. Onze photos inutilisables (aucun objet identifié dessus) ont été retirées le 15/09 pour ne jamais fausser les chiffres.
- Types d'objets : routeurs / box internet **29** · enceintes connectées **8** · prises connectées **5** · caméras IP **4** · ampoules **2**. Le jeu n'est donc **pas équilibré par type d'objet** — c'est assumé.
- Ce qui, lui, est découpé par étages, c'est le **risque que l'IA ait déjà vu le produit pendant son apprentissage** : un modèle d'IA apprend sur des millions de photos d'internet ; s'il a déjà mémorisé la photo officielle d'un produit, il le « reconnaît » sans rien analyser — ça ne prouve rien. Trois niveaux de risque :
  - **3** photos de présentation officielle (risque élevé de mémorisation),
  - **129** photos d'acheteurs ou de revues en ligne (risque moyen),
  - **12** photos de forums ou de démontage (angles inhabituels, éclairage atypique — risque faible, donc le test le plus honnête).
- 5 types d'objets visés, plus un cas explicite « **je ne sais pas** » qui empêche le système d'inventer.

**La lecture automatique du texte présent sur la photo (OCR)**

*C'est quoi* : un logiciel qui lit les mots imprimés sur l'objet — comme un scanner de document, mais appliqué à une photo. Dans ce projet, il est un simple **aide** : seule l'étiquetage fait par une personne fait foi.

*Comment il a été évalué* : deux logiciels de lecture comparés ; on retient le texte si l'un **ou** l'autre le lit (décision du 15/09). Trois mesures, du plus facile au plus réaliste — la fourchette `[x ; y]` est la marge d'erreur de la mesure à 95 % :

| Situation testée | Résultat | Lecture simple |
|---|---|---|
| On donne la zone du texte (rectangle déjà tracé) | **0,657** [0,631 ; 0,681], sur 1 384 textes | il lit **environ 2 textes sur 3** quand on lui montre où chercher |
| Scènes entières, gros plan | **0,351** [0,322 ; 0,379], sur 600 photos et 2 604 mots | il lit **environ 1 mot sur 3** |
| Vraie utilisation : trouver le texte puis le lire | **0,10** [0,058 ; 0,167], soit 12 cas sur 120 | **1 cas sur 10** — la chaîne complète est **faible**, et on n'a pas le droit de compter dessus |

- **Sur le point de jugement principal** (« quel type d'objet est-ce ? », indépendamment de la marque exacte) : le modèle répond juste dans **119 cas sur 144 (82,6 %)**. L'écart entre types d'objets n'est pas statistiquement significatif : on ne peut pas affirmer qu'un type soit plus facile qu'un autre.

### 3.3 Les ordinateurs de l'école et ce qu'ils ont donné

- Trois machines identiques mises à disposition par l'école (**cartes graphiques RTX 3060 de 12 Go** de mémoire), pilotées par un logiciel d'exploitation sans gestionnaire de services, avec des pilotes graphiques alignés. Recette complète passée sur les trois : **10/10 points de contrôle** (relevé du 15/09).
- **Mesure de sécurité réseau** : le 16/09, sur les trois machines, l'accès aux sites internet de référence (NVD, HuggingFace, PyPI) a été **bloqué** — et l'analyse des photos a **quand même tourné**, preuve que rien ne dépend d'internet. Les règles de blocage ont été retirées juste après le test.
- **Temps de réponse GPU** : médian 1,08 s, dégradé au pire 1,88 s (sur 12 mesures, 15/09) — pour une cible contractuelle de 10 s.
- **Journal du 24/09** (trois relevés du jour, dans l'ordre) : 20h56 — une des machines devient injoignable ; 21h11 — deux machines répondent (2,3 s) ; **21h59 — les trois répondent en conditions réelles** : temps dégradé 2,1 s / 2,1 s / 5,1 s, et **les trois donnent exactement les mêmes réponses** sur les 4 photos testées. Conséquence écrite : ces machines sont **partagées entre étudiants** (à un moment, l'une d'elles était saturée par un logiciel tiers occupant 11,6 Go sur 12 Go de mémoire graphique). **Décision : le projet fonctionne de bout en bout sur une seule machine** ; les trois ne sont qu'un accélérateur, jamais une dépendance.

### 3.4 Ce qui existe déjà et ce qui reste à construire

| Élément | État | Mesure / constat au 24/09 |
|---|---|---|
| Copie locale de la base des failles (NVD) + moteur de recherche de failles | ✅ **première ingestion le 24/09** | **121 719 failles et 324 470 critères matériels** sur les années 2021 à 2024, importés en **11 secondes** — mais il reste à relancer l'import une 2ᵉ fois (preuve qu'on peut le relancer sans doublons) et à vérifier 60 cas à la main (§6, porte G1) |
| Index de recherche rapide sur le dictionnaire des produits (FTS5) | ⏳ | absent à ce jour — prévu en porte G2 |
| Résolution « quelle fiche CPE correspond à cette photo ? » | 📝 | test actuel : **37 % de réussite au 1ᵉʳ choix / 56 % dans le top 3**, contre des cibles de 80 % et 92 % — **échec assumé et documenté** (§7, AC10) |
| Confiance à deux vérifications croisées (§8 du CDS) | ⏳ | absent |
| Journal scellé + signature électronique + PDF | ⏳ | absent |
| Interface de démonstration (photo → rapport) | ⏳ | absent |
| Tests automatisés | ✅ | **40 tests passent** en 0,34 s le 24/09 — mais **aucun** ne vérifie encore les messages d'erreur (§7, AC12) |
| Dépôt de code versionné (Git) | ✅ | créé et alimenté le 24/09 ; les gros fichiers de données restent hors du dépôt car on peut les retélécharger |
| Corpus de photos gelé | ✅ | base de 500 Ko : 48 objets, 144 photos, licence et provenance par photo |

### 3.5 Acquis et reste-à-faire (séparation nette)

**Acquis — prouvé par une mesure datée, ne se rediscute plus :**

- corpus gelé (48 objets / 144 photos / 11 exclues) ;
- modèle retenu : réponses au format 144/144, résultat principal 79/144, et un rejeu complet a donné **des réponses identiques à la première** ;
- test des trois machines le 24/09 (mêmes réponses partout) et blocage réseau le 16/09 (3/3 sites bloqués) ;
- import de la base des failles (121 719 failles, empreinte d'identification enregistrée) + 40/40 tests ;
- outil de notation unique et barème figé avant mesure.

**À faire — aucun résultat n'est annoncé avant d'être mesuré :**

- **G1 non fermée** : deuxième import sans doublon + vérification à la main de 60 cas (§6) ;
- G2 : index de recherche rapide + réglage du résolveur sur 200 cas (aujourd'hui : 37 % au 1ᵉʳ choix) ;
- G3/G4 : chaîne complète photo → PDF scellé + tests d'altération ;
- G5/G6/G7 : interface web, régénération des chiffres par script, clôture le 15/12.

---

## 4. Ce que le projet fait, et ce qu'il ne fait pas

### 4.1 Dans le projet

- **Une photo = un objet** seul et net ; sinon refus explicite (code `E_MULTI_OBJECT_OR_UNCLEAR`).
- **5 types d'objets** visés (prise, caméra, ampoule, routeur, enceinte) + un « je ne sais pas ».
- **Tout tourne en local** : le dictionnaire des produits et la base des failles sont des fichiers sur la machine ; **aucun appel internet pendant un audit** (prouvé le 16/09, §3.3).
- **Un rapport PDF** qui rappelle la limite du §2, avec un journal de bord scellé et la provenance complète (quelles photos, quel modèle, quelle base).
- **Une interface minimale** pour envoyer une photo et obtenir le rapport (démonstration, §6 G5).

### 4.2 Hors projet (assumé)

- Deviner la version du logiciel interne à partir d'une photo — **impossible**, c'est toute la limite du §2.
- Traiter des photos contenant plusieurs objets mélangés.
- Faire du scan réseau ou de l'interrogation de l'appareil (mDNS, UPnP…) : **exclu**, car cela exigerait l'autorisation écrite du propriétaire (articles 323-1 et suivants du Code pénal).
- Interroger le site NVD en direct pendant un audit (interdit par conception).
- Exploitation de failles, preuves de concept, application mobile, multi-utilisateur.

### 4.3 La piste « FCC ID » (à trancher)

L'énoncé du sujet propose d'utiliser le **FCC ID** — le numéro d'homologation imprimé sur les appareils — pour construire une première base. État : **zéro ligne de code, zéro donnée** ; pourtant deux de ces numéros sont déjà lus correctement par notre outil de lecture sur 2 photos sur 144. Reste : il n'existe **aucun tableau de correspondance entre FCC ID et codes CPE** — l'adopter créerait une seconde base de données à alimenter. **Recommandation** : d'abord **mesurer** combien de numéros lisibles nous avons réellement (~30 photos dédiées, une séance) avant de décider — question **Q8** (§13).

---

## 5. Ce qui sera livré finalement

| # | Livrable | État au 24/09 |
|---|---|---|
| L1 | Dépôt de code versionné + dépendances figées | ✅ |
| L2 | Corpus de photos gelé (licences et provenances) | ✅ |
| L3 | Mesures d'identification (chiffres + marges d'erreur + protocoles) | ✅ (§3.1, §3.2) |
| L4 | Résolveur CPE réglé sur 200 cas | ❌ (actuel : 37 % au 1ᵉʳ choix) |
| L5 | Base locale des failles + recherche traçable | 📝 importée le 24/09 ; 2ᵉ import et vérification de 60 cas ⏳ |
| L6 | Rapport PDF signé + journal scellé + vérificateur | ⏳ |
| L7 | Interface de démonstration | ⏳ |
| L8 | Tests + chiffres régénérables par script | 📝 40/40 tests (24/09) ; régénération ⏳ |
| L9 | Rapport de PFE, carnet de défense, démo hors-ligne | ⏳ (15/12) |

---

## 6. Les jalons (portes de validation G0 → G7)

Une « porte » est un jalon **démontrable en une séance** : soit le critère est atteint et prouvé, soit la semaine suivante sert à l'atteindre — jamais on ne passe outre.

| Porte | Date | Ce qu'il faut prouver | État au 24/09 |
|---|---|---|---|
| **G0** | 21/09 | 0 photo inutilisable dans les chiffres · dépôt Git créé · dépendances figées | ✅ fermée le 24/09 (retard de 3 jours) |
| **G1** | 19/10 | base des failles importée **2 fois sans doublons** · 60 cas vérifiés à la main ⇒ **0 faux positif raté** · temps de recherche mesuré | 📝 **les trois critères sont mesurés le 29/09** (`benchmarks/cve.json`) : rejeu **sans doublon** ✓ · 60 cas ⇒ **0 faux négatif et 0 faux positif** ✓ — les deux sont nuls, donc l'écart de rédaction entre ce tableau (« faux positif raté ») et `docs/07` A3 (« 0 faux négatif ; faux positifs documentés ») ne change pas le verdict · p95 **0,3–0,6 ms** pour une cible de 50 ms ✓ · **reste la relecture humaine des 60 cas** — c'est là que se tranche la décision `part='h'` (§14.3.10) |
| **G2** | 02/11 | index de recherche rapide en place · 200 cas de résolution réglés avec leur marge d'erreur | ⏳ |
| **G3** | 23/11 | chaîne complète photo → PDF · rejeu identique · 2 modes dégradés | ⏳ |
| **G4** | 30/11 | 6 tentatives de falsification détectées · rapport modifié ⇒ refus | ⏳ |
| **G5** | 07/12 | parcours complet via une interface web (transcription des échanges) | ⏳ |
| **G6** | 14/12 | tout chiffre publié régénéré automatiquement, avec son intervalle | ⏳ |
| **G7** | 15/12 | dépôt figé (tag) · rapport · démonstration hors-ligne | ⏳ |

**Chemin critique** : la porte **G1** n'est plus bloquée par l'ingestion — les trois critères sont mesurés le 29/09 (`benchmarks/cve.json`). Ce qui reste sur ce chemin est **une décision, pas un travail** : la base ne garde que les critères **matériels** (`part='h'`), et cette seule règle **vide la liste de failles des vendeurs du corpus** (§14.3.10 : 10 CVE gardées sur 11 714). Tant qu'elle n'est pas tranchée, G1 peut être « verte » et la chaîne CVE **inutile pour l'audit**.

---

## 7. Les critères d'acceptation (AC1 → AC12) — avec l'état réel

| # | Ce qui est promis (cible) | État mesuré au 24/09 |
|---|---|---|
| **AC1** | Précision de reconnaissance, comptée **par objet** (pas par photo) : **≥ 70 %** | **❌ échec** : **21 % [12 ; 34]** (10 objets sur 48, au moins une bonne photo) · en exigent marque + modèle exacts : **31 % [17 ; 50]** (8 sur 26) · *à titre indicatif seulement, compté par photo* : 55 % (79/144) |
| **AC2** | Quand le modèle dit avoir lu une étiquette, le texte est bien présent : **≥ 90 %** | **94 % (75/80)** — ✅ |
| **AC3** | Toutes les réponses sont au format attendu | **144/144**, aucune réponse cassée — ✅ |
| **AC4** | Temps de réponse dégradé **< 10 s** | **1,9 s** au pire sur une machine · **3,9 s** en flux réel · sur les trois machines : 2,1 / 2,1 / 5,1 s — ✅ |
| **AC5** | Le modèle n'invente **jamais** de marque inexistante : **< 5 %** | **0 % (0 sur 19)** — ✅ |
| **AC6** | En relançant le même test, on obtient la même chose : catégorie **100 %**, identification **≥ 95 %** | **144/144 réponses identiques à la première** — ✅ |
| **AC7** | L'analyse tourne même avec internet **coupé** | **3/3 machines, 3/3 sites bloqués**, analyse OK — ✅ |
| **AC8** | Le corpus est gelé : 144 photos, 0 photo inutilisable comptée | ✅ |
| **AC9** | 2ᵉ import sans doublons · 60 cas ⇒ 0 raté · recherche rapide mesurée (porte G1) | **✅ mesuré le 29/09** : rejeu en 3 passes, données identiques, **0 doublon** · 60 cas ⇒ **0 raté** · p95 **0,3–0,6 ms** · ⏳ **relecture humaine des 60 cas** · ⚠️ la base ne contient que **10 CVE des vendeurs du corpus sur 11 714** (§14.3.10) |
| **AC10** | Résolution de produit : **≥ 80 % au 1ᵉʳ choix / ≥ 92 % dans le top 3**, sur 200 cas | **37 % / 56 %** sur 68 cas — **❌ échec** |
| **AC11** | Bout en bout photo → PDF scellé + 6 tests d'altération (G3/G4) | ⏳ |
| **AC12** | Un test par message d'erreur (20 codes) | **0/20 couverts** — 📝 40/40 tests passent (24/09), mais aucun ne vérifie les messages d'erreur |

**Trois critères sont mesurés et en échec** (AC1, AC10, AC12). Ils ne seront **jamais** présentés comme atteints, et aucune phrase « ≥ 70 % » ne sortira du projet tant que la borne basse de la marge d'erreur ne dépassera pas la cible. Chaque échec a son levier de correction identifié (§9.2).

---

## 8. Les décisions prises, et pourquoi (forme courte)

1. **Garder Qwen2.5-VL** comme modèle — écart statistiquement réel avec la génération suivante (§3.1).
2. **Se limiter au niveau produit** — une photo ne porte jamais de logiciel interne (§2).
3. **Aucun score de risque agrégé** — l'auditeur classe lui-même les failles ; le système ne décide pas à sa place.
4. **Tout tient sur une seule machine** — le cluster partagé n'est qu'un accélérateur (§3.3).
5. **Bases de données figées et signées** — chaque analyse enregistre l'empreinte exacte des données utilisées ; sinon un rapport de septembre deviendrait inexplicable en octobre.
6. **La confiance se vérifie à deux niveaux** : « le modèle est d'accord avec lui-même sur plusieurs photos » **et** « sa réponse existe bien dans la nomenclature officielle ». L'un sans l'autre autorise les réponses inventées — situation d'ailleurs la plus fréquente sur nos tests.
7. **Lecture du texte : on garde ce que lisent les deux logiciels** — chaque variante a été mesurée avant de trancher.
8. **Réglages gelés avant chaque test** (température, nombre de mots, consigne) — on ne retouche pas un réglage après avoir vu les résultats.
9. **Une des trois machines est exclue du périmètre** (24/09) — occupée par un logiciel tiers : on négocie, on ne dépend pas d'elle.

---

## 9. Temps disponible et risques

### 9.1 Temps

Deux estimations assumées : **60 journées** (prudente) et **73 journées** (réaliste, avec soirées et week-ends). L'écart de 13 journées est absorbé par une **liste de coupes préparée à l'avance** (on retire toujours la même chose, dans le même ordre, plutôt que de laisser filer). La vraie ressource rare n'est pas le calendrier mais l'**attention** : le planning est donc découpé en **portes démontrables en une séance** (§6), pas en dates vagues.

### 9.2 Risques

| # | Risque | Conséquence | Parade |
|---|---|---|---|
| R1 | Le site NVD limite le téléchargement (920 pages déjà consommées le 14/09) | retard sur la porte G1 | téléchargement fait **hors ligne** le 24/09 ; reprise possible là où on s'est arrêté |
| R2 | Aucune vérification automatique continue ; 0/20 messages d'erreur testés | une régression passerait inaperçue | tests lancés à chaque modification ; un test par message d'erreur (AC12) |
| R3 | Un seul développeur, 60 à 73 journées | dépassement probable sur les dernières portes | portes hebdomadaires + liste de coupes ; le périmètre recule avant la qualité |
| R4 | Machines partagées avec d'autres étudiants | un run peut être impossible si notre machine est occupée | le fonctionnement mono-machine (§3.3) ; vérification obligatoire avant chaque run |
| R5 | Certains produits grand public **absent** du dictionnaire officiel | objet non résolu = message « aucune faille » trompeur | petit tableau de correspondance manuelle ≈ 50 entrées (levier déjà mesuré) ; sinon refus explicite `E_NO_CPE_MATCH` |
| R6 | AC1 à 21 % pour une cible de 70 % | la phrase « ≥ 70 % » est **interdite** | diagnostic erreur par erreur ; les leviers mesurés sont la consigne de test et le rapprochement de fiches — pas la taille du modèle |
| R7 | L'ingestion ne garde que les critères **matériels** (`part='h'`) | pour un objet du corpus, la liste de failles serait **vide ou quasi vide** alors que la base en contient des centaines : le rapport afficherait « aucune faille » — une **affirmation interdite** (§11.1) | mesuré le **29/09** (§14.3.10) : élargir l'ingestion aux parties `o` et `a`, **ou** écrire que le périmètre est « matériel nu » et **refuser explicitement** (`E_NO_CPE_MATCH`) au lieu de conclure « aucune faille » |

---

## 10. Comment on prouve ce qu'on affirme

- **Chaque chiffre porte sa date de mesure** ; les mesures passent par des tests **relançables** — on les refait et on vérifie qu'elles donnent la même chose.
- **Un seul outil de notation** pour toutes les mesures d'identification, jamais retouché à la main : une version recopiée « de mémoire » avait publié 77 % au lieu de 45 % — l'histoire complète est gardée au dossier (CDS §15.3).
- **Les corrections sont des ajouts datés** : une preuve ne se réécrit pas (§14.3).
- Les statuts ✅ / 📝 / ⏳ viennent toujours avec le chiffre qui les justifie (§3.4).

---

## 11. Ce que le système n'a jamais le droit de dire

### 11.1 Les cinq affirmations interdites

| Interdit | Pourquoi |
|---|---|
| « Ces failles concernent l'exemplaire que vous avez sous les yeux » | la photo ne montre aucune version de logiciel interne (§2) |
| « L'objet est sûr : aucune faille trouvée » | rien de répertorié ≠ rien qui existe (code `E_NO_CVE`) |
| « Le système détecte les failles » / « note de risque de l'appareil : 7/10 » | il fait un **classement au niveau du modèle**, pas une détection |
| « 90 % de précision » (sans la taille de l'échantillon ni sa marge d'erreur) | tout pourcentage sort avec son protocole, son effectif et sa fourchette |
| « Le rapport est signé, donc inaltérable » | le scellement prouve qu'**après** la signature, rien n'a changé — il ne prouve pas par lui-même qui a signé ; c'est le rôle de la signature électronique de tête de chaîne |

### 11.2 Règles de mesure

- Tout réglage qui influence un résultat est **figé avant le test** et noté dans le manifeste (consigne, température, nombre de mots, format de réponse).
- Toute figure indique son **unité de comptage** (photos ou objets) — jamais les deux mélangées ; les marges d'erreur ne s'appliquent qu'au niveau **objet**.

---

## 12. Portée de ce document

Ce document forme, avec le **cahier des spécifications techniques** (CDS-v2.1), l'ensemble de référence du projet : ici le **quoi** (périmètre, chiffres mesurés, critères, jalons) ; là le **comment** (organisation technique, données, épreuves de sécurité). Il se lit seul : toute mesure y porte sa date, et les corrections ultérieures seront des ajouts datés (§14.3).

---

## 13. Deux questions pour le tuteur

Sur les huit questions du projet, six ont une valeur par défaut qui permet d'avancer sans réponse (calendrier, validation avant export, diffusion des photos, parallélisation, scan réseau, dates de remise). **Deux changent le périmètre** et demandent une décision :

- **Q3 — photos dans des conditions « propres »** : aujourd'hui seulement 3 photos sur 144 sont des visuels officiels. Deux voies : acheter et photographier 5–8 vrais objets (une demi-journée, budget ≈ 50–60 €), **ou** retirer ce critère **en écrivant pourquoi**.
- **Q8 — FCC ID** (§4.3) : mesurer d'abord (~30 photos dédiées), ou écarter.

---

## 14. Traçabilité et versions

### 14.1 Quand un chiffre change

Il change **dans la ligne correspondante du §7**, avec sa nouvelle date — jamais dans une figure isolée.

### 14.2 Matrice de traçabilité

La matrice **est** le tableau §7 : chaque critère porte sa cible, son état et sa date ; chaque porte (§6) renvoie aux critères qu'elle conditionne (G1 → AC9 ; G2 → AC10 ; G3/G4 → AC11).

### 14.3 Corrections datées (24/09 et 29/09/2026)

1. Marge d'erreur de 79/144 corrigée : `[0,460 ; 0,621]` → **`[0,467 ; 0,628]`** (l'ancienne valeur était celle de 78/144).
2. « 5 types d'objets équilibrés » retiré : répartition réelle 29/8/5/4/2.
3. Protocoles de lecture de texte détaillés (les trois situations du §3.2).
4. Temps de réponse séparés par protocole — non comparables entre eux.
5. État des machines ramené à des **relevés datés** (machines partagées).
6. **État rafraîchi le 24/09 (21h36–21h59)** : 1ᵉʳ import de la base des failles, 40 tests, banc des trois machines — figures de §3.3, §3.4, §5, §6 et §7 mises à jour.
7. **Versionnement** : dépôt créé le 24/09 ; les gros fichiers de données sont **exclus** car re-téléchargeables.

**Ajouts du 29/09/2026** (banc CVE : `benchmarks/run_cve.py`, résultats dans `benchmarks/cve.md`) :

8. **`row_count` ne voulait pas dire ce que le schéma annonçait.** La colonne est documentée comme « nombre de lignes de critères **insérées** », mais le code y écrivait le nombre de critères **produits** par le flux. Comme un même critère répété dans un flux n'est écrit qu'une fois, les deux nombres différaient sur les quatre flux (92 968 annoncés contre 90 646 lignes en 2021 ; 5 309 écarts au total). La lecture naturelle de cet écart est « des doublons sont entrés », donc **une idempotence brisée qui n'existait pas** — la table ne contenait aucun doublon. Corrigé dans le code (`row_count` = lignes réellement présentes) et dans les quatre lignes déjà écrites : `92 968 → 90 646`, `86 988 → 85 474`, `99 578 → 98 302`, `50 245 → 50 048` (total inchangé : 324 470).
9. **Le rejeu n'était prouvé qu'à moitié.** Un second import du même fichier **saute** le flux grâce à son empreinte : cela prouve la provenance, pas le chemin d'écriture. Le banc rejoue donc les quatre flux une **troisième** fois sous un autre nom, pour forcer l'écriture : les comptes de données restent identiques et il n'y a **aucun doublon**. Sans cette passe, « idempotent » restait non prouvé.
10. **Ce que le filtre `part='h'` retire — mesure du 29/09.** L'ingestion ne garde que les critères **matériels**. En relisant les quatre flux bruts : pour les vendeurs du corpus, la base garde **10 CVE sur 11 714** (0,09 %). TP-Link, D-Link, Hikvision, AVM (Fritz!), Philips, Zyxel, MikroTik, Tuya, Verisure, Wemo, Amazon : **0 CVE matérielle** sur 2021–2024. Google/Nest : 2 sur 5 581. Apple : 2 sur 2 318. Huawei : 1 sur 1 143. Ces failles existent bien, mais classées `part='o'` (système) ou `part='a'` (application). **Conséquence** : pour un routeur ou une caméra du corpus, le rapport annoncerait « aucune faille connue » alors que la base locale en contient des centaines — retirées par une décision d'ingestion. Ce n'est **pas** un défaut du moteur (il rend exactement ce que la base contient), c'est une **conséquence de périmètre qui n'avait jamais été mesurée**. Mesure reproductible : `benchmarks/run_cve.py` ; section 2 de `benchmarks/cve.md`. **Décision à prendre** (§11.1 interdit de conclure « aucune faille »).

### 14.4 Annulations de versions

- **Version du 13/09/2026** : annulée — ses affirmations périmées sont corrigées ici (voir aussi §15).
- **Versions du 15/09 et du matin du 24/09** : remplacées par la présente version.

---

## 15. Lexique (pour lire ce document sans jargon)

| Terme | Explication en une phrase |
|---|---|
| **Firmware** | le logiciel embarqué qui tourne dans l'objet — invisible sur une photo. |
| **CVE** | le nom public d'une faille de sécurité connue (ex. CVE-2024-1234). |
| **NVD** | la base officielle qui relie ces failles aux produits — copiée ici en local. |
| **CPE** | le code officiel désignant un modèle de produit précis (ex. un routeur Archer C7 v2). |
| **Modèle de vision / VLM** | l'IA qui regarde la photo et écrit ce qu'il y voit, sur la carte graphique. |
| **OCR** | le logiciel qui lit le texte imprimé sur l'objet. |
| **Quantifié** | modèle compressé pour tenir dans la mémoire de la carte graphique (12 Go max). |
| **Fourchette à 95 %** | l'intervalle où se situe vraisemblablement le vrai chiffre — plus l'échantillon est grand, plus il est étroit. |
| **Compter par objet vs par photo** | un même objet photographié 8 fois ne vaut pas 8 réussites indépendantes : l'unité de preuve est l'**objet** (48). |
| **Accord (A)** | « le modèle donne la même réponse sur plusieurs photos du même objet ». |
| **Résolvabilité (R)** | « cette réponse existe-t-elle vraiment dans la nomenclature officielle ? ». |
| **Consensus halluciné** | accord parfait sur une réponse **inventée** → refusé par construction (A élevé, R faible). |
| **Journal scellé** | un carnet où chaque ligne scelle la précédente : modifier une ligne casse toute la suite, la falsification est détectée. |
| **Signature électronique** | clé privée pour signer, clé publique pour vérifier — un tiers vérifie sans recevoir aucun secret. |
| **FTS5** | un index de recherche interne à SQLite qui trouve un produit même avec des fautes d'orthographe. |
| **G0 → G7** | les jalons de validation du projet (§6). |
| **AC1 → AC12** | les promesses chiffrées du projet, avec leur état honnête (§7). |
| **✅ / 📝 / ⏳** | fait et prouvé / commencé mais incomplet / pas commencé. |
