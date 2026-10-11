"""Tests unitaires de résolution CPE et fusion lexicale / sémantique (docs/07 §4.2, D3, D14).

Vérifie :
1. Règle D3 : le sémantique est ignoré quand le lexical est confiant (lex >= T_ACCEPT) ;
2. Le sémantique repêche quand le lexical est faible ;
3. Prise en compte de version exacte (+0.05) vs différente (-0.05) ;
4. Matrice de décision : E_NO_CPE_MATCH si score < T_MIN ;
5. Matrice de décision : E_CPE_AMBIGUOUS si marge top1-top2 < T_MARGIN ;
6. Sélection auto si score >= T_ACCEPT et marge >= T_MARGIN ;
7. Sélection avec réserve si T_MIN <= score < T_ACCEPT.
"""

from __future__ import annotations

import pytest

from iot_audit.contracts import Category, CPECandidate, ErrorCode
from iot_audit.modules.resolve_cpe import (
    T_ACCEPT,
    T_MARGIN,
    T_MIN,
    _fuse,
    _FuzzFallback,
    _lexical,
    decide_cpe_code,
    resolve,
)


def _cand(
    product: str,
    version: str | None = None,
    sem_score: float | None = None,
) -> CPECandidate:
    return CPECandidate(
        cpe_name=f"cpe:2.3:h:tp-link:{product}:{version or '*'}:*:*:*:*:*:*:*",
        vendor="tp-link",
        product=product,
        version=version,
        category=Category.ROUTER,
        lexical_score=0.0,
        semantic_score=sem_score,
        score=0.0,
        strategy="lexical" if sem_score is None else "hybrid",
    )


def test_semantic_ignored_when_lexical_confident() -> None:
    """Règle D3 : lexical fort -> le sémantique ne doit PAS dégrader le score."""
    assert _fuse(0.95, 0.10) == 0.95
    assert _fuse(0.90, 0.0) == 0.90


def test_semantic_rescues_when_lexical_weak() -> None:
    """Règle D3 : lexical faible -> le sémantique vient en renfort pondéré."""
    assert _fuse(0.40, 0.90) == pytest.approx(0.65)
    assert _fuse(0.50, None) == 0.50


def test_lexical_version_bonus_and_penalty() -> None:
    cand_v2 = _cand("archer_c7", version="2")
    score_v2 = _lexical("archer c7", "2", cand_v2)
    score_v3 = _lexical("archer c7", "3", cand_v2)
    assert score_v2 > score_v3
    assert score_v2 == pytest.approx(1.0)


def test_resolve_ranks_by_fused_score() -> None:
    cands = [
        _cand("tl_wr841n", sem_score=0.2),
        _cand("archer_c7", sem_score=0.9),
        _cand("archer_c9", sem_score=0.5),
        _cand("deco_m5", sem_score=0.1),
    ]
    ranked = resolve("archer c7 wireless router", None, cands)
    assert len(ranked) == 3  # top-3 max
    assert ranked[0].product == "archer_c7"
    assert ranked[0].score >= ranked[1].score >= ranked[2].score


def test_decision_no_cpe_match_under_t_min() -> None:
    cands = [
        _cand("gadget_xyz", sem_score=0.1),
    ]
    ranked = resolve("completely different item", None, cands)
    status, code = decide_cpe_code(ranked)
    assert status == "no_match"
    assert code == ErrorCode.E_NO_CPE_MATCH


def test_decision_ambiguous_when_top2_within_margin() -> None:
    # 2 candidats très proches au-dessus de T_ACCEPT
    cands = [
        _cand("archer_c7", sem_score=0.92),
        _cand("archer_c7_eu", sem_score=0.91),
    ]
    ranked = resolve("archer c7", None, cands)
    assert ranked[0].score >= T_ACCEPT
    assert (ranked[0].score - ranked[1].score) < T_MARGIN
    status, code = decide_cpe_code(ranked)
    assert status == "ambiguous"
    assert code == ErrorCode.E_CPE_AMBIGUOUS


def test_decision_auto_selected() -> None:
    cands = [
        _cand("archer_c7", sem_score=0.95),
        _cand("archer_c2", sem_score=0.50),
    ]
    ranked = resolve("archer c7", None, cands)
    assert ranked[0].score >= T_ACCEPT
    assert (ranked[0].score - ranked[1].score) >= T_MARGIN
    status, code = decide_cpe_code(ranked)
    assert status == "auto"
    assert code is None


def test_decision_reserve_when_between_t_min_and_t_accept() -> None:
    cands = [
        _cand("archer_c7", sem_score=0.75),
    ]
    # Requete partielle donnant un score moyen
    ranked = resolve("archer pro router", None, cands)
    if T_MIN <= ranked[0].score < T_ACCEPT:
        status, code = decide_cpe_code(ranked)
        assert status == "reserve"
        assert code is None


# --------------------------------------------------------------------------- #
# Le repli difflib — le mesurer est la seule façon de savoir qu'il n'est pas
# fidèle (revue du 2026-10-06)
# --------------------------------------------------------------------------- #
# Le repli vivait dans une branche ``except ImportError`` : impossible à
# importer, donc impossible à tester, donc jamais mesuré. Il gonflait de ×1,25
# et rendait 1,00 pour des produits DIFFÉRENTS. Les quatre tests ci-dessous le
# rendent visible : deux cas nommés, une requête sur-ensemble, la tolérance
# mesurée vis-à-vis du primaire, et la décision qui en découle.


def test_le_repli_ne_fabrique_pas_de_produits_identiques() -> None:
    """Les deux cas nommés par ``corpus/m4_bench_v2.py`` (2026-09-15).

    L'ancien repli rendait ``100,00`` pour les deux paires : deux références
    *différentes* notées « identiques », donc sélectionnées automatiquement.
    """
    fb = _FuzzFallback.token_set_ratio
    assert fb("archer c7", "archer c9") < 90.0
    assert fb("mt8163", "mt8863") < 90.0
    # le cas séparateur du §15.6 de docs/06 : l'ancien repli rendait 100,00
    # pour ``dir 600`` vs ``dir-600``, là où le primaire dit 42,86.
    assert fb("dir 600", "dir-600") < 90.0
    # une référence identique reste à 100
    assert fb("archer c7", "archer c7") == 100.0


def test_le_repli_ne_punit_pas_une_requete_sur_ensemble() -> None:
    """docs/05 §2.4 : les jetons parasites ne pénalisent pas une bonne réponse."""
    fb = _FuzzFallback.token_set_ratio
    assert fb("amazon echo dot wireless device", "echo dot") == 100.0
    assert fb("tp link archer c7 wireless router", "archer c7") == 100.0


def test_le_repli_serre_rapidfuzz_a_tolerance_mesuree() -> None:
    """Le repli APPROCHE le primaire — il ne le reproduit pas, et c'est écrit.

    Mesuré le 2026-10-06 sur 500 paires de jetons du vocabulaire CPE : 86 % de
    valeurs exactes, erreur maximale 24 points sur 100 (l'ancien repli : 19 %
    et 33 points). La tolérance ci-dessous est celle de ce jeu fixe ; elle tombe
    si le repli repart en inflation.
    """
    rapidfuzz = pytest.importorskip("rapidfuzz.fuzz")
    fixtures = [
        ("archer c7", "archer c7"),
        ("archer c7", "archer c9"),
        ("archer c7", "archer c7 wireless router"),
        ("amazon echo dot wireless device", "echo dot"),
        ("mt8163", "mt8863"),
        ("tp link", "tp link"),
        ("gadget xyz", "completely different item"),
        ("dir 600", "dir 600"),
        ("c7", "archer c7"),
        ("netgear", "tp link"),
        ("archer c7", "archer c7 eu"),
        ("dir 600", "dir-600"),
        ("dsl 524t", "dsl-524t"),
        ("p 870ha", "p-870ha"),
        ("a", ""),
    ]
    for a, b in fixtures:
        ref = rapidfuzz.token_set_ratio(a, b)
        got = _FuzzFallback.token_set_ratio(a, b)
        assert abs(got - ref) <= 10.0, f"{a!r} vs {b!r} : repli {got:.2f} vs primaire {ref:.2f}"


def test_sous_le_repli_la_decision_reste_celle_du_primaire(monkeypatch) -> None:
    """Le repli doit reproduire la DÉCISION du primaire, pas seulement un score.

    Cas mesuré : requête « archer c7 » face à ``archer_c7`` et ``archer_c9``.
    Avec rapidfuzz le second sort à 0,889, la marge dépasse ``T_MARGIN`` ⇒
    ``auto``. Avec l'ANCIEN repli les deux sortaient à 1,00, la marge tombait
    sous ``T_MARGIN``, et le système forçait une revue humaine
    (``E_CPE_AMBIGUOUS``) : une différence de comportement selon que la machine
    avait ou non ``rapidfuzz`` installé.
    """
    from iot_audit.modules import resolve_cpe

    monkeypatch.setattr(resolve_cpe, "fuzz", resolve_cpe._FuzzFallback())
    ranked = resolve_cpe.resolve("archer c7", None, [_cand("archer_c7"), _cand("archer_c9")])
    status, code = resolve_cpe.decide_cpe_code(ranked)
    assert status == "auto"
    assert code is None
