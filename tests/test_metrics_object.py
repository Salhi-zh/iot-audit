"""Verrouille les métriques **au niveau objet** contre la table publiée.

Ce fichier existe parce que le M1 publié n'était pas reproductible : la table de
verdicts du 2026-09-14 était conservée
(`evidence/2026-09-14/corpus/object-results.json`) mais aucune fonction du dépôt
ne la recalculait. Un second banc a donc réinventé une consolidation différente
et publié `8/48 = 0,167` sous l'étiquette « marque ET modèle » alors qu'il ne
notait que le modèle (voir `docs/06` §19).

Les tests ci-dessous ne « vérifient » pas que 8/26 est la bonne réponse : ils
vérifient qu'on **recalcule** le chiffre publié, verdict par verdict, à partir
des prédictions brutes. Le jour où la règle change, ils cassent — c'est le but.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iot_audit.corpus import metrics

ROOT = Path(__file__).resolve().parent.parent
CORPUS_V1 = ROOT / "evidence/2026-09-14/corpus/predictions-zabeth22.json"
TABLE_PUBLIEE = ROOT / "evidence/2026-09-14/corpus/object-results.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _verdicts(records, rule):
    return {r.object_id: r.verdict for r in metrics.object_results(records, rule)}


# --------------------------------------------------------------------------- #
# Reproduction de la table publiée — le contrôle d'instrument
# --------------------------------------------------------------------------- #

def test_reproduit_le_m1_publie_8_sur_26():
    """M1 `conservative` sur le corpus publié : 8/26, IC [0,165 ; 0,500]."""
    recs = _load(CORPUS_V1)
    m1 = metrics.summarize("M1", metrics.object_results(recs, "conservative"))
    assert (m1.k, m1.n) == (8, 26)
    assert m1.p == pytest.approx(8 / 26)
    lo, hi = metrics.wilson(8, 26)
    assert (round(lo, 3), round(hi, 3)) == (0.165, 0.500)


def test_reproduit_la_repartition_des_verdicts():
    """La répartition publiée : 8 exact, 2 marque-sans-modèle, 13 marque-non, 3 faux."""
    recs = _load(CORPUS_V1)
    m1 = metrics.summarize("M1", metrics.object_results(recs, "conservative"))
    assert m1.detail == {"exact": 8, "brand_ok_model_no": 2,
                         "brand_no_category_ok": 13, "faux": 3}


def test_reproduit_les_26_verdicts_individuels():
    """Verdict par verdict, contre la table stockée — **les 26**, sans exception.

    La règle en code est donc la règle publiée, et pas seulement sur le total :
    sans ce test, deux consolidations différentes peuvent tomber sur le même
    numérateur et diverger sur *quels* objets passent — exactement le défaut qui
    a produit le faux « 8/48 » du 2026-09-29.
    """
    recs = _load(CORPUS_V1)
    attendu = {o["object_id"]: o["verdict"] for o in _load(TABLE_PUBLIEE)}
    obtenu = _verdicts(recs, "conservative")
    assert set(obtenu) == set(attendu)
    assert {o: (attendu[o], obtenu[o]) for o in attendu if attendu[o] != obtenu[o]} == {}


# --------------------------------------------------------------------------- #
# Les deux règles de consolidation
# --------------------------------------------------------------------------- #

def test_les_deux_regles_donnent_des_chiffres_differents():
    """Si `conservative` et `answered` coïncidaient, publier les deux serait un
    théâtre : c'est précisément leur écart qui documente la politique d'abstention."""
    recs = _load(CORPUS_V1)
    cons = metrics.summarize("c", metrics.object_results(recs, "conservative"))
    rep = metrics.summarize("r", metrics.object_results(recs, "answered"))
    assert (cons.k, cons.n) == (8, 26)
    assert (rep.k, rep.n) == (12, 26)
    assert rep.k > cons.k


def test_answered_ne_peut_pas_etre_inferieur_a_conservative():
    """Propriété attendue : ignorer les abstentions ne peut pas *retirer* un
    verdict `exact`. Le test documente la propriété et échouerait si une
    consolidation future la violait — c'est ce qu'on veut savoir."""
    recs = _load(CORPUS_V1)
    cons = _verdicts(recs, "conservative")
    rep = _verdicts(recs, "answered")
    gagnes = {o for o in cons if cons[o] != "exact" and rep[o] == "exact"}
    perdus = {o for o in cons if cons[o] == "exact" and rep[o] != "exact"}
    assert gagnes, "les deux règles devraient différer au moins une fois"
    assert not perdus, f"objet(s) perdu(s) en ignorant les abstentions : {sorted(perdus)}"


def test_regle_inconnue_refusee():
    with pytest.raises(ValueError):
        metrics.consolidate_object([], "règle-imaginaire")


# --------------------------------------------------------------------------- #
# Déterminisme — le départage des ex æquo est figé
# --------------------------------------------------------------------------- #

def test_modal_departage_par_ordre_dinsertion():
    """Ex æquo ⇒ première valeur rencontrée. Observé sur la table publiée :
    `zxel__p_870ha` a deux photos, `ZyXEL` puis `""` ; l'ordre décide du verdict."""
    assert metrics.modal(["ZyXEL", ""]) == "ZyXEL"
    assert metrics.modal(["", "ZyXEL"]) == ""
    assert metrics.modal([]) == ""
    assert metrics.modal(["", ""]) == ""


def test_consolidation_est_champ_par_champ():
    """Motif du défaut corrigé : voter sur le couple (marque, modèle) perd les
    objets dont une photo a le bon modèle et une autre la bonne marque."""
    rows = [
        {"pred": {"brand": "", "model": "Echo Dot", "category": "smart_speaker"}},
        {"pred": {"brand": "Amazon", "model": "", "category": "smart_speaker"}},
    ]
    # `conservative` : chaque champ est à égalité et le départage par ordre
    # d'insertion garde la **première** valeur vue.
    assert metrics.consolidate_object(rows, "conservative") == {
        "brand": "", "model": "Echo Dot", "category": "smart_speaker"}
    # `answered` : les abstentions sortent du vote, les deux moitiés se rejoignent.
    assert metrics.consolidate_object(rows, "answered") == {
        "brand": "Amazon", "model": "Echo Dot", "category": "smart_speaker"}


def test_m1_ne_depend_pas_de_lordre_dappel():
    """Verdict identique quel que soit l'ordre des enregistrements en entrée.

    Ce test existe parce que le contraire est arrivé : le banc triait ses lignes
    par ``image_id`` et un autre consommateur ne les triait pas, si bien que
    **deux scripts du même dépôt publiaient 11/48 et 10/48** pour la même donnée.
    Sans ce verrou, un tri introduit dans un appelant peut changer un chiffre
    publié sans qu'aucun test ne tombe.
    """
    recs = _load(CORPUS_V1)
    reference = _verdicts(recs, "conservative")
    for cle in (lambda r: r["image_id"],
                lambda r: r["object_id"],
                lambda r: (r["object_id"], r["image_id"])):
        assert _verdicts(sorted(recs, key=cle), "conservative") == reference
    assert _verdicts(list(reversed(recs)), "conservative") == reference


def test_per_field_agreement_lit_sous_pred():
    """L'accord lit ``pred.<champ>``, pas la racine de l'enregistrement.

    Défaut corrigé le 2026-09-29 (`docs/06` §20) : la fonction lisait la racine,
    n'y trouvait jamais le champ, et renvoyait donc **1,000** — un parfait
    accord pour un jeu où rien n'est identique. Aucune figure publiée n'en
    dépendait, mais l'accord du §8.4 de `docs/06` (0,915 / 0,840) aurait été
    publié faux.
    """
    rows = [{"pred": {"brand": "Amazon"}}, {"pred": {"brand": "Apple"}}]
    assert metrics.per_field_agreement(rows, "brand") == pytest.approx(0.5)
    # une seule valeur distincte ⇒ accord parfait
    same = [{"pred": {"brand": "Amazon"}}, {"pred": {"brand": "amazon"}}]
    assert metrics.per_field_agreement(same, "brand") == 1.0
    # le champ est cherché sous `pred`, jamais à la racine
    flat = [{"brand": "Amazon"}, {"brand": "Apple"}]
    assert metrics.per_field_agreement(flat, "brand") == 1.0


def test_laccord_du_corpus_publie_vaut_0_915_et_0_840():
    """Verrouille les deux accords du §8.4 contre la bonne lecture du champ.

    C'est la figure qui serait devenue `1,000 / 1,000` sous l'ancienne version.
    """
    import statistics
    from collections import defaultdict

    rows: dict[str, list[dict]] = defaultdict(list)
    for r in _load(CORPUS_V1):
        rows[r["object_id"]].append(r)
    a_brand = statistics.mean(metrics.per_field_agreement(v, "brand") for v in rows.values())
    a_model = statistics.mean(metrics.per_field_agreement(v, "model") for v in rows.values())
    assert round(a_brand, 3) == 0.915
    assert round(a_model, 3) == 0.840


def test_les_lignes_non_200_sont_exclues():
    rows = [
        {"object_id": "o", "image_id": "a", "http_status": 500,
         "pred": {"brand": "X"}},
        {"object_id": "o", "image_id": "b", "http_status": 200,
         "pred": {"brand": "Amazon"}},
    ]
    assert [r.n_images for r in metrics.object_results(rows)] == [1]


# --------------------------------------------------------------------------- #
# full_report — la ventilation exigée par docs/06 §5 (M1–M3)
# --------------------------------------------------------------------------- #
# ``full_report`` était la **seule** implémentation de la ventilation du §5, et
# elle n'était appelée nulle part : 0 % de ses lignes par catégorie étaient
# exécutées. Un rapport exigé par le document directeur et jamais lancé ne peut
# pas être faux — il ne peut pas non plus être juste. Les tests ci-dessous
# l'exécutent, et verrouillent le défaut trouvé le 2026-10-06 : ``other`` était
# comptée dans M1 et **absente** de la ventilation (c'est la catégorie de vérité
# du bras non-IoT, donc exactement ce que D16 met au centre).


def _synth_rows() -> list[dict]:
    """Quatre objets : 3 exacts, 1 faux, répartis sur les 3 strates.

    ``d`` est le cas limite : sa catégorie de vérité est ``smart_plug`` mais le
    modèle répond ``other``, ce qui produit ``faux`` (et non
    ``brand_no_category_ok``, qui exigerait que la catégorie prédite soit juste).
    """
    def row(oid, stratum, text_visible, truth, pred):
        return {"object_id": oid, "image_id": f"{oid}1", "stratum": stratum,
                "text_visible": text_visible,
                "truth_brand": truth[0], "truth_model": truth[1], "truth_category": truth[2],
                "pred": {"brand": pred[0], "model": pred[1], "category": pred[2]}}
    return [
        row("a", "official", 0, ("TP-Link", "Archer C7", "router_ap"),
            ("TP-Link", "Archer C7", "router_ap")),
        row("b", "review", 0, ("Google", "Nest Hello", "ip_camera"),
            ("Google", "Nest Hello", "ip_camera")),
        row("c", "forum", 1, ("D-Link", "DIR 600", "other"),
            ("D-Link", "DIR 600", "other")),
        row("d", "official", 1, ("TP-Link", "Archer C7", "smart_plug"),
            ("Netgear", "R7000", "other")),
    ]


def test_full_report_ventile_tout_ce_qui_est_compte():
    rep = metrics.full_report(metrics.object_results(_synth_rows()))
    assert [s.label for s in rep] == [
        "M1 toutes strates",
        "M3 strate official",
        "M3 strate review",
        "M3 strate forum",
        "M2 no_text (chiffre principal)",
        "M2 with_text (confort OCR)",
        "catégorie router_ap",
        "catégorie ip_camera",
        "catégorie smart_plug",
        "catégorie other",
    ]
    by = {s.label: (s.k, s.n) for s in rep}
    assert by["M1 toutes strates"] == (3, 4)
    assert by["M3 strate official"] == (1, 2)
    assert by["M3 strate review"] == (1, 1)
    assert by["M3 strate forum"] == (1, 1)
    assert by["M2 no_text (chiffre principal)"] == (2, 2)
    assert by["M2 with_text (confort OCR)"] == (1, 2)
    assert by["catégorie router_ap"] == (1, 1)
    assert by["catégorie ip_camera"] == (1, 1)
    assert by["catégorie smart_plug"] == (0, 1)
    assert by["catégorie other"] == (1, 1)


def test_full_report_ne_perd_aucune_categorie_presente():
    """Verrou du défaut du 2026-10-06 : ``other`` comptée mais non ventilée."""
    res = metrics.object_results(_synth_rows())
    labels = {s.label for s in metrics.full_report(res)}
    assert {r.category for r in res} == {"router_ap", "ip_camera", "other", "smart_plug"}
    for category in {r.category for r in res}:
        assert f"catégorie {category}" in labels, f"{category} comptée dans M1 mais non ventilée"


def test_ordre_de_publication_des_categories():
    """L'ordre observé d'abord, les catégories non listées à la fin, triées."""
    cats = metrics._categories_to_report(metrics.object_results(_synth_rows()))
    assert cats[: len(metrics._REPORT_CATEGORIES)] == metrics._REPORT_CATEGORIES
    assert cats[len(metrics._REPORT_CATEGORIES):] == ("other",)


def test_full_report_omet_les_sous_ensembles_vides():
    """Aucune ligne pour ce qui n'existe pas dans les résultats.

    En ne gardant que les photos qui portent du texte, il ne reste que ``c``
    (forum) et ``d`` (official) : plus de strate ``review``, plus de M2
    ``no_text``. Une ligne à zéro objet serait un faux sous-ensemble.
    """
    rows = [r for r in _synth_rows() if r["text_visible"]]
    rep = metrics.full_report(metrics.object_results(rows))
    labels = [s.label for s in rep]
    assert {r["stratum"] for r in rows} == {"forum", "official"}
    assert "M2 with_text (confort OCR)" in labels
    assert not any("no_text" in lab for lab in labels)
    assert "M3 strate review" not in labels


def test_full_report_sur_liste_vide():
    rep = metrics.full_report([])
    assert [s.label for s in rep] == ["M1 toutes strates"]
    assert (rep[0].k, rep[0].n) == (0, 0)


# --------------------------------------------------------------------------- #
# minimum_n_for_target — « combien d'objets pour avoir le droit d'écrire 70 % ? »
# --------------------------------------------------------------------------- #
# ``docs/06`` §2343 écrit : « Dimensionnement (règle du §1.1, **outillée par**
# ``metrics.minimum_n_for_target``) ». La fonction existait, n'était appelée
# nulle part et n'était pas testée : le document renvoyait à un outil que rien
# ne vérifiait. Les chiffres ci-dessous sont donc épinglés — ce sont des
# **critères d'arrêt de collecte**, et un critère d'arrêt qui se trompe coûte
# des heures d'annotation.

@pytest.mark.parametrize(
    ("p_hat", "target", "expected"),
    [
        (0.80, 0.70, 77),
        (0.90, 0.70, 15),
        (0.75, 0.70, 306),
        (0.80, 0.60, 22),
    ],
)
def test_minimum_n_for_target_est_epingle(p_hat: float, target: float, expected: int) -> None:
    assert metrics.minimum_n_for_target(p_hat, target) == expected


@pytest.mark.parametrize(
    ("p_hat", "target"),
    [(0.80, 0.70), (0.90, 0.70), (0.75, 0.70), (0.80, 0.60)],
)
def test_minimum_n_for_target_est_le_plus_petit_possible(p_hat: float, target: float) -> None:
    """Le n rendu suffit, et n−1 ne suffit pas. Sinon ce n'est pas un minimum."""
    n = metrics.minimum_n_for_target(p_hat, target)
    assert metrics.wilson(round(p_hat * n), n)[0] >= target
    assert metrics.wilson(round(p_hat * (n - 1)), n - 1)[0] < target


def test_minimum_n_for_target_croit_quand_p_hat_baisse() -> None:
    """Moins le modèle est juste, plus il faut d'objets pour l'affirmer."""
    n_90 = metrics.minimum_n_for_target(0.90, 0.70)
    n_80 = metrics.minimum_n_for_target(0.80, 0.70)
    n_75 = metrics.minimum_n_for_target(0.75, 0.70)
    assert n_90 < n_80 < n_75


def test_minimum_n_for_target_rend_moins_un_quand_c_est_hors_d_atteinte() -> None:
    """Cible inatteignable : sentinelle ``-1``, jamais un grand nombre trompeur."""
    assert metrics.minimum_n_for_target(0.10, 0.99) == -1


# --------------------------------------------------------------------------- #
# Summary.line — la règle 2 de docs/06 §4.3, exécutée par personne
# --------------------------------------------------------------------------- #
# Règle 2 : ne déclarer « >= 70 % » **que si la borne INFÉRIEURE de Wilson
# l'est**. ``lower_bound_ge_target`` et ``line()`` portent cette règle — et
# n'étaient exécutés par aucun test (mesuré le 2026-10-06). Une règle appliquée
# par du code que personne ne lance n'est pas une règle, c'est une intention.


def _res(verdict: str, **kw) -> metrics.ObjectResult:
    base = dict(object_id="o", brand="", model="", category="router_ap",
                stratum="official", n_images=1, verdict=verdict,
                agreement_brand=1.0, agreement_model=1.0, text_visible=False)
    base.update(kw)
    return metrics.ObjectResult(**base)


def test_summary_autorise_70_si_la_borne_inferieure_le_ten() -> None:
    s = metrics.summarize("t", [_res("exact")] * 100)
    assert (s.k, s.n) == (100, 100)
    assert s.lower_bound_ge_target is True
    assert "NON affirma" not in s.line()
    assert "100/100" in s.line()


def test_summary_interdit_70_quand_la_borne_inferieure_ne_le_ten_pas() -> None:
    """1/2 = 0,500 : la valeur centrale est sous 0,70, donc la borne aussi."""
    s = metrics.summarize("t", [_res("exact"), _res("faux")])
    assert (s.k, s.n) == (1, 2)
    assert s.lower_bound_ge_target is False
    assert "NON affirma" in s.line()


def test_summary_sur_liste_vide_ne_plante_pas() -> None:
    s = metrics.summarize("vide", [])
    assert (s.k, s.n, s.p) == (0, 0, 0.0)
    assert s.lower_bound_ge_target is False
    assert "0/  0" in s.line()  # k=0, n=0 : la ligne reste imprimable


# --------------------------------------------------------------------------- #
# Les branches marginales que la couverture signalait (2026-10-06)
# --------------------------------------------------------------------------- #

def test_agreement_sur_liste_vide() -> None:
    a, dist = metrics.agreement([])
    assert a == 0.0
    assert not dist


def test_grade_marque_juste_et_verite_sans_modele() -> None:
    """Vérité sans modèle : la marque suffit à dire ``exact`` (barème, pas bug)."""
    assert metrics.grade({"brand": "TP-Link"}, {"brand": "TP-Link", "model": ""}) == "exact"


def test_group_by_object_ignore_un_pred_non_dict() -> None:
    rows = [
        {"object_id": "o", "image_id": "a", "pred": "pas un dict"},
        {"object_id": "o", "image_id": "b", "pred": {"brand": "X"}},
    ]
    groups = metrics.group_by_object(rows)
    assert [r["image_id"] for r in groups["o"]] == ["b"]
