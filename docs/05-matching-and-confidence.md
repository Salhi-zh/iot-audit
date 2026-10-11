# 05 — Matching CPE et mesure de confiance

---

## 1. Contrat de sortie du VLM (Guided Decoding)

Ce que le schéma JSON contraint **avant** toute logique métier :

```json
{
  "type": "object",
  "required": ["brand", "model", "category", "visible_text", "identification_status"],
  "additionalProperties": false,
  "properties": {
    "brand":  { "type": "string", "maxLength": 64 },
    "model":  { "type": "string", "maxLength": 64 },
    "category": {
      "enum": ["smart_plug", "ip_camera", "smart_bulb", "router_ap", "smart_speaker", "other"]
    },
    "visible_text": { "type": "string", "maxLength": 512 },
    "identification_status": { "enum": ["identified", "partial", "unidentifiable"] },
    "evidence_image_region": { "type": "string", "maxLength": 128 }
  }
}
```

**Ce que le Guided Decoding garantit :** la **validité syntaxique** (pas de JSON malformé, pas de catégorie hors liste, pas de texte libre hors schéma). C'est une vraie garantie dont il faut se servir.

**Ce qu'il ne garantit pas :** la **justesse sémantique**. Le modèle peut mettre « TP-Link » quand c'est du D-Link. Et il peut être *incité* par du texte présent sur l'étiquette : le schéma empêche de **sortir du format**, pas de **se tromper dans le format**.

**Décision de contrat :** `category` est un `enum` (possible car vocabulaire fermé et petit) ; `brand`/`model` restent du texte libre. Un `enum` de marques est **irréaliste** (vocabulaire de vendeurs CPE trop large pour un grammaire de décodage) — c'est pourquoi l'invention de marque se traite **après** le décodage, par résolution, pas par contrainte.

---

## 2. Algorithme de résolution CPE

### 2.1 Vue

```
sortie VLM ─► normalisation ─► canonicalisation de version
                  │
                  ▼
        ┌── ÉTAGE 1 : portail vendeur ──────────────┐
        │  vendor_exact ?  sinon Levenshtein ≤ 2    │
        │  via table d'alias (tp-link/tplink/tp link)│
        └───────────────┬───────────────────────────┘
                        ▼
        ┌── ÉTAGE 2 : classement produit (lexical) ──┐
        │  FTS5 trigram + token_set_ratio             │
        └───────────────┬────────────────────────────┘
                        ▼
        ┌── ÉTAGE 3 : sauvetage sémantique ───────────┐
        │  uniquement si le lexical est faible        │
        └───────────────┬────────────────────────────┘
                        ▼
                  score fusionné  ─► décision (§3)
```

### 2.2 Table d'alias vendeur

Construite **depuis le dictionnaire CPE** (source de vérité), complétée à la main :

```python
# iot_audit/pipeline/vendor_index.py
from iot_audit.pipeline.normalize import normalize_display

# Alias dérivés : 'tp-link' -> 'tp link', 'tplink' -> 'tp link'
ALIASES: dict[str, str] = {
    "tp link": "tp link", "tplink": "tp link", "tp-link": "tp link",
    "d link": "d link", "dlink": "d link",
    "hikvision": "hikvision", "hik vision": "hikvision",
    "xiaomi": "xiaomi", "mi": "xiaomi",
    "eufy": "eufy", "anker eufy": "eufy",
    "amazon": "amazon", "ring": "ring", "blink": "amazon",
    "philips hue": "philips", "signify": "philips",
    # ... complété depuis la table `vendors` du dictionnaire
}


def canon_vendor(raw: str) -> str:
    n = normalize_display(raw)
    return ALIASES.get(n, n)
```

### 2.3 Canonicalisation de version — **étape indispensable**

`Archer C7 **v2**` doit atteindre `cpe:2.3:h:tp-link:archer_c7:**2.0**`. Sans canonicalisation, le modèle de longueur de chaîne pénalise le match alors que c'est **le bon produit**.

```python
# iot_audit/pipeline/normalize.py  (suite)
_VERSION_RX = re.compile(r"^(?:v|ver|version)?\s*(\d+)(?:[._](\d+))?$")


def canon_version(tok: str) -> str | None:
    """'v2' | '2.0' | '2' | 'ver2' -> '2'.  Renvoie None si non reconnaissable."""
    m = _VERSION_RX.match(tok.strip().lower())
    if not m:
        return None
    major, minor = m.group(1), m.group(2)
    return major if minor in (None, "0") else f"{major}.{minor}"


def split_version(model_norm: str) -> tuple[str, str | None]:
    """Détache un suffixe de version : 'archer c7 v2' -> ('archer c7', '2')."""
    toks = model_norm.split()
    if len(toks) >= 2:
        v = canon_version(toks[-1])
        if v is not None:
            return " ".join(toks[:-1]), v
    return model_norm, None
```

### 2.4 Score lexical, puis sauvetage sémantique

```python
# iot_audit/modules/resolve_cpe.py
from __future__ import annotations

from dataclasses import replace

from rapidfuzz import fuzz

from iot_audit.contracts import CPECandidate, Identification

# Seuils INITIAUX — à recalibrer sur le jeu étiqueté (§3.4). Ne pas les traiter
# comme des constantes physiques : ils se règlent sur les données.
T_ACCEPT = 0.90     # auto-sélection
T_MIN    = 0.60     # en-dessous : E_NO_CPE_MATCH
T_MARGIN = 0.08     # écart top1/top2 minimal pour trancher
W_SEM_RESCUE = 0.5


def _lexical(q_model: str, q_version: str | None, cand: CPECandidate) -> float:
    base = fuzz.token_set_ratio(q_model, cand.product) / 100.0
    if q_version and cand.version:
        base = min(1.0, base + 0.05) if q_version == cand.version else base - 0.05
    return max(0.0, min(1.0, base))


def _fuse(lex: float, sem: float | None) -> float:
    """Le lexical d'abord (D3) ; le sémantique n'intervient qu'en rattrapage."""
    if sem is None:
        return lex
    if lex >= T_ACCEPT:
        return lex                       # le lexical tranche : on ignore le sémantique
    return W_SEM_RESCUE * lex + (1 - W_SEM_RESCUE) * sem


def resolve(vlm_model: str, vlm_version: str | None,
            pool: list[CPECandidate]) -> list[CPECandidate]:
    scored = [
        replace(c, lexical_score=_lexical(vlm_model, vlm_version, c),
                   score=_fuse(_lexical(vlm_model, vlm_version, c), c.semantic_score))
        for c in pool
    ]
    return sorted(scored, key=lambda c: c.score, reverse=True)[:3]
```

**Pourquoi `token_set_ratio` et pas une distance d'édition brute :** le CPE donne `archer c7` et le modèle peut dire `archer c7 wireless router`. `token_set_ratio` ignore les jetons supplémentaires, la distance d'édition les pénalise.

---

## 3. Décision, seuils, ambiguïté

### 3.1 Marge, pas seulement score

Un score absolu ne dit pas si le résultat est **discriminant**. `top1 − top2` distingue « ce produit » de « l'un de ces trois produits proches ».

| Condition | Sortie | Code |
|---|---|---|
| `score ≥ T_ACCEPT` **et** `marge ≥ T_MARGIN` | auto-sélectionné | — |
| `score ≥ T_ACCEPT` **et** `marge < T_MARGIN` | 2 candidats proposés, HITL obligatoire | `E_CPE_AMBIGUOUS` |
| `T_MIN ≤ score < T_ACCEPT` | retenu **avec réserve** | `E_UNCALIBRATED_CONSENSUS` si A élevé |
| `score < T_MIN` | aucun CPE | `E_NO_CPE_MATCH` |

### 3.2 Marque inventée par le VLM

Chemin exact :

1. **Étage 1** : `canon_vendor(brand)` → aucun match exact, aucun alias, aucune distance de Levenshtein ≤ 2 contre la table `vendors` ⇒ `|V| = 0`.
2. **Étage 2** (rattrapage) : FTS5 trigram sur l'ensemble du dictionnaire hardware ⇒ meilleurs scores faibles.
3. **Décision** : `score < T_MIN` ⇒ **`E_NO_CPE_MATCH`**, top-3 présenté avec ses scores, **aucun CPE inventé, aucun plus-proche-voisin forcé**.

**Interdit :** choisir le vendeur le plus proche « pour rendre un résultat ». Le CDC l'exige (EF5), et c'est le mode de défaillance le plus probable d'un système de récupération.

**Métrique à publier :**

```
InventedBrandRate = |{i : canon_vendor(brand_i) ∉ vendors}| / N
```

Si elle dépasse ~5 %, c'est le **prompt** qui doit être revu (ajouter une consigne « si la marque n'est pas lisible, renvoyer `unknown` »), pas le matcher.

### 3.3 Sélection : automatique, manuelle ou hybride

**Hybride, avec un seuil explicite** — jamais silencieux :

- auto-sélection **uniquement** au-dessus de `T_ACCEPT` avec marge ⇒ c'est là qu'on défend une précision ≥ 0,95 ;
- sinon HITL avec les candidats ordonnés et leurs scores visibles ;
- la sélection manuelle est **tracée** (table `corrections`, D15) et **chaînée au journal HMAC**.

### 3.4 Calibration des seuils (méthode, pas intuition)

Sur les ≥ 200 paires étiquetées :

1. balayer le seuil d'auto-sélection ;
2. tracer précision (sur les auto-sélectionnés) vs taux d'auto-sélection ;
3. choisir le seuil **le plus permissif** dont la précision ≥ 0,95.

Même procédure pour `T_MARGIN`. Les constantes ci-dessus sont le **point de départ**, pas le résultat — le tableau de calibration est un livrable.

---

## 4. Mesure de confiance

### 4.1 Formalisation

Soit N photos du **même** objet. Après normalisation, chaque photo i donne un tuple `t_i = (brand_i, model_i)`. On regroupe par tuple identique.

**Accord inter-photos (A)** — la part des photos qui tombent dans la classe modale :

$$A = \frac{\max_{t} |\{i : t_i = t\}|}{N} \in \left[\tfrac{1}{N},\, 1\right]$$

Accords **par champ** (utiles car la marque est souvent stable et le modèle non) :

$$A_{brand} = \frac{\max_b |\{i: brand_i = b\}|}{N}, \quad A_{model} = \frac{\max_m |\{i: model_i = m\}|}{N}, \quad A_{cat} = \dots$$

On a toujours `A ≤ min(A_brand, A_model, A_cat)`.

> **Deux implémentations d'`A`, sous le même nom — mesuré le 2026-10-06.**
> `iot_audit.corpus.metrics.agreement` compare des **chaînes exactes** : c'est la
> définition **publiée** (accord du §8.4 de `06`).
> `iot_audit.modules.confidence.compute_agreements` compare des tuples
> **canonisés** (`canon_vendor` / `normalize_display`) et c'est celui qui alimente
> la matrice ci-dessous. Les deux **coïncident** sur le corpus publié
> (`0,9153` marque / `0,8397` modèle) et **divergent** de 0,4 pt (marque) et
> 0,8 pt (modèle) sur le corpus v4 du 2026-09-15 — deux objets seulement, `zyxel__p_870ha`
> (casse) et `amazon__echo_dot` (suffixe de génération). Publier un `A` sans dire
> laquelle des deux lectures c'est est un défaut de la même famille que celui
> relevé au §21.4 de `06` (le sigle `(A)` qui voulait dire *accord*).

**Résolvabilité (R)** = score fusionné du tuple consensuel (`R = top1.score`).

### 4.2 Matrice de décision (les deux axes, jamais un seul)

| A \ R | R ≥ 0,90 | 0,60 ≤ R < 0,90 | R < 0,60 |
|---|---|---|---|
| **A ≥ 0,70** | `identified` | `identified_with_reserve` | `unidentified` (`E_UNCALIBRATED_CONSENSUS`) |
| **0,40 ≤ A < 0,70** | `identified_with_reserve` | `identified_with_reserve` | `unidentified` (`E_LOW_CONFIDENCE`) |
| **A < 0,40** | `unidentified` | `unidentified` | `unidentified` (`E_NO_IDENTIFICATION`) |

La cellule **A élevé / R faible** est celle qui justifie tout le dispositif : c'est la signature d'un **consensus halluciné** (erreur systématique répétée sur les N photos). Un score d'accord seul aurait affiché « confiance 100 % ».

### 4.3 Pourquoi pas d'intervalle de confiance sur A

Tentation naturelle : mettre un IC de Wilson sur A. **C'est faux ici**, et il faut savoir le dire. Les N photos d'un même objet **ne sont pas indépendantes** (même appareil, souvent même angle) : elles échantillonnent une pose, pas un objet. Un IC calculé comme si elles étaient i.i.d. **sous-estime l'incertitude** et donne une fausse précision.

Règle retenue :
- **A est descriptif** — on le publie comme fraction brute (`6/8`), sans IC ;
- les **IC de Wilson** sont réservés à l'**accuracy objet-level**, où les objets *sont* approximativement indépendants (`06`).

```python
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """IC de Wilson — à utiliser sur l'ACCURACY (par objet), pas sur A."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / d
    return (max(0.0, centre - demi), min(1.0, centre + demi))
```

### 4.4 Cas « 5 réponses différentes sur 8 photos »

Distribution : `{t1: 3, t2: 2, t3: 1, t4: 1, t5: 1}`, N = 8.

- `A = 3/8 = 0,375` → **A < 0,40** ⇒ `unidentified`, code `E_NO_IDENTIFICATION`.
- Message : « Objet non identifié — vérification manuelle requise. »
- **Mais on affiche la distribution complète.** L'auditeur qui voit « 3× TP-Link, 2× D-Link, 3 réponses isolées » apprend quelque chose qu'aucun scalaire ne transmet : le modèle a probablement identifié un *type* d'objet sans la marque. Cacher la distribution derrière un score unique est une perte d'information pure.

**Règle de conception :** l'UI affiche (A, R) **et** la distribution. Le score unique n'existe que pour trier une liste.

### 4.5 Exemple travaillé — TP-Link Archer C7 v2

| Étape | Valeur |
|---|---|
| Sortie VLM | `brand="TP-Link"`, `model="Archer C7 v2"` |
| Normalisation | `vendor="tp link"`, `model_norm="archer c7 v2"` |
| Canonicalisation | `split_version` → `("archer c7", "2")` |
| CPE candidat | `cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*` |
| Étage 1 | `canon_vendor("tp link")` = `tp link` → match exact, `|V|` grand |
| Étage 2 | `token_set_ratio("archer c7", "archer c7")` = 1,00 ; version `"2"` == `"2"` ⇒ **+0,05** ⇒ plafonné à 1,00 |
| `R` | 1,00 ; marge top1−top2 large |
| Si A = 8/8 = 1,00 | → **`identified`**, CPE auto-sélectionné, recherche CVE lancée |

Sans la canonicalisation de version, `"c7 v2"` vs `"c7"` plafonnerait plus bas et le bon produit pourrait passer en « avec réserve » — c'est exactement le genre de détail qui fait la différence entre 80 % et 95 % de top-1.
