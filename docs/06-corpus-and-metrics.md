# 06 — Corpus et plan de mesure

> Le tuteur a autorisé des **photos internet**, l'essentiel du projet étant logiciel, le matériel venant plus tard. C'est une **très bonne nouvelle statistique** et une **mauvaise nouvelle de validité**. Ce document traite les deux.

---

## 1. Ce que change « photos internet »

### 1.1 Le gain : `n` n'est plus limité par la physique

Le goulot d'étranglement n'est plus l'accès aux objets, mais **l'annotation**. Conséquence directe : on peut viser un corpus statistiquement défendable au lieu de 8 objets.

**À 400–800 images, le calcul change complètement :**

| n objets | IC 95 % de Wilson autour de p̂ = 0,70 | Granularité d'une erreur |
|---|---|---|
| 10 | ≈ [0,40 ; 0,89] — **±25 pts** | 10 pts |
| 30 | ≈ [0,52 ; 0,83] — ±15 pts | 3,3 pts |
| **50** | ≈ [0,56 ; 0,81] — ±12 pts | 2 pts |
| **100** | ≈ [0,60 ; 0,78] — ±9 pts | 1 pt |

**Point décisif, à comprendre avant d'écrire le CDC :** la cible « ≥ 70 % » n'est **démontrable que si le taux mesuré est ≈ 80 % à n ≈ 100**. Avec p̂ = 0,70 exactement, la borne inférieure de l'IC est **0,60** : on ne peut **pas** affirmer « ≥ 70 % », on peut seulement dire « 70 %, IC [0,60 ; 0,78] ». Un jury qui sait lire un intervalle posera la question.

⇒ **Cible de corpus : 50 objets minimum, 100 visés ; 8–10 photos/objet ; 5 catégories × 10–20 objets.**

Cette seule correction règle le problème de puissance statistique relevé en amont.

### 1.2 La menace : trois biais introduits par le web

#### (a) Contamination d'entraînement

Qwen2.5-VL a été entraîné sur du web. Les visuels produit **officiels** (top des résultats d'image) ont pu être **mémorisés**. La précision mesurée serait alors une mesure de mémorisation, pas de reconnaissance. **C'est la menace de validité n°1 du projet.**

#### (b) Biais de facilité (photos de catalogue)

Les visuels marketing sont cadrés, éclairés, mono-objet, marque bien lisible. Le terrain, non. Mesurer 85 % sur du catalogue et annoncer « 85 % de précision » sans qualifier est une faute.

#### (c) Le pire : le système peut ne faire que de l'**OCR**

Sur la plupart des photos web, **le nom du produit est imprimé sur l'objet ou la boîte**. Un VLM qui « identifie » un routeur en lisant « TP-Link Archer C7 » sur son étiquette ne fait pas de la reconnaissance : il fait de la **lecture de texte**. Il peut alors afficher 90 % tout en étant incapable de reconnaître le même objet retourné, flou, ou photographié sans étiquette.

C'est **le** contrôle à ne pas manquer : pour ce projet, la variable `text_visible` est aussi importante que la catégorie.

---

## 2. Stratification du corpus

```python
from iot_audit.contracts import Stratum
```

| Strate | Source | `text_visible` attendu | Risque contamination | Rôle |
|---|---|---|---|---|
| **S1 `official`** | visuels marketing, sites constructeur | souvent oui | **élevé** | borne haute (optimiste) |
| **S2 `review`** | photos d'avis clients (marketplaces) | variable | moyen | condition « réaliste » |
| **S3 `forum`** | forums, réparation, teardown, angles inhabituels, emballages non anglophones | souvent non | **faible** | borne honnête |

**Prédiction falsifiable :** précision(S1) > précision(S2) > précision(S3). L'**écart S1 − S3** est le résultat principal du rapport sur la validité. Le publier, même s'il est défavorable, vaut mieux que le découvrir en soutenance.

### 2.1 Sous-ensembles nommés (contrôles)

| Sous-ensemble | Contenu | Ce qu'il prouve |
|---|---|---|
| `no_text` | images où **aucun texte produit n'est lisible** | la **vraie** capacité de reconnaissance (sans OCR) |
| `with_text` | texte produit lisible | mesure le confort OCR — à ne **pas** confondre avec la reconnaissance |
| `confusable` | ~5 paires white-label (même OEM, marques différentes) | le risque explicitement identifié au CDC |
| `perturbed` | transformations géométriques/photométriques d'images existantes | robustesse |

`confusable` transforme un risque *déclaré* en un **résultat mesuré** : c'est exactement ce qu'un jury sécurité attend, et ça ne coûte que 5 paires.

---

## 3. Schéma du corpus (provenance obligatoire)

```sql
ALTER TABLE images ADD COLUMN source_url   TEXT NOT NULL;
ALTER TABLE images ADD COLUMN license     TEXT NOT NULL;   -- 'editorial','CC-BY-4.0','unknown'
ALTER TABLE images ADD COLUMN retrieved_at TEXT NOT NULL;
ALTER TABLE images ADD COLUMN stratum     TEXT NOT NULL;   -- official|review|forum
ALTER TABLE images ADD COLUMN text_visible INTEGER NOT NULL; -- 0/1 : texte produit lisible
ALTER TABLE images ADD COLUMN label_source TEXT NOT NULL;  -- 'listing'|'manual'
ALTER TABLE images ADD COLUMN subset      TEXT;            -- no_text|with_text|confusable|perturbed
CREATE UNIQUE INDEX ux_images_sha ON images (sha256);
```

**`label_source` est un contrôle anti-fuite :** si la vérité terrain provient du **titre de l'annonce** et que ce titre est **imprimé sur l'objet**, l'étiquette est *dans* l'image. Le système peut alors « réussir » en recopiant la réponse. Le drapeau permet de rapporter séparément les cas non contaminés.

**Licence / provenance :** nécessaire pour un rapport destiné à un client, et pour citer le corpus dans le dépôt. Par défaut : **citer par URL, ne pas redistribuer** les images.

---

## 4. Plan de mesure

### 4.1 Deux niveaux, à ne pas mélanger

| Niveau | Unité | Usage | `n` |
|---|---|---|---|
| **objet** | 1 objet = 1 verdict (consolidé sur ses photos) | les **cibles de précision** (A1) | 50–100 |
| **image** | 1 photo | diagnostic (accord A, OCR, confusion) | 400–800 |
| **CPE** | 1 paire requête→CPE | la cible A2 (top-1/top-3) | 200 |

Les **IC de Wilson** ne s'appliquent qu'au **niveau objet** (§4.3). Au niveau image, les photos d'un même objet ne sont pas indépendantes.

### 4.2 Comment obtenir 200 paires CPE pour ~2 h de travail

50 objets réellement annotés → générer **4 variantes réalistes de bruit d'inférence** par objet :

| Variante | Exemple (objet : Archer C7 v2) |
|---|---|
| faute de frappe | `Archer C7 V2` → `Archer C7 V2` / `Arcer C7` |
| version omise | `Archer C7` |
| alias de marque | `tplink Archer C7 v2` |
| descripteur parasite | `TP-Link Archer C7 v2 wireless router` |

⇒ **50 × 4 = 200 paires**. Le benchmark mesure alors la robustesse du matcher **et** la précision, avec un coût d'annotation quasi nul. C'est le meilleur rapport effort/preuve du projet.

### 4.3 Statistiques : ce qu'on peut et ne peut pas affirmer

```python
# iot_audit/report/metrics.py
from iot_audit.report.wilson import wilson


def object_accuracy(results: list[tuple[bool, Stratum]]) -> dict:
    """Accuracy objet-level + IC de Wilson, globale et PAR STRATE."""
    out = {}
    for stratum in ("ALL", "official", "review", "forum"):
        sel = [ok for ok, s in results if stratum == "ALL" or s.value == stratum]
        if not sel:
            continue
        k, n = sum(sel), len(sel)
        lo, hi = wilson(k, n)
        out[stratum] = {"k": k, "n": n, "p": k / n, "ci95": (round(lo, 3), round(hi, 3))}
    return out
```

**Règles d'énoncé :**
- publier **p̂ ET IC** ; ne jamais citer un pourcentage sans `n` ;
- ne déclarer « ≥ 70 % » **que si la borne inférieure ≥ 0,70** ;
- par catégorie, `n` tombe à 10–20 ⇒ IC ≈ ±25 pts ⇒ **publier une matrice de confusion**, pas une précision par catégorie ;
- la précision sur `no_text` est **le chiffre principal** ; celle sur `with_text` est un chiffre de confort OCR.

### 4.4 Benchmark de robustesse (perturbations)

| Perturbation | Paramètre | Mesure |
|---|---|---|
| recadrage | 70 %, 85 % | Δprécision |
| rotation | ±10°, ±20° | Δprécision |
| luminosité/contraste | ±30 % | Δprécision |
| flou de mouvement | rayon 3, 7 | Δprécision |
| fond | remplacement/détourage | Δprécision |

Sortie : **courbe Δprécision vs intensité**. Un système qui perd 30 pts sur une rotation de 15° n'est pas exploitable sur le terrain — et c'est une phrase utile au rapport.

---

## 5. Métriques révisées (à mettre dans le CDC)

| # | Métrique | Cible | Base | Statut |
|---|---|---|---|---|
| M1 | Précision identification, **niveau objet**, toutes strates | p̂ ≥ 70 %, IC publié | n ≥ 50 objets | MESURÉ |
| M2 | Précision identification sur **`no_text`** | **publiée telle quelle** (probablement < M1) | n ≥ 20 objets | MESURÉ — chiffre honnête |
| M3 | Écart **S1 − S3** (proxy de contamination) | **publié**, pas de cible | 3 strates | MESURÉ — le résultat méthodologique |
| M4 | Précision CPE top-1 / top-3 | ≥ 80 % / ≥ 92 % | 200 paires | MESURÉ |
| M5 | Paires `confusable` | **publié**, pas de cible | ~5 paires | DIAGNOSTIC |
| M6 | Robustesse (Δ sous perturbation nominale) | ≤ 15 pts | ~100 images | MESURÉ |
| M7 | `InventedBrandRate` | < 5 % | image | MESURÉ |
| M8 | Latence p95 end-to-end | < 10 s | ≥ 100 images | MESURÉ |
| M9 | Accord de rejeu (2 runs identiques) | catégorie 100 %, tuple ≥ 95 % | 100 images | MESURÉ (ENF5, D8) |

**Retiré du CDC :** « précision conditions terrain ≥ 50 % ». Sans photos terrain, cette ligne est **fausse** : des photos web ne sont pas des photos terrain. Deux options, à trancher avec le tuteur : la **retirer**, ou la **requalifier** en « précision sur photos d'avis utilisateurs (proxy réaliste) ≥ 50 % » — auquel cas la strate `review` sert de mesure dédiée et le mot « terrain » disparaît.

---

## 6. Effort d'annotation (budget réaliste)

| Tâche | Volume | Rythme | Coût |
|---|---|---|---|
| Collecte + métadonnées par image (URL, licence, strate, `text_visible`) | 400–800 | ~20 s/image | **2–4,5 h** |
| Vérité terrain par **objet** (marque, modèle, CPE) | 50–100 | ~3 min/objet | **2,5–5 h** |
| Paires CPE bruitées (générées + vérifiées) | 200 | automatique | ~0,5 h |
| Sous-ensembles `confusable` / `perturbed` | ~40 | semi-auto | ~1 h |
| **Total** | | | **≈ 6–11 h sur 4 semaines** |

C'est borné, et surtout : **c'est le seul poste du projet dont le volume dépend du choix de corpus**. Le commence **en semaine 1** (voir `08`) car il n'est pas sur le chemin critique mais il est purement manuel.

---

## 7. Amendement daté — 2026-09-14 : le corpus Commons est construit, et il **ne suffit pas**

> Statut : **MESURÉ**. Outillage : `iot_audit/corpus/` (schéma, collecte, identité,
> annotation, métriques). Données brutes : `corpus/inventory.json`,
> `corpus/corpus.sqlite` (gitignored, images non redistribuées).

Le §1 autorise les photos internet et fixe la cible à **50–100 objets**. Cette
section rapporte ce qu'une collecte réelle produit, parce que l'écart change des
décisions du §4 et du §5.

### 7.1 Ce qui a été collecté

Source retenue : **Wikimedia Commons**, et non une place de marché. Raison
ordre : licence **machine-lisible** (427 CC BY-SA, 106 CC BY, 52 CC0, 38 domaine
public — **zéro licence problématique**), provenance complète et citable par URL,
API documentée donc reproductible.

| Étape | Volume |
|---|---|
| Catégories graines (5 catégories projet) | 40 |
| Parcours des sous-catégories (profondeur 2) | 862 titres uniques |
| Candidats après filtres (licence, MIME, résolution) | **739** |
| Rejetés, motif conservé | 123 (40 résolution, 35 logo/carte/diagramme, 21 licence « Attribution » nue, 14 MIME vidéo/PDF/GIF, 8 autres licences non libres) |

Les filtres de licence sont volontairement stricts : les licences **NC** sont
ecartées (livrable client), et toute valeur non vide de `Restrictions`
(marque ou personne) est un rejet dur.

### 7.2 Le résultat qui compte : **27 objets**, pas 50

L'extraction d'identité (marque + modèle) est lexicale, sur le titre, la
description et la catégorie Commons :

| Niveau | Objets | Images couvertes | Objets ≥ 2 photos |
|---|---|---|---|
| **strict** (marque **et** modèle) | **27** | 73 | 11 |
| relaxed (marque + ligne de produit) | 46 | 320 | 26 |
| aucune marque identifiée | — | 400 candidats écartés | — |

**Le mode strict est le seul qui alimente M1.** Le mode relaxed gonfle `n` en
créant des objets du type `amazon / <ligne de produit>` — 45 images pour un seul
objet. Ce n'est pas un objet identifiable : c'est un sac. Il est calculé pour
montrer l'écart, jamais pour publier une précision.

19 objets ont été **exclus avec motif écrit** (`annotate.NON_IOT`) :
`samsung sgh d880` (téléphone) et `netgear nic fa312` (carte réseau) étaient
rangés par l'extraction dans `smart_speaker` et `router_ap`. Une exclusion
documentée est une décision de méthode ; une correction silencieuse serait une
falsification du taux d'erreur.

### 7.3 Deux trous structurels, pas des accidents

| Dimension | Couverture | Conséquence |
|---|---|---|
| `smart_plug` | **0 objet** | M1 « toutes strates » ne couvre que **4 catégories sur 5** |
| strate `forum` | **0 objet** | **M3 est incalculable** : l'écart `official − forum` — présenté au §2 comme *le résultat principal du rapport sur la validité* — n'existe pas |
| strate `review` | 24 objets / 26 | domine écrasamment |
| strate `official` | 3 objets | cellule trop petite pour un IC utile |

Le trou `forum` a une cause précise et non réparable par plus de collecte sur
cette source : **Commons est majoritairement `review`-like**, et le vocabulaire
de démontage y est rare. L'écart `S1 − S3` exige des sources **hétérogènes**
(visuel constructeur d'un côté, forum de réparation de l'autre) ; un seul site
ne peut pas le produire.

`smart_plug` est vide pour une raison différente : `Category:Home automation`
(133 fichiers) apporte des armoires électriques, des distributeurs d'aliments
pour animaux et des modules KNX — pas des prises connectées.

### 7.4 La contrainte statistique, chiffrée

`minimum_n_for_target()` (`iot_audit/corpus/metrics.py`) donne le plus petit `n`
tel que la **borne inférieure** de Wilson ≥ 0,70 :

| si l'exactitude réelle est… | `n` nécessaire pour écrire « ≥ 70 % » |
|---|---|
| 0,75 | **306** |
| 0,80 | **77** |
| 0,85 | **30** |
| 0,90 | **15** |

**Ce tableau se lit dans les deux sens, et c'est son intérêt.** `n` n'est pas
fixé à l'avance : il dépend du résultat. Un corpus de 27 objets **suffit** si le
modèle atteint 0,85 — et **ne suffit pas** s'il plafonne à 0,75.

Conséquence opérationnelle : **la cible « 50–100 objets » du §1 n'est pas un
objectif en soi.** Le critère d'arrêt correct est *« mesurer à `n` courant, puis
étendre jusqu'à ce que la borne inférieure passe la cible »*. À `n` = 27 et
`p̂` = 0,815, l'IC est **[0,633 ; 0,918]** : la cible n'est pas atteinte.

### 7.5 Ce que le §5 doit corriger

| Métrique | Statut réel |
|---|---|
| M1 (objet, toutes strates) | calculable, **sur 4 catégories, `n` = 27** |
| M2 (`no_text`) | calculable, **instrument à trancher** (voir 7.6) |
| **M3 (écart S1 − S3)** | **incalculable** — strate `forum` vide |
| M4 (paires CPE) | calculable — 27 × 4 = **108 paires**, pas 200 |
| M5 (`confusable`) | **non trouvé** sur cette source |
| M6 (robustesse) | calculable — perturbations générées localement |
| M7 (InventedBrandRate) | calculable |
| M8 / M9 | calculables |

### 7.6 Décision ouverte : l'instrument `text_visible`

`text_visible` est **la** variable décisive du §1.2c, et rien n'est disponible
pour la mesurer proprement sur cette machine :

* `tesseract` est **absent** ; l'installer demande `apt`/`sudo` sur le poste de
travail ;
* `pytesseract`, `cv2`, `sklearn`, `rapidfuzz` sont absents de l'environnement.

Deux voies, à trancher :

| Voie | Force | Faiblesse |
|---|---|---|
| **Tesseract** (installer) | instrument **indépendant du VLM** ; c'est la seule mesure propre | dépendance système à installer |
| **Transcription par le VLM** | disponible immédiatement | **même modèle** que celui testé ⇒ instrument lié. Il mesure « l'information est-elle présente sous forme de texte », pas « un OCR tiers la lit » |

La question posée reste correcte dans les deux cas (« l'information nécessaire
est-elle disponible comme texte ? »), mais la seconde voie **sous-estime** le
phénomène si le modèle OCR mal, et l'écrire est nécessaire.

### 7.7 Ce que cet amendement ne dit pas

* **Aucun chiffre de précision n'est encore produit.** Le corpus existe ; la
  mesure n'a pas été lancée. Tout chiffre publié avant cette mesure serait faux.
* Les images de ce corpus sont des **photos réelles** (ce n'est plus le cas de
  l'échantillon `v16` de zabeth22, qui était des rendus PIL) — c'est le progrès
  principal de cette session.
* Le corpus est **`review`-dominant** : il mesure la reconnaissance en conditions
  réalistes, ce qui est la borne **honnête**, mais il ne permet **aucune**
  affirmation sur la contamination d'entraînement.
* Extensions non tentées : Wikidata (`P31` + `P18`) donnerait une identité
  **structurée** plutôt que lexicale — la meilleure source de vérité terrain —
  mais le service de requête a renvoyé `429` à répétition ; les places de marché
  et les sites constructeur couvriraient `official` mais ne sont ni licites ni
  reproductibles.

---

## 8. Résultats mesurés — 2026-09-14

> Statut : **MESURÉ**. Provenance complète dans
> `evidence/2026-09-14/corpus/provenance.json`. Le protocole est gelé **avant**
> la mesure (`measure.py` : manifeste figé, `text_visible` calculé **avant** de
> voir une prédiction).

**Dispositif.** `Qwen2.5-VL-7B-Instruct-GPTQ-Int4` (vLLM 0.29.0, torch
2.13.0+cu132, zabeth22) · corpus strict **26 objets / 73 images** · 63 % des
images sans texte produit lisible · `temperature=0`, graine 1234, **1 image par
requête** (aucun lot : le batching continu introduirait une dépendance à la
composition du lot) · prompt `sha256=26599423…`, schéma `sha256=5938283e…`
(le schéma JSON de `05` §1) · **73/73 requêtes réussies, 0 échec**.

### 8.1 Le chiffre, et ce qu'il n'autorise pas

> **Niveau × barème :** **objet** × `iot_audit.corpus.metrics`, règle de consolidation
> `conservative` (l'abstention compte comme une réponse). L'IC n'est valide qu'au niveau
> objet (§7.3) — c'est cette ligne qui fonde le chiffre principal du rapport.

| Métrique | k/n | p̂ | IC 95 % | « ≥ 70 % » ? |
|---|---|---|---|---|
| **M1 strict** (marque **et** modèle) | **8/26** | **0,308** | **[0,165 ; 0,500]** | **non** |
| M1 modèle seul (modal) | 10/26 | 0,385 | [0,224 ; 0,575] | non |
| M1 modèle correct sur ≥ 1 photo | 16/26 | 0,615 | [0,425 ; 0,776] | non |
| M1 catégorie seule (modal) | 21/26 | 0,808 | [0,621 ; 0,915] | non |

**Aucune cible du §5 n'est atteinte, et aucune ne peut être affirmée.** M1 tombe
à **0,308**, très en dessous de 0,70. Le CDC **ne peut pas** écrire
« précision ≥ 70 % » : la borne supérieure de l'IC elle-même vaut 0,500.

### 8.2 Le résultat principal : le système lit plus qu'il ne reconnaît

C'est la prédiction du §1.2c, et elle est **vérifiée** :

> **Niveau × barème :** **image** × `metrics`, **sans consolidation** — chaque photo
> compte pour elle-même. Ce n'est donc **pas** la même mesure que le §8.1 (objet), et
> les deux ne se comparent pas ligne à ligne.

| Au niveau **image** (n = 73) | texte lisible (n = 27) | **sans texte** (n = 46) |
|---|---|---|
| marque correcte | 0,593 | **0,065** |
| **modèle correct** | **0,704** | **0,304** |
| IC 95 % (modèle) | [0,515 ; 0,841] | [0,191 ; 0,448] |

**Le taux d'identification du modèle chute de 0,704 à 0,304 quand le nom du
produit n'est pas lisible — un facteur 2,3**, et les deux intervalles ne se
chevauchent pas. La reconnaissance dépend donc lourdement de la lisibilité du
texte. C'est exactement le risque que le §1.2c désigne comme *le contrôle à ne
pas manquer*.

**Mais le chiffre qui qualifie ce résultat est ailleurs :** la **catégorie** est
correcte dans **68/73 images (0,932)**. Le modèle sait donc **quel type d'objet**
il regarde — à 93 % — tout en échouant sur **lequel**. Sans texte, il reconnaît
« une enceinte connectée », pas « l'Amazon Echo Dot de 3ᵉ génération ».

Cette distinction change la lecture du projet : la sortie `category` est
**exploitable** ; la sortie `brand`/`model` ne l'est pas, et c'est précisément
celle dont le pipeline CPE→CVE dépend.

### 8.3 Un effet de bord du prompt, qu'il faut écrire

Sur **16 des 73 images** (critère **A**, celui du contrat), le modèle a rempli
`model` **correctement** tout en laissant `brand` **vide** et en se déclarant
`unidentifiable` :

> **Corrigé le 2026-09-29 (§20.3).** Cette ligne annonçait **17** sans nommer de
> critère. Sous **A** le compte est **16** ; sous **P** il vaut **17** — la seule
> bascule est `P-870HA` restitué pour un `p 870ha` attendu, c'est-à-dire l'artefact
> de séparateur déjà documenté au §15.6, pas une image de plus.

```
verite = apple / homepod      pred = brand ""  model "HomePod"  status=unidentifiable
```

La cause est connue et volontaire : le prompt du projet impose EF5
(« aucune marque inventée »), et le modèle obéit. Il **sait** ce qu'il voit et
refuse de s'engager sur la marque.

Consquence mesurée, et elle est générale : **`InventedBrandRate` = 0/19 = 0,000**
(cible < 5 %, largement tenue) **mais au prix d'un rappel très faible**. Le
taux d'auto-déclaration `unidentifiable` est de **0,740**. EF5 et le rappel sont
en **tension directe** ; le §3.2 de `05` traite ce cas comme un problème de
matcher, ce que ces données contredisent : c'est un arbitrage de **prompt**.
À traiter par une instruction explicite (« si le type est identifiable mais la
marque non, renvoyer la marque vide **et** le modèle »), pas par la résolution.

### 8.4 Stabilité et latence

> **Niveau × barème :** trois mesures hétérogènes dans un même tableau — l'**accord**
> (image *dans* l'objet × égalité de chaîne brute, moyenne des accords par objet), la
> **latence** (requête, en secondes) et `M7` (revue humaine, §14.4). Aucune de ces trois
> lignes n'est une exactitude objet ; l'accord n'est pas un barème.
>
> **Le `(A)` de ces deux lignes veut dire *accord*, pas le critère `A`** (§21.4). Mesuré :
> l'accord *modal brut* vaut `0,915` / `0,840` ; le *critère* A, lui, donnerait `0,405` /
> `0,144`. Deux conventions qui portent le même sigle dans un document qui définit `A`
> comme un critère de notation — la lecture est désormais sans ambiguïté.

| Mesure | Valeur | Cible | Verdict |
|---|---|---|---|
| Accord marque (`A` = *accord*) | 0,915 | — | élevé |
| Accord modèle (`A` = *accord*) | 0,840 | — | élevé |
| Latence p50 | **2,242 s** | — | — |
| **M8 latence p95** | **3,895 s** | < 10 s | **PASS** (marge 2,6×) |
| M8 max | 5,462 s | < 10 s | PASS |
| M7 `InventedBrandRate` | **0,000** (0/19) | < 0,05 | **PASS** |

**A élevé et verdict faux simultanément** : c'est la signature du
**consensus halluciné** que le §4.2 de `05` cherche précisément à détecter, et
elle est ici **majoritaire**. Un score de confiance fondé sur l'accord seul
afficherait « identifié, confiance 92 % » sur des objets que le système
identifie mal.

La latence p95 mesurée ici (**3,895 s**) est à comparer aux **0,417 s** de
`SPEC-infra` §V9 : ce dernier avait été obtenu sur une **image répétée**, donc
cache de préfixe chaud. La valeur honnête pour le flux réel (photo nouvelle à
chaque fois) est **≈ 2,2 s en médiane**. La cible < 10 s reste tenue, avec une
marge de **2,6×** et non de 24×.

### 8.5 Ce que ces résultats interdisent d'écrire

* **« Précision ≥ 70 % »** — non : M1 = 0,308, IC [0,165 ; 0,500].
* **« Précision en conditions terrain ≥ 50 % »** — non : mesuré à 0,308, et le
  corpus est web, pas terrain.
* **« Le système identifie les objets connectés »** — non : il identifie la
  **catégorie** (0,932) et lit le **texte** (0,704 quand il est lisible).
* **M3 (écart `official − forum`)** — toujours **incalculable** (§7.3).
* **Toute généralisation** : 26 objets, 4 catégories sur 5, corpus
  `review`-dominant, sujet à un **biais de sélection** (les objets photographiés
  par des contributeurs Commons ne sont pas un échantillon aléatoire du marché),
  et à la **contamination d'entraînement** du §1.2a que ce corpus **ne peut pas
  mesurer**.

### 8.6 La seule formulation défendable aujourd'hui

> *Sur un corpus de 26 objets connectés (73 photographies réelles sous licence
> libre, Wikimedia Commons), `Qwen2.5-VL-7B-Instruct-GPTQ-Int4` identifie
> correctement marque **et** modèle pour **8 objets sur 26** (p̂ = 0,31 ;
> IC 95 % [0,17 ; 0,50]). La catégorie de l'objet est correcte pour
> **21 objets sur 26** (p̂ = 0,81). Le taux d'identification du modèle passe de
> **0,70** (n = 27) lorsque le nom du produit est lisible à **0,30** (n = 46)
> lorsqu'il ne l'est pas, ce qui indique que le système s'appuie largement sur
> la lecture de texte plutôt que sur la reconnaissance visuelle. Aucune cible de
> précision du CDC n'est atteinte.*

### 8.7 Suite : ce que le critère d'arrêt impose

§7.4 s'applique. Pour avoir le droit d'écrire « ≥ 70 % » à `p̂` = 0,80 il
faudrait **n = 77** objets, et le `p̂` observé est **0,31** — pas 0,80. **Aucun
volume de corpus ne rattrape un `p̂` de 0,31** : à `p̂` = 0,308, la borne
supérieure de l'IC vaut 0,50 même à `n` = 26.

**La collecte n'est donc pas la prochaine étape. Le prompt et le contrat de
sortie le sont** (§8.3 a identifié un levier gratuit : 17 images où le modèle
connaît la réponse et ne la donne pas). Étendre le corpus vient **après** avoir
mesuré l'effet de ce levier, sinon on finance un intervalle de confiance autour
d'un chiffre faux.

---

## 9. Bancs étendus — 2026-09-14 (soirée)

> **365/365 requêtes, 0 échec** : 73 base + 292 perturbations (4 types).
> Évidence : `evidence/2026-09-14/corpus/bench-zabeth22.json`.
> Perturbations générées **sur le nœud** (Pillow 12.3.0) : aucune image ne
traverse la liaison SSH.

### 9.1 Défaut d'intégrité trouvé dans ma propre mesure, et corrigé

La première exécution nommait les fichiers téléchargés par `image_id[:80]`.
**5 `image_id` du corpus dépassent 80 caractères**, et tronquer faisait
collisionner **3 photos distinctes d'Echo Dot sur un seul fichier** — donc **5
prédictions calculées sur la mauvaise image**.

Ce qui rend ce défaut dangereux : **il est invisible dans la sortie**. Le run
rapportait `ok=73 fail=0`, tous les lots réussissaient, les latences étaient
normales. Il n'a été détecté qu'en comparant le **nombre de fichiers sur le
disque (70)** au **nombre de lignes de résultat (73)**.

Corrigé par hachage du `image_id` comme nom de fichier, corpus re-mesuré. **Le
chiffre principal est inchangé** (8/26 avant et après) : l'objet touché
(`amazon__echo_dot`) était déjà un échec. Mais la mesure est désormais valide, et
la leçon est générale — *un compteur de succès ne vérifie pas l'intégrité de ce
qui a été mesuré.*

### 9.2 Le résultat le plus net : la catégorie est **robuste**, le modèle non

La comparaison des deux exécutions corrige et précise le §8.2 :

> **Niveau × barème :** **image** × `metrics`, sans consolidation — identique au §8.2,
> mais sur l'exécution corrigée (§9.1). À ne pas comparer au §8.1 (objet).

| au niveau image | texte lisible (n = 27) | **sans texte** (n = 46) |
|---|---|---|
| marque correcte | 0,593 | 0,065 |
| modèle correct | **0,704** | **0,304** |
| **catégorie correcte** | **0,926** | **0,935** |

**La reconnaissance de catégorie est insensible à la présence de texte** (0,926
contre 0,935 — les intervalles se recouvrent largement), **alors que
l'identification du modèle s'effondre** (facteur 2,3).

Interprétation, et elle est favorable au projet : le modèle **voit** réellement
la forme d'un routeur, d'une prise ou d'une enceinte. Ce qu'il ne peut pas faire
sans texte, c'est passer de *« c'est une enceinte connectée »* à *« c'est un
Echo Dot de 3ᵉ génération »*. **Le prompt de `05` §1 est donc bien calibré sur la
catégorie et mal sur l'identité** — ce qui déplace le problème du corpus vers le
contrat de sortie.

### 9.3 M6 — robustesse : un seul point de rupture, et c'est le flou

Perturbations de `§4.4`, intensité nominale, sur les 73 images :

> **Niveau × barème :** **objet** × `metrics`, règle `conservative`. Δ = base − variante,
> donc une **baisse** s'écrit positive. Le §10.5 a les mêmes perturbations au niveau
> **image** sous un autre barème : les deux tableaux ne sont **pas** interchangeables.

| variante | M1 strict | Δ | modèle seul | Δ | verdict (cible ≤ 15 pts) |
|---|---|---|---|---|---|
| base | 8/26 = 0,308 | — | 10/26 = 0,385 | — | — |
| recadrage 85 % | 6/26 = 0,231 | +7,7 pt | 9/26 = 0,346 | +3,8 pt | **OK** |
| rotation +10° | 7/26 = 0,269 | +3,8 pt | 10/26 = 0,385 | 0,0 pt | **OK** |
| luminosité ×1,30 | 8/26 = 0,308 | 0,0 pt | 11/26 = 0,423 | **−3,8 pt** | **OK** |
| **flou gaussien r = 3** | **2/26 = 0,077** | **+23,1 pt** | 5/26 = 0,192 | +19,2 pt | **DÉPASSÉ** |

> **Corrigé le 2026-09-29 (§20.3).** La colonne « modèle seul » annonçait
> `6/26 = 0,231` (Δ +15,4 pt) au flou. Le recalcul canonique donne **`5/26 = 0,192`
> (Δ +19,2 pt)**. Les quatre autres lignes de cette colonne sont exactes. Le
> **verdict ne change pas** (le flou reste le seul point de rupture, et il l'est
> davantage), mais le chiffre, si.

**Le système est robuste au cadrage, à l'orientation et à l'exposition — et
fragile au flou de mouvement.** Un rayon 3 est modéré (léger bougé à main levée,
pas un flou artistique) et coûte **23 points**, soit les trois quarts de la
précision restante.

C'est directement actionnable, et cela contredit partiellement le §6.1 : la
consigne « photo nette » n'est pas une commodité d'ergonomie, c'est **la
condition de validité du système**. Une photo prise sur le vif, à la main, dans
un local technique mal éclairé, tombe exactement dans le régime dégradé. Le
message utilisateur du §5 de `03` (« Plusieurs objets détectés… ») mérite un
pendant : *« Photo floue — reprenez en stabilisant l'appareil. »*

### 9.4 M9 — rejeu : reproductibilité parfaite

> **Niveau × barème :** **image** × comparaison brute de deux exécutions — il n'y a pas
> de barème, on compare les sorties entre elles.

| Mesure | Valeur | Cible | Verdict |
|---|---|---|---|
| Accord catégorie (2 exécutions) | **73/73 = 1,000** | 100 % | **PASS** |
| Accord tuple (marque, modèle) | **73/73 = 1,000** | ≥ 95 % | **PASS** |

**73/73 sur les deux axes**, sans un seul écart. À `temperature=0`, graine fixée,
**une image par requête**, la sortie est **exactement reproductible**. C'est la
preuve qu'ENF5 est satisfaite — et la raison pour laquelle l'absence de batching
(§8) était le bon choix : en lot, cette garantie aurait disparu.

### 9.5 Tableau consolidé de toutes les métriques mesurées

> **Niveau × barème, ligne à ligne :** `M1`/`M1b`/`M1c` = **objet** × `metrics`
> (`conservative`) ; `M2`/`M2b` = **image** × `metrics` ; `M6` = objet × `metrics` ;
> `M3` = incalculable ; `M7` = revue humaine ; `M8` = requête ; `M9` = image ×
> comparaison brute. Un tableau « consolidé » dont les lignes ne sont pas au même niveau
> est exact ici, mais ne doit pas être lu comme une seule mesure.

| # | Métrique | Valeur | Cible | Verdict |
|---|---|---|---|---|
| M1 | exactitude objet, strict | **8/26 = 0,308**, IC [0,165 ; 0,500] | ≥ 0,70 | **ÉCHEC** |
| M1b | exactitude objet, modèle seul | 10/26 = 0,385, IC [0,224 ; 0,575] | — | — |
| M1c | exactitude objet, catégorie | 21/26 = 0,808 | — | — |
| M2 | `no_text` (modèle, image) | **0,304**, IC [0,191 ; 0,448] | publié | chiffre honnête |
| M2b | `with_text` (modèle, image) | 0,704, IC [0,515 ; 0,841] | — | facteur 2,3 |
| M3 | écart `official − forum` | **incalculable** | publié | **strate vide** |
| M6 | robustesse toutes perturbations | **1 sur 4 DÉPASSÉ** (flou) | ≤ 15 pt | **ÉCHEC partiel** |
| M7 | `InventedBrandRate` | **0/19 = 0,000** | < 0,05 | **PASS** |
| M8 | latence p95 | **3,895 s** | < 10 s | **PASS** |
| M9 | accord de rejeu | **73/73 = 1,000** | 100 % / ≥ 95 % | **PASS** |

**Trois cibles sur sept sont atteintes.** Les deux échecs (M1, M6-flou) et la
métrique incalculable (M3) sont, chacun, un livrable du rapport : ils disent au
jury ce que le système ne sait pas faire, avec un chiffre.

### 9.6 Sources essayées et refusées (traçabilité des tentatives)

| Source | Résultat | Cause |
|---|---|---|
| Commons API | partiellement exploitable | 429 avec `Retry-After: 48 s` après usage intensif |
| Wikidata `P31`+`P18` | **refusé** | 429 sur toute requête réelle (requête triviale acceptée) |
| **Openverse** (agrégateur CC : flickr + wikimedia) | **refusé** | **défi Cloudflare** « Just a moment… » sur client non-navigateur |
| Places de marché / sites constructeur | non tentées | ni licites ni reproductibles (§3) |

Openverse restait la piste la plus prometteuse — il apporte la **diversité de
sources** qui manque pour combler la strate `forum`, et ses titres portent les
références produit (`« TP-Link Archer C7 AC1750 Dual Band… »`). Blocage
contournable **avec un jeton d'API** (compte gratuit) plutôt qu'en forçant le
défi. À reprendre avec un jeton.

> **Filtre de licence Openverse, à retenir :** sur un échantillon de 20
> résultats, **14 étaient `by-nd` (NoDerivatives)** et 1 `by-nc-sa`. Or le §4.4
> **crée des œuvres dérivées** (recadrage, rotation, flou) : une image `by-nd`
> **ne peut pas** alimenter le banc de robustesse, même si sa lecture est libre.
> Le filtre doit donc être `by` / `by-sa` / `cc0` / `pd` **strictement**.

## §10 — Avenant du 2026-09-14 (soir) : expansion, effet prompt v2, courbe M6

**MESURÉ — zabeth22, serveur démarré puis arrêté (38 MiB restant, 0 processus).**
Prompts : v1 `sha256=26599423…`, v2 `sha256=e01e6db2…` ; `temperature=0`, graine 1234,
1 image/requête, manifeste identique entre les deux passes (128 octets de texte près).

### §10.1 Corpus étendu

48 objets / 144 images / 5 catégories (dont `smart_plug` : 5 objets, 12 photos) /
3 strates (dont `forum` : 11 objets, 12 images). Méthodes ajoutées : recherche
plein-texte (vocabulaire teardown/produit), Openverse API avec licence vérifiée côté
client (`by-nd` refusé : les perturbations §4.4 créent des œuvres dérivées),
**annotation manuelle** des identités (`identity_source='manual'`, révisable, supérieure
au lexique). Contaminants détectés et exclus avec motif : 2 photos d'archéologie
captées par le lexique de marques.

### §10.2 Le chiffre redescend — l'échantillon initial était flatteur

> **Niveau × barème, ligne à ligne (§21.3, mesuré).** Ce tableau ne mélange pas deux
> barèmes : il en mélange **trois** combinaisons. La ligne `catégorie` est en `metrics`
> (`115/144`) et **non** en A (`114/144`) — c'est la seule ligne du §10 où le barème change.

| critère | niveau | barème | k/n | p̂ | IC 95 % |
|---|---|---|---|---|---|
| M1 strict (marque+modèle) | image | `audit-grading` A | 11/144 | 0,076 | [0,043 ; 0,132] |
| modèle seul | image | `audit-grading` A | 32/144 | 0,222 | [0,162 ; 0,297] |
| catégorie | image | **`metrics`** | 115/144 | 0,799 | [0,726 ; 0,856] |
| objet, modèle correct sur ≥1 photo | objet | `audit-grading` A | 10/48 | 0,208 | [0,117 ; 0,343] |

Les 71 nouvelles images (cartes nues, vues de dos, prises producteur) sont des cas
difficiles **réels** ; les 73 initiales étaient des angles produit lisibles. La cible
« ≥70 % » du CDC reste **inatteignable en l'état du modèle**, sur corpus élargi.

### §10.2 bis La comparaison re-dérivée à périmètre **et** barème constants

Le §8.1 (26 objets) est en **objet × `metrics`** ; les deux premières lignes du §10.2
sont en **image × A**. Les comparer directement mesure donc deux choses à la fois — le
**corpus** et la **convention** —, ce que le §20.5 a relevé. Refait sur les neuf
combinaisons mesurables (`probe-niveau-bareme.py`) :

| figure | niveau × barème | 26 objets (73 img) | 48 objets (144 img) | sens |
|---|---|---|---|---|
| M1 strict | objet × `metrics` `conservative` | 8/26 = 0,308 [0,165 ; 0,500] | 8/48 = 0,167 [0,087 ; 0,296] | baisse |
| M1 | objet × `metrics` `answered` | 12/26 = 0,462 [0,288 ; 0,645] | 13/48 = 0,271 [0,166 ; 0,410] | baisse |
| M1b modèle | objet × `metrics` `answered` | 16/26 = 0,615 [0,425 ; 0,776] | 21/48 = 0,438 [0,307 ; 0,577] | baisse |
| objet, modèle ≥ 1 photo | objet × `audit-grading` A | 7/26 = 0,269 [0,137 ; 0,461] | 10/48 = 0,208 [0,117 ; 0,343] | baisse |
| strict | image × `audit-grading` A | 7/73 = 0,096 [0,047 ; 0,185] | 11/144 = 0,076 [0,043 ; 0,132] | baisse |
| modèle | image × `audit-grading` A | 23/73 = 0,315 [0,220 ; 0,429] | 32/144 = 0,222 [0,162 ; 0,297] | baisse |
| catégorie | image × `metrics` | 68/73 = 0,932 [0,849 ; 0,970] | 115/144 = 0,799 [0,726 ; 0,856] | baisse |
| strict | image × `metrics` | 16/73 = 0,219 [0,140 ; 0,327] | 20/144 = 0,139 [0,092 ; 0,205] | baisse |
| modèle | image × `metrics` | 33/73 = 0,452 [0,343 ; 0,566] | 47/144 = 0,326 [0,255 ; 0,407] | baisse |

**Ce qui tient, et ce qui était trop fort.** Ce qui **tient sous les neuf combinaisons** :
la valeur centrale **baisse**, et **aucune** combinaison ne place la borne inférieure près
de la cible de 0,70 — au mieux `0,165` sur le petit corpus, et elle **baisse** elle aussi.
Ce qui **n'est pas démontré** : que l'échantillon initial était *flatteur* au sens
statistique. **Aucun des neuf intervalles ne se sépare** — le corpus étendu ne
contredit pas le petit, il en donne une mesure plus basse et plus précise.

> Formulation défendable, et c'est celle à retenir : *le chiffre obtenu sur le corpus
> initial n'était pas représentatif — il baisse sous les neuf combinaisons (niveau ×
> barème) —, mais la baisse n'est pas significative à ces `n`.* Écrire « l'échantillon
> initial était flatteur » supposait une séparation que les données ne portent pas.

### §10.3 M3 calculé — les teardowns sont hors de portée visuelle

> **Niveau × barème :** **image** × `audit-grading` **A**, run **v1**. `strict` = marque ET
> modèle. La strate `review` porte **129** images (`11/129 = 0,085` · `32/129 = 0,248`) ;
> l'agrégat du §10.2 est sur 144.

| strate | strict | modèle |
|---|---|---|
| review | 0,085 | 0,248 |
| forum (teardown) | **0,000** (0/12) | **0,000** |
| official | 0,000 (0/3) | 0,000 |

Une carte nue n'a pas de marque à lire : ce n'est pas une faiblesse du modèle mais
une **absence d'information dans l'image**. Conséquence pipeline (docs/05) : le
routage des photos de démontage vers d'autres signaux (silkscreen OCR → CPE, MAC
OUI) n'est plus une optimisation, c'est la seule voie.

### §10.4 Effet prompt v2 — expérience contrôlée, critère constant

> **Niveau × barème :** **image** × `audit-grading` **A**, deux prompts (v1, v2) — c'est le
> « critère constant » du titre. Les lignes `unidentifiable` sont des sorties brutes.

| sous-groupe (modèle seul) | v1 | v2 |
|---|---|---|
| toutes images | 32/144 = 0,222 [0,162 ; 0,297] | **62/144 = 0,431 [0,353 ; 0,512]** (IC disjoints) |
| sans texte lisible | 0,155 | **0,423** |
| avec texte | 0,362 | 0,447 |
| auto-déclaration `unidentifiable` | 114/144 (79 %) | 26/144 (18 %) |

> **⚠️ Deux cellules de ce tableau sont périmées** (relevé au §13.2 bis, revérifié au
> §20.3) : la colonne v2 vaut **`63/144 = 0,438`**, pas `62/144 = 0,431`, et le
> `no_text` v2 vaut **0,433** (42/97), pas `0,423` (41/97). Les deux écarts sont
> d'**une image**, cohérents entre eux. La ligne v1 est exacte. Les chiffres v2 du
> §14.2 et du §14.1 (recalculés) utilisent déjà les valeurs gelées.

**Contrôle EF5 passé sous v2** : 9 marques « hors lexique » examinées une à une —
toutes des lectures **correctes** de marquages réels (MediaTek = SoC de l'Echo Dot
lu sur la carte ; `FRITZ!`→avm, `nest`→google = synonymes). Taux de marque inventée
après revue : **0/52**. v2 est **adopté comme prompt de mesure** ; v1 est conservé
comme témoin de reproductibilité.

### §10.5 Courbe M6 dose-réponse (v1, 73 images d'origine)

> **Niveau × barème :** **image** × `audit-grading` **A**, run v1 — les 7 points sont
> reproduits par `probe-courbe-M6-image.py` (tous `OK`). Au niveau **objet** sous `metrics`
> la même expérience donne d'autres valeurs : c'est le §9.3, et **les deux tableaux ne
> sont pas interchangeables**.

| perturbation | strict | modèle |
|---|---|---|
| base | 0,096 | 0,315 |
| rotation +5° | 0,068 | 0,274 |
| luminosité ×0,7 | 0,082 | 0,260 |
| recadrage 70 % | 0,082 | 0,219 |
| flou r=2 | 0,068 | 0,274 |
| **flou r=5** | 0,000 | **0,082** |
| **flou r=8** | 0,000 | **0,041** |

Le flou ne franchit pas un seuil : il s'effondre en deux paliers (r=2→r=5 : −19 pt).
« Photo nette » (§6.1) est une **condition de validité**, pas une commodité.

### §10.6 M9

73/73 sorties identiques sur les images communes (4ᵉ exécution consécutive).

### §10.7 Incidents corrigés

429 Wikimedia sur les re-téléchargements → `ship-stream.sh` (flux unique, sha256
vérifié) ; endpoint 127.0.0.1 du runner vs IP LAN du serveur → `VLLM_ENDPOINT` en
env ; `build_objects` écrasait les identités manuelles → corrigé (annotation
manuelle prioritaire, journalisée) ; `smart_plug` vide → récupération Verisure/EDP
+ identités manuelles.

## §11 — Avenant : M4 mesuré (matcher CPE), V12 prouvé (egress)

### §11.1 M4 — le banc existe, les cibles ne sont pas atteintes, la cause est documentée

Dictionnaire CPE complet ingéré : **1 838 235 entrées** (NVD API 2.0, 920 pages,
sha256 `f5df2cc8…`, provenance en base). Banc : 68 paires bruitées (§4.2) issues
des 50 objets, matcher à étages docs/05 §2.

Quatre défauts du banc lui-même trouvés et corrigés **par mesure** (historique
conservé) : inflation ×1,25 du repli difflib (références proches indiscernables) ;
intersection seule notée (requête sur-ensemble → produit correct rejeté à 0,41) ;
marque notée contre produit (amazon_key battait echo_dot) ; LIMIT SQL sur lignes de
version (p_870ha absent du pool). Après corrections :

| issue | part | lecture |
|---|---|---|
| auto top-1 correct | **0,324** | décision machine |
| réserve top-1 correct | 0,044 | file humaine, produit en tête |
| ambigu, attendu visible | 0,191 | file humaine |
| no-match pur | 0,118 | divergence de nommage |
| absent du pool | 0,324 | couverture CPE |

Résolu opérationnellement 0,368 · top-3 0,559 — **cibles 0,80/0,92 non atteintes**.
Trois causes structurelles mesurées : couverture IoT du CPE (`hs110` absent,
`wemo_mini` absent), deux conventions de nommage sans table d'alias
(`p_870ha`↔`p-870h-51`), marge de décision volontairement conservatrice (jamais de
devinette). **Le levier suivant est une table d'alias manuelle (~50 entrées), pas un
réglage de score.**

M4b (silkscreen) : marquages puce → CPE **2/5 auto-résolus à égalité exacte**
(`mediatek/mt8163`, `mediatek/mt6625`) ; les 3 échecs sont des absences du
dictionnaire. La voie de rattrapage des teardowns est réelle et bornée par la
couverture, pas par le mécanisme.

### §11.2 V12 — preuve directe, restitution propre

nftables déjà présent (1.1.3-1). Ruleset runtime uniquement (output policy drop ;
LAN 172.26/16, DNS campus, lo ; établi/connexe), homme-mort 300 s + script de
rollback avant toute application. Mesuré : nvd.nist.gov / huggingface.co / pypi.org
en timeout ; DNS OK ; LAN autorisé ; SSH entrant non perturbé. Restitution :
`nft flush ruleset` → HTTP 200 vérifié. **V12 : PASS.** Deux incidents d'opération
(PATH /usr/sbin ; course timer + vérification sans privilège) documentés au
rapport 16 — le second a produit des règles dupliquées, corrigées par flush +
application unique.

> **Addendum du 2026-09-29 — `nft flush ruleset` n'est plus une restitution propre.** La commande citée
> ci-dessus est exactement celle qui, le 2026-09-16, a détruit les **91 règles nftables d'un tiers**
> (Tailscale) sur **zabeth23** — incident diagnostiqué, réparé le jour même, documenté dans
> `cahiers/NOTE-CONFORMITE-z23-tailscale.md`. Or depuis le **2026-09-24 à 21h07**, **zabeth22 héberge le même
> co-locataire** : mêmes 12 chaînes `ts-*`, mêmes 91 règles, `/etc/resolv.conf` réécrit par `tailscaled`.
> **Rejouer la procédure de restitution décrite ici sur zabeth22 reproduirait l'incident.** Les outils V12 du
> 2026-09-29 n'utilisent plus aucun flush global : table `inet v12` dédiée, chargement **atomique** en un
> seul `nft -f`, suppression de cette seule table. Vérifié après essai sur z22 : `tables inet v12 = 0`,
> **12 chaînes `ts-*` intactes**. Détail et mesures : `evidence/2026-09-28/risk-probes/SUMMARY.md` §20.6.

## §12 — Avenant : le canal de lecture est mesuré (2026-09-15)

**MESURÉ — calcul local, `~/iot-audit/corpus/ocr-validation/`.** Rapport complet et
défendable : `~/zabeth22-vllm-repair/20-OCR-PRECISION.md`. Évidence :
`evidence/2026-09-15/ocr-precision/`.

Le SPEC portait depuis la session 2 : *« no OCR-accuracy figure exists »*. Elle
existe. Elle vient d'une vérité terrain **humaine externe**, pas de nous :
COCO-Text (**600** photographies entières, **2 604** mots, annotations **CC BY
4.0**) pour le canal tel que le projet l'utilise (détection + reconnaissance),
TextOCR (1 387 découpes, annotations **MIT**, images **CC BY 4.0**) pour la
reconnaissance seule.

### §12.1 Le chiffre du canal

| mesure | valeur | IC 95 % |
|---|---|---|
| rappel mot, scène complète (R_token) | **0,351** (913/2604) | [0,322 ; 0,379] · bootstrap **images** |
| rappel mot, variante R_flat (sensibilité) | 0,325 (847/2604) | [0,296 ; 0,354] |
| précision (plancher, cf. §12.5) | 0,513 (879/1713) | — |
| photographies avec ≥ 1 mot lu | **0,565** (339/600) | [0,525 ; 0,604] |
| photographies lues intégralement | 0,157 (94/600) | — |
| reconnaissance seule, découpe isolée | **0,657** (909/1384) | [0,631 ; 0,681] · CER 0,234 |

Par strate de forme — `alnum` est la forme des références de modèle :
`short` (< 3 car.) **0,224** · `alpha` **0,398** · `alnum` **0,402**.

**Répliqué hors échantillon.** L'étalon ayant été doublé (300 → 600 images), il a
été découpé en deux moitiés disjointes : **0,350** (IC95 [0,307 ; 0,394]) contre
**0,352** ([0,315 ; 0,389]) — écart **0,2 point**, intervalles recouvrants. Le
chiffre regroupé est publiable, et la dispersion entre moitiés *est* l'incertitude
qui compte.

**Le rappel suit la proéminence**, et c'est la clé de lecture de ce chiffre.
L'étalon compte *tous* les mots annotés (enseignes de fond, texte minuscule),
alors que le drapeau cherche *une* chaîne proéminente. Par quartile de surface de
boîte : **0,198** → **0,316** → **0,406** → **0,482** (monotone). Le **mot le plus
proéminent de chaque image** donne **0,392** (IC95 [0,352 ; 0,428]) : c'est le
chiffre comparable au cas d'usage du projet, pas le rappel global.

### §12.2 Un effet à connaître avant d'optimiser

Sur les **mêmes 120 découpes**, la chaîne complète obtient **0,100**
d'exact-match là où la reconnaissance seule obtient **0,625** (IC95 [0,536 ; 0,707]).
**Un détecteur appliqué à un mot déjà isolé détruit cinq sixièmes de la
précision.** Conséquence pratique : ne jamais « accélérer » le corpus en découpant
les zones de texte avant de les passer au moteur.

### §12.2 bis Le chiffre appartient au moteur, pas à la tâche

Le 0,351 repose sur un seul moteur (PP-OCR). Un second moteur d'une **autre famille**
(`onnxtr` = docTR, DBNet + CRNN) a été mesuré sur les **mêmes 150 images** :

| moteur | rappel R_token | IC95 |
|---|---|---|
| 1 — PP-OCR (le moteur du projet) | 0,329 | [0,276 ; 0,386] |
| 2 — docTR | **0,411** | [0,334 ; 0,495] |
| différence appariée (1 − 2) | **−0,083** | [−0,143 ; −0,020] → **significative** |

Contrôle de confusion (les jetons parasites d'un caractère pouvaient gagner par
accident, et 28 % des mots annotés font < 3 caractères), restreint aux mots
**≥ 3 caractères** : **0,371** contre **0,449**, différence [−0,130 ; −0,025].
L'avantage **survit** au contrôle. Sur découpes, en revanche, docTR ne trouve rien
(exact-match **0,000** contre 0,100) : le « ne pas pré-découper » du §12.2 tient
donc sur deux architectures.

**Conséquence pour le projet** : le drapeau sous-détecte parce que *son moteur*
sous-détecte. Un meilleur moteur trouverait plus d'identités lisibles, retirerait
des images de la strate `no_text`, et ferait **baisser** le chiffre `no_text`
publié. La conclusion critique du §8.2 (*« le système lit plus qu'il ne
reconnaît »*) n'est donc pas un artefact d'un moteur faible : **elle s'accentue**
si le moteur s'améliore.

### §12.3 Correction à porter au §9.2 et au §10.2 — et elle va dans le sens du projet

Sur le corpus (144 photos, 48 objets), l'identité est récupérable par OCR seul
dans **47/144 = 0,326**, IC 95 % **[0,230 ; 0,462]** — bootstrap par **objets**
(§4.1 ; l'IC image [0,255 ; 0,407] n'est pas utilisé). Un second canal de lecture
indépendant du moteur OCR (transcription `visible_text` du VLM) recoupe 144
décisions : accord **0,896**, **κ = 0,762**.

**Ce que le drapeau manque, estimé et non borné grossièrement** — estimateur de
capture–recapture de Chapman sur les deux lecteurs (n1 = 47, n2 = 46, m = 39) :

```
images à identité lisible, estimées : 55,4   (se 1,39 ; IC95 [52,7 ; 58,1]) sur 144
rappel OCR 0,848   ·   rappel VLM 0,830
faux négatifs du drapeau : ≥ 0,152 des lisibles  =  0,058 des images
```

Le sens du biais est connu et **publié** : les deux lecteurs lisant du texte, le
recouvrement observé surestime ce que prédirait l'indépendance, donc `N̂` est
sous-estimé et le taux de faux négatifs est un **minorant**. Bande de sensibilité
(recouvrement 36 → 42) : **[0,152 ; 0,216]**. La dépendance positive pousse vers le
haut, jamais vers le bas.

La strate `no_text` étant censée ne contenir que des images **sans** identité
lisible, les images concernées sont plus **faciles** :

> le chiffre `no_text` du §9.2 (**0,304** au niveau image) et le taux de réussite
> du §10.2 (0,155 en v1) sont des **majorants** de la reconnaissance visuelle, pas
> des mesures. Aucun chiffre publié ne change ; la **formulation** doit changer
> (« ≤ 0,304 »), et `text_visible` doit être décrit comme un instrument à faux
> négatifs.

Deuxième correction, dans le même sens : la lisibilité globale du corpus est
**0,385** (IC95 [0,366 ; 0,404], estimateur de Chapman), pas 0,326. Le 0,326 est
un minorant.

**Causes des 15 désaccords, classées sur les textes stockés** (aucune image
relue, donc reproductible depuis l'évidence seule) : 6 « VLM transcrit un autre
texte », 4 « OCR ne lit rien du tout », 3 « OCR lit un texte sans rapport »,
2 « VLM ne transcrit rien ». **Zéro quasi-lecture** : quand le drapeau échoue, il
échoue complètement — ses erreurs sont des échecs de *lecture*, pas d'*appariement*,
et aucun réglage de seuil ne les corrigerait. Les 15 cas sont listés nommément
dans `results/corpus-legibility.json`.

### §12.4 §6.1 — ce qui reste non satisfait, chiffré

Le cahier des charges §6.1 demande **la moitié** des photographies en conditions
propres (studio, fond neutre) et l'autre moitié en conditions terrain.
Opérationnalisé par la provenance (`official` = propre ; `review` + `forum` =
terrain) :

| conditions | images | lisibles | p̂ |
|---|---|---|---|
| **propre** | **3** | 1 | 0,333 |
| **terrain** | **141** | 46 | 0,326 |

**Le corpus est à 98 % en conditions terrain ; l'arm « propre » compte 3 images.**
La comparaison propre/terrain n'est pas supportable et le §6.1 **n'est pas
satisfait** sur ce point.

La cause est **structurelle à la source**, et `commons.py` l'annonçait : Commons
refuse la plupart des contenus promotionnels, donc les visuels marketing
y sont rares. Compléter l'arm propre demande **une autre source sous licence
propre** (kits presse constructeur, Openverse) — une décision de collecte, pas une
réanalyse. Fabriquer cet arm à partir de Commons donnerait l'illusion d'un §6.1
fermé.

### §12.5 Ce que cet avenant ne dit pas

Le 0,351 est mesuré sur de la **scène naturelle** (enseignes, emballages), pas sur
des étiquettes d'objets connectés : il mesure le canal, pas le canal *sur ce type
d'objet* — le gradient de proéminence du §12.1 chiffre le transfert, il ne le
prouve pas. La précision est un **plancher** (COCO-Text n'annote que le lisible).
Deux moteurs mesurés (PP-OCR, docTR), pas deux familles complètes : un troisième
(EasyOCR) demanderait torch, non installé. Enfin, la bande [0,152 ; 0,216] n'est
pas un intervalle de confiance mais une **bande de sensibilité** à une hypothèse
non testable — elle est plus honnête que l'IC de Chapman, qui suppose
l'indépendance et est donc trop étroit.

## §13 — Avenant : le drapeau bascule sur un autre moteur, et le §12.2 bis est réfuté (2026-09-15)

**MESURÉ — calcul local, `~/iot-audit/`.** Rapport complet :
`~/zabeth22-vllm-repair/21-FLAG-SWAP.md`. Évidence :
`evidence/2026-09-15/flag-swap/`. Corpus 144 images / 48 objets, prompt v2
(`sha256=e01e6db2…`), **aucun nœud touché**.

Le §12.2 bis avait **pré-enregistré** une prédiction directionnelle. Elle a été
testée en basculant le drapeau `text_visible` sur docTR — moteur d'une autre
famille, meilleur sur l'étalon externe — **critère lexémique inchangé**.

### §13.1 Les deux moteurs ne se trompent pas sur le nombre, mais sur lesquelles

| | PP-OCR (publié) | docTR |
|---|---|---|
| `with_text` (drapeau) | **47**/144 | **40**/144 |
| caractères extraits (moyenne / médiane) | 72,1 / 8 | **223,5** / 33 |
| images sans texte lu | 39 | **24** |
| lisibles estimées `N̂` (Chapman) | 55,4 | 55,7 |
| **faux négatifs du drapeau** | **0,152** [0,152 ; 0,216] | **0,282** [0,282 ; 0,346] |
| accord / `κ` au canal VLM | 0,896 / 0,762 | 0,861 / 0,669 |

Accord des deux drapeaux : **131/144 = 0,910** (37 les deux, **10 PP-OCR seul**,
**3 docTR seul**, 94 aucun). docTR lit **trois fois plus** de texte et échoue sur
les **marques courtes et stylisées** (`'D-Link'` → `'1 | à'` ; `'HomePod'` →
`'TACE | ))) | A | (( | S | NeorT'`), tandis que ses 3 gains sont réels et tous
des **marques** (il sépare `AMAZON` de `EU` que PP-OCR collait en `AMAZONEUL`).

### §13.2 Le chiffre `no_text` monte, et l'écart lecture/reconnaissance change de signe

Barème gelé **A** (`audit-grading.py`), niveau image (définition publiée), prompt
v2 :

| drapeau | `no_text` n | modèle | `with_text` n | modèle | écart |
|---|---|---|---|---|---|
| `ppocr` (publié) | 97 | **42/97 = 0,433** [0,339 ; 0,532] | 47 | **21/47 = 0,447** [0,314 ; 0,588] | **+1,4 pt** |
| **`doctr`** | 104 | **47/104 = 0,452** [0,360 ; 0,548] | 40 | **16/40 = 0,400** [0,264 ; 0,554] | **−5,2 pt** |
| `union` | 94 | 42/94 = 0,447 [0,350 ; 0,547] | 50 | 21/50 = 0,420 [0,294 ; 0,558] | −2,7 pt |

L'asymétrie qui produit le basculement : sur les **10 images** qui sortent de
`with_text`, **5 sont modèle-correctes** (0,50) ; sur les **3** qui y entrent,
**0** (0,00). Cinq correctes entrent dans `no_text`, aucune n'en sort — et cela
suffit à retourner l'écart. Une strate `no_text` **plus facile** que `with_text`
est la signature d'une **contamination** : des images lisibles y ont fuité.

**Le signe du déplacement est le même sur les quatre barèmes** (`A`/`B`/`C`
+0,019 ; `D` +0,021), et le barème **strict** suit (`no_text` 2/97 → 6/104).
L'`union`, elle, déplace dans le **bruit** (+0,014) et **laisse le strict
intact** (2/97). Sous v1 l'effet va dans le même sens : l'écart passe de
**+20,7 pt** à **+14,2 pt**.

### §13.2 bis Une correction plus grave que le basculement : c'est v2 qui a effacé l'écart

| prompt | `no_text` | `with_text` | écart |
|---|---|---|---|
| **v1** | 15/97 = **0,155** | 17/47 = **0,362** | **+20,7 pt** |
| **v2** (adopté) | 42/97 = **0,433** | 21/47 = **0,447** | **+1,4 pt** |

Le passage à v2 a fait monter `no_text` de **0,155 à 0,433** (+28 pts) en ne
bougeant `with_text` que de 0,362 à 0,447. **C'est le prompt, pas le moteur, qui a
effacé l'essentiel de l'écart lecture/reconnaissance.** Le basculement de moteur
ne fait que pousser un écart déjà réduit de l'autre côté de zéro. Conséquence de
formulation : l'écart de **+40 pts** présenté au §9.2 est mesuré en **v1 sur les 73
images d'origine** ; sous le prompt de mesure adopté il vaut **+1,4 pt**. Aucun
chiffre ne change, mais l'écart ne doit plus être présenté comme une propriété
stable du système.

**Ligne périmée trouvée au passage** : le §10.4 publie `no_text` v2 = **0,423**
(41/97) ; le barème gelé donne **0,433** (42/97) — une image d'écart, cohérente
avec le `62/144` du même paragraphe (gelé : `63/144`, cf. AUDIT 1). La ligne v1 du
même tableau est, elle, **exacte** (0,155 / 0,362), ce qui confirme que le barème
réutilisé est le bon.

**§12.2 bis est réfuté, dans les deux sens.** docTR est meilleur sur l'étalon
externe (0,411 contre 0,329) et **moins bon sur la tâche du drapeau** (40/144
contre 47/144) : le **classement s'inverse** entre les deux tâches. Un moteur qui
lit mieux « du texte en général » n'est pas un moteur qui lit mieux **la chaîne
qui compte** — marque ou référence, souvent petite, stylisée, isolée. Le §12.2 bis
inférait de l'un vers l'autre ; c'était une inférence, et elle est fausse.

Ce qui **tient** : le §12.3 reste vrai. Le drapeau publié garde ≥ 15 % de faux
négatifs (minorant), donc « ≤ 0,433 » reste la bonne formulation du chiffre
`no_text`.

### §13.3 Décision (opérateur, 2026-09-15) : ne pas basculer sur docTR seul — **adopter l'union**

Le drapeau ne sert pas à décrire le corpus mais à **exclure** les images où le
modèle pourrait lire. Son seul défaut coûteux est le faux négatif, et docTR le
**multiplie par 1,9**. L'**union PP-OCR ∪ docTR** est le meilleur des trois :
faux négatifs **0,130** [0,130 ; 0,195] contre 0,152 pour le drapeau publié et
0,282 pour docTR, et `κ` 0,750. Elle n'ajoute que **3 images** à `with_text`,
toutes `strict`-incorrectes : elle **sécurise** le chiffre publié sans l'embellir.

**L'union est le drapeau canonique depuis le 2026-09-15.** État appliqué :
**94 `no_text` / 50 `with_text`** (contre 97/47 publié) ; commande rejouable :

```
python -m iot_audit.corpus.ocrtext flag --from rapidocr-ppocr,onnxtr-db_resnet50-crnn_vgg16_bn
```

Chiffres **recalculés sous le drapeau adopté** (barème gelé A, niveau image,
prompt v2) — ce sont désormais **les chiffres canoniques de la strate** :

| sous-ensemble | n | modèle | strict | marque | catégorie |
|---|---|---|---|---|---|
| `no_text` | 94 | **42/94 = 0,447** [0,350 ; 0,547] | **2/94 = 0,021** | 8 | 71 |
| `with_text` | 50 | **21/50 = 0,420** [0,294 ; 0,558] | **15/50 = 0,300** | 35 | 48 |
| écart | | **−2,7 pt** | | | |

### §13.3 bis Le choix lui-même : ce qu'il ne faut pas se raconter

Adopter un drapeau **après** avoir vu les prédictions est exactement ce que le §8
interdit par ailleurs (le manifeste fige `text_visible` **avant** de voir la
moindre prédiction, précisément pour empêcher de réviser le drapeau en fonction du
résultat). Il faut donc dire pourquoi ce choix-là est défendable :

1. **il n'est pas fait pour améliorer les chiffres publiés** — il les *dégrade*.
   L'écart lecture/reconnaissance passe de **+1,4 pt à −2,7 pt** : sous le drapeau
   adopté, la strate censée être la plus difficile est identifiée *mieux* que
   l'autre. Un choix fait pour flatter la revendication aurait gardé `ppocr` ;
2. il est fait sur un critère de **qualité d'instrument** (faux négatifs mesurés
   contre un lecteur indépendant) **et** sur un critère de **robustesse
   structurelle** — ne pas dépendre d'avoir choisi le bon moteur ;
3. son effet sur les chiffres publiés est **dans le bruit** (intervalles
   recouvrants, §13.2).

**Réserve, écrite parce qu'elle est réelle** : le critère de faux négatifs utilise
le canal `visible_text` du **même** VLM dont les prédictions sont notées, donc il
n'est pas *entièrement* indépendant des chiffres qu'il sert à interpréter. La
règle propre pour la suite : **figer le choix de drapeau avant le prochain run**, et
ne plus le rouvrir après.

**Le manifeste gelé n'a pas été régénéré** (`corpus/measure-manifest.json`, 2026-09-14) :
il porte le drapeau `ppocr` et reste l'entrée historiquement figée des runs v1/v2.
C'est pourquoi les figures des §10.2/§10.4 restent des figures **au drapeau
`ppocr`** ; le §13.3 ci-dessus donne leur version **au drapeau adopté**.

### §13.4 Le barème est **réutilisé**, pas redécrit — et une implémentation fausse a été attrapée

Le barème n'est **pas** réimplémenté : `flag_swap_identification.py` **importe**
`~/zabeth22-vllm-repair/audit-grading.py` — le module qui a produit le transcript
gelé — et **assert les huit agrégats publiés** avant de rien écrire (sinon il sort
en erreur sans publier). La comparabilité est donc **assertée**, pas espérée.

Ce garde-fou a servi immédiatement. J'avais d'abord réécrit le critère « de
mémoire » ; ma version écrasait les séparateurs (`DIR-600` → `dir 600`), celle du
projet les **conserve**. L'arm `with_text` passait de **0,447** à **0,766** sous ma
version — **32 points de trop**. C'est exactement la classe de défaut que `docs/09`
§2 interdit, et la raison pour laquelle le script importe le barème au lieu de le
redécrire.

Le module de lisibilité **reproduit exactement** les chiffres du §12.3
(`N̂ = 55,4`, FN `0,152`, accord `0,896`, `κ = 0,762`), ce qui valide la chaîne de
mesure sur un résultat déjà publié.

### §13.5 Ce que le code porte désormais

`DocTREngine` est un **instrument de première classe** de `ocrtext.py`, et
`run`/`flag` sont désormais séparés : **`run` mesure** (une ligne `image_text_ocr`
par instrument), **`flag --from <instr>[,<instr>…]` sélectionne** le drapeau
canonique (`--dry-run`, union par virgule). Comme les deux colonnes
`hit_brand`/`hit_model` sont stockées pour **chaque** instrument, les deux
drapeaux restent recalculables : le basculement est une **sélection**, pas une
réécriture, et il est réversible par une commande. État canonique depuis le
2026-09-15 : **l'union**, soit **94 `no_text` / 50 `with_text`** — avec la réserve
écrite au §13.3 bis, et la règle « figer le drapeau avant le run » pour la suite.

Le venv du projet est **intact** — docTR vit dans `.venv-ocr2` — donc la
reproductibilité de tout ce qui était déjà publié est préservée.

---

## §14 — Avenant du 2026-09-15 : toutes les figures passées par catégorie, et l'auto-déclaration mesurée

Motif : ce document stratifie par `text_visible` (§9.2), par prompt (§10.4) et par
strate de provenance (§10.3), **jamais par catégorie**. Ce trou a coûté cher : la
catégorie `router_ap` sortait à **0/41**, invisibilité totale d'un défaut touchant
**28 % du périmètre** (rapport 25). Toutes les figures publiées qui sont
**recalculables** sont donc ventilées ici.

### §14.1 Hétérogénéité : un critère, pas un coup d'œil

Règle appliquée, conforme au §4.3 (on n'affirme pas un écart que les intervalles
ne soutiennent pas) : hétérogénéité **DÉMONTRÉE** si les intervalles de Wilson de
la meilleure et de la pire catégorie (n ≥ 10) sont **disjoints** ; **NON TRANCHÉE**
sinon. Le test peut donc répondre « non tranché » — c'est ce qui le rend
informative.

> **Niveau × barème :** **image** × prompt **v2**. Les lignes nommées **`(P)`** sont sous
> `audit-grading` **P**, celles nommées **`(A)`** sous **A** — **y compris `catégorie`**, où
> A vaut `119/144 = 0,826` (override de vérité terrain compris) contre `120/144 = 0,833`
> sous `metrics`. `M7` n'est pas ventilable (§14.4).

Prompt v2, drapeau union, périmètre 144 :

| métrique | agrégat | `smart_speaker` | `router_ap` | `smart_bulb` | `smart_plug` | `ip_camera` | hétérogénéité |
|---|---|---|---|---|---|---|---|
| **modèle** (critère P) | **0,535** | 0,695 | 0,342 | 0,600 | **0,167** | 0,250 | **DÉMONTRÉE** |
| modèle (critère A, publié) | 0,438 | 0,695 | **0,000** | 0,600 | 0,167 | 0,250 | **DÉMONTRÉE** |
| strict (A) | **0,118** | 0,171 | 0,000 | 0,400 | 0,083 | 0,000 | **DÉMONTRÉE** |
| **marque** | **0,299** | 0,183 | 0,415 | 0,600 | **0,583** | 0,250 | **DÉMONTRÉE** |
| catégorie | **0,826** | 0,890 | 0,707 | 0,600 | 1,000 | 0,500 | **non tranchée** |

**Conséquence de publication** : les quatre premières lignes ne doivent **plus**
être citées comme des propriétés du modèle. `strict` va de **0,000 à 0,400**,
`marque` de **0,183 à 0,583** : ce sont des **moyennes pondérées de situations
inégales**, dominées par `smart_speaker` qui porte **57 % du périmètre**.

**Contre-épreuve** : la ligne `catégorie` sort **non tranchée** — les intervalles
se recouvrent. C'est cohérent avec le §9.2 (« la catégorie est robuste, le modèle
non ») et cela prouve que le test **distingue** au lieu de tout flaguer. Un test
qui aurait déclaré les cinq lignes hétérogènes n'aurait rien mesuré.

### §14.2 L'auto-déclaration n'est pas calibrée — et v2 en a changé le sens

Le §10.4 justifie l'adoption de v2 par la chute des `unidentifiable` de **114/144
(79 %)** à **26/144 (18 %)**. Cette chute a été lue comme une amélioration. Mesurée
contre l'exactitude réelle, elle ne l'est pas :

> **Niveau × barème :** **image** ; les deux barèmes (**A**, **P**) sont des colonnes
> nommées. `identified` est la sortie brute du champ `identification_status`.

| prompt / barème | déclare `identified` | exact (modèle) | écart | sens |
|---|---|---|---|---|
| v1 / A | 28/144 = **0,194** | 32/144 = 0,222 | −0,028 | sous-déclare |
| v1 / P | 28/144 = **0,194** | 45/144 = 0,312 | −0,118 | sous-déclare |
| v2 / A | 116/144 = **0,806** | 63/144 = 0,438 | **+0,368** | **SUR-déclare** |
| v2 / P | 116/144 = **0,806** | 77/144 = 0,535 | **+0,271 (39 images)** | **SUR-déclare** |

**Le système déclare identifier 80,6 % des images et n'est exact que sur 53,5 %.**
v2 a donc **retourné** le défaut au lieu de le corriger : d'une sous-déclaration
modérée il est passé à une sur-déclaration de **27 points**. Le champ
`identification_status` n'est **pas calibré**, et **le coût de v2 sur ce champ
n'avait jamais été chiffré**. C'est la correction la plus importante de cet
avenant.

Conséquence pour C1 : toute revendication appuyée sur « le système identifie X %
des objets » doit préciser **lequel des deux chiffres** est cité — le taux
d'**exactitude** (0,535) ou le taux d'**auto-déclaration** (0,806). Les
confondre serait une faute.

### §14.3 Pourquoi le modèle échoue — taxonomie mesurée

En comparant la sortie au **texte réellement présent** (trois lectures
indépendantes : 2 moteurs OCR + la transcription du VLM) :

| étiquette | nombre | nature |
|---|---|---|
| **sans appui textuel** | **52 (78 %)** | la référence n'apparaît dans **aucune** des trois lectures |
| référence lisible non restituée | 5 | actionnable |
| near-miss (1 caractère) | 5 | actionnable (`HS110`→`HS105`) |
| `model` = marque | 3 | défaut de contrat |
| `model` vide | 2 | refus defendable |

Sur **67 échecs**, **10 seulement sont actionnables** : **le plafond d'un
changement de prompt est de 6,9 points.**

**Le nom de l'étiquette importe** : `sans_appui_textuel` ne veut pas dire
« impossible » — `smart_speaker` est reconnue **57/82**, dont beaucoup sans texte.
Cela veut dire « seule la reconnaissance **de forme** peut aboutir ». C'est le
régime où vivent les chiffres du §8.2 et du §9.2, et il n'est **pas** corrigeable
par le prompt.

### §14.4 Non recalculable, et déclaré tel

`M7 InventedBrandRate` (0/19, §9.5) provient d'une **revue manuelle** de 9 marques
hors lexique : il n'existe **aucun lexique de marques au niveau du projet**. La
figure n'est donc **pas ventilable** par catégorie, et elle n'est pas remplacée par
une approximation. Un chiffre issu d'une revue manuelle non exécutable reste
publiable — à condition d'être **étiqueté comme tel**.

### §14.5 Ce que cet avenant change dans ce document

| figure | avant | après |
|---|---|---|
| `modèle` (v2) | 0,438 (A) | **0,438 (A) · 0,535 (P)** — les deux publiées |
| `strict` | 0,118 | 0,118 (A) — **à publier par catégorie** (0,000–0,400) |
| `marque` | 0,299 | 0,299 — **à publier par catégorie** (0,183–0,583) |
| auto-déclaration `identified` | non mesurée | **0,806**, à opposer à 0,535 ⇒ **sur-déclaration de 27 pt** |
| genou de charge (§11/V11) | « vers 16 » (pas de 8) | **encadré 16–18** ; SM saturé dès 14 ⇒ SM n'est pas le seuil opérant |

Scripts : `corpus/publish_by_category.py`, `corpus/diagnose_identification.py`.
Rapport complet : `26-DIAGNOSTIC-CATEGORIES-ET-GENOU.md`.

---

## §15 — Avenant du 2026-09-15 (soir) : le contrat **v3**, et la fin de l'auto-déclaration

Le §14 a mesuré que `identification_status` (auto-déclaré) sur-déclarait de **27 points**
en v2. Cet avenant en tire la conséquence : le champ est **remplacé**, pas recalibré.

### §15.1 Pourquoi remplacer, et non corriger

`identification_status` demandait au modèle de juger sa propre réponse. Seul le
modèle peut dire ce qu'il « voulait dire » : l'affirmation est **non
falsifiable**, donc contraire à la prémisse du projet (rapport opposable, journal
HMAC — un tiers doit pouvoir re-vérifier). Aucun réglage de prompt ne rend
falsifiable une confiance auto-déclarée.

### §15.2 Le contrat v3

```
identification_basis ∈ { label, visual, none }

label   la marque ou la référence rapportée est ÉCRITE sur l'appareil,
        et transcrite dans visible_text      -> vérifiable par comparaison
visual  l'appareil est reconnu à sa forme, sans texte sur lui
none    rien d'identifié (brand et model doivent être vides)
```

`identification_status` **n'est plus demandé** : il devient une propriété
**calculée** (marque *et* modèle non vides sous une base `label`/`visual`).
Le point clé est que `visible_text` existait **déjà** au schéma : v3 ne fait que
**lier** l'auto-déclaration à une preuve déjà présente dans la sortie.

**Invariants** : 144 items identiques à v2 (`sha256 fbc6abe3…`), `temperature=0`,
`seed=1234`. Le générateur `corpus/make_runner_v3.py` est déterministe.

### §15.3 Résultats (144 images, 3 nœuds, 0 erreur de transport)

| grandeur | valeur |
|---|---|
| déclarent `label` / `visual` | 0,542 / 0,444 |
| contrat respecté (marque *ou* référence dans `visible_text`) | **0,936** (73/78) |
| **violations** (ni l'une ni l'autre) | **0,064** (5/78) |
| référence **modèle** étayée | 0,628 (49/78) |
| `visible_text` vide sous un `label` | **0/78** |
| contrôle : `visual` avec la réponse pourtant dans le texte | 0,141 (9/64) |

**Exactitude conditionnelle à la base** — et le sens est contre-intuitif :

| base | n | exact (A) | exact (P) | IC95 (P) |
|---|---|---|---|---|
| `label` | 78 | 0,282 | 0,462 | [0,355 ; 0,571] |
| `visual` | 64 | 0,656 | **0,656** | [0,534 ; 0,761] |

Écart **−0,195** en faveur de `visual`, **intervalles non disjoints ⇒ NON TRANCHÉE**
(règle §4.3). Direction à noter, pas à affirmer : la strate `label` contient les
vues de cartes électroniques, où le texte lisible est une référence de
**composant** (`MT6323LGA`, `ADC3101`), pas du produit. **Le texte présent induit
en erreur autant qu'il aide.**

### §15.4 Ce que v3 **ne** fait pas

**L'exactitude ne bouge pas** : 0,535 (v2) → 0,542 (v3) sur le périmètre entier,
+0,024 au mieux par catégorie (`router_ap`). Le changement de contrat achète de
la **mesurabilité**, pas de la performance. Lire « v3 » comme une amélioration
serait une erreur.

**Le statut calculé n'est pas mieux calibré, il est calibré dans l'autre sens** :
v2 sur-déclarait de +0,271 ; le statut v3 sous-déclare de **−0,160**. Et c'est une
propriété de la **règle de calcul choisie** (exiger marque *et* modèle), pas du
modèle — à déclarer comme telle.

### §15.5 Plafond de jetons : 256 est insuffisant, 640 est le bon

`visible_text` (maxLength 512) plus du texte bilingue dépasse 256 jetons. Mesuré :

| | v3 (256) | v3b (640) |
|---|---|---|
| réponses non-JSON | 2/144 | **0/144** |
| exactitude (P) | 78/144 = 0,542 | **79/144 = 0,549** |
| prédictions identiques entre les deux variantes | **142/144 = 0,986** (mesure symétrique) | |

Les 2 divergences sont **exactement** les 2 images que v3 n'a pas su rendre ⇒
relever le plafond n'a rien changé d'autre (argument vérifié image par image,
`corpus/compare_v3_v3b.py`). **Le plafond à retenir est 640.**

### §15.6 Une sonde a établi `finish_reason`, et découvert autre chose

La sonde `corpus/probe-token-budget.py` enregistre `finish_reason`, que le runner
ne stockait pas. Résultat : `zyxel_p_870ha_bottom` rend **441 jetons** à 640 et
`finish=length` à 256 (troncature **démontrée**), mais l'image
`philips_hue_bridge` rend une réponse **valide de 65 jetons** à 256 — donc sa
troncature pendant le run v3 ne se reproduit pas. Rejeu de 10 passes : **10/10
identiques** pour chaque couple (image, plafond) ⇒ le décodage est **déterministe**.
La variable restante est le **nœud** :

| `philips`, cap 256 | résultat |
|---|---|
| zabeth21 | `finish=stop`, **65 jetons, valide** |
| zabeth22, zabeth23 | **`finish=length`**, 256 jetons, invalide |

### §15.7 Équivalence des nœuds : divergence réelle, effet **nul** sur les figures

Configuration **identique** sur les trois nœuds (pilote 615.71.09, torch
2.13.0+cu132, vLLM 0.29.0, même chemin de modèle, mêmes arguments — vérifié en
direct). Un passage **complet** (144 images) par nœud, séquentiellement :

| mesure | z21/z22 | z21/z23 | z22/z23 |
|---|---|---|---|
| **accord en forme brute** | **0,917** | **0,938** | **0,938** |
| identiques après normalisation | 0,958 | 0,965 | 0,965 |
| **notées différemment — `modele`** (§4.2) | 0/144 | 0/144 | 0/144 |
| **notées différemment — `marque`** | **1/144** | **1/144** | 0/144 |
| **notées différemment — `categorie`** | **1/144** | **1/144** | 0/144 |
| ensembles d'images correctes | **identiques** (78 partout, 0 pour un seul) | idem | idem |
| accord des **trois** nœuds | **129/144 = 0,896** | | |

Exactitude (P) : **0,5417 sur les trois nœuds**, au dix-millième.

**L'unique image notée différemment a la même cause que le plafond de jetons** :
`philips_hue_bridge_bottom_2021`, valide sur zabeth21, **tronquée** sur zabeth22
et zabeth23 (§15.5). Ce n'est pas un effet propre de la divergence. Corriger le
plafond à 640 le ramène à **0/144**.

À noter que **zabeth22 et zabeth23 sont exactement équivalents en notation**
(0/144 sur les quatre métriques, les deux barèmes) et s'accordent davantage entre
eux (135/144) qu'avec zabeth21 (132 et 135) — cohérent avec la sonde du §15.6.

> **[Correction 2026-09-15, soir — voir §16.1]** L'interprétation de la sonde du
> §15.6 (« zabeth21 valide, z22/z23 tronquent ») était un artefact d'échantillonnage
> n=1 : rejouée **3 fois par nœud** (36 requêtes), elle montre que z22 et z23 ne
> tronquent que la **première requête** après idle, puis rendent **exactement** la
> réponse de z21 (même sha256). À l'état chaud, les trois nœuds produisent des
> sorties **identiques à l'octet près**. La cause du désaccord `marque`/`categorie`
> 1/144 ci-dessus reste la troncature (même racine), mais ce n'est **pas une
> propriété de nœud**. Le tableau d'équivalence ci-dessus **tient** (il a été
> mesuré à l'état chaud, plusieurs requêtes par nœud).

Les divergences restantes sont des **quasi-égalités de décodage glouton** qui
déplacent la **forme** sans franchir la frontière de l'exactitude
(`DS-2DE7225IW-AEL` vs `…-AE`, casse, fragment de transcription en plus). Contrôle
qui aurait pu piéger : le cas `B18D B` où zabeth22 dit `other` et les deux autres
`smart_speaker` **ne change aucun score** — la vérité est `router_ap`, donc les
trois ont tort de toute façon. Un désaccord de fond peut donc être neutre en
notation. Conséquences :

- **M9 (accord de rejeu) ne peut pas valoir 1** au niveau de la sortie brute
  (0,896 à trois nœuds, 0,917–0,938 deux à deux) ; elle vaut **1 au niveau de la
  notation** entre zabeth22 et zabeth23, et **0,993** dès que zabeth21 est
  impliqué — l'écart restant étant la troncature. *(Correction du soir : la
  composante « premier-requête » de cet écart est un artefact à froid, pas une
  divergence de nœud — §16.1 ; à l'état chaud, M9 notation = 1 partout sauf
  l'effet plafond, supprimé par le cap 640.)*
- **Risque latent** : 10,4 % de quasi-égalités sur un corpus aux références peu
  ambiguës ; un corpus plus ambigu ferait franchir la frontière à certaines.
  La mesure est à refaire avant d'agrandir le corpus.
- **Le seul correctif qui rapporte est le plafond de jetons** (§15.5). Épingler
  la mesure à un nœud unique n'apporterait rien de mesurable ici.

### §15.8 Ce que cet avenant change dans ce document

| figure | avant | après |
|---|---|---|
| `identification_status` auto-déclaré | 0,806 « déclaré identifié » | **abandonné** — remplacer par `identification_basis` |
| base d'identification | non mesurée | **`label` 0,542 · violation 0,064** |
| statut | auto-déclaré | **calculé** (−0,160, règle choisie, à déclarer) |
| plafond de jetons de mesure | 256 | **640** (256 perd 2 images sur 144) |
| accord inter-nœuds | supposé (config identique) | **0,917 en forme brute, 1,000 en notation** |
| prétraitement (agrandissement) | candidat non testé | **mesuré, NON TRANCHÉ** (+2/144, IC recouvrants) |

Scripts : `corpus/{make_runner_v3.py,grade_v3.py,compare_v3_v3b.py,compare_nodes.py,
assemble_evidence_v3.py,make_probe_token_budget.py}`.
Rapport complet : `27-CONTRAT-FALSIFIABLE-ET-NOEUDS.md`.
Preuve : `evidence/2026-09-15/contrat-v3-et-nodes.json`.

---

## §16 — Avenant du 2026-09-15 (soir) : les nœuds sont convergents, le statut est calibré (et conservateur)

### §16.1 La sonde à répétitions réfute la « divergence de nœuds » (§15.6–§15.7)

Élimination matérielle d'abord : **poids identiques** (14/14 sha256 : 2 safetensors
+ 12 JSON, vérifiés sur les trois nœuds), CPU identique (i9-13900 ×3), stack Python
identique — **sauf numpy** (2.2.6 sur z21/z23, 2.3.5 sur z22), dérive déjà documentée
en `18-DEPLOIEMENT.md`. Cette différence ne peut pas expliquer le clustering observé
(z23 partageait 2.2.6 avec z21 et se comportait comme z22) ; elle est corrigée
(2.2.6 → 2.3.5 sur z21/z23, `uv pip check` PASS, effectif au prochain redémarrage
planifié — hygiène de provenance, pas un correctif de comportement).

Puis la sonde décisive (`corpus/probe-divergence.py`, prompt/schéma identiques à v3
au jeton près, température 0, graine 1234) : **2 images × 3 nœuds × 2 caps × 3
répétitions = 36 requêtes**, chaque nœud interrogé séparément :

* `zyxel_p_870ha` cap 256 : **length/256 sur les trois nœuds, 3/3 répétitions** —
  la troncature est **déterministe et identique partout** (441 jetons nécessaires).
  C'est un problème de **plafond**, pas de nœud ; correctif = cap 640 (stop/441,
  même sha, 3/3 sur les trois).
* `philips_hue_bridge` cap 256 : z21 stop/65 3/3 ; z22 et z23 **length/256 à la
  première requête seulement**, puis **stop/65 — exactement la réponse de z21**
  (même sha256 de texte) aux répétitions suivantes.

**Verdict : à l'état chaud, les trois nœuds produisent des sorties identiques à
l'octet près.** La lecture du §15.6 (« zabeth21 valide, z22/z23 tronquent ») était
un **artefact de premier-requête-après-idle** observé avec n=1 par case. Le désaccord
de notation 1/144 du §15.7 reste réel et garde la même racine (troncature), mais il
n'est **pas une propriété de nœud**. Correctif opérationnel inchangé, désormais
justifié : **cap 640 + garde client sur `finish_reason=length`**.

**Règle de méthode (ajoutée au CDC §3.7)** : aucune conclusion de divergence entre
machines sans **répétitions** ; trois généralisations à partir d'une mesure unique
ont déjà été attrapées dans ce projet (62-vs-5 violations ; 0/144-vs-1/144 ; celle-ci).

Preuves : `evidence/2026-09-15/convergence/{weight-hashes-raw.txt,
stack-freeze-raw.txt,numpy-alignment.txt,probe-divergence-run1.txt,probe-divergence.json}`.

### §16.2 Calibrage du statut dérivé (`corpus/calibrate_status.py`)

La dérivation v3 du statut (`derive_status`) était un choix non calibré — le défaut
de v2 déplacé du modèle vers le code. Protocole : **3 règles candidates** lisant
uniquement les champs de prédiction (déterministes d'un run à l'autre), **split par
objet gelé** par hachage (24/48 objets → 88 train / 56 eval), **sélection sur train**
(min |déclaré − exact|), **publication sur eval** jamais vu par la sélection.

Sélection (train) : R1 écart −0,057 · R2 (porte du contrat sur `label`) −0,080 ·
R3 (sévérité visuelle) −0,080 → **R1 retenue**.

Évaluation tenue à part (56 images) :

| règle | déclaré `identified` | exact (P) | écart | sur-allègues |
|---|---|---|---|---|
| **R1 (retenue)** | 0,268 [0,170 ; 0,396] | 0,589 [0,459 ; 0,708] | **−0,321** | 5 |
| R2 | 0,232 | 0,589 | −0,357 | 5 |
| v2 auto-déclaré | 0,821 | 0,571 | **+0,250** | **14** |
| v1 auto-déclaré | 0,161 | 0,321 | −0,161 | 3 |

**Lecture** : la dérivation calculée supprime la sur-allégation (5/56 contre 14/56,
tous en `label`) mais **sous-déclare** de −0,321 : la frontière identified/partial
n'est pas linéaire dans les champs de prédiction — 31 des 32 `visual` de l'eval
sortent `partial` alors que leur exactitude (0,656) dépasse celle des `label`
(0,522). **Décision** : le statut reste une **métrique publiée**, pas une **garantie
opposable** ; le rapport opposable repose sur `model_correct` (barème gelé) + journal
HMAC. Règle dérivée versionnée (R1), split gelé, reproductible.

Preuve : `evidence/2026-09-15/status-calibration.json`. Rapport complet :
`28-CONVERGENCE-ET-CALIBRAGE.md`.

Scripts de l'avenant : `corpus/{make_probe_divergence.py,probe-divergence.py,
calibrate_status.py}`.

### §16.3 Reprise des 144 au plafond corrigé (run v4) — les figures du contrat, republiées

Le run **v4** (`corpus/runner4-v4-cap640.py`, généré par `make_runner_v4.py`)
reprend les 144 images avec les réglages corrigés : **cap 640** + **garde
`finish_reason` enregistrée nativement** sur chaque prédiction (v3 ne la
capturait pas — il a fallu une sonde pour l'établir). Items, prompt, schéma,
température 0, graine 1234 : **ceux de v3 à l'octet près** (asserté au
générateur, sha256 items `fbc6abe3…`). 3 shards concurrents, un par endpoint —
**144/144, 0 erreur de transport, 0 réponse non-JSON, 0 `finish_reason=length`**.

**Comparabilité (3 exécutions indépendantes)** :

| paire | prédictions identiques | notées différemment (A / P) |
|---|---|---|
| v3 vs v3b | 142/144 | 0 / 1 |
| v3 vs v4 | 142/144 | 0 / 1 |
| **v3b vs v4** | **144/144** | **0 / 0** |

Les 2 seules différences sont **exactement** les images que v3 ne savait pas
rendre (`zyxel_p_870ha`, `philips_hue_bridge`) ⇒ le plafond n'a changé **rien
d'autre** que la suppression des troncatures. `v3b` vs `v4` : deux exécutions
séparées d'environ une heure produisent des sorties **identiques à l'octet
près sur 144/144** — la stabilité de rejeu (M9) vaut **1 en forme brute ET en
notation** au réglage corrigé.

**Figures du contrat à publier (run v4, cap 640)** — elles remplacent celles
du §15.3 (mesurées au plafond défectueux 256) :

| figure | v3 (cap 256) | **v4 (cap 640)** |
|---|---|---|
| images rendues | 142/144 (2 non-JSON) | **144/144, 0 troncature** |
| base `label` / `visual` / `none` | 78 / 64 / 0 + 2 invalides | **80 / 64 / 0** |
| contrat `label` respecté | 0,936 (73/78) | **0,938 (75/80)** |
| violations (ni l'un ni l'autre) | 0,064 (5/78) | **0,062 (5/80)** |
| `visible_text` vide sous `label` | 0/78 | **0/80** |
| exactitude `label` (P) | 0,462 | **0,463** [0,357 ; 0,571] |
| exactitude `visual` (P) | 0,656 | **0,656** [0,534 ; 0,761] |
| écart label − visual | −0,195 NON TRANCHÉ | **−0,194 NON TRANCHÉ** |
| **exactitude totale (P)** | 0,5417 | **0,5486 (79/144)** |
| statut calculé : déclaré / exact / écart | 0,382 / 0,542 / −0,160 | **0,389 / 0,549 / −0,160** |

**Ce qui bouge et ce qui ne bouge pas** : l'exactitude gagne **+1 image**
(79/144 — la troncature `zyxel`, désormais correcte) ; la strate `label`
absorbe les 2 images retrouvées et **toutes ses figures restent stables** ; le
verdict d'informativité de la base est **inchangé (NON TRANCHÉ)** ; la
calibration du statut (§16.2) est **inchangée en écart** : déclaré − exact =
**−0,160** sur les deux runs (v3 0,382/0,542 → v4 0,389/0,549 — l'image gagnée
par le plafond est identifiée des deux côtés, donc les deux taux montent
ensemble). Le
correctif du plafond est donc **sans effet de bord sur le contrat** — les
conclusions §15/§16.2 tiennent, désormais mesurées sur un run complet.

**Réglage désormais gelé** (M6) : cap 640, garde `finish_reason` native, règle
de troncature = exclure du dénominateur et compter à part (aucune exclusion
n'a été nécessaire : 0 troncature).

Preuves : `evidence/2026-09-15/corpus/expanded/predictions-v4-shard{0,1,2}.json` ·
`results/{v4-contrat-cap640.json, v4-vs-v3-v3b-equivalence.json}`. Rapport :
`29-REPRISE-CAP640.md`.

## §17 — Avenant du 2026-09-29 : le banc d'identification au niveau objet, et **M1 mesuré à n = 48**

> ⚠️ **FIGURES PÉRIMÉES — LIRE LE §19 AVANT DE CITER CE §.** Le chiffre principal
> de cet avenant (`8/48 = 0,167`) est **faux**, pas seulement imprécis : il était
> étiqueté « M1 (marque ET modèle) » alors que le code notait le **modèle seul**,
> et sur un barème (`audit-grading.py`, égalité *stricte* de marque) qui n'est pas
> celui du M1 objet. M1 à `n = 48` vaut **10/48 = 0,208** sous la règle publiée,
> et **15/48 = 0,312** si l'abstention est retirée du vote. Le §17.2, le §17.3, le
> §17.6 et le tableau de `benchmarks/README.md` sont donc à relire avec le §19.
> Ce qui **reste valable** dans ce § : la mesure du plafond `oracle_any`, la
> matrice de confusion, et l'identification du gisement (corpus, pas prompt).

### §17.1 Pourquoi cet avenant

Toutes les figures publiées jusqu'ici étaient **au niveau image**. La métrique que
le projet met en tête de son propre plan est **M1 : marque ET modèle, au niveau
objet, agrégation modale, cible ≥ 0,70** (§5, §8). Elle n'avait été mesurée que
sur un sous-ensemble de **n = 26 objets** (`8/26 = 0,308`, §8).

Le run **v4 gelé** porte **48 objets / 144 images**. Le banc
`benchmarks/run_identification.py` (nouveau, régénérable) calcule M1 sur ces 48 —
sans aucun chiffre saisi à la main. **Contrôle d'instrument** : sur le critère **P**,
il reproduit *exactement* les figures publiées du §15 (total `79/144 = 0,549` ; base
`label` `37/80 = 0,463` ; base `visual` `42/64 = 0,656`). Mêmes données, même barème
(`audit-grading.py`), mêmes chiffres ⇒ le banc est fiable, donc ses figures neuves
sont publiables.

### §17.2 M1 au niveau objet — le chiffre qui change

| agrégation des photos d'un objet | exactitude objet (n = 48) |
|---|---|
| `modal_tuple` **← M1 publiée** | **8/48 = 0,167** IC95 [0,087 ; 0,296] |
| `first` | 9/48 = 0,188 IC95 [0,102 ; 0,319] |
| `brand_then_model` / `basis_preferred` | 8/48 = 0,167 IC95 [0,087 ; 0,296] |
| `all_images` (toutes les photos doivent être justes) | 6/48 = 0,125 IC95 [0,059 ; 0,247] |
| **`oracle_any`** (une seule photo juste suffit) | 11/48 = 0,229 IC95 [0,133 ; 0,365] |

| figure objet | valeur |
|---|---|
| marque seule (modale) | 17/48 = 0,354 IC95 [0,234 ; 0,496] |
| catégorie seule (modale) | 35/48 = 0,729 IC95 [0,590 ; 0,834] |

**Correction du chiffre publié** : M1 passe de `8/26 = 0,308` à **`8/48 = 0,167`**.

> ⚠️ **CE PARAGRAPHE A ÉTÉ CORRIGÉ LE 2026-09-29 (§19).** Les deux nombres ci-dessus
> ne sont pas des M1 : ce sont des « modèle seul » sous le barème `audit-grading`.
> La vraie correction est `8/26 = 0,308` → **`10/48 = 0,208`** (règle publiée) /
> **`15/48 = 0,312`** (abstention retirée). Le raisonnement qui suit sur le
> *dénominateur* reste juste ; le numérateur, non.
Le numérateur est **identique (8 objets)** — seul le dénominateur double, parce que
le corpus a grandi. M1 n'a donc pas « baissé » : il a été **enfin mesuré sur le
corpus réel**, et il est **plus bas que le chiffre de travail**.

**Ce que ce chiffre établit, sans ambiguïté :**

1. **L'écart à la cible est un ordre de grandeur, pas un réglage.** 0,167 contre
   ≥ 0,70 : ce n'est pas un pipeline à optimiser, c'est une **capacité absente**.
2. **Le plafond `oracle_any` = 0,229 borne le problème en amont de l'agrégation.**
   Même en donnant au système le bénéfice du doute *à chaque objet* (une photo juste
   suffit), il reste sous 0,23. **Aucune règle d'agrégation ne peut sauver M1** — la
   perte se produit dans la perception, pas dans le vote.
3. **La marque seule (0,354) et la catégorie seule (0,729) tiennent** : c'est bien
   la conjonction marque **et** modèle qui s'effondre. Le système *classe* sans
   *identifier*.

### §17.3 La base `label` / `visual` : le verdict dépend du critère

| base | n | exact (A) | exact (P) | catégorie |
|---|---|---|---|---|
| `label` (texte lu) | 80 | 22/80 = 0,275 | 37/80 = 0,463 | 61/80 = 0,762 |
| `visual` (forme) | 64 | **42/64 = 0,656** | 42/64 = 0,656 | 61/64 = 0,953 |

- critère **A** ⇒ **INFORMATIF** ;
- critère **P** ⇒ **NON TRANCHÉ** (IC qui se recouvrent).

Le §16.2 avait conclu NON TRANCHÉ ; le §15 était en P. Le §17 ne les contredit pas :
il **expose la dépendance au critère**. Publiables toutes deux, chacune sous son
critère. Sous A, la lecture de texte est **nettement moins fiable** que la
reconnaissance de forme (0,275 vs 0,656) — c'est exactement le sens du §15, et cela
va **contre** l'intuition « le texte écrit est la source sûre ».

### §17.4 Contamination et canal : §10.3 **reproduit à n = 48**

| strate | objets | modèle exact (A) | catégorie |
|---|---|---|---|
| `forum` (teardown) | 11 | **0/12 = 0,000** IC95 [0,000 ; 0,242] | 1/12 = 0,083 |
| `official` | 3 | **0/3 = 0,000** IC95 [0,000 ; 0,561] | 3/3 = 1,000 |
| `review` | 34 | 64/129 = 0,496 IC95 [0,411 ; 0,581] | 118/129 = 0,915 |

**`forum = 0/12` et `official = 0/3` reproduisent à l'identique** les figures du
§10.3 : c'est la confirmation la plus forte du dossier, sur un corpus plus grand,
un prompt adopté et un plafond corrigé. La conclusion du §10.3 tient donc :
**sur une carte de démontage, il n'y a rien à lire** — ce n'est pas une faiblesse du
modèle, c'est une **absence d'information dans l'image**, et le routage
(silkscreen OCR → CPE, MAC OUI) reste « non plus une optimisation, mais la seule
voie ». *Nuance honnête* : la strate `review` diffère (0,248 au §10.3 en critère
« modèle » vs 0,496 ici en critère A, runs et plafonds différents) ; ce sont les
deux strates **invariantes** (forum, official) qui portent la conclusion.

`text_visible` (annotation, pas auto-déclaration) :

| `text_visible` | modèle exact | catégorie |
|---|---|---|
| 0 | 42/97 = 0,433 | 75/97 = 0,773 |
| 1 | 22/47 = 0,468 | **47/47 = 1,000** |

**Correction du facteur 2,3** : les §9.2/§10.4 annonçaient l'identification
« 0,704 avec texte / 0,304 sans » (facteur 2,3, M2/M2b). Sur le run v4, critère A,
l'écart est **0,468 vs 0,433** — **quasi nul**. L'ancien facteur était mesuré sur le
run d'origine v1 (73 images, autres réglages) ; il **ne se reproduit pas** au réglage
gelé actuel. Ce qui subsiste, et c'est la lecture défendable :

- `text_visible` **ne prédit pas** la réussite d'identification ;
- en revanche `text_visible = 1` ⇒ **catégorie juste 47/47 (1,000)** : le texte
  visible détermine la **catégorie**, jamais l'identité ;
- l'effet réellement mesuré est **l'inverse de l'intuition** côté base : c'est
  l'image où le modèle **déclare avoir lu le texte** (`label`) qui réussit *moins*
  (0,275) que l'image où il **reconnaît la forme** (`visual`, 0,656).

### §17.5 Classification : où ça tient et où ça casse

| catégorie (vérité effective) | exactitude |
|---|---|
| `smart_plug` | 12/12 = 1,000 |
| `smart_speaker` | 76/82 = 0,927 |
| `smart_bulb` | 4/5 = 0,800 |
| `router_ap` | 29/41 = 0,707 |
| **`ip_camera`** | **1/4 = 0,250** |

Matrice de confusion (extraits parlants) : `router_ap → other` **8** ;
`smart_speaker → other` **6** ; `router_ap → smart_speaker` 4 ;
`ip_camera → smart_speaker` 2.

La catégorie globale (0,847 image, 0,729 objet) est **portée par une seule classe
sur-représentée** (`smart_speaker`, 82/144 = 57 % du corpus). Les deux échecs réels :
`router_ap` borde `smart_speaker` (routeurs à enceinte type Echo/Home), et
`ip_camera` (n = 4) est **trop petit pour conclure**. « Distinguer un routeur d'une
enceinte » est le seul vrai front de classification interne.

### §17.6 Rejeu et latence — **M9 et M8 au vert**

- **M9** : 144/144 prédictions identiques, 144/144 verdicts de catégorie identiques
  ⇒ **1,000** IC95 [0,974 ; 1,000]. Cinquième exécution consécutive stable.
- **M8** : p50 **2,385 s** · p95 **3,759 s** · p99 6,478 s · max 8,152 s
  (n = 144) ⇒ **p95 < 10 s : PASS**.

### §17.7 Ce que §17 ne dit pas

- Il ne mesure **pas** la chaîne CPE/CVE — c'est le chemin critique du plan (§11.1)
  et un autre chantier.
- Il ne mesure **pas** des photos terrain ni une quelconque version firmware
  (limites 1 et 2, §8 de `docs/07`).
- Il ne désigne **pas** de « meilleure règle d'agrégation » : la règle retenue sur
  train (`modal_tuple`, 3/23) n'est pas celle qui gagne sur eval (`first`, 7/25),
  et à n = 48 objets **aucune règle n'est distinguable d'une autre**. La conclusion
  défendable est « **l'agrégation ne sauve pas l'identification objet** », ce que
  `oracle_any` borne aussi.

Preuves : `benchmarks/run_identification.py` · `benchmarks/results.{json,md}` ·
`evidence/2026-09-29/identification-benchmark/`. Rapport : `benchmarks/README.md`.

## §18 — Avenant du 2026-09-29 : **pourquoi** l'identification échoue, et M1 dépend du critère

> ⚠️ **LES CHIFFRES DE M1 DE CE § SONT PÉRIMÉS — VOIR LE §19.** Le §18 mesure l'écart
> A/P sur la métrique du §17, qui n'était pas M1 (§19.1). Le raisonnement sur le
> **besoin en information textuelle** (§18.2–18.3) reste valable et a été reproduit au
> §19.4, avec un résultat plus net : le champ `brand` est à **0,766** quand le texte est
> lisible et **0,103** quand il ne l'est pas. Ce sont les valeurs de M1 (`8/48`, `16/48`)
> qui sont à remplacer par **`10/48 = 0,208`** et **`15/48 = 0,312`** (§19.2).

### §18.1 Motif

Le §17 a établi **combien** : M1 ≈ 0,17–0,33 selon le critère, contre 0,70 visé. Il ne
dit pas **pourquoi**. La question a deux réponses de nature opposée, et les confondre
mène à deux décisions inverses :

- si la référence **n'est pas dans l'image**, aucun prompt ne la fera apparaître ⇒
  problème de **corpus / collecte** ;
- si elle **y est lisible** et n'est pas restituée ⇒ problème de **prompt / contrat de
  sortie**, donc actionnable immédiatement.

Le seul moyen de trancher est de confronter la sortie du modèle au texte
**réellement présent** dans l'image, lu par des instruments **indépendants** : deux
moteurs OCR (`image_text_ocr`, 288 lectures = 144 images × 2) plus la transcription
`visible_text` du VLM lui-même. L'outil `corpus/diagnose_identification.py` fait cela ;
il est ici **étendu** (`--run v2|v4` + agrégation objet) et **reproduit à l'identique**
la taxonomie v2 déjà publiée (contrôle d'instrument : 77 reconnue, 67 échecs, 10
actionnables — inchangés).

### §18.2 Niveau image — v2 → v4

| étiquette | v2 | **v4 (gelé)** |
|---|---|---|
| `reconnue` | 77 | **79** |
| `reference_lue_non_restituee` | 5 | **4** |
| `near_miss` (1 caractère) | 5 | **7** |
| `modele_egale_marque` (défaut de contrat) | 3 | **3** |
| `vide` | 2 | **2** |
| `sans_appui_textuel` | 52 | **49** |
| **échecs** | 67 | **65** |
| dont **actionnables** | 10 | **11** |
| plafond d'un changement de prompt | +10 images (6,9 pt) | **+11 images (7,6 pt)** |

Le résultat qui compte n'est pas le total, c'est le **plafond** : même en réussissant
**tout** ce qu'un changement de prompt peut réussir (les 11 images où la référence
était lisible et n'a pas été restituée), on gagne **7,6 points** sur 144 images. Le
reste — **49 images sur 65 échecs** — n'a **aucune** trace textuelle de la référence
dans l'une quelconque des trois lectures.

### §18.3 Niveau objet — le chiffre qui décide

| | v2 | **v4** |
|---|---|---|
| objets | 48 | 48 |
| M1 reconnus (critère P) | 14/48 = 0,292 | **16/48 = 0,333** |
| échecs **récupérables** (≥ 1 photo où la référence était lisible) | 5/34 | **6/32** |
| échecs **sans appui textuel** (aucune des 3 lectures ne contient la réf.) | 29/34 | **26/32** |

**Le plafond d'une action sur le prompt est de 6 objets** : M1 passerait de 16 à 22 sur
48, soit **0,333 → 0,458**. **La cible de 0,70 n'est pas atteignable par le prompt.**
Ce n'est pas une opinion, c'est la borne haute : on a compté, sur chaque photo des 32
objets ratés, si l'un des trois lecteurs voyait la référence.

**Ce que « sans_appui_textuel » ne dit PAS** — et la nuance est dans l'outil lui-même :
cela signifie « aucun indice **textuel** », pas « impossible ». Le corpus le prouve :
57/82 `smart_speaker` sont reconnus, dont beaucoup sans texte lisible — le modèle
y arrive **de forme**. La bonne lecture est donc : pour ces 26 objets, la lecture de
texte est **hors jeu**, et le seul levier restant est la **reconnaissance visuelle et
la connaissance a priori** (lexique de marques, forme des produits). Cela recoupe la
conclusion du §10.3 pour les teardowns : là aussi, il n'y a rien à lire.

### §18.4 M1 dépend du critère de notation — et l'instrument s'était trompé

En confrontant les deux outils, un écart est apparu : le banc donnait **8/48** et le
diagnostic **17/48** pour la *même* quantité. Cause trouvée et corrigée :

> le nouveau rollup objet **normalisait** les chaînes (`ocrtext.normalise`) **avant**
> de les confier au barème, qui les normalisait **une seconde fois**. Or les critères A
> et P du barème ne diffèrent que par le traitement du tiret/souligné : pré-normaliser
> **efface la distinction qu'on veut mesurer**. Corrigé en votant sur la normalisation
> du barème lui-même (`grading.norm`) et en laissant `model_correct` seul juge. Les
> deux outils donnent alors **le même nombre**.

Une fois le critère fixé, la dépendance est grande et doit être publiée :

| critère | M1 (vote modale, 48 objets) | ce qu'il mesure |
|---|---|---|
| **A** — critère **publié** du contrat | **8/48 = 0,167** | égalité stricte ; `dir 600` ≠ `DIR-600` |
| **P** — séparateur neutralisé | **16/48 = 0,333** | tiret et souligné assimilés à l'espace |

Le **doublement** (8 → 16) vient du même artefact déjà documenté au §16 : les libellés
de vérité sont des slugs à espaces (`dir 600`, `p 870ha`) et le modèle restitue la
référence commerciale avec son tiret (`DIR-600`, `P-870HA`). Sous A, le modèle est noté
**faux alors qu'il a donné la référence exacte**. Deux conséquences :

1. **À publier tel quel** : « M1 = 0,167 sous le critère publié A ; 0,333 sous le
   critère P qui neutralise l'artefact de séparateur ». La cible de 0,70 est manquée
   **dans les deux cas** — la conclusion ne dépend donc pas du critère.
2. **L'écart A−P est un livrable en soi** : il chiffre la part de la « non-reconnaissance »
   qui n'est qu'un **défaut de notation**. Ici, une bonne moitié de M1 sous A est de
   l'artefact, pas de la perception.

### §18.5 Ce que §18 impose au pipeline

1. **Le prompt est presque épuisé** (plafond +7,6 pt image, +6 objets). Il faut le
   corriger — c'est gratuit — mais **il ne portera jamais M1 à 0,70**.
2. **Le vrai gisement est le corpus / la collecte** : 49 des 65 échecs image et 26 des
   32 objets ratés n'ont aucune référence textuelle dans l'image. Cela plaide pour un
   corpus où la marque ou la référence est **effectivement photographiée** (face, fond,
   étiquette, silkscreen), pas seulement un objet nu sur fond blanc.
3. **Le routage par signal devient la voie principale, pas l'optimisation** — même
   conclusion que le §10.3, désormais quantifiée au niveau objet.

Preuves : `corpus/diagnose_identification.py` (étendu : `--run`, rollup objet) ·
`corpus/ocr-validation/results/diagnostic-identification-{v2,v4}.json` · copie dans
`evidence/2026-09-29/identification-benchmark/`.

---

## §19 — Avenant du 2026-09-29 (suite) : **M1 n'était pas M1**, et le canal de la
marque est identifié

### §19.1 Le défaut, trouvé en vérifiant une affirmation plutôt qu'un chiffre

Le §17.2 publiait `8/48 = 0,167` sous l'étiquette « **M1 (marque ET modèle)** ». En
vérifiant la fonction qui produisait ce nombre, l'étiquette ne correspondait pas à la
mesure :

```python
# benchmarks/run_identification.py, avant correction
ok = grading.model_correct(as_object_rec(rs[0], b, m), "A")   # ← modèle SEUL
```

`model_correct` **ne lit jamais `brand`**. Le banc publiait donc, sous le nom du chiffre
principal du projet, la variante `M1b` — et sur un barème qui n'est pas celui du M1
objet : `audit-grading.brand_correct` exige une **égalité stricte** de marque, alors que
`metrics.grade` (l'implémentation du §8.1) normalise `-` et `_` via `normalise()`. Deux
barèmes, un seul nom.

**Ce n'est pas un détail d'étiquetage : les deux lectures encadrent la même réalité et
la conclusion dépend de laquelle on cite.** `8/48` et `10/48` ne se remplacent pas
l'un l'autre, ils mesurent deux choses.

### §19.2 M1 à `n = 48`, corrigé

| corpus | M1 `conservative` (règle publiée) | M1 `answered` |
|---|---|---|
| publié, 26 objets (§8.1) | **8/26 = 0,308** IC [0,17 ; 0,50] | 12/26 = 0,462 IC [0,29 ; 0,65] |
| run2-v2, 48 objets | 9/48 = 0,188 IC [0,10 ; 0,32] | 14/48 = 0,292 IC [0,18 ; 0,43] |
| **v4 gelé, 48 objets** | **10/48 = 0,208** IC [0,12 ; 0,34] | **15/48 = 0,312** IC [0,20 ; 0,45] |
| v3b (2ᵉ exécution) | 10/48 = 0,208 | 15/48 = 0,312 |
| rejeu de contrôle ×2 | 10/48 = 0,208 | 15/48 = 0,312 |

**`10/48 = 0,208` est le M1 à citer**, pas `8/48`. La cible de 0,70 reste manquée d'un
ordre de grandeur, et la conclusion du §17 (« capacité absente, pas réglage ») n'est pas
affectée — elle est même renforcée, puisque le plafond `oracle_any` vaut `17/48 = 0,354`.

**Les deux règles de consolidation, et pourquoi les deux se publient.**

| règle | ce qu'elle compte | M1 (n = 48) |
|---|---|---|
| `conservative` | l'**abstention est une réponse** — c'est la règle des figures publiées | 10/48 = 0,208 |
| `answered` | l'abstention sort du vote ; un objet sans réponse est en échec | 15/48 = 0,312 |

Le prompt du projet **ordonne** l'abstention (« *Do NOT guess a brand you cannot see: an
invented brand is worse than an empty answer* »). Sous `conservative`, un modèle qui
obéit est donc noté plus mal qu'un modèle qui devine : la règle publiée mesurait, sans le
dire, une **politique d'abstention** autant qu'une capacité de reconnaissance. Publier une
seule des deux règles, c'est choisir cette politique en silence.

Répartition des verdicts (v4 gelé) :

| règle | `exact` | `brand_ok_model_no` | `brand_no_category_ok` | `faux` |
|---|---|---|---|---|
| `conservative` | 10 | 9 | 17 | 12 |
| `answered` | 15 | 10 | 11 | 12 |

### §19.3 La règle de consolidation n'était **pas dans le code** — et dépendait de l'ordre

Toutes les figures objet publiées avant cette date venaient de *heredocs éphémères* : la
table de verdicts a été conservée (`evidence/2026-09-14/corpus/object-results.json`),
mais **aucune fonction du dépôt ne la recalculait**. C'est la cause racine du §19.1 : un
second banc, ne trouvant rien à appeler, a écrit sa propre consolidation — et donc mesuré
autre chose.

Elle est désormais dans `iot_audit/corpus/metrics.py` (`consolidate_object`,
`object_results`, `modal`), **validée par reconstruction** :

* `8/26` est reproduit, et **les 26 verdicts individuels** avec lui
  (`tests/test_metrics_object.py`) ;
* la répartition publiée `{exact 8, brand_ok_model_no 2, brand_no_category_ok 13, faux 3}`
  est reproduite exactement.

**Deuxième défaut, trouvé en comparant deux consommateurs du même dépôt.** Le banc triait
ses lignes par `image_id` ; le comparateur de variante ne les triait pas. Les deux
publiaient... **10/48 et 11/48 pour la même donnée.** Motif : à 1–5 photos par objet, les
ex æquo sont fréquents (13 objets du run v4), et le départage retenu est « première valeur
rencontrée » — donc l'ordre d'entrée décidait du verdict. `philips__hue_white` a deux
photos, `PHILIPS` et `""` : exact dans un ordre, non dans l'autre.

Correction : `object_results` **prescrit** l'ordre. Il n'est pas inventé, il est dérivé du
corpus (`measure.build_manifest` gèle le manifeste par `ORDER BY object_id, image_id`) ; le
tri par `image_id` rend donc la fonction indépendante de l'ordre d'appel **sans déplacer
la table publiée**. Un test le verrouille (`test_m1_ne_depend_pas_de_lordre_dappel`).

**Effet secondaire utile** : une fois l'ordre prescrit, les quatre exécutions indépendantes
de la perception (v4, v3b, deux rejeux) donnent **toutes** `10/48`. Ce qui se lisait comme
de la non-déterminisme du modèle était le départage des ex æquo. Au niveau objet,
l'accord de rejeu est **1,000**.

### §19.4 Pourquoi la marque échoue : le canal est la **lisibilité**, pas la reconnaissance

C'est le résultat principal de cet avenant. En séparant les objets selon que le texte
imprimé est lisible dans les photos (`text_visible`, calculé **avant** toute prédiction) :

| objets | n | `exact` | `brand_no_category_ok` | `faux` |
|---|---|---|---|---|
| `text_visible = 1` | 17 | **9/17 = 0,529** | 3 | **0** |
| `text_visible = 0` | 31 | **1/31 = 0,032** | 14 | 12 |

Et au niveau image, où les deux champs se séparent :

| images | n | `brand` juste | `brand` non vide | `model` juste |
|---|---|---|---|---|
| `text_visible = 1` | 47 | **36/47 = 0,766** | 0,809 | 17/47 = 0,362 |
| `text_visible = 0` | 97 | **10/97 = 0,103** | 0,196 | 23/97 = 0,237 |

**La lecture est nette : le champ `brand` suit la lisibilité (×7,4), le champ `model` ne la
suit pas (×1,5).** Le système **lit** la marque ; il ne la **reconnaît** pas. Deux exemples
nommés, sur les objets les plus représentés du corpus :

* `amazon__echo_dot` (41 photos) : `text_visible=1` → `amazon`/`Amazon` **12/12** ; `text_visible=0` → vide **25/29**.
* `apple__homepod` (16 photos) : `text_visible=1` → `Apple` **2/2** ; `text_visible=0` → vide **14/14**.

Sur `text_visible=0`, **zéro** objet est `faux` quand le texte est lisible, contre 12 quand
il ne l'est pas : ce n'est pas une dégradation progressive, c'est un canal qui s'éteint.

### §19.5 Résultats négatifs — ce qui ne marche pas, mesuré

Trois leviers ont été essayés. Aucun ne tient ; les publier évite qu'on les retente.

1. **Le dictionnaire CPE comme a priori de marque : 0/22.** Résoudre la marque des 22
   objets à marque vide par les 1 839 235 entrées de `corpus/cpe.sqlite` donne **0**
   résolution correcte en recherche par jeton — et **17 propositions fausses**. Motif
   instructif : `Echo Dot` ressort `dnnsoftware`, `HomePod mini` ressort `minio`,
   `Google Home Mini` ressort `onlyoffice`. Le CPE est dominé par des entrées
   **logiciel/OS**, et « Echo » y est un module DNN : rien dans la chaîne du modèle ne dit
   qu'on cherche du matériel grand public. En correspondance **exacte** le rendement monte à
   `3/22` (`echo_dot`, `echo_plus`, `echo_show` → amazon) mais sur les 5 produits trouvés,
   **2 sont faux** (`dir_645` → `microsoft` — « Xbox 360 » *est* un produit Microsoft ;
   `verisure__smartplug` → `tp-link` — « smart plug » n'est pas une référence). Le CPE
   n'est pas un annuaire de marques grand public : c'est la cause du §17.4 (R7) mesurée ici
   pour la première fois. Sonde reproductible :
   `evidence/2026-09-29/m1-canonical/probe-cpe-brand-prior.py`.
2. **Le prompt « dis la marque d'un produit que tu reconnais » (v5) : +1 objet.**
   `11/48 = 0,229` contre `10/48` pour le run gelé, soit **un objet**, avec des intervalles
   qui se recouvrent massivement (IC [0,13 ; 0,37] contre [0,12 ; 0,34]). Sous la règle
   `answered`, l'écart est **nul** (15/48 des deux côtés). Le gain image est réel mais il ne
   traverse pas l'agrégation objet.
3. **L'ensemble de deux prompts ne peut pas aider.** `v4` et `v5` **s'abstiennent sur les
   mêmes photos** : sur `amazon__echo_dot`, `v4` dit `""` sur 25 photos et `v5` sur 23 — et
   les photos concernées sont les `text_visible=0`. L'abstention est déterminée par
   l'**image**, pas par la formulation : deux prompts voient la même photo. Combiner des
   variantes de prompt ne peut donc pas fabriquer l'information absente.

### §19.6 Ce que §19 impose

1. **Citer `10/48 = 0,208`** (règle publiée) et, à côté, `15/48 = 0,312` (abstention
   retirée), en nommant la règle. Toute citation de « M1 » sans sa règle de consolidation
   est incomplète.
2. **`8/48 = 0,167` ne doit plus apparaître** nulle part comme M1 (§17 est marqué périmé).
3. **Le levier n'est pas le prompt, ni l'agrégation, ni un a priori de marque.** Le §17.5
   concluait « le gisement est le corpus » ; §19.4 le **localise** : il faut des photos où
   la marque est **effectivement lisible** (face, étiquette, sérigraphie). Sur
   `text_visible=1`, le système est déjà à `0,529` au niveau objet, et `0` `faux`.
4. **Un corpus sans texte ne peut pas être sauvé par la marque** : la reconnaissance
   visuelle de marque n'existe pas dans ce modèle, et ce n'est pas une opinion — c'est
   `0,103` de marque juste sur 97 photos, contre `0,766` sur 47.

Preuves : `benchmarks/results.{json,md}` · `benchmarks/recognition-v5.{json,md}` ·
`tests/test_metrics_object.py` · `iot_audit/corpus/metrics.py` (§ « Consolidation par
objet ») · copies dans `evidence/2026-09-29/m1-canonical/`.

---

## §20 — Avenant du 2026-09-29 : **audit des figures de 2026-09-14** contre le barème
canonique

### §20.1 Pourquoi cet audit, et ce qu'il visait

Le §19 a montré que la règle de consolidation des objets n'était **pas dans le code** :
toutes les figures objet publiées avant le 2026-09-29 venaient de *heredocs éphémères*.
Impossible, donc, de savoir **lesquelles** sont encore valides sans les recalculer toutes.

Cet avenant le fait : chaque figure des §8, §9, §10 et §14 a été recalculée avec
`iot_audit.corpus.metrics` (l'unique implémentation du dépôt) et comparée, cellule par
cellule, à ce qui est écrit. L'outil est reproductible et versionné :
`benchmarks/object_figures.py`.

### §20.2 Le résultat : le corpus de 2026-09-14 est **massivement reproductible**

C'est la conclusion principale, et elle est favorable : les *heredocs* de cette session
utilisaient **la même règle** que celle désormais encodée. Recoupé figure par figure :

| figure | section | valeurs publiées | recalcul canonique |
|---|---|---|---|
| M1 strict (objet) | §8.1, §9.5 | `8/26 = 0,308` IC [0,165 ; 0,500] | **identiques** |
| M1 modèle seul (objet) | §8.1, §9.5 | `10/26 = 0,385` IC [0,224 ; 0,575] | **identiques** |
| M1 modèle ≥ 1 photo (objet) | §8.1 | `16/26 = 0,615` IC [0,425 ; 0,776] | **identiques** |
| M1 catégorie seule (objet) | §8.1, §9.5 | `21/26 = 0,808` IC [0,621 ; 0,915] | **identiques** |
| canal image `text_visible=1` | §8.2, §9.2 | 0,593 · 0,704 · 0,926 | **identiques** |
| canal image `text_visible=0` | §8.2, §9.2 | 0,065 · 0,304 · 0,935 | **identiques** |
| accord marque / modèle | §8.4 | 0,915 · 0,840 | **identiques** |
| latence p50 / p95 / max | §8.4 | 2,242 · 3,895 · 5,462 s | **identiques** |
| M6 colonne `M1 strict` (5 lignes) | §9.3 | 8/6/7/8/2 sur 26 | **identiques** |
| M2 / M2b | §9.5 | 0,304 / 0,704 + IC | **identiques** |
| corpus étendu, image (`M1 strict`, modèle, catégorie) | §10.2 | 11/144 · 32/144 · 115/144 | **identiques** |
| corpus étendu, **objet** « modèle ≥ 1 photo » | §10.2 | `10/48 = 0,208` | **identique sous `audit-grading` A** ; **`21/48 = 0,438` sous `metrics`** — voir §20.5 |
| M3 par strate | §10.3 | review 0,085/0,248 · forum 0/12 · official 0/3 | **identiques** |
| courbe M6 (7 points) | §10.5 | 0,096→0,000 · 0,315→0,041 | **identiques** |
| tableau par catégorie (**35 cellules**) | §14.1 | 5 métriques × 5 catégories + agrégats | **identiques** |

**35 cellules** du seul §14.1 se recalculent à l'identique, agrégat compris — y compris le
`0,826` de la catégorie, qui suppose l'application de `TRUTH_CATEGORY_OVERRIDES`
(`google__nest_doorbell` → `ip_camera`). Un chiffre calculé avec la mauvaise catégorie ne
tombe pas juste par hasard.

**Conséquence** : le corpus de 2026-09-14, sa mesure et ses ventilations **n'ont pas à
être refaits**. Ce qui était faux, c'est le chiffre **agrégé de l'avant-veille** (§17,
`8/48` qui n'était pas M1) — pas la mesure d'origine.

### §20.3 Ce qui était faux, et qui est corrigé **sur place**

| # | figure | publié | recalculé | effet sur le verdict |
|---|---|---|---|---|
| 1 | §9.3, M6 flou r=3, colonne **modèle seul** | `6/26 = 0,231` (Δ +15,4 pt) | **`5/26 = 0,192`** (Δ **+19,2 pt**) | **aucun** — le flou reste le seul point de rupture, et il l'est plus |
| 2 | §8.3, images « modèle juste, marque vide, `unidentifiable` » | « **17** » (sans critère) | **16** sous **A** ; 17 sous **P** | **aucun** — mais la ligne nomme désormais son critère |
| 3 | §9.5, M8 latence p95 | `3,898 s` | **`3,895 s`** | aucun (le §8.4 donnait déjà 3,895) |
| 4 | §10.4, « toutes images » v2 et `no_text` v2 | `62/144`, `0,423` | **`63/144`**, **`0,433`** | aucun — **déjà relevé au §13.2 bis** ; pointeur ajouté sur place |

**Aucun verdict ne change.** Les quatre corrections portent sur des numérateurs, jamais sur
les conclusions — et trois des quatre étaient invisibles à l'œil nu. C'est exactement ce
qu'un audit chiffré doit produire.

Le défaut nº 2 est le plus instructif : `17` **n'était pas faux**, il était **non
qualifié**. La correction n'est pas un chiffre, c'est un **critère**. C'est la même classe
de défaut que le §18.4 et le §19.2, et elle a la même cause — une figure publiée sans son
barème.

### §20.4 Défaut de code trouvé en chemin : `per_field_agreement` lisait le mauvais niveau

En cherchant à reproduire l'accord du §8.4, l'appel naturel du dépôt :

```python
metrics.per_field_agreement(rows, "brand")   # -> 1.000  (faux)
```

La fonction lisait `r.get(fieldname)` — la **racine** de l'enregistrement — alors que les
prédictions sont sous `pred`. Le champ n'existant jamais à la racine, elle renvoyait
**toujours `1,000`** : un accord parfait pour un jeu où rien ne l'est.

* **Aucune figure publiée n'est affectée** : la fonction n'était appelée **nulle part**
  (vérifié par recherche sur tout le dépôt).
* **Le piège était armé** : l'accord réel du §8.4 vaut `0,915` / `0,840`; l'appeler
  aurait publié `1,000` / `1,000`.
* Fonction **corrigée** (lecture sous `pred`), et **verrouillée** par deux tests, dont un
  qui fixe `0,915` / `0,840` sur le corpus publié.

### §20.5 Le résultat structurel : le document mélange **trois** combinaisons (niveau, barème)

C'est la découverte la plus utile de cet audit, et elle n'apparaît dans aucun tableau : les
figures du document ne sont pas toutes calculées avec le même barème **ni au même niveau**.
En recalculant les unes et les autres, la correspondance est sans ambiguïté :

| section | niveau | barème qui **reproduit** |
|---|---|---|
| §8.1, §9.5 — M1 / M1b / M1c | **objet** | `metrics.grade` : inclusion bidirectionnelle, `normalise` (tirets → espace) |
| §8.2, §9.2 — canal `text_visible` | image | idem `metrics` (`model` = **19/27** et **14/46**) |
| §9.3 — colonne « M1 strict » | **objet** | idem `metrics` |
| §10.2, §10.4, §10.5, §14.1 | image (+ **1** ligne objet) | `audit-grading` **A** (`model` = 32/144, 63/144, 23/73…) |

Les deux barèmes donnent, sur **le même run et le même périmètre**, des chiffres qui
diffèrent d'un facteur 2 sur le champ `model` :

| figure, run v1 (73 images) | `metrics` | `audit-grading` A |
|---|---|---|
| `model` juste, `text_visible=1` | **19/27 = 0,704** | 10/27 = 0,370 |
| `model` juste, `text_visible=0` | **14/46 = 0,304** | 13/46 = 0,283 |

**Ce n'est pas une erreur d'arithmétique** : chaque section reproduit ses propres chiffres.
C'est un défaut d'**étiquetage**, et il a une conséquence précise : le §10.2 intitule son
propos « le chiffre redescend, l'échantillon initial était flatteur » et **compare des
lignes image en `audit-grading` A à des lignes objet en `metrics`** (§8.1). Les deux
changements — de niveau *et* de barème — vont dans le même sens, donc la conclusion tient ;
mais elle est établie sur deux mesures qui ne sont pas la même mesure.

**Ce que le §20.5 ne fait pas** : il ne remplace pas les chiffres publiés par ceux de
l'autre barème. Les deux barèmes sont légitimes (le §15.6 publie A *et* P) ; ce qui manquait
dans chaque section, c'est le **nom**. La règle qui en sort est celle du §19.2, étendue :
**toute figure doit nommer son niveau et son barème**, sinon elle est incoherente avec la
moitié du document.

> **Suivi (§21.4).** L'attribution ci-dessus est un premier classement, fait à la main ;
> la mesure l'a corrigé sur deux points. Le §10.2 n'est pas « image × A » en bloc : sa
> ligne `catégorie` est en **`metrics`** (`115/144`). Et le §14.1, lui, l'est bien en **A**
> (`119/144 = 0,826`). Le lecteur pressé doit lire le §21.3, qui est la table de
> référence.

### §20.6 Ce que §20 impose

1. **Le corpus de 2026-09-14 reste citable tel quel**, à l'exception des quatre cellules
   ci-dessus — qui sont corrigées **dans le texte**, pas dans une note.
2. **Toute figure objet doit nommer sa règle de consolidation** (§19.2) : `conservative`
   (l'abstention compte, règle publiée) ou `answered`. Aucune figure de 2026-09-14
   n'utilise `answered` ; elles sont toutes en `conservative`.
3. **Toute figure de modèle doit nommer son critère** : les corrections nº 1 et nº 2 sont
   toutes deux des mélanges A/P silencieux. Le recalcul les rend visibles.
4. **`benchmarks/object_figures.py` est l'outil d'audit** : il prend n'importe quel
   fichier de prédictions et rend ces figures en Markdown, pour comparer sans écrire de
   heredoc. Ses figures objet sont en `metrics` ; les figures image du §10/§14 se
   vérifient avec `audit-grading` (voir §20.5).
5. **Nommer le niveau *et* le barème** sur toute figure neuve : `objet`/`image` ×
   `metrics`/`audit-grading` A/P. Le §20.5 montre qu'un document peut être entièrement
   reproduisible et pourtant incohérent d'une section à l'autre. **Appliqué rétroactivement
   au §21**, qui étiquette les §8–§14 et re-dérive le §10.2.

Preuves : `benchmarks/object_figures.py` · sorties dans
`evidence/2026-09-29/corpus-2026-09-14-audit/` (v1 26 objets, v1 + perturbations M6,
corpus étendu, courbe M6) · `tests/test_metrics_object.py` (53 tests).

---

## §21 — Avenant du 2026-09-29 : **étiquetage (niveau, barème)** des figures §8–§14, et §10.2 re-dérivé

### §21.1 Pourquoi

Le §20.5 a trouvé que le document mélange trois combinaisons (niveau, barème) ; le §20.6
en a tiré une règle — *toute figure doit nommer son niveau et son barème*. Cet avenant
l'**applique rétroactivement** : chaque tableau de figure des §8 à §14 porte désormais
son étiquette (§21.3), et le §10.2 — le seul qui comparait deux corpus **à deux niveaux
et deux barèmes** — est re-dérivé à périmètre et barème constants (§10.2 bis).

L'étiquetage n'est **pas** déduit du §20.5 : il est **mesuré**. `probe-niveau-bareme.py`
recalcule les quatre combinaisons — (objet / image) × (`metrics` / `audit-grading` A) — sur
**les trois exécutions** de 2026-09-14 (v1 26 objets, v1 48 objets, v2 48 objets), plus les
ventilations par strate, et nomme pour chaque figure publiée la combinaison qui la
reproduit à la cellule près.

### §21.2 La convention

Une ligne, placée juste avant chaque tableau :

```
> **Niveau × barème :** …
```

avec trois axes, et rien d'autre :

* **niveau** — `objet` (consolidé, la seule unité où l'IC de Wilson est valide, §7.3) ou
  `image` (chaque photo vote, sans consolidation) ;
* **barème** — `iot_audit.corpus.metrics` (sous-chaîne bidirectionnelle sur `normalise()`,
  tirets → espace) ou `audit-grading` **A** / **P** (le barème vendu,
  `VENDORED-audit-grading.md`) ;
* **règle de consolidation** — obligatoire dès que le niveau est objet : `conservative`
  (l'abstention compte) ou `answered` (§19.3).

Une figure sans ces trois axes est désormais **une figure incomplète**, pas une figure
légèrement approximative : la moitié du document est calculée de l'autre façon.

### §21.3 L'attribution, mesurée

| section | figure publiée | niveau | barème | règle | exécution |
|---|---|---|---|---|---|
| §8.1 | `M1` / `M1b` / `M1c` | **objet** | `metrics` | `conservative` | v1, 26 obj |
| §8.2 | canal `text_visible` | image | `metrics` | — | v1, 73 img |
| §8.3 | les 16 images « modèle juste, marque vide » | image | **A** | — | v1, 73 img |
| §8.4 | accord marque / modèle `0,915` / `0,840` | image *dans l'objet* | **aucun** (chaîne brute, mode modal) | — | v1, 26 obj |
| §8.4 | latences p50 / p95 / max | requête | — (secondes) | — | v1, 73 img |
| §8.4, §14.4 | `M7` `InventedBrandRate` | revue humaine | — | — | v1 |
| §9.2 | canal `text_visible` | image | `metrics` | — | v1, 73 img |
| §9.3 | `M6` (col. `M1 strict` et `modèle seul`) | **objet** | `metrics` | `conservative` | v1, perturbations |
| §9.4 | `M9` rejeu | image | **comparaison brute** | — | v1 ×2 |
| §9.5 | `M1` / `M1b` / `M1c` | **objet** | `metrics` | `conservative` | v1, 26 obj |
| §9.5 | `M2` / `M2b` | image | `metrics` | — | v1, 73 img |
| §10.2 | `M1 strict`, `modèle seul` | image | **A** | — | **v1**, 144 img |
| §10.2 | `catégorie` | image | **`metrics`** | — | **v1**, 144 img |
| §10.2 | objet, modèle ≥ 1 photo | **objet** | **A** | ≥ 1 photo | **v1**, 48 obj |
| §10.3 | par strate | image | **A** | — | **v1** |
| §10.4 | modèle seul, v1 → v2 | image | **A** | — | v1, v2 |
| §10.5 | courbe `M6` (7 points) | image | **A** | — | **v1**, 73 img |
| §14.1 | `modèle (P)` | image | **P** | — | **v2**, 144 img |
| §14.1 | `modèle (A)`, `strict (A)`, `marque` | image | **A** | — | **v2**, 144 img |
| §14.1 | `catégorie` | image | **A** | — | **v2**, 144 img |
| §14.2 | exactitude sous A et P | image | **A**, **P** | — | v1, v2 |

L'exécution compte autant que le barème : le §10.2 est en **v1** et le §14.1 en **v2**, si
bien que deux figures du même champ — `catégorie` — diffèrent à la fois par le prompt *et*
par le barème.

### §21.4 Correction du §20.5 lui-même, et sa conséquence

Le §20.5 rangeait « §10.2, §10.4, §10.5, §14.1 » dans **un seul** groupe
(`audit-grading` A). La mesure le précise :

* **§10.2, ligne `catégorie`** = `115/144` = **`metrics`** ; sous A elle vaut `114/144`. Le
  §10.2 est donc, à lui seul, **trois** combinaisons (image/A, image/`metrics`, objet/A).
* **§14.1, ligne `catégorie`** = `0,826` = `119/144` = **A** (override de vérité terrain
  compris) ; sous `metrics` elle vaut `0,833` (`120/144`).

C'est plus qu'une coquille de classement : **le même champ `catégorie` change de barème
entre le §10.2 (v1, `metrics`) et le §14.1 (v2, A) sans que rien ne le signale.** Un lecteur
qui suit l'évolution de la catégorie d'un avenant à l'autre compare `0,799` et `0,826` en
croyant lire une progression du modèle : il lit aussi un changement d'instrument. Les deux
lignes sont désormais étiquetées.

**Un troisième sigle ambigu, du même genre.** Le §8.4 intitule ses deux premières lignes
« Accord marque `(A)` / Accord modèle `(A)` ». Le document définit `A` comme un **critère de
notation** (§15.6) ; ici `(A)` abrège **accord**. Mesuré, les deux lectures ne se
ressemblent pas : accord modal brut `0,915` / `0,840`, critère A `0,405` / `0,144`. Les deux
lignes portent maintenant `(A = accord)` et le §8.4 dit lequel des deux nombres il publie.

### §21.5 Le §10.2 re-dérivé — ce qui survit, et ce qui était trop fort

La re-dérivation complète est au **§10.2 bis**. Le résultat, en deux lignes :

* **survit** — sous les **neuf** combinaisons mesurables, la valeur centrale **baisse**
  quand le corpus passe de 26 à 48 objets, et **aucune** combinaison ne rapproche la borne
  inférieure de la cible de 0,70 ;
* **tombe** — « l'échantillon initial était flatteur » : **aucun** des neuf intervalles de
  Wilson ne se sépare. Le corpus étendu ne contredit pas le petit ; il en donne une mesure
  plus basse et plus précise. La phrase publiée affirmait une séparation que les données
  ne portent pas.

C'est exactement la forme du défaut nº 2 du §20.3 : le chiffre était bon, la **force** de
la conclusion ne l'était pas, et c'est le barème qui manquait.

### §21.6 Ce que §21 impose

1. **Toute figure des §8–§14 porte son étiquette** (niveau × barème × règle × exécution),
   sur la ligne qui précède le tableau. L'attribution est celle du §21.3, et elle est
   reproductible par `probe-niveau-bareme.py`.

   Et **aucun sigle ne reste ambigu** : le §8.4 intitulait deux lignes « Accord … `(A)` »,
   alors que le document définit `A` comme un **critère**. C'était *accord* ; la ligne dit
   maintenant lequel des deux, parce que les deux nombres (`0,915` contre `0,405`) n'ont
   rien à voir.
2. **Le §10.2 ne se cite plus sans son étiquette** : ses quatre lignes ne sont pas au même
   niveau ni au même barème, et sa ligne `catégorie` est en `metrics`.
3. **Toute figure neuve** nomme les trois axes (§20.6.5, désormais outillé).
4. **Une conclusion ne se durcit pas plus que son intervalle** ne le permet : le §10.2 bis
   en donne l'exemple publié, et le §12.5 en donnait déjà la règle.

Preuves : `evidence/2026-09-29/corpus-2026-09-14-audit/probe-niveau-bareme.py` et sa sortie
`06-grille-niveau-bareme.log` (grille complète, ventilations, comparaisons 26 → 48 à
périmètre constant) · `probe-courbe-M6-image.py` (les 7 points du §10.5, tous `OK`).

---

## §22 — Avenant du 2026-10-05 : le cap devient « IoT ou non, catégorie sans marque »

### §22.1 La directive

> « reconnaître la catégorie d'un objet et savoir si c'est un objet connecté est essentiel.
> Le prochain travail doit être d'augmenter les résultats de reconnaissance **sans lecture
> des marques**, juste en regardant des objets. Lire une marque sera toujours possible par
> l'auditeur mais pour cela il faut qu'il soit averti que l'objet a un intérêt, i.e.,
> déterminer si un objet est un IoT. » — Thomas Vantroys, 2026-10-05

Conséquence : la marque n'est plus la première porte de la chaîne. Elle devient :
**photo → {catégorie, « IoT ou non »} → (si IoT) photo de la marque par l'auditeur → fiche
produit → failles**. M1 (§17–§19) reste publié — il mesure la fin de la chaîne — mais il
n'est plus l'unique mesure qui décide du succès du projet.

### §22.2 Ce que la mesure donne déjà, sans attendre de nouvelles photos

Sonde `evidence/2026-10-05/category-without-brand/probe-category-no-text.py` (sortie et
JSON joints), sur le run v4 **gelé**, barème `audit_grading` pour les images et règle de
consolidation de M1 (`conservative`) pour les objets :

| niveau | `text_visible` | catégorie juste | marque juste |
|---|---|---|---|
| image | 1 (47 photos) | **47/47 = 1,000** | 36/47 = 0,766 |
| image | 0 (97 photos) | **75/97 = 0,773** | 10/97 = 0,103 |
| objet | 1 (17 objets) | **17/17 = 1,000** IC [0,816 ; 1,000] | 14/17 = 0,824 |
| objet | 0 (31 objets) | **18/31 = 0,581** IC [0,408 ; 0,736] | 5/31 = 0,161 |

Trois faits à retenir :

1. **Sans texte, la catégorie survit quand la marque s'éteint** (0,581 contre 0,161, ×3,6) :
   c'est le seul canal que la directive peut exploiter tel quel.
2. **Il n'est pas fini** : sans texte, `router_ap` tombe à 8/18 = 0,444 IC [0,246 ; 0,663],
   les enceintes tiennent à 7/7 = 1,000, et la répartition des 97 photos sans texte
   s'écrase sur `smart_speaker` (64/97). La confusion routeur ↔ enceinte du §17 se paie ici.
3. **La catégorie est juste même quand la marque est fausse** (13/26 = 0,500 des objets :
   le type d'objet est un signal indépendant du texte, contrairement à la marque.

Le §22.6 explique **d'où vient** ce 58,1 % — et pourquoi ce n'est ni un problème
d'agrégation ni un problème de prompt.

### §22.3 Le protocole du corpus mixte (« IoT ou non ») — à valider par le tuteur

« IoT ou non » **ne se mesure pas sur le corpus actuel : 48/48 objets sont connectés.**
Protocole proposé, coût 0 € (objets du quotidien, aucun achat) :

* **60 objets** : 30 objets connectés (dont ceux du corpus) + 30 objets non connectés
  (mug, livre, chaise, stylo, plante…) ;
* **deux photos par objet** : une où un texte imprimé est lisible, une où il ne l'est pas —
  le plan est donc 2 classes × 2 conditions (120 photos minimum) ;
* drapeau `text_visible` calculé par OCR **et gelé avant** toute prédiction, comme pour le
  corpus (même règle de drapeau) ;
* mesures **au niveau objet**, IC de Wilson : rappel IoT, précision, exactitude équilibrée ;
  et, sur le sous-ensemble IoT sans texte, l'exactitude de catégorie du §22.2.

Dimensionnement (règle du §1.1, outillée par `metrics.minimum_n_for_target`) :
* pour la **catégorie sans texte** (cible borne inférieure ≥ 0,70) : avec 30 objets, la
  revendication « ≥ 70 % » n'est démontrable que si le taux mesuré est ≈ 0,85 ; avec
  p̂ ≈ 0,80 il faut 77 objets ;
* pour le **rappel IoT** (cible proposée ≥ 95 %) : sur les 30 objets connectés, même un
  score parfait de 30/30 ne donne qu'une borne inférieure de Wilson de **0,887**
  (`wilson(30, 30) = [0,8865 ; 1,000]`). Pour borner rigoureusement un rappel à ≥ 95 %
  sous la règle du projet, il faut **au minimum n = 73 objets connectés sans aucune erreur**
  (73/73 donne LB = 0,950), ou n = 173 si p̂ = 0,98. Avec 30 objets, le rappel de 95 % est
  donc une **cible empirique** (p̂), pas une borne d'intervalle démontrable.

Le protocole fixe donc ces distinctions **avant** la collecte.

**Cibles proposées, en avenant au CDC (arbitrage tuteur — Q9)** :

* **rappel IoT ≥ 95 %** (taux observé p̂ sur 30 objets connectés, ou borne inférieure si le corpus est étendu à 73+) — un faux « non-IoT » éteint l'alerte, c'est l'erreur qui coûte ;
* **catégorie sans texte : borne inférieure ≥ 70 %** sur le sous-ensemble IoT, mesurée avec
  `n` suffisant (30 objets si le taux observé tient ≈ 0,85).

### §22.4 Leviers à essayer, dans l'ordre — et ce qui est déjà exclu

1. **Prompt v6 — prêt, non lancé** : `corpus/make_runner_v6.py` génère
   `corpus/runner6-v6-triage.py` (écrit et vérifié le 2026-10-05). Le prompt et le
   schéma ne demandent plus que `{view, category, iot}` — ni marque, ni modèle ;
   `view` (objet entier vs détail/close-up) est la variable qui explique l'essentiel
   des échecs du §22.6, et elle sera publiée par le run. Items, température, graine
   et plafond sont ceux de v4 **à l'octet près** (items sha256 `fbc6abe3…`).
   À lancer sur un nœud ; sur les 144 photos actuelles il mesure la catégorie sans
   marque et le taux de faux « non-IoT » ; la spécificité exige le corpus mixte du
   §22.3.
2. **Collecte ciblée** : plus d'angles pour `router_ap` (8/18 sans texte) — la confusion
   routeur/enceinte est un défaut de point de vue, pas de formulation.
3. **Déjà exclu par la mesure** : prompt « dis la marque » (v5, +1 objet), a priori CPE
   (0/22), ensemble de deux prompts (§19.5). Ne pas les réessayer sans raison neuve.

### §22.5 Ce que §22 change dans les autres documents

* **CDC** : AC13 **proposé** (« déterminer si un objet est connecté ») et AC1 requalifié
  (catégorie sans texte lisible) — cet avenant est soumis à l'arbitrage du tuteur (Q9) et
  ne sera intégré formellement au CDC que sur sa validation ; le CDC v3.1 reste la référence
  en vigueur.
* **État d'avancement** : les chiffres du §22.2 sont citables (ils portent niveau, barème et
  règle d'abstention) ; le §22.3 est un **protocole**, pas un résultat — sa moitié non-IoT
  a été exécutée le 2026-10-06 (**§22.7**), sans la condition de texte.
* **Preuves** : `evidence/2026-10-05/category-without-brand/` (sonde, sortie, JSON, LIRE-MOI) ;
  `evidence/2026-10-06/` (run v6 live, B9 inter-nœuds, **protocole de spécificité §22.7**).
* La règle « Niveau × barème » du §21 s'applique telle quelle à toute figure du nouveau banc.

### §22.6 Diagnostic : d'où vient le 58,1 %, et ce qui n'est pas le levier (2026-10-05)

Sonde `evidence/2026-10-05/category-without-brand/probe-category-diagnosis.py` (+ `.log`,
`category-diagnosis.json`), mêmes entrées gelées que §22.2. Objets sans texte, règle
`conservative`.

1. **Pas de paradoxe d'agrégation.** Les photos des objets sans texte valent 87/108 =
   0,806, les objets 18/31 = 0,581. Mais 29/31 objets sont **unanimes** (accord 1,0),
   2 majoritaires, **zéro divisé** — et le plafond « au moins une photo juste » vaut
   exactement 18/31, le résultat modal. **Aucun objet n'est récupérable par le vote** :
   quand un objet est faux, *toutes* ses photos sont fausses. Le levier n'est pas
   l'agrégation.
2. **C'est un problème de type de vue.** Par strate : `review` 15/18 = 0,833
   IC [0,608 ; 0,942] ; `forum` (démontages, cartes) 1/11 = 0,091 IC [0,016 ; 0,377] ;
   `official` 2/2. Les confusions sont dominées par les cartes du routeur Zyxel
   P-2602HW (`router_ap` → `other` ×7, → `smart_speaker` ×3) et deux caméras isolées.
3. **Le canal « étiquette » n'est pas tranché comme signal.** 37 photos sans texte
   déclarent `identification_basis = label` (dont 20 ressemblent à des close-ups de
   carte/puce, heuristique de nom de fichier). Brut : catégorie 18/37 = 0,486 contre
   57/60 = 0,950 en `visual` (IC disjoints) — mais le contrôle enlève l'effet :
   `review` hors close-ups donne 12/16 = 0,750 IC [0,505 ; 0,898] contre 51/52 = 0,981
   IC [0,899 ; 0,997] (limite), et en retirant aussi `amazon__echo_dot` (dont les 12
   photos sont des vues de carte) les intervalles **se recouvrent** : NON TRANCHÉ.
   Conclusion publiée : l'explication dominante est le **type de vue**, pas un canal
   d'hallucination distinct. Un `view` auto-déclaré (v6) remplacera l'heuristique.
4. **Ce n'est pas le prompt.** Catégorie sans texte (objets) par version de prompt :
   v1 19/31 = 0,613, v2 20/31 = 0,645, v4 18/31 = 0,581, v5 19/31 = 0,613 — quatre
   intervalles qui se recouvrent. C'est une propriété du modèle et du corpus, pas de
   la formulation.

**Conséquences pratiques** : (a) la collecte du §22.3 doit imposer des photos de
l'objet **entier** et publier le type de vue ; (b) la cible « catégorie sans texte »
se juge sur des photos de produit, pas sur des démontages ; (c) le v6 (levier 1) est
le bon premier essai, et son champ `view` est aussi un instrument de diagnostic.

### §22.7 « IoT ou non » : les DEUX critères de §22.1 mesurés (2026-10-06)

Le §22.2 mesurait la catégorie et la marque ; le §22.3 restait un **protocole**.
La moitié non-IoT du §22.3 a été exécutée le 2026-10-06, en direct sur le cluster, et
les deux critères de la directive du tuteur ont désormais une valeur **mesurée**.

| critère | mesure | valeur | IC Wilson 95 % | source |
|---|---|---|---|---|
| **rappel** IoT (48 objets connectés) | objets détectés connectés | 47/48 = 0,979 | [0,891 ; 0,996] | v6 live, corpus gelé |
| **spécificité** — vote brut du modèle | « non connecté » **et** catégorie `other` | 30/30 = **1,000** | [0,886 ; 1,000] | protocole §22.3, moitié non-IoT |
| spécificité — décision **consolidée** | négatif après la règle rappel-d'abord | 6/30 = 0,200 | [0,095 ; 0,373] | idem |
| spécificité — vue **globale** seulement | vote brut restreint à `view=whole` | 6/6 = 1,000 | [0,610 ; 1,000] | idem |

**Lecture — et c'est le résultat important de la journée.** Le modèle **sait dire
« non connecté »** : 30/30 objets du quotidien (mug, livre, chaise, guitare, vélo,
échelle, poêle, montre à aiguilles…) reçoivent `iot=false` et `category=other`, sans
un seul faux positif, avec une borne basse de Wilson de 0,886 qui **exclut** la
spécificité médiocre. L'écart entre 1,000 et 0,200 n'est **pas** un défaut du modèle :
24 des 30 photos sont classées `view=detail` (plans serrés d'objet), et la règle
rappel-d'abord alerte par défaut sur un fragment — c'est le coût assumé du §22.6.
Quand la photo montre l'objet **entier**, le chiffre remonte à 6/6.

Trois conséquences opérationnelles :

1. **La consigne de prise de vue du §22.3 n'est pas un confort, c'est une exigence** :
   photographier l'objet entier fait passer le coût de vérification humaine de 24/30 à
   6/30 sur ces objets. Elle doit être écrite dans le protocole de collecte, pas
   suggérée.
2. **Le rappel 47/48 et la spécificité 30/30 ne sont pas comparables en n** : 48 objets
   connectés contre 30 non connectés. La borne basse de 0,886 sur la spécificité est
   solide ; celle du rappel (0,891) repose sur 48 objets. Les deux sont publiées avec
   leur `n`.
3. **Ce qui reste non mesuré est nommé** : la condition de texte (« texte imprimé
   lisible » / « non lisible », drapeau OCR gelé **avant** prédiction) n'existe pas sur
   la moitié non-IoT — une photo par objet, aucun drapeau. Le §22.3 n'est donc pas
   intégralement exécuté ; les cibles proposées (rappel ≥ 0,95 ; catégorie LB ≥ 0,70)
   restent en arbitrage tuteur (Q9). Ce qui est publié ici sont des **mesures**, pas
   des cibles atteintes.

**Preuves** : `evidence/2026-10-06/specificity-protocol/` (script, JSON complet par
objet avec URL, licence et `sha256` ; images non redistribuées). Reproductible :
`benchmarks/live_specificity_protocol.py --n 30` ; la collecte et la mesure sont deux
phases séparées (`--collect-only`, cache disque) parce que Wikimedia plafonne les
requêtes (HTTP 429) et que le portier du campus coupe les tunnels.

### §22.8 Le cadrage est mesuré, et « combien d'objets » n'est pas la bonne question ; `identification_basis` ne vérifie rien (2026-10-06)

Deux des propriétés que ce document attendait sans les mesurer ont une valeur,
aujourd'hui. Les deux mesures portent un résultat **négatif**, et c'est leur intérêt :
elles interdisent une ligne de travail qui semblait acquise.

#### (a) P1 « une photo = un objet » : la sonde détecte, mais pas la bonne chose

Une sonde **séparée** (`salience-v1`, `corpus/make_runner_v7_salience.py`,
exécutée le 2026-10-06) a posé une seule question — « combien d'objets distincts
cette photo présente-t-elle ? » — aux 144 mêmes photos, sans toucher au manifeste v6
(`predictions-v6.json` inchangé, empreinte vérifiée avant/après ; items identiques à
l'octet). Résultats gelés : `evidence/2026-10-06/salience-probe/`.

| mesure | valeur |
|---|---|
| photos signalées `n_objects >= 2` | **68/144 = 47,2 %** |
| dont `view=whole` (objet entier) | 16/38 = 42,1 % |
| dont `view=detail` | 52/106 = 49,1 % |
| positif nommé d'avance — « Wemo smart plugs and switches » | 13 |
| positif nommé d'avance — « Echo Dot … with normal coffee mug » | 2 |

**Les deux positifs annoncés avant la mesure sont trouvés** — la sonde n'est donc pas
aveugle, et le critère de falsifiabilité est satisfait. Mais le taux de 47,2 % ne
dépend **pas** de la vue (42,1 % vs 49,1 %), ce qui dit ce que le modèle compte : des
objets **quelconques** — les composants d'une carte mère autant qu'une seconde
prise — et non des **appareils concurrents**. Une porte qui rejette 47 % du corpus,
dont 42 % des photos d'objet entier, détruirait des mesures valides pour tenir un
principe.

**Décision (mesurée, pas arbitrée à la main) : la campagne v7 n'est pas écrite.** Le
manifeste v6 reste le seul manifeste de triage, la porte `screen_frame` reste la seule
qui refuse, et le champ de cadrage est **étiqueté `unverified`** partout où le prompt
ne pose pas la question (docs/07 §5.1) au lieu de valoir « un objet » par défaut. La
question à poser n'est pas « combien d'objets » mais « combien **d'appareils de ce
type** » — formulation à écrire, puis à mesurer sur ces mêmes 144 photos.

#### (b) Divergence d'étiquette : le corpus ne valide pas le détecteur

`corpus/probe-label-divergence.py` (sortie gelée :
`evidence/2026-10-06/label-divergence/probe-output.txt`) applique les règles au
**corpus entier** — toutes les sorties réelles du dépôt — et rend d'abord une
propriété de forme que ce document n'avait pas écrite :

> 1008 enregistrements valides = **144 photos, mesurées 7 fois chacune**
> (3 nœuds + les passes par shards de v3, v3b et v4). Un taux calculé sur les
> enregistrements est gonflé par la répétition : la même photo peut y compter six
> fois. **L'unité publiée ici est la photo distincte.**

| règle | enregistrements | photos distinctes |
|---|---|---|
| A — la marque annoncée n'est pas dans le texte imprimé | 88/556 = 15,8 % | 15/94 = 16,0 % |
| B — A + `identification_basis == "label"` | 88 | 15 |
| C — B + un **autre vendeur connu** dans le texte (lexique cru) | 6 | **1** |
| C′ — idem, lexique livré (mots ordinaires refusés) | 0 | **0** |

**La règle A est inutilisable** (une photo sur six rétrogradée, dont des identifications
correctes). **La règle C du lexique cru ne pèse qu'une photo**, vue 6 fois :
`zyxel__p_870ha_vtu_r_2`, dont la façade porte « **POWER ALARM** 10/100 DUPLEX… » — le
vendeur CPE `alarm` (Alarm.com) y voit une marque. C'est un faux positif fabriqué par
le lexique, pas une divergence détectée ; le détecteur livré refuse donc `alarm` et
`free` (mots anglais ordinaires), et ne déclenche alors **sur rien** dans le corpus.
Il est câblé pour le cas qui l'a fait exister (un texte qui nomme une autre marque),
il n'est **pas** validé par la mesure, et les deux phrases sont écrites pour que
personne ne cite l'une sans l'autre.

Un chiffre antérieur (« 6 détections, 1,08 % ») a circulé avant cette sonde : il
comptait une photo six fois et prenait un mot ordinaire pour une marque. Il est
remplacé, pas corrigé.

#### (c) Nouvelle limite déclarée : `identification_basis` ne vérifie rien

Le §15.2 présente ce champ comme l'instrument qui remplace l'auto-déclaration de
confiance, et la mesure ci-dessus le met à l'épreuve : **dès que le modèle nomme une
marque sur ce corpus, il écrit `label`** — y compris dans les 88 enregistrements
(15 photos) où le texte imprimé **ne contient pas** la marque annoncée. Les règles A
et B sont le même ensemble (88 = 88) : `identification_basis = label` n'implique **pas**
que la marque revendiquée soit lisible sur l'objet.

Ce n'est pas un défaut du modèle : c'est le champ qui promet plus qu'il ne tient. Il
reste utile pour distinguer `visual` et `none`, et il ne doit **pas** être lu comme une
vérification de containment. La seule vérification de containment qui existe dans le
système est `label_divergence`, et elle porte sur *un autre vendeur*, pas sur la marque
annoncée.

#### (d) Ce que §22.8 impose

1. **Ne plus publier de taux sur les enregistrements** quand les photos sont mesurées
   plusieurs fois : l'unité est la photo distincte, et le `n` qui l'accompagne doit le
dire.
2. **Ne pas écrire v7** tant que la question de cadrage n'est pas reformulée ; l'état
   du cadrage est `unverified`, et cet état est affiché.
3. **Ne pas présenter `identification_basis` comme vérifiable** dans les documents qui
   le citent (§15.2, §22.5) sans cette réserve.
4. **Ne pas activer la règle A** de divergence : 16 % de rétrogradations, dont des
   identifications correctes, n'est pas de la sévérité, c'est une régression.
