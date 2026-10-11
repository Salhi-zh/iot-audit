"""Tests unitaires pour iot_audit/modules/confidence.py (docs/05 §4).

Couvre :
1. Calculs d'accords A, A_brand, A_model, A_cat et distributions
2. Tous les 9 quadrants de la matrice de décision (docs/05 §4.2)
3. Détection de consensus halluciné (E_UNCALIBRATED_CONSENSUS)
4. Faible accord inter-photos (E_LOW_CONFIDENCE et E_NO_IDENTIFICATION)
5. Intervalle de confiance de Wilson (propriétés mathématiques, cas limites)
6. Intégration avec les sorties VLMRawOutput
"""

import pytest

from iot_audit.contracts import Category, CPECandidate, ErrorCode, Status, VLMRawOutput
from iot_audit.modules.confidence import (
    compute_agreements,
    decide_status,
    evaluate_confidence,
    wilson,
)


def test_wilson_score_bounds() -> None:
    # 0 observations
    lo, hi = wilson(0, 0)
    assert (lo, hi) == (0.0, 1.0)

    # 100% succès
    lo, hi = wilson(10, 10)
    assert 0.0 <= lo < 1.0
    assert hi == 1.0

    # 0% succès
    lo, hi = wilson(0, 10)
    assert lo == 0.0
    assert 0.0 < hi <= 1.0

    # 50/100
    lo, hi = wilson(50, 100)
    assert 0.40 <= lo < 0.50
    assert 0.50 < hi <= 0.60


def test_compute_agreements_empty() -> None:
    a, per_field, dist, modal = compute_agreements([])
    assert a == 0.0
    assert per_field == {"brand": 0.0, "model": 0.0, "category": 0.0}
    assert dist == {}
    assert modal is None


def test_compute_agreements_unanimous() -> None:
    raw = [
        VLMRawOutput(
            brand="TP-Link",
            model="Archer C7",
            category=Category.ROUTER,
            visible_text="Archer C7",
            evidence_image_region="box",
            confidence_self=0.9,
        )
        for _ in range(5)
    ]
    a, per_field, dist, modal = compute_agreements(raw)
    assert a == 1.0
    assert per_field["brand"] == 1.0
    assert per_field["model"] == 1.0
    assert per_field["category"] == 1.0
    assert modal == ("tp-link", "archer c7", Category.ROUTER)
    assert len(dist) == 1


def test_compute_agreements_partial_distribution() -> None:
    # 5 réponses différentes sur 8 photos (docs/05 §4.4)
    items: list[tuple[str, str, Category]] = [
        ("TP-Link", "Archer C7", Category.ROUTER),
        ("TP-Link", "Archer C7", Category.ROUTER),
        ("TP-Link", "Archer C7", Category.ROUTER),
        ("D-Link", "DIR-842", Category.ROUTER),
        ("D-Link", "DIR-842", Category.ROUTER),
        ("Netgear", "Nighthawk", Category.ROUTER),
        ("Asus", "RT-AC68U", Category.ROUTER),
        ("Linksys", "WRT3200", Category.ROUTER),
    ]
    a, per_field, dist, modal = compute_agreements(items)
    assert pytest.approx(a) == 3 / 8
    assert modal == ("tp-link", "archer c7", Category.ROUTER)
    # Marque : 3 tp link, 2 d link, 1 netgear, 1 asus, 1 linksys -> max = 3/8
    assert pytest.approx(per_field["brand"]) == 3 / 8
    # Catégorie : unanime router -> 8/8 = 1.0
    assert per_field["category"] == 1.0
    # A <= min(A_brand, A_model, A_cat)
    assert a <= per_field["brand"]
    assert a <= per_field["category"]
    assert len(dist) == 5


@pytest.mark.parametrize(
    ("a", "r", "expected_status", "expected_err"),
    [
        # Quadrants A >= 0.70
        (0.85, 0.95, Status.IDENTIFIED, None),
        (0.70, 0.90, Status.IDENTIFIED, None),
        (0.75, 0.80, Status.WITH_RESERVE, None),
        (0.70, 0.60, Status.WITH_RESERVE, None),
        (0.80, 0.50, Status.UNIDENTIFIED, ErrorCode.E_UNCALIBRATED_CONSENSUS),
        (0.99, 0.10, Status.UNIDENTIFIED, ErrorCode.E_UNCALIBRATED_CONSENSUS),
        # Quadrants 0.40 <= A < 0.70
        (0.50, 0.92, Status.WITH_RESERVE, None),
        (0.40, 0.75, Status.WITH_RESERVE, None),
        (0.65, 0.60, Status.WITH_RESERVE, None),
        (0.55, 0.40, Status.UNIDENTIFIED, ErrorCode.E_LOW_CONFIDENCE),
        (0.40, 0.59, Status.UNIDENTIFIED, ErrorCode.E_LOW_CONFIDENCE),
        # Quadrants A < 0.40
        (0.35, 0.95, Status.UNIDENTIFIED, ErrorCode.E_NO_IDENTIFICATION),
        (0.20, 0.70, Status.UNIDENTIFIED, ErrorCode.E_NO_IDENTIFICATION),
        (0.10, 0.30, Status.UNIDENTIFIED, ErrorCode.E_NO_IDENTIFICATION),
        (0.00, 0.00, Status.UNIDENTIFIED, ErrorCode.E_NO_IDENTIFICATION),
    ],
)
def test_decide_status_matrix(
    a: float, r: float, expected_status: Status, expected_err: ErrorCode | None
) -> None:
    status, err = decide_status(a, r)
    assert status == expected_status
    assert err == expected_err


def test_evaluate_confidence_full_flow() -> None:
    # Cas nominal : 4 photos d'un Archer C7, bon candidat CPE
    raw = [
        VLMRawOutput(
            brand="TP-Link",
            model="Archer C7",
            category=Category.ROUTER,
            visible_text="TP-Link",
            evidence_image_region="",
            confidence_self=0.9,
        )
        for _ in range(4)
    ]
    cand = CPECandidate(
        cpe_name="cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*",
        vendor="tp-link",
        product="archer_c7",
        version="2.0",
        category=Category.ROUTER,
        lexical_score=1.0,
        semantic_score=None,
        score=1.0,
        strategy="lexical",
    )

    ev = evaluate_confidence(raw, [cand])
    assert ev.status == Status.IDENTIFIED
    assert ev.error_code is None
    assert ev.agreement == 1.0
    assert ev.resolvability == 1.0
    assert ev.consensus_tuple == ("tp-link", "archer c7", Category.ROUTER)


def test_evaluate_confidence_hallucinated_consensus() -> None:
    # 5 photos concordantes sur une marque/modèle inconnue du référentiel
    raw = [
        ("FakeCorp", "QuantumGizmo 9000", Category.PLUG)
        for _ in range(5)
    ]
    # Aucun candidat CPE valide (score 0.25)
    cand = CPECandidate(
        cpe_name="cpe:2.3:h:fake:gizmo:*:*:*:*:*:*:*:*",
        vendor="fake",
        product="gizmo",
        version=None,
        category=Category.PLUG,
        lexical_score=0.25,
        semantic_score=None,
        score=0.25,
        strategy="lexical",
    )
    ev = evaluate_confidence(raw, [cand])
    assert ev.status == Status.UNIDENTIFIED
    assert ev.error_code == ErrorCode.E_UNCALIBRATED_CONSENSUS
    assert ev.agreement == 1.0
    assert ev.resolvability == 0.25
