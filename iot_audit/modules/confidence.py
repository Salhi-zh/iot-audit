"""Mesure de confiance et matrice de décision à deux axes (docs/05 §4).

Formalisation (docs/05 §4.1) :
Soit N photos du même objet. Après normalisation, chaque photo i donne
un tuple t_i = (brand_i, model_i, category_i).

Accord inter-photos (A) :
    A = max_t |{i : t_i = t}| / N  in [1/N, 1]

Accords par champ :
    A_brand = max_b |{i : brand_i = b}| / N
    A_model = max_m |{i : model_i = m}| / N
    A_cat   = max_c |{i : cat_i = c}| / N

Résolvabilité (R) :
    R = score fusionné du candidat CPE top 1 retenu (ou 0.0 si aucun candidat).

Matrice de décision (A, R) (docs/05 §4.2) :
+-------------------+----------------+--------------------------+-------------------------------------+
|      A \\ R       |    R >= 0.90   |     0.60 <= R < 0.90     |               R < 0.60              |
+-------------------+----------------+--------------------------+-------------------------------------+
| A >= 0.70         | identified     | identified_with_reserve  | unidentified (E_UNCALIBRATED_CONS)  |
| 0.40 <= A < 0.70  | with_reserve   | identified_with_reserve  | unidentified (E_LOW_CONFIDENCE)     |
| A < 0.40          | unidentified   | unidentified             | unidentified (E_NO_IDENTIFICATION)  |
+-------------------+----------------+--------------------------+-------------------------------------+

Règle d'or :
La cellule A >= 0.70 et R < 0.60 est la signature d'un consensus halluciné.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from iot_audit.contracts import Category, CPECandidate, ErrorCode, Status, VLMRawOutput
from iot_audit.pipeline.normalize import canon_vendor, normalize_display

__all__ = [
    "ConfidenceEvaluation",
    "compute_agreements",
    "decide_status",
    "evaluate_confidence",
    "wilson",
]


@dataclass(frozen=True, slots=True)
class ConfidenceEvaluation:
    """Résultat complet de l'évaluation de confiance."""

    status: Status
    error_code: ErrorCode | None
    agreement: float
    resolvability: float
    consensus_tuple: tuple[str, str, Category] | None
    per_field_agreement: dict[str, float]
    distribution: dict[str, int]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance de Wilson (docs/05 §4.3).

    À utiliser sur l'ACCURACY par objet, PAS sur l'accord inter-photos A.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + (z * z) / n
    centre = (p + (z * z) / (2.0 * n)) / d
    demi = (z * ((p * (1.0 - p) / n + (z * z) / (4.0 * n * n)) ** 0.5)) / d
    return (max(0.0, centre - demi), min(1.0, centre + demi))


def compute_agreements(
    outputs: Sequence[VLMRawOutput | tuple[str, str, Category]],
) -> tuple[float, dict[str, float], dict[str, int], tuple[str, str, Category] | None]:
    """Calcule l'accord global A, les accords par champ, et la distribution.

    Chaque élément est converti en tuple normalisé (brand, model, category).

    **Ce ``A`` n'est pas celui du §8.4.** Il **canonise** les libellés
    (``canon_vendor`` / ``normalize_display``) ; l'``agreement`` de
    ``iot_audit.corpus.metrics`` compare des chaînes exactes et c'est celui des
    figures publiées (§8.4 de ``docs/06``). Les deux coïncident sur le corpus
    publié (marque ``0,9153``, modèle ``0,8397``) et divergent de 0,4 à 0,8
    point sur le corpus v4 (mesure et objets concernés dans la docstring de
    ``corpus.metrics.agreement``). C'est bien celui-ci qui **décide** : il est
    appelé par ``pipeline.orchestrate`` et alimente la matrice ``A × R``.
    """
    if not outputs:
        return (0.0, {"brand": 0.0, "model": 0.0, "category": 0.0}, {}, None)

    n = len(outputs)
    tuples: list[tuple[str, str, Category]] = []

    for item in outputs:
        if isinstance(item, VLMRawOutput):
            b = canon_vendor(item.brand)
            m = normalize_display(item.model)
            c = item.category
        else:
            raw_b, raw_m, c = item
            b = canon_vendor(raw_b)
            m = normalize_display(raw_m)
        tuples.append((b, m, c))

    counts = Counter(tuples)
    most_common_tuple, best_count = counts.most_common(1)[0]
    agreement = best_count / n

    brand_counts = Counter(t[0] for t in tuples)
    model_counts = Counter(t[1] for t in tuples)
    cat_counts = Counter(t[2] for t in tuples)

    per_field = {
        "brand": brand_counts.most_common(1)[0][1] / n,
        "model": model_counts.most_common(1)[0][1] / n,
        "category": cat_counts.most_common(1)[0][1] / n,
    }

    distribution = {f"{t[0]} | {t[1]} | {t[2].value}": count for t, count in counts.items()}

    return (agreement, per_field, distribution, most_common_tuple)


def decide_status(agreement: float, resolvability: float) -> tuple[Status, ErrorCode | None]:
    """Matrice de décision à deux axes (docs/05 §4.2).

    Retourne (Status, ErrorCode | None).
    """
    if agreement >= 0.70:
        if resolvability >= 0.90:
            return (Status.IDENTIFIED, None)
        elif resolvability >= 0.60:
            return (Status.WITH_RESERVE, None)
        else:
            # A élevé, R faible : consensus halluciné
            return (Status.UNIDENTIFIED, ErrorCode.E_UNCALIBRATED_CONSENSUS)
    elif agreement >= 0.40:
        if resolvability >= 0.60:
            return (Status.WITH_RESERVE, None)
        else:
            return (Status.UNIDENTIFIED, ErrorCode.E_LOW_CONFIDENCE)
    else:
        # A < 0.40
        return (Status.UNIDENTIFIED, ErrorCode.E_NO_IDENTIFICATION)


def evaluate_confidence(
    outputs: Sequence[VLMRawOutput | tuple[str, str, Category]],
    cpe_candidates: Sequence[CPECandidate] | None = None,
) -> ConfidenceEvaluation:
    """Évalue la confiance et rend la décision consolidée."""
    agreement, per_field, distribution, modal_tuple = compute_agreements(outputs)

    resolvability = 0.0
    if cpe_candidates:
        resolvability = max(c.score for c in cpe_candidates)

    status, err = decide_status(agreement, resolvability)

    return ConfidenceEvaluation(
        status=status,
        error_code=err,
        agreement=agreement,
        resolvability=resolvability,
        consensus_tuple=modal_tuple,
        per_field_agreement=per_field,
        distribution=distribution,
    )
