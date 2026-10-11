"""Résolution CPE et fusion lexicale / sémantique (docs/05 §2, D3, D14).

Règles non négociables :
1. Lexical d'abord (D3) : si le score lexical est confiant (>= T_ACCEPT),
   le score sémantique NE DOIT PAS pouvoir dégrader le score.
2. Sauvetage sémantique : le sémantique n'intervient qu'en rattrapage quand
   le lexical est faible.
3. Seuil et marges de décision (docs/05 §3.1) :
   - score >= T_ACCEPT et marge >= T_MARGIN -> sélection automatique
   - score >= T_ACCEPT et marge < T_MARGIN  -> E_CPE_AMBIGUOUS (HITL forcé)
   - T_MIN <= score < T_ACCEPT             -> sélection avec réserve
   - score < T_MIN                         -> E_NO_CPE_MATCH (jamais de CPE inventé)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from difflib import SequenceMatcher

from iot_audit.contracts import CPECandidate, ErrorCode


class _FuzzFallback:
    """Repli de ``rapidfuzz.fuzz.token_set_ratio`` quand la dépendance manque.

    **Ce repli n'est pas fidèle, et le mesurer était le seul moyen de le
    savoir** (revue du 2026-10-06). Sur 500 paires de jetons tirées du
    vocabulaire CPE, la version antérieure reproduisait ``rapidfuzz``
    exactement ``96/500 = 19 %`` du temps, avec une erreur maximale de **33
    points** sur l'échelle 0–100 — soit 0,33 sur l'échelle du projet, quatre
    fois ``T_MARGIN`` (0,08), et de quoi faire passer un score de 0,80
    (``reserve``) à ≥ ``T_ACCEPT`` (``auto``).

    Elle faisait pire sur deux cas **nommés et datés** par le banc
    ``corpus/m4_bench_v2.py`` (2026-09-15) :

      ``archer c7`` vs ``archer c9``   ancien **1,00**  →  0,89 ici
      ``mt8163``    vs ``mt8863``      ancien **1,00**  →  0,83 ici

    Deux produits *différents* notés « identiques », donc sélectionnés
    automatiquement. La correction existait dans le banc depuis le 2026-09-15 ;
    elle n'avait jamais été reportée dans le chemin chaud. Elle l'est ici —
    et le repli est désormais **importable**, donc testable : il était défini
    dans une branche ``except ImportError``, ce qui explique qu'il n'ait
    jamais été mesuré.

    Le pire cas mesuré porte un nom dans ce projet : ``dir 600`` vs
    ``dir-600`` sortait à **100,00** chez l'ancien repli contre **42,86** chez
    le primaire — 57 points d'erreur, et c'est exactement la famille de
    séparateur du §15.6 de ``docs/06`` (``DIR-600`` écrit avec un tiret), que
    l'ancien repli appelait donc « identiques ». Le repli ci-dessous rend
    42,86, 50,00 et 71,43 sur ``dir 600``/``dsl 524t``/``p 870ha`` : la valeur
    du primaire, au centième.

    Pourquoi le **maximum de trois** comparaisons : une requête SUR-ENSEMBLE
    (« amazon echo dot wireless device » vs « echo dot ») doit atteindre 1,00 —
    les jetons parasites ne pénalisent pas (docs/05 §2.4) — et l'intersection
    seule ne doit pas suffire, sinon ``mt8163`` et ``mt8863`` se rejoignent.

    Résidu assumé : ``difflib.ratio`` (Ratcliff-Obershelp) n'est pas
    ``rapidfuzz.ratio`` (Indel). Ce repli reste une **approximation** : 86 % de
    reproductions exactes, erreur maximale 24 points. Il ne remplace pas le
    primaire, il s'en approche — et il ne fabrique plus de produits identiques.
    """

    @staticmethod
    def token_set_ratio(a: str, b: str) -> float:
        ta, tb = sorted(a.split()), sorted(b.split())
        if not ta or not tb:
            return 0.0
        inter = sorted(set(ta) & set(tb))
        da = [t for t in ta if t not in inter]
        db = [t for t in tb if t not in inter]
        joined = " ".join
        # r0 = plein vs plein · r1 = requête vs intersection · r2 = intersection vs produit
        r0 = SequenceMatcher(None, joined(inter + da), joined(inter + db)).ratio()
        r1 = SequenceMatcher(None, joined(inter + da), joined(inter)).ratio()
        r2 = SequenceMatcher(None, joined(inter), joined(inter + db)).ratio()
        return max(r0, r1, r2) * 100.0


try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover  (rapidfuzz est une dépendance déclarée)
    fuzz = _FuzzFallback()  # type: ignore[assignment]


T_ACCEPT = 0.90
T_MIN = 0.60
T_MARGIN = 0.08
W_SEM_RESCUE = 0.5

__all__ = [
    "T_ACCEPT",
    "T_MARGIN",
    "T_MIN",
    "W_SEM_RESCUE",
    "_FuzzFallback",
    "_fuse",
    "_lexical",
    "decide_cpe_code",
    "resolve",
]


def _lexical(q_model: str, q_version: str | None, cand: CPECandidate) -> float:
    """Calcule le score d'appariement lexical entre requête et candidat CPE."""
    q_norm = q_model.lower().strip()
    cand_prod = cand.product.replace("_", " ").lower().strip()
    base = fuzz.token_set_ratio(q_norm, cand_prod) / 100.0
    if q_version and cand.version:
        base = min(1.0, base + 0.05) if q_version == cand.version else base - 0.05
    return max(0.0, min(1.0, base))


def _fuse(lex: float, sem: float | None) -> float:
    """Le lexical d'abord (D3) ; le sémantique n'intervient qu'en rattrapage."""
    if sem is None:
        return lex
    if lex >= T_ACCEPT:
        return lex  # le lexical tranche : on ignore le sémantique
    return W_SEM_RESCUE * lex + (1.0 - W_SEM_RESCUE) * sem


def resolve(
    vlm_model: str,
    vlm_version: str | None,
    pool: list[CPECandidate],
) -> list[CPECandidate]:
    """Score et classe les candidats CPE par pertinence (top-3 max)."""
    scored = []
    for c in pool:
        lex = _lexical(vlm_model, vlm_version, c)
        fused = _fuse(lex, c.semantic_score)
        strategy = c.strategy
        if c.semantic_score is not None:
            strategy = "hybrid" if lex < T_ACCEPT else "lexical"
        scored.append(
            replace(
                c,
                lexical_score=lex,
                score=fused,
                strategy=strategy,
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:3]


def decide_cpe_code(
    top3: Sequence[CPECandidate],
) -> tuple[str, ErrorCode | None]:
    """Applique la matrice de décision de résolvabilité (docs/05 §3.1).

    Renvoie :
      - status: 'auto' | 'ambiguous' | 'reserve' | 'no_match'
      - error_code: ErrorCode | None
    """
    if not top3 or top3[0].score < T_MIN:
        return "no_match", ErrorCode.E_NO_CPE_MATCH

    top1 = top3[0]
    if top1.score >= T_ACCEPT:
        if len(top3) > 1 and (top1.score - top3[1].score) < T_MARGIN:
            return "ambiguous", ErrorCode.E_CPE_AMBIGUOUS
        return "auto", None

    return "reserve", None
