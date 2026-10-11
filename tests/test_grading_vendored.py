"""Verrouille la copie *vendored* du barème gelé (`iot_audit/corpus/audit_grading.py`).

Un barème gelé dont on ne peut pas montrer qu'il n'a pas dérivé n'est plus gelé. Ce
fichier vérifie trois choses, dans cet ordre d'importance :

1. **le diff avec l'original est exactement celui qui est documenté** — c'est la
   propriété qui permet de dire que la copie juge *comme* l'original, et pas
   seulement « comme prévu » ;
2. **l'empreinte de la copie n'a pas bougé** — même quand l'original est
   injoignable (autre poste), la copie reste figée ;
3. **la copie est fonctionnellement celle qu'on croit** — même API, et les
   figures publiées du §10.2 / §14.1 la reproduisent depuis le dépôt seul.

Sans le point 1, le point 2 ne prouverait rien : n'importe quelle copie aurait une
empreinte stable. Sans le point 2, le point 1 ne serait vérifiable que sur un poste
qui possède le voisin.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VENDORED = ROOT / "iot_audit" / "corpus" / "audit_grading.py"
SOURCE = ROOT.parent / "zabeth22-vllm-repair" / "audit-grading.py"
PROVENANCE = ROOT / "iot_audit" / "corpus" / "VENDORED-audit-grading.md"

# Empreintes publiées dans `VENDORED-audit-grading.md`. Les deux sont épinglées :
# si l'une bouge sans l'autre, ce test tombe et il faut mettre à jour le document
# **et** expliquer pourquoi dans `docs/06` (§15.6 est le précédent : l'ajout du
# critère P a publié les deux chiffres, jamais le seul nouveau).
SHA_VENDORED = "30ca55a0d2eb08e0218b4df28e15771717c24d7d36160fd0a1d5c0dd8182d440"
SHA_SOURCE = "2120ce2af409972816d74384529036312f0d3572363bcd83dd2cc23a567e25f1"
# Les deux tailles diffèrent de 17 octets : c'est exactement ce que la ligne `EV`
# réécrite fait gagner. Les déclarer séparément plutôt qu'une seule valeur rend
# l'écart *attendu* — et donc vérifiable — au lieu de surprenant.
SIZE_VENDORED = 16466
SIZE_SOURCE = 16483

# Le diff autorisé, **une seule ligne** : le chemin d'évidence `EV`, qui diffère
# par construction entre le dépôt voisin et celui-ci. Aucune fonction de notation
# ne doit jamais apparaître ici.
DIFF_ATTENDU = (
    "-EV = Path(__file__).resolve().parent.parent / \"iot-audit\" / \"evidence\" "
    "/ \"2026-09-14\" / \"corpus\" / \"expanded\"\n"
    "+EV = Path(__file__).resolve().parents[2] / \"evidence\" "
    "/ \"2026-09-14\" / \"corpus\" / \"expanded\"\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _diff_lines(a: Path, b: Path) -> list[str]:
    """Lignes de diff (contenu seul, sans en-têtes ni contexte), dans l'ordre."""
    la = a.read_text(encoding="utf-8").splitlines(keepends=True)
    lb = b.read_text(encoding="utf-8").splitlines(keepends=True)
    return [
        line for line in difflib.unified_diff(la, lb, n=0)
        if line[:1] in "+-" and line[:3] not in ("+++", "---")
    ]


def test_la_copie_existe_et_a_la_taille_attendue():
    assert VENDORED.is_file(), f"barème vendored absent : {VENDORED}"
    assert VENDORED.stat().st_size == SIZE_VENDORED


def test_empreinte_de_la_copie_est_epinglee():
    """Vaut même sans le voisin : c'est le verrou qui reste sur n'importe quel poste."""
    assert _sha(VENDORED) == SHA_VENDORED


@pytest.mark.skipif(not SOURCE.is_file(), reason="dépôt voisin absent sur ce poste")
def test_lempreinte_de_loriginal_est_epinglee():
    assert _sha(SOURCE) == SHA_SOURCE
    assert SOURCE.stat().st_size == SIZE_SOURCE
    # L'écart de taille est la somme du diff : 17 octets, ni plus ni moins.
    assert SIZE_SOURCE - SIZE_VENDORED == 17


@pytest.mark.skipif(not SOURCE.is_file(), reason="dépôt voisin absent sur ce poste")
def test_le_diff_avec_loriginal_est_exactement_celui_du_document():
    """La propriété centrale : **une** ligne change, et c'est `EV`.

    Si une ligne de notation s'ajoutait au diff, la copie cesserait d'être le même
    barème — et toutes les figures du §10/§14 recalculées depuis le dépôt
    deviendraient non comparables à celles de 2026-09-14. Ce test est la seule
    chose qui empêche cela d'arriver en silence.
    """
    assert "".join(_diff_lines(SOURCE, VENDORED)) == DIFF_ATTENDU


def test_le_document_de_provenance_cite_les_deux_empreintes():
    """Le document et le test doivent porter les mêmes empreintes.

    Sinon l'un des deux vieillit tout seul : un test vert avec un document faux est
    pire qu'un test rouge.
    """
    doc = PROVENANCE.read_text(encoding="utf-8")
    assert SHA_VENDORED in doc
    assert SHA_SOURCE in doc
    assert "parents[2]" in doc


def test_la_copie_expose_lapi_de_notation():
    from corpus._common import load_grading  # noqa: PLC0415  (import tardif : dépend du sys.path)

    g = load_grading()
    for nom in ("norm", "norm_sep", "model_correct", "brand_correct",
                "effective_category", "cat_correct", "wilson"):
        assert callable(getattr(g, nom)), f"{nom} manquant du barème vendored"
    assert set(g.TRUTH_ALIASES) == {"nest doorbell"}
    assert g.TRUTH_CATEGORY_OVERRIDES == {"google__nest_doorbell": "ip_camera"}


def test_la_copie_reproduit_les_figures_publiees_du_depot():
    """Vérifie depuis le **dépôt seul** — aucune évidence hors dépôt n'est relue ici.

    Les chiffres attendus sont ceux publiés : `11/144` et `32/144` (§10.2),
    `63/144` et `17/144` (§13.2 bis et §14.1). Un barème qui juge autrement
    invaliderait ces sections ; le test le dit tout de suite.
    """
    from corpus._common import load_grading  # noqa: PLC0415

    g = load_grading()
    ev = ROOT / "evidence" / "2026-09-14" / "corpus" / "expanded"
    v1 = json.loads((ev / "run2-v1-predictions.json").read_text(encoding="utf-8"))
    v2 = json.loads((ev / "run2-v2-predictions.json").read_text(encoding="utf-8"))

    assert sum(g.model_correct(r, "A") for r in v1) == 32
    assert sum(g.brand_correct(r) and g.model_correct(r, "A") for r in v1) == 11
    assert sum(g.model_correct(r, "A") for r in v2) == 63
    assert sum(g.brand_correct(r) and g.model_correct(r, "A") for r in v2) == 17


# --------------------------------------------------------------------------- #
# Le barème copie `wilson` — donc il faut vérifier que les copies concordent   #
# --------------------------------------------------------------------------- #
# HISTORIQUE (revue du 2026-10-06). ``wilson`` existe en SEPT exemplaires dans
# le dépôt : ``docs/05`` §4.3, ``modules/confidence.py``, ``corpus/metrics.py``,
# ce barème, ``corpus/calibrate_status.py``, ``corpus/ocr-validation/
# corpus_legibility.py`` et ``corpus/ocr-validation/evaluate_ocr.py``. Le barème
# est **gelé** (empreinte épinglée plus haut) : si une copie divergeait, deux
# chiffres publiés portant le même nom cesseraient d'être comparables, et rien
# ne le signalerait — chaque copie a ses propres tests, donc chacune reste verte.
#
# Mesure du 2026-10-06 : sur ``n ∈ {1,2,5,8,17,30,48,97,144,1000}`` et tous les
# ``k``, les trois copies du paquet concordent à moins de ``1e-12`` près. Elles
# diffèrent au dernier bit dans 4 cas sur ~30 000 (``math.sqrt`` contre
# ``** 0.5``, deux écritures de la même formule) — jamais au-delà. La SEULE
# divergence de **comportement** est ``n = 0``, et elle est historique :
# le barème gelé y rend ``(0, 0)``, le code déployé ``(0, 1)``.

N_GRID = (1, 2, 5, 8, 17, 30, 48, 97, 144, 1000)


def test_les_trois_wilson_du_paquet_concordent_a_un_bit_pres():
    """``confidence``, ``metrics`` et le barème gelé doivent rendre le même IC.

    Tolérance ``1e-12`` et non égalité exacte : deux écritures équivalentes de
    la même formule peuvent différer du dernier bit sans que le chiffre publié
    (arrondi au millième) bouge d'un iota. Exiger l'égalité *exacte* ferait
    tomber ce test sur une non-différence — un faux positif qui apprendrait à
    ignorer le test.
    """
    from corpus._common import load_grading  # noqa: PLC0415  (dépend du sys.path)
    from iot_audit.corpus import metrics  # noqa: PLC0415
    from iot_audit.modules import confidence  # noqa: PLC0415

    bareme = load_grading()
    copies = {
        "confidence.wilson": confidence.wilson,
        "metrics.wilson": metrics.wilson,
        "audit_grading.wilson": bareme.wilson,
    }
    for n in N_GRID:
        for k in range(n + 1):
            ref = copies["confidence.wilson"](k, n)
            for nom, f in copies.items():
                got = f(k, n)
                assert abs(got[0] - ref[0]) < 1e-12, f"{nom}({k},{n}) = {got} != {ref}"
                assert abs(got[1] - ref[1]) < 1e-12, f"{nom}({k},{n}) = {got} != {ref}"


def test_les_wilson_ne_divergent_que_sur_le_groupe_vide():
    """``n = 0`` : le barème gelé rend ``(0, 0)``, le code déployé ``(0, 1)``.

    Ce n'est **pas** une divergence à corriger, c'est une divergence à ne pas
    déclencher :

    * ``(0.0, 1.0)`` est le comportement juste — aucune mesure, donc aucune
      information, donc l'intervalle plein ``[0 ; 1]`` ;
    * ``(0.0, 0.0)`` est un intervalle **vide**, c'est-à-dire l'affirmation
      d'une certitude sur zéro observation.

    Le barème est gelé (empreinte ``SHA_VENDORED``, ci-dessus), donc il ne se
    corrige pas : la règle est de ne **jamais** l'appeler sur un groupe vide
    (ni ``fmt(k, 0)``, qui divise par zéro de toute façon). Ce test épingle les
    deux valeurs pour que la règle soit explicite et pour qu'un appel
    accidentel se voie ici plutôt qu'en production.
    """
    from corpus._common import load_grading  # noqa: PLC0415
    from iot_audit.corpus import metrics  # noqa: PLC0415
    from iot_audit.modules import confidence  # noqa: PLC0415

    bareme = load_grading()
    assert bareme.wilson(0, 0) == (0.0, 0.0)
    assert confidence.wilson(0, 0) == (0.0, 1.0)
    assert metrics.wilson(0, 0) == (0.0, 1.0)
