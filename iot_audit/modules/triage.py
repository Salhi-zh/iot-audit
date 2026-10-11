"""Module de triage visuel et reconnaissance de catégorie sans lecture de marque (docs/06 §22).

Principes fondamentaux :
1. **Séparation Stricte des Rôles** :
   Le triage visuel a pour rôle de répondre à :
   (a) l'objet est-il un objet connecté (IoT) ?
   (b) quelle est sa catégorie générale ?
   Sans tenter de lire ou deviner une marque ou un modèle spécifique.
2. **Filtrage par type de vue (`view`)** :
   Les photos de détail (`detail` : cartes mères démontées, connecteurs bruts,
   étiquettes gros plan) induisent un biais massif vers `smart_speaker` (64/97) ou `other`.
   Le consolidateur priorise les vues d'ensemble (`whole`) lorsqu'elles sont présentes.
3. **Seuil de Rappel IoT vs Précision** :
   En sécurité, rater un objet connecté (faux négatif IoT) est l'erreur la plus coûteuse
   (alerte manquée). Un objet est considéré IoT si au moins une vue globale le classe
   en catégorie IoT ou si le vote majoritaire sur `iot` est positif.
4. **Calcul de Métriques et Intervalles de Wilson** :
   Conformément à docs/06 §22.3, calcul du rappel IoT, de la spécificité, et de la précision
   catégorie avec leurs intervalles de confiance de Wilson respectifs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from iot_audit.contracts import (
    Category,
    ErrorCode,
    FramingState,
    ObjectTriage,
    ViewType,
    VLMTriageOutput,
)
from iot_audit.modules.confidence import wilson

__all__ = [
    "TriageBenchmarkMetrics",
    "benchmark_triage",
    "consolidate_triage",
    "framing_state",
    "screen_frame",
]


@dataclass(frozen=True, slots=True)
class TriageBenchmarkMetrics:
    """Métriques consolidées d'un banc de test de triage (docs/06 §22.3)."""

    n_objects: int
    n_iot_true: int
    n_non_iot_true: int
    iot_recall: float
    iot_recall_ci: tuple[float, float]
    iot_specificity: float
    iot_specificity_ci: tuple[float, float]
    category_accuracy_on_iot: float
    category_accuracy_on_iot_ci: tuple[float, float]


def framing_state(output: VLMTriageOutput) -> FramingState:
    """P1 « une photo = un objet » — trois états, dont un qui n'est pas un accord.

    * ``"unverified"`` — le producteur n'a pas posé la question
      (``n_salient_objects is None``). Ce n'est pas une conformité : c'est
      l'absence de vérification, et c'est l'état de **toutes** les mesures v6
      publiées, dont le schéma figé est ``{view, category, iot}``.
    * ``"rejected"`` — le cadre ne désigne pas un objet unique (``<= 0`` ou
      ``>= 2``) ; l'appelant le refuse.
    * ``"ok"`` — la question a été posée et la réponse est ``1``.

    L'ordre des tests porte tout le sens : ``None`` est testé **avant** la
    comparaison, sinon ``None <= 0`` lèverait un ``TypeError`` au lieu de
    rendre ``unverified`` — et un défaut transformé en exception se serait vu.
    """
    n = output.n_salient_objects
    if n is None:
        return "unverified"
    if n <= 0 or n >= 2:
        return "rejected"
    return "ok"


def screen_frame(output: VLMTriageOutput) -> ErrorCode | None:
    """P1 « une photo = un objet » — refuse un cadrage inexploitable.

    Renvoie ``E_MULTI_OBJECT_OR_UNCLEAR`` si la photo ne peut pas désigner un
    objet unique, ``None`` sinon. Deux cas de rejet, un seul code : la taxonomie
    D14 en déclare un seul pour les deux, et les séparer inventerait une
    distinction que le rapport n'utilise pas.

    * ``n_salient_objects >= 2`` — deux objets, deux vérités terrain, un seul
      tuple de sortie. Le modèle ne peut en décrire qu'un : le rapport
      attribuerait à l'objet A la marque de l'objet B, et cette erreur-là est
      indétectable en aval (elle a l'apparence d'une identification réussie).
    * ``n_salient_objects == 0`` — il n'y a rien à identifier (gros plan d'un
      mur, photo de nuit, image de test).

    **``None`` ne veut pas dire « conforme »** (corrigé le 2026-10-06). Cette
    fonction ne rend que deux choses : un refus, ou « rien à refuser ». Sur un
    champ non renseigné, « rien à refuser » n'est pas un feu vert — c'est
    l'absence de vérification. L'appelant qui veut la distinction appelle
    ``framing_state`` : ``None`` couvre ``ok`` **et** ``unverified``, et les
    confondre est exactement le défaut que cette paire de fonctions sépare.

    Le rejet est **par photo**, pas par objet : les autres photos du même objet
    restent exploitables, et c'est l'orchestrateur qui décide si l'objet
    survit (il ne doit pas). Rejeter l'objet entier sur une seule photo mal
    cadrée perdrait des mesures valides ; accepter la photo perdrait la
    traçabilité du tuple.
    """
    if framing_state(output) == "rejected":
        return ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR
    return None


def consolidate_triage(
    object_id: str,
    predictions: Sequence[VLMTriageOutput],
) -> ObjectTriage:
    """Consolide les prédictions multi-vues d'un objet en une décision de triage.

    Règles de consolidation — mesurées, pas supposées (2026-10-06, run v6 live) :

    1. **Catégorie** : si au moins une vue globale (`WHOLE`) existe, seules les
       vues globales votent — les démontages / gros plans font basculer la
       catégorie vers `other` ou `smart_speaker` (mesuré : vues globales 16/17
       = 0,941 vs détails 52/80 = 0,650 sur le run v6).

    2. **Décision `is_iot` — asymétrie de coût assumée** (docs/06 §22.3 : « un
       faux « non-IoT » éteint l'alerte, c'est l'erreur qui coûte ») :

       * toute catégorie IoT explicite (hors OTHER) ⇒ `True` ;
       * tout vote `iot=True` sur une photo quelconque ⇒ `True` (un seul signal
         positif suffit à alerter) ;
       * l'**absence** de connectivité ne s'établit que sur une vue **globale** :
         au moins une vue `WHOLE` et toutes les votes à `False` ⇒ `False` ;
       * fragment seul (détail uniquement, aucun vote positif) ⇒ `True` par
         défaut : un gros plan de carte mère ne peut pas prouver l'absence de
         connectivité — c'est précisément le mode de faux négatif mesuré sur les
         démontages Zyxel (9 faux « non-IoT » en 24 h).

       Coût assumé : un objet **non** connecté photographié uniquement en détail
       déclenche une fausse alerte (spécificité sacrifiée sur ce cas). La
       vérification humaine qui suit coûte un regard ; une alerte éteinte coûte
       l'objet du rapport.
    """
    if not predictions:
        # Zéro observation ⇒ zéro accord, jamais 1,0 : un accord parfait ne
        # s'affirme pas sans données (l'absence de connectivité n'est pas
        # davantage démontrée ici — l'appelant doit la traiter comme un échec).
        return ObjectTriage(
            object_id=object_id,
            is_iot=False,
            category=Category.OTHER,
            iot_agreement=0.0,
            category_agreement=0.0,
            whole_view_ratio=0.0,
            n_images=0,
            framing="unverified",
            category_distribution={},
            view_distribution={},
        )

    n = len(predictions)
    whole_views = [p for p in predictions if p.view == ViewType.WHOLE]
    whole_ratio = len(whole_views) / n

    view_counts = Counter(p.view.value for p in predictions)
    view_dist = dict(view_counts)

    # Sélection du jeu de prédictions pour la catégorie
    active_preds = whole_views if whole_views else predictions
    cat_counts = Counter(p.category for p in active_preds)
    modal_cat, best_cat_count = cat_counts.most_common(1)[0]
    cat_agreement = best_cat_count / len(active_preds)
    cat_dist = {c.value: count for c, count in Counter(p.category for p in predictions).items()}

    # Accord et décision IoT
    iot_votes = [p.iot for p in predictions]
    iot_true_count = sum(1 for v in iot_votes if v)
    iot_agreement = max(iot_true_count, n - iot_true_count) / n

    # Rappel d'abord (docs/06 §22.3) : la fausse alerte coûte un regard, le
    # faux négatif éteint l'objet du rapport.
    #   1. catégorie IoT explicite, ou un seul vote positif ⇒ alerte ;
    #   2. l'absence ne s'établit que sur une vue globale unanime à False ;
    #   3. fragment seul sans signal positif ⇒ alerte par défaut.
    explicit_cat = modal_cat in (
        Category.PLUG,
        Category.CAMERA,
        Category.BULB,
        Category.ROUTER,
        Category.SPEAKER,
    )
    if explicit_cat or iot_true_count > 0:
        final_is_iot = True
    elif whole_views and all(not p.iot for p in whole_views):
        final_is_iot = False
    else:
        final_is_iot = True

    # Cadrage consolidé : le **pire** état l'emporte, dans l'ordre
    # rejected > unverified > ok. Un seul cadre non vérifié suffit à ce que
    # l'invariant P1 ne soit pas établi sur l'objet, et un cadre rejeté qui
    # aurait échappé à l'appelant doit rester visible plutôt que d'être résumé
    # en « ok » par les autres photos.
    states = [framing_state(p) for p in predictions]
    if "rejected" in states:
        framing: FramingState = "rejected"
    elif "unverified" in states:
        framing = "unverified"
    else:
        framing = "ok"

    return ObjectTriage(
        object_id=object_id,
        is_iot=final_is_iot,
        category=modal_cat,
        iot_agreement=iot_agreement,
        category_agreement=cat_agreement,
        whole_view_ratio=whole_ratio,
        n_images=n,
        framing=framing,
        category_distribution=cat_dist,
        view_distribution=view_dist,
    )


def benchmark_triage(
    ground_truth_and_predictions: Sequence[tuple[str, bool, Category, Sequence[VLMTriageOutput]]],
) -> TriageBenchmarkMetrics:
    """Évalue les métriques de triage sur un ensemble d'objets annotés (docs/06 §22.3).

    Chaque élément du tuple :
    (object_id, truth_is_iot, truth_category, list_of_vlm_predictions)
    """
    total = len(ground_truth_and_predictions)
    if total == 0:
        return TriageBenchmarkMetrics(
            n_objects=0,
            n_iot_true=0,
            n_non_iot_true=0,
            iot_recall=0.0,
            iot_recall_ci=(0.0, 1.0),
            iot_specificity=0.0,
            iot_specificity_ci=(0.0, 1.0),
            category_accuracy_on_iot=0.0,
            category_accuracy_on_iot_ci=(0.0, 1.0),
        )

    iot_true = 0
    iot_detected = 0
    non_iot_true = 0
    non_iot_rejected = 0
    cat_correct = 0

    for oid, truth_iot, truth_cat, preds in ground_truth_and_predictions:
        consolidated = consolidate_triage(oid, preds)
        if truth_iot:
            iot_true += 1
            if consolidated.is_iot:
                iot_detected += 1
            if consolidated.category == truth_cat:
                cat_correct += 1
        else:
            non_iot_true += 1
            if not consolidated.is_iot:
                non_iot_rejected += 1

    recall = iot_detected / iot_true if iot_true > 0 else 0.0
    recall_ci = wilson(iot_detected, iot_true) if iot_true > 0 else (0.0, 1.0)

    spec = non_iot_rejected / non_iot_true if non_iot_true > 0 else 0.0
    spec_ci = wilson(non_iot_rejected, non_iot_true) if non_iot_true > 0 else (0.0, 1.0)

    cat_acc = cat_correct / iot_true if iot_true > 0 else 0.0
    cat_ci = wilson(cat_correct, iot_true) if iot_true > 0 else (0.0, 1.0)

    return TriageBenchmarkMetrics(
        n_objects=total,
        n_iot_true=iot_true,
        n_non_iot_true=non_iot_true,
        iot_recall=recall,
        iot_recall_ci=recall_ci,
        iot_specificity=spec,
        iot_specificity_ci=spec_ci,
        category_accuracy_on_iot=cat_acc,
        category_accuracy_on_iot_ci=cat_ci,
    )
