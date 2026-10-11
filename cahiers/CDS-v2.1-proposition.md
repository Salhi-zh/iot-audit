# Cahier des spécifications techniques — v2.1

**Projet** : Reconnaissance d'objets connectés pour audit de sécurité IoT  
**Auteur** : Mohamed Salhi — Polytech Lille / ENSA Kénitra · **Tuteur** : Thomas Vantroys  
**Version** : 24/09/2026 · **Statut** : version de référence — remplace toutes les versions antérieures.  
**Compagnon** : le cahier des charges (CDC-v3.1) porte le **quoi** (périmètre, chiffres mesurés, critères d'acceptation, jalons) ; le présent document porte le **comment** : comment c'est construit, sur quelles machines, avec quelles garanties.

> **Comment lire ce document.** Écrit **sans prérequis technique** ; chaque terme utile est expliqué au passage (un lexique complet est dans le CDC §15). Les statuts sont : ✅ fait et prouvé · 📝 commencé mais incomplet · ⏳ pas commencé. Tout chiffre vient d'une mesure datée.

---

## 1. Les règles de fabrication du logiciel

1. **Les étapes se parlent avec des formulaires fixes.** Chaque étape du traitement transmet à la suivante un objet de type défini (pas un dictionnaire libre où n'importe quoi peut se glisser). Conséquence : un test peut vérifier une étape **à la seule**, sans rien lancer d'autre.
2. **Une base de données simple et locale.** Tout est stocké dans des fichiers SQLite (un format de base de données qui tient dans un fichier, sans serveur à administrer), en mode d'écriture sûre : un seul programme écrit, les autres lisent sans se gêner.
3. **Ça tourne sur une seule machine.** La chaîne complète fonctionne sur une machine de 12 Go de mémoire graphique (et même sur le processeur seul pour la partie recherche de fiches/failles). Le cluster de l'école sert à accélérer les tests, il n'est **jamais indispensable**.
4. **Fermeture d'internet pendant l'audit.** Pendant un traitement, **aucune requête ne sort** vers l'extérieur — prouvé le 16/09 : les sites internet de référence étaient bloqués et l'analyse a quand même tourné.
5. **Le code fait foi.** Ce document décrit les choix ; pour le détail d'un algorithme, c'est le code qui dit la vérité (écrit pour être lu).

---

## 2. Les machines et le modèle d'IA retenus (faits mesurés)

### 2.1 Le modèle d'IA

- **Modèle retenu** : `Qwen2.5-VL-7B-Instruct` en version **compressée 4 bits** (une compression nécessaire pour tenir dans les 12 Go de la carte graphique — voir le choix détaillé au CDC §3.1).
- **Comment il est servi** : par le logiciel **vLLM 0.29.0** qui expose le modèle sur le réseau local (port 8000). Poids : ≈ 6,9 Go ; mémoire réellement utilisée : **8 962 Mo sur 12 288 Mo** mesurée le 14/09.
- **Réponses en format rigide** : le modèle est contraint de répondre en **JSON** (le format d'échange standard des logiciels : paires « clé : valeur », sans phrase autour), température **0** (aucun hasard), **640 mots maximum** par réponse — trois réglages **figés avant les tests**. Résultat : 0 réponse mal formée, 0 réponse coupée en plein milieu sur les 144 photos.
- **Rappel du choix** (détail et corrections datées au CDC §3.1) : 79/144 pour le modèle retenu contre 53 pour la génération suivante (écart réel), et un modèle concurrent écarté car il respecte mal le format (21 réponses sur 144 hors format).

### 2.2 Les machines de l'école

- Trois machines identiques : processeur i9, 62 Go de RAM, carte graphique **RTX 3060 de 12 Go**, système sans gestionnaire de services (tout se lance à la main, par port), pilotes graphiques **alignés entre les trois**, recette de contrôle **10/10** (15/09).
- **État au 24/09** : relevés du jour — 20h56 une machine injoignable → 21h11 deux machines en service → **21h59 les trois en service**, temps dégradé 2,1 s / 2,1 s / 5,1 s sur 4 photos, **réponses identiques entre les trois machines**.
- **Ces machines sont partagées avec d'autres étudiants** : à un moment, l'une d'elles était saturée par un logiciel tiers (11,6 Go sur 12 Go de mémoire graphique) et un réseau privé tiers était actif dessus. **Décision consignée (24/09)** : périmètre contractuel = une machine saine ; les trois ne sont qu'un banc d'accélération.

---

## 3. L'organisation du traitement, étape par étape

Chaque flèche ci-dessous est un **type de données fixe**, pas une boîte noire :

```
[Photo] ──► 1. Lecture par le modèle de vision (+ lecture du texte)
                 │  ▼ sortie brute du modèle (marque, modèle, type, texte lu)
             2. Consolidation (accord entre photos × vérification officielle)
                 │  ▼ identification consolidée + statut
             3. Résolution de fiche produit (recherche approximative)
                 │  ▼ candidat(s) CPE + score
             4. Recherche de failles connues (locales, en Python)
                 │  ▼ liste de CVE (+ mention « niveau produit »)
             5. Rapport : journal scellé + PDF
```

### 3.1 Les jeux de valeurs fermés

| Domaine | Valeurs autorisées |
|---|---|
| **Type d'objet** | prise, caméra, ampoule, routeur, enceinte **+ `other`** (le « je ne sais pas ») |
| **Statut d'identification** | identifié / identifié avec réserve / non identifié — **trois valeurs, jamais deux** (un système qui ne peut que répondre « oui » ne peut pas reconnaître son ignorance) |
| **Niveau de preuve** | correspondance exacte au produit / plage de version / simple vendeur — exposé tel quel à l'auditeur (§9.3) |
| **D'où vient l'étiquetage** | catégorie officielle / nom de fichier / annonce de vente / saisie manuelle — traçable pour détecter les fuites de réponse |

### 3.2 Les formulaires échangés entre étapes

| Élément transmis | Contenu essentiel |
|---|---|
| **Sortie du modèle de vision** | marque, modèle, type d'objet, texte lu sur l'objet, « confiance ressentie » par le modèle (**jamais affichée** à l'utilisateur : elle n'est pas fiable) |
| **Candidat de fiche produit** | code CPE, fabricant, produit, version, scores, méthode employée |
| **Résultat de faille** | identifiant de la faille, sévérité, date, **niveau de preuve** (produit exact / plage de version / vendeur entier) |
| **Identification finale** | marque, modèle, statut, nombre de photos, **accord** et **résolvabilité** (§8), distribution des réponses, fiches et failles associées |
| **Provenance du traitement** | empreintes numériques (empreinte = empreinte digitale d'un fichier) des poids du modèle, de la consigne et du schéma de réponse ; versions du logiciel ; **empreinte de la base des failles** ; dates de début et de fin |
| **Événement de journal** | numéro de ligne **toujours croissant** (résiste à une horloge qui dérive), étape, message, charge utile, horodatage |
| **Entrée photo** | identifiant, empreinte, provenance, licence, date de collecte, dimensions, présence ou non de texte lisible |

### 3.3 Ce que le modèle doit obligatoirement renvoyer

Un objet JSON à champs fixes : `brand`, `model`, `category`, `visible_text`, `identification_basis` — **aucun champ supplémentaire toléré**, longueur maximale par champ, type d'objet pris dans la liste fermée (§3.1). Ce format garantit une réponse **lisible par la machine**, pas son exactitude.

---

## 4. Les quatre bases de données locales

| Base | Ce qu'elle contient réellement | État |
|---|---|---|
| **Photos du projet** (500 Ko) | 48 objets, 144 photos utilisables + 11 retirées, 288 relevés de lecture de texte, 2 traitements enregistrés ; les tables de résultats bruts et de cas de calibration existent mais sont **encore vides** | ✅ vérité terrain gelée |
| **Dictionnaire des produits CPE** (463 Mo) | **1 838 235 fiches** au total, dont **64 842** concernent du matériel (le périmètre du projet) ; empreinte d'identification enregistrée (14/09) | ✅ |
| **Base des failles NVD** (154 Mo, importée le 24/09) | **121 719 failles** et **324 470 critères matériels** répartis sur **873 fabricants** ; les 4 fichiers d'origine sont tracés par empreinte ; statuts réellement présents : 83 617 modifiées, 23 569 analysées, 10 855 différées, **3 559 retirées par le NVD** (et conservées telles quelles, §7.6), 119 diverses | ✅ premier import — les preuves complètes du §7 restent ⏳ |
| **Référentiel de vérification du texte** | un jeu public annoté (COCO-Text) servant à noter notre outil de lecture | ✅ |

Toutes les photos publiables portent leur **adresse d'origine, leur licence (CC-BY / CC-BY-SA) et leur empreinte** ; les fichiers d'images ne sont **pas diffusés** avec le rapport.

---

## 5. La lecture automatique du texte (OCR) — un aide, pas une vérité

- **Deux logiciels** comparés côte à côte (PaddleOCR et OnnxTR) ; on retient un texte si **l'un ou l'autre** le lit (choix du 15/09 : 50 photos avec texte, 94 sans, sur 144).
- **Trois mesures, trois situations** — lisons-les du plus favorable au plus réaliste :

| Situation | Résultat | En clair |
|---|---|---|
| On dessine le rectangle autour du texte | **66 %** de réussite (1 384 textes, fourchette 63–68 %) | il recopie bien les 2 textes sur 3 quand on lui montre où chercher |
| Photo entière, gros plan | **35 %** (600 photos, 2 604 mots, fourchette 32–38 %) | il lit environ 1 mot sur 3 |
| Vraie vie : trouver puis lire | **10 %** (12 sur 120, fourchette 6–17 %) | **la chaîne complète est faible** — on n'a pas le droit de compter dessus |

- **Rôle** : alimenter le champ « texte lu » et le drapeau « photo contient du texte » ; remplacer **jamais** l'étiquetage humain. Quand un modèle affirme avoir lu une étiquette, le système vérifie que le texte est bien présent (critère AC2 du CDC : 94 % de conformité mesurée).

---

## 6. Retrouver la bonne fiche produit (résolution CPE)

- **Comment ça marche** : on cherche d'abord le **fabricant exact** (petit dictionnaire d'alias pour les orthographes : « tp-link », « tplink », « tp link »), puis on classe les produits par **similarité de mots** (fonction de rapprochement qui ignore les mots superflus), puis on décide par **marge** : si le meilleur candidat n'est pas nettement devant le deuxième, on refuse de trancher.
- **Ses seuils** : acceptation automatique à **0,90** ; plancher à **0,60** (en dessous : refus explicite, jamais de réponse approximative) ; marge minimale **0,08** entre le 1ᵉʳ et le 2ᵉ. Méthode de réglage : on balaie les seuils et on garde **le plus souple qui garde une fiabilité ≥ 95 %**. **Ce réglage définitif attend le banc de 200 cas (porte G2).**
- **Index de recherche rapide (FTS5)** : prévu pour retrouver un produit même mal orthographié — **pas encore en place** (constat du 24/09) ⏳.
- **État actuel du banc de mesure** : sur 68 cas volontairement dégradés : **37 % au 1ᵉʳ choix, 56 % dans le top 3**, contre des cibles de 80 % et 92 % — **échec public** (critère AC10). Causes diagnostiquées : des produits grand public **absents** du dictionnaire, deux orthographes concurrentes sans table d'alias, et un refus par marge volontairement prudent. **Levier identifié** : un tableau d'alias manuel d'environ 50 entrées.
- **Refus explicites** : `E_NO_CPE_MATCH` (aucune fiche trouvée) et `E_CPE_AMBIGUOUS` (plusieurs fiches plausibles) — le système présente ses doutes plutôt qu'une fausse certitude.

---

## 7. La base locale des failles (NVD) — première importation faite le 24/09

### 7.1 D'où viennent les données et comment on les trace

Les fichiers officiels annuels du NVD sont téléchargés une fois, conservés sur disque, et **signés par empreinte** (sha256 — l'empreinte digitale du fichier) : nom, empreinte, date de publication, date d'import, nombre de lignes et de failles. C'est cette traçabilité qui rend un rapport reproductible : le rapport dit exactement **quel fichier de failles** il a consulté.

### 7.2 Ce qui est conservé pour chaque faille

L'identifiant (ex. CVE-2024-1234), son **statut officiel brut** (dont les **3 559 failles retirées** par le NVD — on les garde pour ne jamais se demander « pourquoi celle-là a disparu ? »), les dates, la description, et la sévérité avec son score de criticité.

### 7.3 Les critères d'association à un produit

Une ligne par association : le **motif officiel original** conservé tel quel (c'est la pièce montrant *pourquoi* cette faille remonte), le fabricant, le produit, la version, les quatre bornes de plage (début/fin, inclus/exclus), les drapeaux « vulnerable », « exclure » et l'opérateur logique — avec interdiction de doublons.

### 7.4 On ne garde que le matériel

Seules les associations vers du **matériel** (`part='h'`) sont importées — **64 842 entrées matérielles sur 1 838 235** au total. Le reste (logiciels, systèmes d'exploitation) est écarté au fil du téléchargement, sans jamais charger une année entière en mémoire.

> **Ce que ce filtre coûte, mesuré le 29/09/2026** : pour les vendeurs du corpus du projet, la base ne garde que **10 failles sur 11 714** (0,09 %) — TP-Link, D-Link, Hikvision, AVM, Philips, Zyxel, MikroTik : **zéro** faille matérielle sur 2021–2024, alors que les mêmes produits en ont des centaines classées `part='o'` (système) ou `part='a'` (application). Voir CDC §14.3.10 et `benchmarks/cve.md` §2.

### 7.5 On peut relancer l'import sans risque

Si le schéma existe déjà, on ne crée rien deux fois ; l'écriture ignore les doublons. **Relancer l'import doit donc produire exactement les mêmes comptes** — c'est la preuve exigée par la porte G1, et elle est **faite le 29/09**. Un compteur de progression permet de reprendre au milieu d'un fichier si le téléchargement est interrompu.

**Nuance apportée le 29/09 :** relancer le **même** fichier ne prouve que la *provenance* — son empreinte le fait sauter avant toute écriture, donc le chemin d'écriture n'est jamais exécuté. Le banc rejoue donc les flux une **troisième** fois sous un autre nom, ce qui force l'écriture : les comptes de données restent identiques et il n'y a **aucun doublon**. Les deux passes sont décrites dans `benchmarks/cve.md` §3.

### 7.6 Les failles retirées restent visibles

Si le NVD retire une faille, elle est **conservée avec son statut** : un rapport antérieur qui la mentionne garde son explication. La recherche les met à part et les signale, sans les mélanger aux failles actives.

> **État (24/09, 21h36)** : **premier import exécuté** — 4 années (2021–2024), **121 719 failles / 324 470 critères matériels en 11 secondes**, empreinte par fichier. ~~Porte G1 non fermée : deuxième import sans doublon et vérification à la main de 60 cas ⏳ ; le temps de recherche n'a été mesuré que sur 6 requêtes (3,5 ms).~~ *(périmé — voir l'état du 29/09 ci-dessous)*

> **État (29/09, 13h50)** — banc `benchmarks/run_cve.py`, résultat complet dans `benchmarks/cve.json` :
> - **rejeu sans doublon** : 3 passes sur une base neuve (flux d'origine, mêmes noms, copies renommées) ⇒ comptes de données **identiques**, `COUNT(*) = COUNT(DISTINCT …)`, **0 doublon** ✓ ;
> - **60 cas** ⇒ **0 faux négatif, 0 faux positif** ✓ — vérité terrain re-dérivée des `.json.gz` **bruts** par un lecteur indépendant de l'ingestion ;
> - **latence** : p95 **0,3–0,6 ms** sur 60 requêtes distinctes (600 exécutions), cible 50 ms ✓ ;
> - ⏳ **reste la relecture humaine des 60 cas** — et c'est précisément là que la décision `part='h'` doit être tranchée (CDC §14.3.10).
> - correction jointe : `feed_versions.row_count` annonçait le nombre de critères **produits** au lieu du nombre de lignes **insérées** ; corrigé dans le code et dans les quatre lignes déjà écrites (CDC §14.3.8).

---

## 8. La confiance : deux vérifications croisées (et non une seule)

- **1ʳᵉ vérification — l'accord** : le modèle est interrogé sur **plusieurs photos du même objet** (prises de côtés différents). S'il répond la même chose à chaque fois, il est « d'accord avec lui-même ». C'est utile, mais insuffisant : un modèle qui a mémorisé une réponse fausse sera d'accord avec lui-même aussi.
- **2ᵉ vérification — la résolvabilité** : la réponse consensuelle **existe-t-elle réellement** dans le dictionnaire officiel des produits ? Si la marque renvoyée n'existe dans aucune fiche, la réponse est inventée.
- **Le cas dangereux** : accord très élevé **et** résolvabilité faible = **réponse inventée, mais répétée avec assurance**. C'est précisément le cas le plus fréquent observé sur nos tests — d'où la règle : ce cas est **refusé** (statut « non identifié »), jamais affiché comme une réussite.
- **La confiance que le modèle affirme lui-même n'est jamais montrée à l'utilisateur** : elle n'est pas fiable (écart mesuré entre ce qu'il déclare et ce qu'il fait : déclaré − juste = **−32 points** sur le banc de calibration).
- **Aucun score de risque agrégé** ; chaque faille remontée porte la mention « niveau produit » (§9.3).

---

## 9. Chercher les failles connues d'un produit

**Validé le 24/09** : **40 tests automatiques passent** ; sur la vraie base de 324 470 critères, une recherche prend **1,5 ms en médiane, 3,5 ms en dégradé** (6 essais) — largement sous la cible contractuelle de 50 ms.

**Mesuré le 29/09** sur **60 requêtes distinctes** (et 600 exécutions) : p50 **0,05–0,13 ms**, p95 **0,3–0,6 ms**, max 5,2 ms — cible de 50 ms tenue avec trois ordres de grandeur de marge. Les 60 cas et le rejeu sans doublon sont produits par `benchmarks/run_cve.py` ; il reste la relecture **humaine** des 60 cas, et la décision de périmètre `part='h'` (CDC §14.3.10) qu'aucun test ne peut trancher.

### 9.1 Le tri préalable (en base de données) ne tranche rien tout seul

Une première requête élimine l'essentiel et ramène des **candidats larges** (fabricant exact, produit exact **ou** tout produit du fabricant) ; la décision finale se prend ensuite en Python, sur des fonctions simples qu'on peut tester une par une — plutôt que dans une requête compliquée que personne ne pourrait relire.

### 9.2 Les plages de versions, évaluées en Python

Une faille concerne souvent une plage (« de 1.0 à 2.0 exclu »). La comparaison des versions se fait **en Python** et de façon lisible : comparaison **numérique** (donc « 1.10 » est bien plus récent que « 1.9 ») et une version d'essai (« 1.2.3-beta ») est considérée comme **antérieure** à sa version finale (« 1.2.3 »).

**Le cas nominal du projet** : nous ne connaissons **pas** la version du logiciel interne (une photo ne le donne pas). Le résultat est alors marqué **`unresolved`** : « non résolu ». Il n'est ni déclaré concerné, ni déclaré non concerné **en silence** — c'est la seule manière de ne pas fabriquer de faux négatifs, le défaut le plus grave d'un tel outil.

### 9.3 Niveau de preuve, affiché tel quel

Trois niveaux, jamais confondus : **produit exact** (preuve forte) > **plage de version** (preuve forte) > **vendeur entier** (preuve faible, quand le critère ne nomme que le fabricant). L'auditeur voit ce niveau dans le résultat ; un match faible n'est jamais fusionné avec un match fort. Chaque faille porte **`triage_scope='product'`** — le champ qui, dans la base comme dans le PDF, interdit d'interpréter le résultat au niveau de l'exemplaire.

---

## 10. Le journal scellé et la signature (intégrité du rapport)

- **Déjà prévu dans les formulaires** : la provenance complète (§3.2) et la ligne de journal avec numéro **toujours croissant** — le journal survit à une horloge qui dérive.
- **À construire (⏳, portes G3/G4)** :
  1. **chaîne de scellement** : chaque ligne du journal est scellée avec la précédente (HMAC, une fonction cryptographique) — modifier une ligne casse toute la suite, la falsification est détectée à la ligne exacte ;
  2. **signature de la dernière ligne** par une clé privée ; la clé publique est **imprimée dans le rapport** : un tiers vérifie le document **sans recevoir aucun secret** ;
  3. l'empreinte de la base des failles est écrite dans chaque traitement ;
  4. **6 tests d'altération** dont deux indispensables : un test de **fausse ligne créée avec la vraie clé, qui doit réussir** (la limite est démontrée, pas cachée) et un test « rapport modifié après coup ⇒ refus ».
- **Formulation exacte à défendre** : le scellement prouve que le contenu **n'a pas changé après** la signature ; il ne prouve pas à lui seul l'identité du signataire — c'est le rôle de la signature à clé publique de la dernière ligne.

---

## 11. Le rapport PDF et l'interface (⏳)

- **Contenu du PDF** : la photo, la fiche produit retenue avec ses candidats et scores, les failles du modèle avec leur niveau de preuve, la provenance complète, et **quatre mentions obligatoires** : triage au niveau produit, logiciel interne non déterminé, message non rassurant si aucune faille, date et empreinte de la base des failles utilisée.
- **Interface de démonstration** : une page web simple **ou** une commande en ligne — parcours complet exigé par la porte G5 (07/12) : envoyer une photo → lancer le traitement → récupérer le PDF → **le vérifier hors-ligne** avec la clé publique.

---

## 12. Temps de réponse mesurés et cas dégradés

*Note de lecture* : le temps **dégradé** (p95) est le temps en deçà duquel se situent 95 requêtes sur 100 — c'est lui qu'on compare à la cible.

| Mesure | Valeur | Situation de mesure |
|---|---|---|
| Temps par image, médian / dégradé | 1,08 s / **1,88 s** | 12 mesures, 15/09 |
| Temps dégradé en vraie chaîne (photo jamais vue) | **3,9 s** (max 5,5 s) | flux réel — la valeur honnête |
| Débit sur les 3 machines ensemble | **57,9 requêtes/s** | banc de charge du 15/09 |
| Panne d'un nœud en plein traitement | **2400 requêtes sur 2400 servies**, 0 abandon | mode dégradé déjà testé |
| Banc des 3 machines (24/09, 4 photos) | dégradé 2,1 / 2,1 / 5,1 s, réponses identiques | les trois en inférence réelle |
| **Cible contractuelle** | dégradé **< 10 s** | ✅ tenue avec une marge ×2,6 en flux réel |

Les temps **ne sont jamais comparés entre protocoles différents sans le dire** (CDC §3.1).

**Modes dégradés prévus** : base des failles indisponible → identification seule, message explicite ; machine perdue en cours de traitement → traitement partiel comptabilisé comme tel ; aucune faille trouvée → message non rassurant (`E_NO_CVE`).

---

## 13. Licences, données personnelles, conformité

- Photos sous licences **CC-BY / CC-BY-SA** (Wikimedia Commons), avec adresse d'origine, licence et empreinte pour chacune ; **jamais diffusées** avec le livrable.
- Aucune donnée personnelle dans le corpus ; **aucun scan réseau**, aucune collecte de terrain (hors projet — articles 323-1 et suivants du Code pénal).
- **Documents de conformité à produire avant la soutenance** : durée de conservation des données, principe de minimisation écrit — ⏳.
- Les données de localisation (EXIF) sont **retirées dès l'import**, avant tout stockage.

---

## 14. Sécurité d'exploitation (en clair)

- **Fermeture totale d'internet pendant un traitement** : règles de pare-feu écrites **en mémoire uniquement** (rien n'est écrit sur le système), autorisant seulement le réseau local, le serveur de noms et la boucle locale ; un **garde de 300 secondes** remet tout dans l'état automatiquement ; le script de restauration est exécuté **avant** d'appliquer quoi que ce soit. Appliqué puis restauré sur les trois machines le 16/09 — incident d'un réseau tiers détecté et réparé le jour même.
- **Mots de passe** : transmis par un canal indirect à deux sauts (poste → passerelle → machine), **jamais dans une ligne de commande** (visible par tous avec la commande `ps`) **ni dans un fichier**.
- **Pas de gestionnaire de services** sur ce système : tout se lance et se vérifie à la main, par port et par numéro de processus, avec un script de recette automatique (version rapide + version approfondie).

---

## 15. Mesure, notation et reproductibilité

### 15.1 Un barème figé, un seul outil de notation

Le barème de notation des photos est **figé avant** toute mesure ; l'outil qui l'applique est **unique** et le même partout — **jamais recopié à la main**, jamais réécrit « de mémoire ».

### 15.2 Par quoi on compte

Les marges d'erreur (fourchettes à 95 %) ne s'appliquent qu'au niveau **objet** (48) : huit photos du même objet ne sont pas huit épreuves indépendantes. **Aucune affirmation de précision n'est validée sans fourchette au niveau objet** ; les chiffres comptés par photo ne sortent qu'avec la mention « indicatif ». Toute figure indique son unité de comptage.

### 15.3 L'incident fondateur (conservé pour la mémoire)

Une **copie** de l'outil de notation, refaite « de mémoire », avait publié **77 % au lieu de 45 %** — 32 points trop haut — parce qu'elle écrasait les séparateurs lors du nettoyage des textes. Conséquence : la correspondance des outils est aujourd'hui **vérifiée automatiquement** (l'outil doit reproduire exactement les chiffres déjà publiés), pas relue à l'œil.

### 15.4 Ce qui est déjà reproductible

Deux exécutions complètes d'une heure d'intervalle ont donné des réponses **identiques à la première** (144/144) ; les réglages (640 mots maximum, garde de fin de texte) ont été **figés avant les mesures**.

### 15.5 La bande de sensibilité (règle anti-complaisance)

Chaque mesure est rejouée sous **4 barèmes de notation différents** (le plus permissif en 5ᵉ point de la bande) : la **direction de la conclusion doit être la même sous les 4**. Les valeurs sont publiées **côte à côte** (borne la plus sévère et borne la plus souple), jamais fusionnées en un chiffre unique.

### 15.6 État restant

- Figures principales **reproductibles** ✅ (outil unique + manifestes figés).
- **Un ancien fichier d'agrégats n'est pas régénérable** (aucun script producteur conservé) — ❌ à réparer avant la porte G6 (14/12).
- Tables de résultats bruts du corpus : **vides** — les résultats publiés vivent dans les archives de mesure, pas encore en base.

---

## 16. Annexe — les formules utilisées

**Marges d'erreur (fourchette de Wilson, confiance 95 %)** — utilisée pour tout pourcentage publié :

$$\hat{p} \pm \tilde{\Delta} \quad\text{avec}\quad
\tilde{\Delta} = \frac{z}{1 + \frac{z^2}{n}}\sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}
\quad (z = 1{,}96)$$

*Lecture* : `p̂` est le pourcentage observé, `n` l'effectif. Cette formule est préférée au calcul naïf parce qu'elle **reste valable pour de petits effectifs et près de 0 % ou 100 %** — exactement notre cas.

**La confiance du projet, en deux comptages :**

- **accord** = proportion de photos donnant la réponse la plus fréquente : $A = \dfrac{\max_t |\{i : t_i = t\}|}{N}$ (publié en fraction brute, ex. « 6 sur 8 », sans marge d'erreur) ;
- **résolvabilité** = meilleur score de rapprochement du consensus dans le dictionnaire officiel ;
- **décision** : accord élevé **et** résolvabilité faible ⇒ réponse inventée et répétée ⇒ **refus explicite**.
