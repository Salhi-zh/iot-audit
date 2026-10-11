# Écart du run `v5` par rapport à la référence gelée v4

> Généré par `benchmarks/run_variant_eval.py`. Barème gelé, `compute()` du banc (métriques identiques à la publication).
> Variante : `predictions.json` · images modifiées : **45/144**.

## Image (n = 144)

| figure | v4 gelé | variante | écart |
|---|---|---|---|
| `brand` | 46/144 = 0.319 | 52/144 = 0.361 | +4.2 pt |
| `model_A` | 64/144 = 0.444 | 65/144 = 0.451 | +0.7 pt |
| `model_P` | 79/144 = 0.549 | 81/144 = 0.562 | +1.4 pt |
| `category` | 122/144 = 0.847 | 123/144 = 0.854 | +0.7 pt |
| `brand` ET `model` (A) | 19/144 = 0.132 | 22/144 = 0.153 | +2.1 pt |
| `brand` ET `model` (P) | 31/144 = 0.215 | 37/144 = 0.257 | +4.2 pt |

## Objet — **M1** (marque ET modèle), `iot_audit.corpus.metrics`

| figure | v4 gelé | variante | écart |
|---|---|---|---|
| M1 `conservative` | 10/48 = 0.208 | 11/48 = 0.229 | +2.1 pt |
| M1 `answered` | 15/48 = 0.312 | 15/48 = 0.312 | +0.0 pt |
| `agregation_modal_tuple` | 9/48 = 0.188 | 10/48 = 0.208 | +2.1 pt |
| `agregation_oracle_any` | 17/48 = 0.354 | 19/48 = 0.396 | +4.2 pt |
| `agregation_first` | 11/48 = 0.229 | 13/48 = 0.271 | +4.2 pt |
| `marque_seule_modal` | 19/48 = 0.396 | 21/48 = 0.438 | +4.2 pt |
| `categorie_seule_modal` | 36/48 = 0.750 | 37/48 = 0.771 | +2.1 pt |

`n_objets` = 48 des deux côtés. Rappel : `conservative` compte l'abstention comme une réponse (règle publiée) ; `answered` ne compte que les réponses.

## Découpage objet gelé (23 train / 25 eval)

| sous-ensemble | v4 gelé | variante | écart |
|---|---|---|---|
| train (23 objets) | 6/23 = 0.261 | 6/23 = 0.261 | +0.0 pt |
| eval (25 objets) | 4/25 = 0.160 | 5/25 = 0.200 | +4.0 pt |

> La figure publiable est celle du sous-ensemble **eval**, tenu à part du diagnostic.

## Effets de bord (marque)

| figure | v4 gelé | variante |
|---|---|---|
| `marque_non_vide` | 57/144 = 0.396 | 66/144 = 0.458 |
| `marque_juste` | 46/144 = 0.319 | 52/144 = 0.361 |
| `marque_FAUSSE` | 11/144 = 0.076 | 14/144 = 0.097 |
| `modele_vide` | 2/144 = 0.014 | 4/144 = 0.028 |
| précision de la marque (justes / non vides) | 0.807 | 0.7879 |

## Objets gagnés (2) et perdus (1)

- ✅ `zyxel__p_870ha` (vérité `zyxel / p 870ha`) : modal ('', 'p-870ha') → **('zyxel', 'p-870ha')**
- ✅ `zyxel__p_872h` (vérité `zyxel / p 872h`) : modal ('', 'p-b721h') → **('zyxel', 'p-872h')**
- ❌ `mikrotik__lte_5g` : perdu
