"""Tests pour le module de triage visuel et l'évaluation du rappel/spécificité (docs/06 §22).

Vérifie :
1. Consolidation multi-vues : priorité aux vues globales (`WHOLE`) vs détails (`DETAIL`)
2. Résolution du piège des cartes mères démontées (forum/teardown)
3. Décision IoT positive et négative (objets connectés vs objets du quotidien)
4. Calcul des métriques de banc d'évaluation (rappel IoT, spécificité, IC de Wilson)
5. Cas limites (liste vide, objets ambigus, désaccord unanime)
"""

import pytest

from iot_audit.contracts import Category, ErrorCode, ViewType, VLMTriageOutput
from iot_audit.modules.triage import (
    benchmark_triage,
    consolidate_triage,
    framing_state,
    screen_frame,
)


def test_consolidate_triage_empty() -> None:
    """Zéro observation : pas d'accord affirmé (0,0), pas d'unanimité fictive."""
    res = consolidate_triage("empty_obj", [])
    assert res.object_id == "empty_obj"
    assert res.is_iot is False
    assert res.category == Category.OTHER
    assert res.n_images == 0
    assert res.iot_agreement == 0.0
    assert res.category_agreement == 0.0
    assert res.whole_view_ratio == 0.0


def test_consolidate_triage_prioritizes_whole_views() -> None:
    # 1 vue entière de routeur + 2 gros plans pris pour une enceinte/carte mère
    # La vue entière doit l'emporter sur les gros plans trompeurs
    preds = [
        VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.SPEAKER, iot=True),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.SPEAKER, iot=True),
    ]

    res = consolidate_triage("router_with_teardown", preds)
    assert res.category == Category.ROUTER
    assert res.is_iot is True
    assert res.whole_view_ratio == pytest.approx(1 / 3)
    assert res.category_agreement == 1.0  # Unanime parmi les vues WHOLE
    assert res.category_distribution["router_ap"] == 1
    assert res.category_distribution["smart_speaker"] == 2


def test_consolidate_triage_detail_only_fallback() -> None:
    # Si uniquement des vues DETAIL, on utilise le vote majoritaire
    preds = [
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.PLUG, iot=True),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.PLUG, iot=True),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=False),
    ]

    res = consolidate_triage("plug_closeup_only", preds)
    assert res.category == Category.PLUG
    assert res.is_iot is True
    assert res.whole_view_ratio == 0.0
    assert pytest.approx(res.category_agreement) == 2 / 3


def test_consolidate_triage_non_iot_object() -> None:
    # Photos d'un objet usuel (mug ou livre) — vue globale : l'absence est établie
    preds = [
        VLMTriageOutput(view=ViewType.WHOLE, category=Category.OTHER, iot=False),
        VLMTriageOutput(view=ViewType.WHOLE, category=Category.OTHER, iot=False),
    ]

    res = consolidate_triage("coffee_mug", preds)
    assert res.is_iot is False
    assert res.category == Category.OTHER
    assert res.iot_agreement == 1.0


def test_fragment_only_defaults_to_alert() -> None:
    """Un détail seul ne peut pas prouver l'absence de connectivité.

    Règle mesurée le 2026-10-06 sur le run v6 live : 9 démontages Zyxel
    (gros plans de carte mère, vote `iot=False`) étaient des faux « non-IoT ».
    La règle rappel-d'abord les convertit en alerte (vérification humaine),
    parce qu'une fausse alerte coûte un regard et qu'un faux négatif éteint
    l'objet du rapport (docs/06 §22.3).
    """
    preds = [
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=False),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=False),
    ]

    res = consolidate_triage("zyxel_teardown", preds)
    assert res.is_iot is True


def test_single_positive_vote_triggers_alert() -> None:
    """Un seul signal positif suffit : le rappel prime sur la majorité."""
    preds = [
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=True),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=False),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=False),
    ]

    res = consolidate_triage("divided_object", preds)
    assert res.is_iot is True
    assert pytest.approx(res.iot_agreement) == 2 / 3


def test_whole_view_false_but_detail_true_still_alerts() -> None:
    # Tout vote positif l'emporte sur les votes négatifs, vue globale comprise
    preds = [
        VLMTriageOutput(view=ViewType.WHOLE, category=Category.OTHER, iot=False),
        VLMTriageOutput(view=ViewType.DETAIL, category=Category.CAMERA, iot=True),
    ]

    res = consolidate_triage("mixed_signals", preds)
    assert res.is_iot is True


def test_benchmark_triage_evaluation() -> None:
    # Simule le protocole du corpus mixte 60 objets (30 IoT + 30 non-IoT) de docs/06 §22.3
    dataset: list[tuple[str, bool, Category, list[VLMTriageOutput]]] = []

    # 30 objets connectés (28 bien détectés et catégorisés, 2 manqués)
    for i in range(28):
        preds = [
            VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True),
            VLMTriageOutput(view=ViewType.DETAIL, category=Category.ROUTER, iot=True),
        ]
        dataset.append((f"iot_{i}", True, Category.ROUTER, preds))

    for i in range(28, 30):
        # 2 ratés
        preds = [
            VLMTriageOutput(view=ViewType.WHOLE, category=Category.OTHER, iot=False),
        ]
        dataset.append((f"iot_missed_{i}", True, Category.ROUTER, preds))

    # 30 objets non connectés (29 bien rejetés, 1 fausse alerte)
    for i in range(29):
        preds = [
            VLMTriageOutput(view=ViewType.WHOLE, category=Category.OTHER, iot=False),
        ]
        dataset.append((f"non_iot_{i}", False, Category.OTHER, preds))

    # 1 fausse alerte
    dataset.append(
        (
            "non_iot_alarm",
            False,
            Category.OTHER,
            [VLMTriageOutput(view=ViewType.WHOLE, category=Category.SPEAKER, iot=True)],
        )
    )

    metrics = benchmark_triage(dataset)

    assert metrics.n_objects == 60
    assert metrics.n_iot_true == 30
    assert metrics.n_non_iot_true == 30

    # Rappel IoT : 28/30 = 93.3%
    assert pytest.approx(metrics.iot_recall, rel=1e-2) == 28 / 30
    assert 0.78 <= metrics.iot_recall_ci[0] <= 0.82
    assert 0.97 <= metrics.iot_recall_ci[1] <= 1.00

    # Spécificité non-IoT : 29/30 = 96.7%
    assert pytest.approx(metrics.iot_specificity, rel=1e-2) == 29 / 30

    # Exactitude catégorie sur IoT : 28/30 = 93.3%
    assert pytest.approx(metrics.category_accuracy_on_iot, rel=1e-2) == 28 / 30


def test_benchmark_triage_empty() -> None:
    metrics = benchmark_triage([])
    assert metrics.n_objects == 0
    assert metrics.iot_recall == 0.0
    assert metrics.iot_specificity == 0.0


# --------------------------------------------------------------------------- #
# P1 « une photo = un objet » — E_MULTI_OBJECT_OR_UNCLEAR (2026-10-06)
# --------------------------------------------------------------------------- #

def test_n_salient_objects_defaults_to_unverified() -> None:
    """Le défaut dit « non posé », pas « un objet » (corrigé le 2026-10-06).

    Le manifeste v6 fige ``{view, category, iot}`` pour que les 144 photos
    restent comparables à v4 à l'octet près : **aucune** mesure publiée n'a
    répondu à la question du nombre d'objets. Le défaut valait ``1``, donc
    ``screen_frame`` rendait ``None`` (feu vert) et rien en aval ne distinguait
    « un objet, vérifié » de « jamais demandé ».

    Ce test verrouillait la mauvaise propriété (la compatibilité du défaut) au
    lieu de la bonne (la sincérité de ce qu'il affirme). Il porte désormais la
    seconde, et les mesures v6 restent valides : elles sont étiquetées pour ce
    qu'elles sont.
    """
    out = VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True)
    assert out.n_salient_objects is None
    assert framing_state(out) == "unverified"
    # « Rien à refuser » n'est pas un refus : screen_frame ne rejette pas le
    # non-vérifié, c'est framing_state qui porte la distinction.
    assert screen_frame(out) is None


def test_an_explicit_one_is_a_verified_framing() -> None:
    """Compatibilité : un producteur qui pose la question passe ``1``, et il est cru.

    C'est ce que le défaut ``1`` ne savait pas dire — un appelant qui n'avait
    rien demandé obtenait le même état qu'un appelant qui avait reçu « un
    objet » comme réponse.
    """
    out = VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True,
                          n_salient_objects=1)
    assert framing_state(out) == "ok"
    assert screen_frame(out) is None


def test_consolidation_reports_the_worst_framing_state() -> None:
    """Un seul cadre non posé suffit à rendre P1 non établi sur l'objet."""
    verified = VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True,
                               n_salient_objects=1)
    unasked = VLMTriageOutput(view=ViewType.DETAIL, category=Category.ROUTER, iot=True)
    two = VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True,
                          n_salient_objects=2)

    assert consolidate_triage("o", [verified]).framing == "ok"
    assert consolidate_triage("o", [verified, unasked]).framing == "unverified"
    assert consolidate_triage("o", [verified, two]).framing == "rejected"
    assert consolidate_triage("o", []).framing == "unverified"


def test_screen_frame_rejects_two_objects() -> None:
    """Deux objets : deux vérités terrain pour un seul tuple de sortie."""
    out = VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True,
                          n_salient_objects=2)
    assert screen_frame(out) is ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR


def test_screen_frame_rejects_an_empty_frame() -> None:
    """Aucun objet : il n'y a rien à identifier."""
    out = VLMTriageOutput(view=ViewType.DETAIL, category=Category.OTHER, iot=False,
                          n_salient_objects=0)
    assert screen_frame(out) is ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR


def test_screen_frame_rejects_a_nonsensical_count() -> None:
    """Un compte négatif est un défaut de sortie : il ne passe pas en silence."""
    out = VLMTriageOutput(view=ViewType.WHOLE, category=Category.PLUG, iot=True,
                          n_salient_objects=-1)
    assert screen_frame(out) is ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR


def test_screen_frame_accepts_three_objects_as_a_rejection_not_a_count() -> None:
    """Le code dit « plusieurs objets détectés », pas « trois » : le compte
    n'est qu'un déclencheur, et il ne doit pas fuiter dans le message."""
    out = VLMTriageOutput(view=ViewType.WHOLE, category=Category.CAMERA, iot=True,
                          n_salient_objects=5)
    assert screen_frame(out) is ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR


def test_screen_frame_does_not_consolidate_or_guess() -> None:
    """Le cadrage se juge photo par photo : aucune agrégation ici.

    Rejeter l'objet entier sur une seule photo mal cadrée perdrait des mesures
    valides ; c'est l'orchestrateur qui décide si l'objet survit.
    """
    good = VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True)
    bad = VLMTriageOutput(view=ViewType.WHOLE, category=Category.SPEAKER, iot=True,
                          n_salient_objects=2)
    assert screen_frame(good) is None
    assert screen_frame(bad) is ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR
    # ...mais « non rejeté » n'est pas « vérifié » : un cadre non posé au modèle
    # n'est pas conforme (défaut réel corrigé le 2026-10-06).
    assert framing_state(good) == "unverified"
    assert framing_state(bad) == "rejected"
