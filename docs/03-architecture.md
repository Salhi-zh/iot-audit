# 03 — Architecture, contrats, modes de défaillance

---

## 1. Les 6 couches et le flux réel

```
                         ┌──────────────────────────────────────┐
  photo (web) ─upload─►  │ 1. API  (Django Ninja)               │
                         └───────────────┬──────────────────────┘
                                         ▼
                         ┌──────────────────────────────────────┐
                         │ 2. Orchestration                     │
                         │  run_id · retries · bascule nœud     │
                         │  provenance · journal HMAC           │
                         └───┬──────────┬──────────┬────────────┘
                             ▼          ▼          ▼
                    ┌────────────┐ ┌─────────┐ ┌──────────┐
                    │3a Ingest   │ │3b Infer │ │3c Resolve│
                    │ sha256     │ │ VLM     │ │ CPE      │
                    │ validation │ │ guided  │ │ lexical+ │
                    └────────────┘ └─────────┘ │ semantic │
                                                └────┬─────┘
                             ┌───────────────────────┘
                             ▼
                    ┌──────────────┐  ┌───────────────┐
                    │3d Vuln (NVD) │  │3e Report (PDF)│
                    └──────┬───────┘  └───────┬───────┘
                           ▼                  ▼
                    ┌──────────────────────────────────────┐
                    │ 4. Storage                           │
                    │ SQLite (WAL) · fichiers · journal    │
                    │ append-only                          │
                    └──────────────────────────────────────┘
```

**Règle de dépendance :** les flèches ne remontent jamais. Le module *Infer* ne connaît pas le module *Report* ; *Resolve CPE* ne connaît pas le NVD. Chaque module reçoit ses entrées par **dataclass** et rend une **dataclass** (§2). Aucun module métier n'importe les modèles ORM d'un autre.

---

## 2. Contrats d'interface

Pas de `dict`. Pas de `**kwargs`. Des types gelés, sérialisables, comparables (utile pour les tests de reproductibilité).

```python
# iot_audit/contracts.py
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence


class Category(StrEnum):
    PLUG = "smart_plug"
    CAMERA = "ip_camera"
    BULB = "smart_bulb"
    ROUTER = "router_ap"
    SPEAKER = "smart_speaker"
    OTHER = "other"


class Status(StrEnum):
    IDENTIFIED = "identified"
    WITH_RESERVE = "identified_with_reserve"
    UNIDENTIFIED = "unidentified"


class Stratum(StrEnum):
    """Risque de contamination décroissant."""
    OFFICIAL = "official"   # visuel marketing -> risque mémorisation ÉLEVÉ
    REVIEW = "review"       # photo d'avis client
    FORUM = "forum"         # forum/réparation, angle inhabituel -> risque FAIBLE


@dataclass(frozen=True, slots=True)
class ImageInput:
    image_id: str
    path: Path
    sha256: str
    stratum: Stratum
    source_url: str
    license: str
    retrieved_at: datetime
    width: int
    height: int
    text_visible: bool          # la marque est-elle LISIBLE sur l'image ?


@dataclass(frozen=True, slots=True)
class VLMRawOutput:
    """Exactement ce que le décodeur contraint a produit. Aucune inférence ici."""
    brand: str
    model: str
    category: Category
    visible_text: str           # texte lu sur l'objet, NON interprété comme instruction
    evidence_image_region: str
    confidence_self: float      # conservé pour analyse, JAMAIS affiché


@dataclass(frozen=True, slots=True)
class CPECandidate:
    cpe_name: str               # cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*
    vendor: str
    product: str
    version: str | None
    category: Category
    lexical_score: float
    semantic_score: float | None
    score: float                # fusion documentée (§05)
    strategy: Literal["lexical", "semantic", "hybrid"]


@dataclass(frozen=True, slots=True)
class CVEResult:
    cve_id: str
    cvss_v3_score: float | None
    severity: str | None
    published: date
    match_basis: Literal["exact_product", "vendor_wildcard", "version_range"]
    criteria_used: tuple[str, ...]
    cache_status: Literal["hit", "miss"]


@dataclass(frozen=True, slots=True)
class Identification:
    """Résultat consolidé sur N photos du MÊME objet. Deux axes, jamais un seul."""
    brand: str | None
    model: str | None
    category: Category
    status: Status
    n_images: int
    agreement: float                      # A  in [0,1]
    resolvability: float                  # R  in [0,1]
    per_field_agreement: Mapping[str, float]
    distribution: Mapping[str, int]       # tuple -> nb d'occurrences
    cpe_candidates: tuple[CPECandidate, ...]
    cves: tuple[CVEResult, ...]


@dataclass(frozen=True, slots=True)
class Provenance:
    model_revision: str
    weights_sha256: str
    prompt_sha256: str
    schema_version: str
    vllm_version: str
    torch_version: str
    nvd_snapshot_sha256: str
    cpe_dict_version_id: int
    sampling_params: Mapping[str, Any]
    nodes_used: tuple[str, ...]
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class JournalEvent:
    run_id: str
    seq: int                     # monotone : survit à une dérive d'horloge
    stage: str
    code: str
    payload: Mapping[str, Any]
    occurred_at: datetime
```

**Découplage par protocole** (injection de dépendance, testable sans GPU ni réseau) :

```python
class VLMRunner(Protocol):
    def infer(self, image: ImageInput, *, prompt_version: str) -> VLMRawOutput: ...

class CPEResolver(Protocol):
    def resolve(self, ident: Identification, *, k: int = 3) -> Sequence[CPECandidate]: ...

class CVESearcher(Protocol):
    def search(self, cpe: CPECandidate, *, since: date) -> Sequence[CVEResult]: ...

class Journal(Protocol):
    def append(self, event: JournalEvent) -> str: ...   # -> hmac courant
```

**Pourquoi des dataclasses gelées et pas des dicts :** un `dict` ne se type pas, ne se compare pas, et laisse passer un champ manquant jusqu'à l'écriture en base. Des `frozen=True, slots=True` comparables rendent les **tests de reproductibilité triviaux** (`run1.identification == run2.identification`) et interdisent la mutation entre couches.

**Pourquoi pas Pydantic pour les sorties VLM :** le schéma du Guided Decoding est **déjà** la contrainte. Ajouter Pydantic crée deux sources de vérité pour le même contrat, qui divergeront. On valide la sortie du serveur avec le **même** schéma JSON, et on convertit en dataclass.

---

## 3. Les 5 couplages cachés qui cassent en phase 3

| # | Couplage | Comment ça casse | Correctif |
|---|---|---|---|
| C1 | **« catégorie » a deux sens** : la catégorie *prédite par le VLM* et la catégorie *du CPE* | on filtre le dictionnaire avec la catégorie du VLM ⇒ **raisonnement circulaire** : le VLM ne peut plus être corrigé par les données | deux types distincts (`vl_category` vs `cpe.category`) + test de cohérence croisée ; le filtrage CPE utilise la catégorie **dérivée**, le VLM est une *hypothèse à tester* |
| C2 | **la confiance est calculée dans la couche rapport** | l'API renvoie un chiffre, le PDF un autre ; impossible de tracer laquelle a servi | le calcul vit dans `resolve`/`orchestration`, la couche rapport **formate** seulement ; `Identification.agreement` est la seule source |
| C3 | **le format du motif CPE est supposé** (`cpe:2.3:h:...:...`) | un changement de format (2.2 vs 2.3, échappements `\\:`) casse silencieusement la recherche CVE | parsing/validation **obligatoires** en amont (le CDC le dit déjà) ; un seul module produit un CPE canonique |
| C4 | **`datetime.now()` dispersé** | ENF5 mort : deux runs du même contenu diffèrent | une seule source de temps injectée ; `now()` interdit dans les modules métier (règle lint) |
| C5 | **le journal HMAC est écrit depuis les modules métier** | la logique métier devient dépendante de l'intégrité ; impossible de tester `Infer` seul | seul l'orchestrateur écrit le journal ; les modules **rendent** des événements, ils ne les écrivent pas |

C5 est le plus insidieux : il paraît anodin en semaine 2 et rend le système intestable en semaine 4.

---

## 4. SPOF et isolement

| SPOF | Impact | Isolement |
|---|---|---|
| Serveur vLLM unique par nœud | run bloqué si le nœud tombe | pool d'URLs + bascule (D9) ; 1 nœud suffit à finir un run |
| **SQLite : écrivain unique** (WAL = 1 writer + N readers) | `database is locked` si Django écrit pendant l'ingestion | **un seul processus écrivain**, file d'attente ; l'ingestion CPE/NVD se fait hors ligne, API en lecture |
| Clé HMAC sur une seule machine | perdue ⇒ chaîne morte ; volée ⇒ forgeage | sauvegarde hors ligne + séparation Ed25519 (D11) ; clé **jamais** dans le dépôt |
| Snapshot NVD (source externe) | mode dégradé | snapshot local **immuable** + sha256 (D13) ; aucun appel réseau en run |
| Horloge système | ordre du journal, `published` | `JournalEvent.seq` monotone **en plus** de l'horodatage ; alerte `E_CLOCK_SKEW` |
| Disque (base append-only) | écriture impossible | contrôle d'espace avant run ⇒ `E_DISK_FULL` ; la base ne se compacte pas, donc on surveille la croissance |
| Le script d'ingestion CPE lui-même | reproductibilité non traçable | il rend un `dictionary_version_id` (D6) |

---

## 5. Taxonomie d'erreurs (complète, opérationnalisée)

Une erreur sans comportement n'est pas une gestion d'erreur. Colonnes : déclencheur / système / message utilisateur (FR) / trace journal.

| Code | Déclencheur | Comportement système | Message utilisateur | Trace |
|---|---|---|---|---|
| `E_MODEL_UNAVAILABLE` | aucun nœud vLLM ne répond | bascule nœud, puis abandon du run | « Service d'identification indisponible. Les photos ont été conservées ; relancez l'analyse. » | stage=infer, nœuds essayés |
| `E_VLM_TIMEOUT` | dépassement du délai par image | retry ×2 avec backoff, puis image marquée | « Analyse trop longue sur cette photo. Résultat partiel. » | image_id, durée |
| `E_VLM_INVALID_JSON` | Guided Decoding échoue (sortie non conforme) | 1 retry avec prompt réparateur ; sinon échec de l'image | « Réponse du modèle inexploitable. Photo non analysée. » | réponse brute tronquée (sans données sensibles) |
| `E_IMAGE_UNREADABLE` | décodage impossible / format | rejet immédiat, pas de retry | « Fichier illisible ou non supporté. » | sha256, cause |
| `E_MULTI_OBJECT_OR_UNCLEAR` | ≥ 2 objets saillants, ou cadrage inexploitable | rejet, pas de tentative d'identification | « Plusieurs objets détectés. Reprenez une photo par objet. » | sortie détection |
| `E_ADVERSARIAL_LABEL_SUSPECTED` | `visible_text` contient une formulation d'instruction | **le texte n'est jamais exécuté** ; run marqué suspect | « Texte suspect détecté sur l'objet. Vérification humaine requise. » | texte brut + motif |
| `E_NO_IDENTIFICATION` | aucun tuple ne se dégage | sortie « non identifié » | « Objet non identifié — vérification manuelle requise. » | distribution complète |
| `E_LOW_CONFIDENCE` | A < seuil bas | sortie « non identifié » (EF5) | « Identification peu stable. Vérification manuelle requise. » | A, distribution |
| `E_UNCALIBRATED_CONSENSUS` | A élevé **et** R faible | « identifié avec réserve », jamais « identifié » | « Résultat cohérent mais non retrouvé dans le référentiel. À vérifier manuellement. » | A, R |
| `E_NO_CPE_MATCH` | meilleur score < seuil de résolvabilité | pas de CPE → pas de CVE ; **jamais** de CPE inventé | « Objet identifié mais absent du référentiel NIST. Aucune CVE ne peut être rattachée. » | top-3 avec scores |
| `E_CPE_AMBIGUOUS` | écart top1−top2 < marge | propose les 2, force le HITL | « Deux référentiels correspondent. Sélectionnez le bon. » | les 2 scores |
| `E_NO_CVE` | 0 CVE après recherche correcte | **message non rassurant** | « Aucune CVE référencée pour ce produit au [date]. Cela **ne signifie pas** qu'il est exempt de vulnérabilités (version firmware non déterminée). » | cpe, snapshot, n |
| `E_NVD_UNAVAILABLE` | snapshot absent/illisible | mode dégradé : identification seule | « Base CVE locale indisponible. Analyse limitée à l'identification. » | cache_status |
| `E_NVD_CACHE_MISS` | CVE hors snapshot | marque explicitement | « Recherche effectuée sur la base du [date] ; certaines CVE récentes peuvent manquer. » | snapshot sha256 |
| `E_PROVENANCE_INCOMPLETE` | un champ de provenance manque | **écriture refusée** (contrainte SQL) | « Analyse refusée : traçabilité incomplète. » | champ manquant |
| `E_HMAC_CHAIN_BROKEN` | vérification de chaîne échoue | **run invalide**, export bloqué | « Intégrité du journal compromise. Export désactivé — contactez l'administrateur. » | index de rupture, attendu vs calculé |
| `E_JOURNAL_WRITE_FAILED` | écriture journal impossible | arrêt du run (on ne produit **pas** de résultat non tracé) | « Impossible d'enregistrer la trace. Analyse interrompue. » | erreur disque |
| `E_DISK_FULL` | espace insuffisant | refus avant run | « Espace de stockage insuffisant. » | seuil, disponible |
| `E_CLOCK_SKEW` | horloge incohérente entre étapes | avertit, continue (seq fait foi) | (invisible) | delta mesuré |
| `E_PARTIAL_RUN` | nœud perdu en cours | run marqué partiel, `nodes_used` mis à jour | « Analyse terminée avec un nœud en moins ; résultats complets pour les photos traitées. » | nœuds, images perdues |

**Deux codes méritent un commentaire :**

- **`E_ADVERSARIAL_LABEL_SUSPECTED`** : le text visible est une **donnée**, jamais une instruction. Le Guided Decoding limite déjà les dégâts (le modèle ne peut pas sortir du schéma), mais il peut encore permuter une marque *à l'intérieur* du schéma. Ce code est la trace de la tentative — utile au narratif sécurité (red-teaming de son propre outil).
- **`E_NO_CVE`** : c'est le message où la plupart des projets se rendent coupables de sur-promesse. « Aucune CVE trouvée » se lit « objet sûr ». La formule ci-dessus est non négociable.

**Trois codes décrivent un refus, et le refus est désormais appliqué au bon endroit** (2026-10-06) :

- `E_HMAC_CHAIN_BROKEN` — `storage.seal.sign_report` vérifie la chaîne **avant**
  de signer et lève `ChainBrokenError` (`break_index`, `expected`, `computed`).
  Auparavant elle scellait n'importe quelle base, chaîne rompue comprise : le
  rapport prouvait qu'une donnée venait de nous, pas qu'elle était inaltérée.
- `E_PROVENANCE_INCOMPLETE` — la contrainte SQL reste la garantie de dernier
  recours, mais le refus intervient plus tôt, au scellement : sans empreinte de
  poids ni SHA de prompt, le run n'est pas rejouable, donc pas défendable. À
  noter que rien dans le dépôt ne construit encore d'objet `Provenance`
  complet : la vérification est en place, l'alimentation de la provenance est
  un travail restant, et c'est écrit ici plutôt que sous-entendu.
- `E_DISK_FULL` — refus **avant** appel de modèle, via le pré-vol optionnel de
  l'orchestrateur (`pipeline.preflight.check_disk`). Un run qui manque d'espace
  en route ne laisse pas un résultat incomplet, il laisse une chaîne tronquée.

---

## 6. Critique du schéma SQLite

**Ce qui manque** (détail en D15) : provenance, `feed_versions`, `dictionary_versions`, table de critères CPE, `corrections` (HITL), colonnes de corpus, `strategy` sur les candidats.

**Ce qui posera problème à l'échelle :**

| Problème | Pourquoi | Correctif |
|---|---|---|
| `cve_cpe_matches.cpe_pattern` interrogeable par `LIKE` | aucun index utilisable, et sémantique fausse (NEGATE/plages) | table de critères dénormalisée + index `(part, vendor, product)` (D5) |
| `cpe_entries.embedding` en BLOB | correct, mais 384 × 4 octets × N ; et surtout **une seule colonne** ⇒ impossible de comparer deux stratégies de récupération | `strategy` enregistrée sur les candidats, colonnes distinctes si multi-modèle |
| Pas de FTS5 | la recherche lexicale (D3) n'a pas d'index | virtual table FTS5 trigram sur `(vendor, product, display_name)` |
| Aucune contrainte `UNIQUE` | doublons d'images/CVE après re-ingestion | `UNIQUE(images.sha256)`, `UNIQUE(cve_cpe_criteria(cve_id, criteria_key))` |
| Aucun `CHECK` sur les scores | `agreement = 7.5` passerait | `CHECK(agreement BETWEEN 0 AND 1)` |
| `cpe_candidates` sans stratégie ni version | impossible de savoir *pourquoi* ce candidat | `strategy`, `dictionary_version_id` |
| Écrivain unique non modélisé | `database is locked` aléatoires | processus écrivain unique + file (WAL) |
| Descriptions NVD en TEXT | ~tens of MB, acceptable, mais pas indexable en plein texte utile | FTS5 si besoin de recherche textuelle ; sinon ne pas indexer |
| Rétention | base append-only qui grossit indéfiniment (photos, runs) | politique de rétention documentée + `E_DISK_FULL` (RGPD : minimisation, voir `07`) |

**Le défaut structurel le plus grave** n'est pas une colonne manquante : c'est que **rien dans le schéma ne relie un résultat à l'état du monde qui l'a produit**. Sans D6 + D13 + D8, un rapport produit en septembre est une affirmation invérifiable en octobre. C'est exactement ce qui fait tomber un projet de ce type en soutenance.
