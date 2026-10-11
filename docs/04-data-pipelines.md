# 04 — Pipelines de données CPE et NVD

> **C'est ici que le projet se gagne ou se perd.** L'inférence VLM est la partie confortable et la mieux outillée. Le spine de données est ce que les deux missions du CDC sous-estiment.
>
> Tout chiffre marqué **VERIFY** est une **estimation à mesurer au jour 1** (méthode donnée). Ne pas les recopier dans le CDC avant mesure.

---

## 1. Pipeline CPE

### 1.1 Chaîne

```
téléchargement ─► parsing streaming ─► filtrage part=h ─► normalisation
      │                 │                   │                 │
      │                 │                   │                 └─► mapping catégorie (curé)
      │                 │                   └─► rejet a/ (app) et o/ (OS)
      │                 └─► iterparse + elem.clear()  (mémoire plate)
      └─► sha256 + dictionary_version_id  (D6)
                                    │
                                    ▼
                    embeddings optionnels (chaîne naturelle, D4)
                                    ▼
                         INSERT OR IGNORE dans cpe_entries
```

### 1.2 Volumétrie attendue — **VERIFY**

| Grandeur | Estimation | Méthode de mesure (jour 1) |
|---|---|---|
| Taille du XML dictionnaire | **~centaines de Mo** (annoncé 500 Mo) | `curl -sI <url> | grep -i content-length` |
| Entrées totales | ordre **10⁵–10⁶** (dépréciées incluses) | `zgrep -c '<cpe-item'` ou compteur du parser |
| Entrées `part=h` (matériel) | minorité (vs `a`/`o`) | requête : `SELECT part, count(*) FROM cpe_entries GROUP BY part` |
| Entrées retenues (5 catégories) | ordre **10³–10⁴** | `SELECT category, count(*) ...` |
| Temps de parsing (i9-13900) | **secondes à ~2 min** | `time python -m iot_audit.pipeline.parse_cpe` |

**Conséquence importante :** avec 10³–10⁴ entrées retenues, **les embeddings ne sont pas un goulot d'étranglement** (quelques secondes à quelques minutes sur GPU). Le coût réel est le **travail curé** : normalisation, mapping de catégorie, gestion des dépréciées. Écrire « 500 Mo de XML » dans le CDC comme *risque* met l'accent au mauvais endroit.

### 1.3 Parsing streaming (mémoire plate)

```python
# iot_audit/pipeline/parse_cpe.py
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from lxml import etree

NS = "{http://cpe.mitre.org/dictionary/2.0}"


def iter_cpe_items(xml_path: Path) -> Iterator[etree._Element]:
    """Parse un dictionnaire CPE 2.3 sans charger l'arbre complet.

    Le double nettoyage (clear + suppression des frères précédents) est ce qui
    maintient la mémoire plate : sans lui, iterparse fuit et le processus gonfle
    jusqu'à plusieurs Go sur un fichier de quelques centaines de Mo.
    """
    context = etree.iterparse(
        str(xml_path), events=("end",), tag=f"{NS}cpe-item", huge_tree=True
    )
    for _event, elem in context:
        yield elem
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
```

### 1.4 Normalisation et mapping de catégorie

Le mémo « ne pas relitiger sans raison nouvelle » est respecté : on ne **remplace** rien, on ajoute une étape déterministe et testable.

```python
# iot_audit/pipeline/normalize.py
from __future__ import annotations

import re
import unicodedata

from iot_audit.contracts import Category

# Normalisation d'un jeton libre (sortie VLM) vers une forme comparable à un jeton CPE.
_PARENS = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_display(s: str) -> str:
    """'TP-Link (EU) Archer C7 v2' -> 'tp link archer c7 v2'."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = _PARENS.sub(" ", s.lower())
    s = _NON_ALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def cpe_token_to_display(t: str) -> str:
    """Jeton CPE -> affichage : 'archer_c7' -> 'archer c7', '\\!' -> '!'."""
    return t.replace("\\", "").replace("_", " ").strip()


def embed_text(vendor: str, product: str, version: str | None, cat: Category) -> str:
    """Texte indexé pour les embeddings (D4). Doit être DÉRIVÉ, jamais saisi."""
    v = cpe_token_to_display(vendor)
    p = cpe_token_to_display(product)
    ver = f" {version}" if version and version not in {"*", "-"} else ""
    return f"{v} {p}{ver} {cat.value.replace('_', ' ')}".strip()


# Mapping curé. Ordonné : la PREMIÈRE règle qui matche gagne (précédence explicite).
CATEGORY_RULES: list[tuple[Category, re.Pattern[str]]] = [
    (Category.CAMERA,  re.compile(r"\b(camera|ipcam|ip cam|nvr|dvr|dome|ptz|webcam)\b")),
    (Category.ROUTER,  re.compile(r"\b(router|gateway|access point|wireless ap|modem|"
                                  r"firewall|switch|mesh|repeater|extender)\b")),
    (Category.BULB,    re.compile(r"\b(bulb|light|lamp|led strip|dimmer|smart light)\b")),
    (Category.SPEAKER, re.compile(r"\b(speaker|soundbar|audio|voice assistant|display)\b")),
    (Category.PLUG,    re.compile(r"\b(plug|socket|outlet|relay|power strip|smart switch)\b")),
]
# Désambiguïsation : 'smart switch' est un plug, pas un switch réseau.
OVERRIDES: dict[str, Category] = {
    "smart switch": Category.PLUG,
    "smart plug": Category.PLUG,
}


def classify(vendor: str, product: str) -> Category:
    hay = f"{cpe_token_to_display(vendor)} {cpe_token_to_display(product)}".lower()
    for needle, cat in OVERRIDES.items():
        if needle in hay:
            return cat
    for cat, rx in CATEGORY_RULES:
        if rx.search(hay):
            return cat
    return Category.OTHER
```

**Point de rigueur :** `switch` est ambigu (switch réseau vs interrupteur). Le harnais de test doit couvrir ces collisions explicitement — c'est là que le mapping gagne ou perd sa précision (D12, cible ≥ 95 %).

### 1.5 Versioning du dictionnaire (D6)

```sql
CREATE TABLE dictionary_versions (
  id            INTEGER PRIMARY KEY,
  source_url    TEXT    NOT NULL,
  source_sha256 TEXT    NOT NULL,
  entry_count   INTEGER NOT NULL,
  loaded_at     TEXT    NOT NULL,
  UNIQUE (source_sha256)
);

ALTER TABLE cpe_entries ADD COLUMN dictionary_version_id INTEGER NOT NULL REFERENCES dictionary_versions(id);
ALTER TABLE cpe_entries ADD COLUMN deprecated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cpe_entries ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
ALTER TABLE cpe_entries ADD COLUMN embed_text TEXT;

CREATE UNIQUE INDEX ux_cpe_entry ON cpe_entries (cpe_name, dictionary_version_id);
```

**Réponse à « comment gérer une MAJ NIST sans casser les runs précédents ? »**

| Étape | Effet |
|---|---|
| 1. Nouveau dictionnaire publié | on calcule son `sha256` → nouvelle ligne `dictionary_versions` |
| 2. Ingestion | `INSERT OR IGNORE` avec le **nouvel** `dictionary_version_id` — **aucune ligne existante n'est modifiée ou supprimée** |
| 3. Entrées disparues | restent présentes avec l'`id` de leur **ancienne** version, `deprecated` mis à 1 |
| 4. Résolution | se fait sur la version **courante** par défaut |
| 5. Ancien run | référence toujours son `cpe_dict_version_id` → **reproductible à l'identique** |

Le coût est un entier par ligne. Le coût de son absence est un rapport de septembre non reproductible en octobre — c'est-à-dire ENF5 morte.

### 1.6 Reprise sur erreur

| Mécanisme | Détail |
|---|---|
| Idempotence | `INSERT OR IGNORE` sur `(cpe_name, dictionary_version_id)` ⇒ rejouer ne duplique rien |
| Progression | table `ingest_progress(job, position, updated_at)` où `position` = index de l'entrée |
| Reprise | relire la position, sauter les entrées déjà traitées |
| Atomicité de version | la version n'est marquée `complete` que si `entry_count` = source ⇒ une version partielle n'est **jamais** visible par la résolution |

---

## 2. Pipeline NVD

### 2.1 Volumétrie — **VERIFY**

| Grandeur | Annoncé au CDC | Estimation | Méthode |
|---|---|---|---|
| Flux NVD complet | **~200 Go** | **quelques Go compressés** | `curl -sI` sur `nvdcve-2.0-2024.json.gz` → `content-length` × nb d'années |
| CVE totales (toutes années) | — | ordre 2,5·10⁵ | compteur du parser |
| CVE matériel 5 ans | — | ordre 10³–10⁴ (**petit**) | `SELECT count(DISTINCT cve_id) FROM cve_cpe_criteria WHERE part='h'` |
| Critères CPE matériel | — | 10× le nb de CVE | `SELECT count(*) FROM cve_cpe_criteria WHERE part='h'` |

**Le « 200 Go » est presque certainement le chiffre toutes-années non filtré et non compressé.** Ce n'est pas neutre : mal calibré, il fait concevoir une ingestion « big data » là où il faut une passe de streaming de quelques minutes. **À mesurer avant le CDC** — c'est un chiffre qui voyage dans un document officiel.

### 2.2 Filtrage en flux (ne jamais matérialiser une année entière)

```python
# iot_audit/pipeline/ingest_nvd.py
from __future__ import annotations

import gzip
from collections.abc import Iterator
from typing import Any

import ijson


def iter_vulnerabilities(path: str) -> Iterator[dict[str, Any]]:
    """Stream les CVE d'un flux annuel .json.gz sans charger l'année en RAM."""
    with gzip.open(path, "rb") as fh:
        yield from ijson.items(fh, "vulnerabilities.item")


def hardware_criteria(vuln: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Extrait uniquement les critères CPE de part=h d'une CVE."""
    for conf in vuln.get("cve", {}).get("configurations", []) or []:
        for node in conf.get("nodes", []) or []:
            for m in node.get("cpeMatch", []) or []:
                criteria: str = m.get("criteria", "")
                parts = criteria.split(":")
                # cpe:2.3:<part>:<vendor>:<product>:...
                if len(parts) < 5 or parts[2] != "h":
                    continue
                yield {
                    "cve_id": vuln["cve"]["id"],
                    "match_criteria_id": m.get("matchCriteriaId"),
                    "criteria": criteria,
                    "part": parts[2],
                    "vendor": parts[3],
                    "product": parts[4],
                    "version": parts[5],
                    "version_start_incl": m.get("versionStartIncluding"),
                    "version_end_excl": m.get("versionEndExcluding"),
                    "vulnerable": 1 if m.get("vulnerable") else 0,
                    "operator": node.get("operator"),
                    "negate": 1 if m.get("negate") else 0,
                }
```

### 2.3 Schéma d'indexation pour une recherche < 50 ms

```sql
CREATE TABLE feed_versions (
  id            INTEGER PRIMARY KEY,
  feed_name     TEXT NOT NULL,           -- nvdcve-2.0-2024.json.gz
  sha256        TEXT NOT NULL,
  published_at  TEXT,
  ingested_at   TEXT NOT NULL,
  row_count     INTEGER,
  UNIQUE (feed_name, sha256)
);

CREATE TABLE cve_cpe_criteria (
  id                  INTEGER PRIMARY KEY,
  cve_id              TEXT    NOT NULL,
  match_criteria_id   TEXT,
  criteria            TEXT    NOT NULL,   -- motif CPE original, conservé pour l'audit
  part                TEXT    NOT NULL,   -- 'h' uniquement ici
  vendor              TEXT    NOT NULL,
  product             TEXT    NOT NULL,   -- peut valoir '*'
  version             TEXT,
  version_start_incl  TEXT,
  version_end_excl    TEXT,
  vulnerable          INTEGER NOT NULL DEFAULT 1,
  negate              INTEGER NOT NULL DEFAULT 0,
  operator            TEXT,               -- AND / OR du nœud
  feed_version_id     INTEGER NOT NULL REFERENCES feed_versions(id),
  UNIQUE (cve_id, match_criteria_id)
);

CREATE INDEX ix_criteria_lookup ON cve_cpe_criteria (part, vendor, product, vulnerable);
CREATE INDEX ix_criteria_cve    ON cve_cpe_criteria (cve_id);
```

**Requête de pré-filtrage (chemin chaud) :**

```sql
SELECT DISTINCT c.cve_id
FROM cve_cpe_criteria c
WHERE c.part     = 'h'
  AND c.vendor   = :vendor
  AND c.product IN (:product, '*')     -- produit exact OU niveau vendeur
  AND c.vulnerable = 1;
```

Puis, **en code** et non en SQL, on applique la logique de plage (`version_start_incl` / `version_end_excl`) sur les rares lignes remontées. La différence entre `product = :product` et `product = '*'` doit rester **visible en sortie** : c'est `CVEResult.match_basis`. Un match « vendeur entier » est une **preuve faible** et ne doit **jamais** être fondu avec un match produit exact.

### 2.4 Wildcards sans explosion de lignes

| Cas | Traitement | Pourquoi |
|---|---|---|
| `product = '*'` (niveau vendeur) | **conservé tel quel**, 1 ligne, match séparé, `match_basis='vendor_wildcard'` | pas d'expansion : une ligne suffit, la sémantique est préservée |
| `version = '*'` avec plages | 1 ligne + colonnes de bornes | la plage **est** la représentation compacte ; l'énumérer serait la faute |
| `NEGATE` | colonne `negate` évaluée en code | un `LIKE` l'ignorerait ⇒ faux positifs silencieux |
| `AND`/`OR` entre critères | `operator` conservé ; pour le MVP, on remonte les CVE candidates et on signale `E_CPE_AMBIGUOUS` si le nœud est complexe | évaluer l'arbre complet est un travail distinct, **à documenter comme limite** si non implémenté |

> **Limite à assumer explicitement :** l'évaluation complète de l'arbre booléen NVD n'est pas dans le MVP. On fait un **rappel élevé** (candidats larges) puis on présente `match_basis`, ce qui est défendable ; prétendre à l'exactitude NVD sans implémenter la sémantique complète ne l'est pas.

### 2.5 Refresh : incrémental vs full reload

| Fréquence | Opération | Coût | Risque couvert |
|---|---|---|---|
| Hebdomadaire | `nvdcve-2.0-modified.json.gz` → upsert par `(cve_id, matchCriteriaId)` | secondes | CVE ajoutées / re-notées / **rejetées** |
| Trimestriel | nouvelle fenêtre 5 ans → **nouveau** `feed_version_id`, bascule atomique | minutes | dérive de composition, feed `modified` incomplet |
| Jamais | mutation en place d'un snapshot | — | interdit (D13) |

Détection des **CVE rejetées** : le flux `modified` marque `vulnStatus = "Rejected"`. Il faut les **conserver** avec un statut, sinon un rapport passé liste une CVE qui a disparu de la base sans explication.

### 2.6 Reprise sur erreur

| Mécanisme | Détail |
|---|---|
| Granularité | par **année** et par `feed_name` : `feed_versions.row_count` atteste la complétion |
| Idempotence | `UNIQUE(cve_id, matchCriteriaId)` + upsert ⇒ rejouer est sûr |
| Reprise | sauter les années déjà présentes avec le même `sha256` |
| Cohérence | un run ne voit qu'une bascule atomique : pas d'état « à moitié ingéré » |

---

## 3. Ce que ces pipelines doivent rendre au reste du système

| Sortie | Consommateur | Garantie |
|---|---|---|
| `dictionary_version_id` | `resolve_cpe`, `analysis_runs` | chaque résolution est rattachée à une version |
| Index FTS5 `(vendor, product, display_name)` | `resolve_cpe` (D3) | récupération lexicale déterministe |
| `embed_text` | embeddings optionnels | texte **dérivé**, donc stable |
| `cve_cpe_criteria` indexé | `search_cve` | < 50 ms p95, pré-filtre correct |
| `feed_versions.sha256` | `Provenance.nvd_snapshot_sha256` | D13 |
| `ingest_progress` | opérateur | reprise sans repartir de zéro |

**Test d'acceptation global de ce module :** ingérer le dictionnaire + 5 ans de NVD **deux fois de suite** doit produire exactement le même `entry_count`, le même nombre de lignes de critères, et **aucun** doublon. C'est la preuve d'idempotence, et elle est trivialement automatisable.
