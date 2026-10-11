# Benchmark identification / classification / reconnaissance — référence générée

> **Généré** par `benchmarks/run_identification.py`. Aucun chiffre saisi à la main.
> Source : run **v4** gelé (144 images, 48 objets) · barème gelé `audit-grading.py`.
> Règle `docs/07` : tout taux publié porte son `n` et un intervalle de Wilson.

Images : **144** notées sur 144 (écartées : 0 — []).

## 1. Image — identification et classification (le niveau élémentaire)

| figure | valeur |
|---|---|
| `brand` | 46/144 = 0.319  IC95 [0.249 ; 0.399] |
| `model_A` | 64/144 = 0.444  IC95 [0.366 ; 0.526] |
| `model_P` | 79/144 = 0.549  IC95 [0.467 ; 0.628] |
| `category` | 122/144 = 0.847  IC95 [0.779 ; 0.897] |
| `brand_and_model` | 19/144 = 0.132  IC95 [0.086 ; 0.197] |

## 2. Objet — **M1** (marque ET modèle), cible ≥ 0,70

M1 n'est **pas** recalculé par ce banc : il est importé de
`iot_audit.corpus.metrics` (§19). Un banc qui réimplémente la métrique qu'il
prétend mesurer finit par en mesurer une autre — c'est arrivé ici, et c'est daté.
Dernier chiffre publié : **8/26 = 0,308** (n = 26 objets).
Ce run porte sur **48 objets / 144 images**.

| consolidation | M1 (k/n) | p̂ | IC95 | ce que la règle mesure |
|---|---|---|---|---|
| `conservative` | 10/48 | 0.208 | [0.117 ; 0.343] | l'abstention **compte** comme une réponse ← règle publiée (§8.1) |
| `answered` | 15/48 | 0.312 | [0.200 ; 0.453] | l'abstention est retirée du vote |

> Le prompt du projet **ordonne** l'abstention (« Do NOT guess a brand you cannot
> see »). Sous `conservative`, un modèle qui obéit est donc noté moins bien qu'un
> modèle qui devine. Les deux règles ne mesurent pas la même chose : publier une
> seule des deux, c'est choisir une politique d'abstention sans le dire.

- verdicts (`conservative`) : `brand_no_category_ok` 17 · `faux` 12 · `exact` 10 · `brand_ok_model_no` 9
- verdicts (`answered`) : `exact` 15 · `faux` 12 · `brand_no_category_ok` 11 · `brand_ok_model_no` 10

### Règles d'agrégation (barème canonique, consolidation `conservative`)

| agrégation | exactitude objet |
|---|---|
| `first` | 11/48 = 0.229  IC95 [0.133 ; 0.365] |
| `modal_tuple` ← **règle publiée** | 9/48 = 0.188  IC95 [0.102 ; 0.319] |
| `brand_then_model` | 9/48 = 0.188  IC95 [0.102 ; 0.319] |
| `basis_preferred` | 12/48 = 0.250  IC95 [0.149 ; 0.388] |
| `oracle_any` | 17/48 = 0.354  IC95 [0.234 ; 0.496] |
| `all_images` | 8/48 = 0.167  IC95 [0.087 ; 0.296] |

| figure objet | valeur |
|---|---|
| marque seule (modale) | 20/48 = 0.417  IC95 [0.288 ; 0.557] |
| catégorie seule (modale) | 36/48 = 0.750  IC95 [0.612 ; 0.851] |

## 3. Choix de la règle d'agrégation — sélection sur train, publication sur eval

Découpage gelé par hachage, **par objet** : 23 train / 25 eval (`train=3ad2d75be8e8e46b`, `eval=779e02e876701ed7`).

| règle | train | eval (tenu à part) |
|---|---|---|
| `first` | 6/23 = 0.261  IC95 [0.126 ; 0.465] | 5/25 = 0.200  IC95 [0.089 ; 0.391] |
| `modal_tuple` | 5/23 = 0.217  IC95 [0.097 ; 0.419] | 4/25 = 0.160  IC95 [0.064 ; 0.346] |
| `brand_then_model` | 6/23 = 0.261  IC95 [0.126 ; 0.465] | 3/25 = 0.120  IC95 [0.042 ; 0.300] |
| `basis_preferred` **← retenue** | 7/23 = 0.304  IC95 [0.156 ; 0.509] | 5/25 = 0.200  IC95 [0.089 ; 0.391] |

Règle retenue sur train : **`basis_preferred`** ; figures publiées sur eval : **5/25 = 0.200  IC95 [0.089 ; 0.391]**.

> **Avertissement, écrit plutôt que tu.** La règle qui gagne sur *train* n'est
> pas celle qui gagne sur *eval* : `basis_preferred` est retenue (train 7/23),
> mais sur eval c'est `first` (5/25). À n = 23 + 25 objets, **aucune règle d'agrégation
> n'est distinguable d'une autre** : l'écart tient dans le bruit d'échantillonnage.
> La conclusion défendable n'est donc pas « la meilleure règle est X », c'est
> « **l'agrégation ne sauve pas l'identification objet**, quelle que soit la règle »,
> ce que le plafond `oracle_any` du §2 borne aussi.

## 4. La base est-elle INFORMATIVE ? (`label` = texte lu, `visual` = forme)

| base | n | modèle exact (A) | modèle exact (P) | catégorie |
|---|---|---|---|---|
| `label` | 80 | 22/80 = 0.275  IC95 [0.189 ; 0.381] | 37/80 = 0.463  IC95 [0.357 ; 0.571] | 61/80 = 0.762  IC95 [0.659 ; 0.842] |
| `visual` | 64 | 42/64 = 0.656  IC95 [0.534 ; 0.761] | 42/64 = 0.656  IC95 [0.534 ; 0.761] | 61/64 = 0.953  IC95 [0.871 ; 0.984] |

- critère **A** : **INFORMATIF**
- critère **P** : **NON TRANCHE**

> **Le verdict dépend du critère de notation.** C'est une affirmation à
> publier telle quelle : « la base est informative » n'est vrai que sous le
> critère A. Sous P, les intervalles se recouvrent et le verdict retombe à
> NON TRANCHÉ — qui est la conclusion écrite au §16.2 du dossier. Les deux
> sont vrais, chacun sous son critère.

## 5. Classification — exactitude par catégorie

| catégorie (vérité effective) | exactitude |
|---|---|
| `ip_camera` | 1/4 = 0.250  IC95 [0.046 ; 0.699] |
| `router_ap` | 29/41 = 0.707  IC95 [0.555 ; 0.824] |
| `smart_bulb` | 4/5 = 0.800  IC95 [0.376 ; 0.964] |
| `smart_plug` | 12/12 = 1.000  IC95 [0.757 ; 1.000] |
| `smart_speaker` | 76/82 = 0.927  IC95 [0.849 ; 0.966] |

### Matrice de confusion (vérité → prédit)

| vérité → prédit | images |
|---|---|
| `ip_camera -> ip camera` | 1 |
| `ip_camera -> router ap` | 1 |
| `ip_camera -> smart speaker` | 2 |
| `router_ap -> other` | 8 |
| `router_ap -> router ap` | 29 |
| `router_ap -> smart speaker` | 4 |
| `smart_bulb -> smart bulb` | 4 |
| `smart_bulb -> smart speaker` | 1 |
| `smart_plug -> smart plug` | 12 |
| `smart_speaker -> other` | 6 |
| `smart_speaker -> smart speaker` | 76 |

## 6. Contamination et canal de lecture

| strate | objets | modèle exact | catégorie |
|---|---|---|---|
| `forum` | 11 | 0/12 = 0.000  IC95 [0.000 ; 0.242] | 1/12 = 0.083  IC95 [0.015 ; 0.354] |
| `official` | 3 | 0/3 = 0.000  IC95 [0.000 ; 0.561] | 3/3 = 1.000  IC95 [0.439 ; 1.000] |
| `review` | 34 | 64/129 = 0.496  IC95 [0.411 ; 0.581] | 118/129 = 0.915  IC95 [0.854 ; 0.952] |

| `text_visible` | modèle exact | catégorie |
|---|---|---|
| `0` | 42/97 = 0.433  IC95 [0.339 ; 0.532] | 75/97 = 0.773  IC95 [0.680 ; 0.845] |
| `1` | 22/47 = 0.468  IC95 [0.333 ; 0.608] | 47/47 = 1.000  IC95 [0.924 ; 1.000] |

## 7. M9 — accord de rejeu (deux exécutions indépendantes)

- prédictions identiques : 144/144 = 1.000  IC95 [0.974 ; 1.000]
- même verdict de catégorie : 144/144 = 1.000  IC95 [0.974 ; 1.000]

## 8. M8 — latence (p95 cible < 10 s)

- n = 144 · p50 = 2.385 s · p95 = 3.759 s · p99 = 6.478 s · max = 8.152 s

---

*Ce fichier est régénéré par script : `python benchmarks/run_identification.py`.*
