# Cahier des spécifications techniques — v2.1

**Projet** : Reconnaissance d'objets connectés pour audit de sécurité IoT  
**Auteur** : Mohamed Salhi — Polytech Lille / ENSA Kénitra · **Tuteur** : Thomas Vantroys  
**Rôle** : Document d'ingénierie normatif (Architecture, contrats formels, modèles et protocoles)  
**Date de révision** : 24 septembre 2026

---

## 1. Principes d'ingénierie logicielle

1. **P1 — Contrats algébriques gelés :** Aucun dictionnaire brut, aucun `**kwargs` entre modules. Utilisation exclusive de `@dataclass(frozen=True, slots=True)` et `StrEnum`.
2. **P2 — Mono-écrivain & SQLite WAL :** Persistance locale en `PRAGMA journal_mode = WAL` et `PRAGMA foreign_keys = ON`. L'ingestion lourde se fait hors ligne ; l'API ou le CLI ne font que lire.
3. **P3 — Déterminisme temporel :** Injection explicite des dates et timestamps. `datetime.now()` direct interdit dans les cœurs de calcul pour garantir le rejeu ($ENF5$).
4. **P4 — Souveraineté mono-machine (P8) :** L'intégralité de la chaîne (VLM, Matching CPE, Recherche CVE, PDF) s'exécute de bout en bout sur 1 seule machine dotée d'un GPU 12 Go. Le cluster 3 nœuds sert à la parallélisation de débit, jamais de dépendance liante.

---

## 2. Pile d'inférence VLM & Résultats du Banc Multi-Nœuds

### 2.1 Configuration de production
- **Modèle sélectionné** : `Qwen2.5-VL-7B-Instruct-GPTQ-Int4` (supériorité statistique formelle sur Qwen3-VL et Llama 3.2 validée par banc sur 144 images).
- **Moteur d'inférence** : vLLM 0.29.0 avec Guided Decoding (schéma JSON strict garantissant la syntaxe).
- **Serveurs actifs** : ports 8000 sur zabeth21 (`172.26.145.71`), zabeth22 (`172.26.145.72`) et zabeth23 (`172.26.145.73`).

### 2.2 Preuve de parallélisme mesurée (Banc du 24/09/2026)
Le banc parallèle 3 nœuds simultané consigné dans `evidence/2026-09-24/bench-3nodes.json` établit :
- **Latence par image** : $p_{50} = 1.80\text{ s}$ (z21), $p_{50} = 1.96\text{ s}$ (z22), $p_{50} = 2.88\text{ s}$ (z23).
- **Concordance des prédictions** : **100 % d'accord** sur le tuple `(marque, modèle, catégorie)` sur les images communes interrogées en parallèle.

---

## 3. Architecture applicative et contrats formels

```
[Photo] ──► 1. Ingestion & VLM (Qwen2.5-VL + OCR)
                 │
                 ▼  (VLMRawOutput)
            2. Matcher CPE (FTS5 trigrammes + TokenSetRatio)
                 │
                 ▼  (CPECandidate)
            3. Moteur CVE local (Pré-filtre SQL + Algèbre de plages)
                 │
                 ▼  (SearchResult -> List[CveHit])
            4. Synthèse (PDF signé + Journal HMAC Ed25519)
```

### Contrats d'échange (`iot_audit/contracts.py`)

```python
from dataclasses import dataclass
from enum import StrEnum

class Category(StrEnum):
    PLUG = "smart_plug"
    CAMERA = "ip_camera"
    BULB = "smart_bulb"
    ROUTER = "router_ap"
    SPEAKER = "smart_speaker"

@dataclass(frozen=True, slots=True)
class VLMRawOutput:
    brand: str
    model: str
    category: Category
    visible_text: str
    evidence_image_region: str
    confidence_self: float

@dataclass(frozen=True, slots=True)
class CPECandidate:
    cpe_name: str
    vendor: str
    product: str
    version: str | None
    score: float
    strategy: str

@dataclass(frozen=True, slots=True)
class CveHit:
    cve_id: str
    match_basis: str  # 'exact_product' | 'version_range' | 'vendor_wildcard'
    unresolved: bool
    cvss_v3_score: float | None
    severity: str | None
    published: str | None
    vuln_status: str | None
    matched_criteria: tuple[str, ...]
```

---

## 4. Données et Moteurs Locaux (Prouvés et Mesurés)

### 4.1 Référentiel matériel CPE (NIST)
- Base locale `corpus/cpe.sqlite` (1 838 235 entrées complètes).
- Sous-ensemble hardware indexé `part='h'` (64 842 entrées) : table FTS5 trigrammes pour recherche lexicale rapide.

### 4.2 Base locale NVD et Moteur CVE (`iot_audit/vuln/`)
- Ingestion streaming idempotente des flux NVD 2021-2024 (`corpus/nvd.sqlite`) : 324 470 critères et 121 719 CVEs.
- **Moteur `search_cve`** : Pré-filtre SQL `(vendor, product)` et évaluation en Python des plages de versions (`versionStartIncluding`, `versionEndExcluding`).
- **Performance mesurée le 24/09/2026** : $p_{50} = 1.54\text{ ms}$, $p_{95} = 3.48\text{ ms}$ sur base réelle (324k lignes).
- **Règle de séparation de preuve** : un critère `product='*'` renvoie `match_basis='vendor_wildcard'` et n'est jamais confondu avec un match produit direct.

---

## 5. Briques suivantes : Intégrité, Rapport & Démo

- **Journal séquentiel HMAC-SHA256 & Signature Ed25519** : Chaque étape génère un bloc chaîné $H_k = \text{HMAC}(H_{k-1}, \text{event}_k)$. La tête est signée par clé asymétrique Ed25519 lors de l'export du rapport PDF.
- **Rapport d'audit PDF** : Édition structurée rappelant la limite `triage_scope='product'` et imprimant la clé publique pour vérification autonome par un auditeur tiers.
- **Interface de démonstration** : CLI interactif et point d'accès HTTP léger pour soumettre une photo et restituer le PDF scellé.
