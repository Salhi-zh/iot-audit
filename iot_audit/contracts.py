"""Contrats d'interface — implémentation de ``docs/03-architecture.md`` §2.

Règle de conception (docs/03 §2) : **pas de dict, pas de ``**kwargs``**. Des
dataclasses gelées, sérialisables, comparables. Deux raisons, toutes deux
opérationnelles :

* ``frozen=True`` interdit la mutation entre couches — une couche ne peut pas
  « corriger » en place la sortie de la précédente ;
* ``slots=True`` + ``eq`` automatique rendent les tests de reproductibilité
  triviaux (``run1.identification == run2.identification``), ce qui est
  exactement ce qu'exige ENF5.

Ce module ne doit importer aucun modèle ORM, aucun module métier, ni
``datetime.now()`` (docs/03 §3, couplage C4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

# --------------------------------------------------------------------------- #
# Vocabulaires fermés
# --------------------------------------------------------------------------- #


class Category(StrEnum):
    """Taxonomie produit. Volontairement **petite et fermée** : c'est ce qui
    permet de la contraindre par un ``enum`` dans le schéma de Guided Decoding
    (docs/05 §1). Un enum de *marques* serait irréaliste."""

    PLUG = "smart_plug"
    CAMERA = "ip_camera"
    BULB = "smart_bulb"
    ROUTER = "router_ap"
    SPEAKER = "smart_speaker"
    OTHER = "other"


class ViewType(StrEnum):
    """Type de prise de vue pour le triage visuel (docs/06 §22, runner v6).

    ``WHOLE``   l'objet entier est visible dans son contexte
    ``DETAIL``  détail, connecteur, carte électronique, étiquette ou gros-plan
    """

    WHOLE = "whole"
    DETAIL = "detail"


class Status(StrEnum):
    """Sortie de la matrice de décision (docs/05 §4.2). Trois valeurs, jamais
    deux : ``identified_with_reserve`` est ce qui empêche d'afficher
    « identifié » sur un consensus halluciné."""

    IDENTIFIED = "identified"
    WITH_RESERVE = "identified_with_reserve"
    UNIDENTIFIED = "unidentified"


class Stratum(StrEnum):
    """Risque de **contamination d'entraînement** décroissant (docs/06 §2).

    ``OFFICIAL``  visuel marketing  -> risque de mémorisation ÉLEVÉ
    ``REVIEW``    photo d'avis client -> risque moyen
    ``FORUM``     forum/réparation/teardown, angle inhabituel -> risque FAIBLE

    La prédiction falsifiable du projet est ``accuracy(OFFICIAL) >
    accuracy(REVIEW) > accuracy(FORUM)`` ; l'écart ``OFFICIAL - FORUM`` est le
    résultat méthodologique principal (docs/06 §2, M3).
    """

    OFFICIAL = "official"
    REVIEW = "review"
    FORUM = "forum"


class Subset(StrEnum):
    """Sous-ensembles de contrôle (docs/06 §2.1).

    ``NO_TEXT``     aucun texte produit lisible -> la **vraie** reconnaissance
    ``WITH_TEXT``   texte produit lisible      -> confort OCR
    ``CONFUSABLE``  paires white-label (même OEM, marques différentes)
    ``PERTURBED``   transformations d'images existantes -> robustesse
    """

    NO_TEXT = "no_text"
    WITH_TEXT = "with_text"
    CONFUSABLE = "confusable"
    PERTURBED = "perturbed"


class LabelSource(StrEnum):
    """Provenance de la vérité terrain — contrôle anti-fuite (docs/06 §3).

    Si la vérité terrain vient du **titre de l'annonce** et que ce titre est
    **imprimé sur l'objet**, l'étiquette est *dans* l'image : le système peut
    « réussir » en recopiant la réponse. Le drapeau permet de rapporter
    séparément les cas non contaminés.

    ``CATEGORY``  dérivée d'une catégorie Commons/Wikidata (curateur, externe
                  à l'image) — la source la plus solide
    ``FILENAME``  dérivée du nom de fichier — peut refléter un texte imprimé
    ``LISTING``   dérivée d'un titre/descriptif de vente — le plus contaminant
    ``MANUAL``    saisie et vérifiée à la main
    """

    CATEGORY = "category"
    FILENAME = "filename"
    LISTING = "listing"
    MANUAL = "manual"


class ErrorCode(StrEnum):
    """Taxonomie d'erreurs (docs/03 §5, D14, AC12). Exactement 20 codes.

    Chaque code possede :
    * un declencheur precis ;
    * un comportement systeme ;
    * un message utilisateur (FR, ton professionnel, non rassurant) ;
    * une trace dans le journal.
    """

    E_MODEL_UNAVAILABLE = "E_MODEL_UNAVAILABLE"
    E_VLM_TIMEOUT = "E_VLM_TIMEOUT"
    E_VLM_INVALID_JSON = "E_VLM_INVALID_JSON"
    E_IMAGE_UNREADABLE = "E_IMAGE_UNREADABLE"
    E_MULTI_OBJECT_OR_UNCLEAR = "E_MULTI_OBJECT_OR_UNCLEAR"
    E_ADVERSARIAL_LABEL_SUSPECTED = "E_ADVERSARIAL_LABEL_SUSPECTED"
    E_NO_IDENTIFICATION = "E_NO_IDENTIFICATION"
    E_LOW_CONFIDENCE = "E_LOW_CONFIDENCE"
    E_UNCALIBRATED_CONSENSUS = "E_UNCALIBRATED_CONSENSUS"
    E_NO_CPE_MATCH = "E_NO_CPE_MATCH"
    E_CPE_AMBIGUOUS = "E_CPE_AMBIGUOUS"
    E_NO_CVE = "E_NO_CVE"
    E_NVD_UNAVAILABLE = "E_NVD_UNAVAILABLE"
    E_NVD_CACHE_MISS = "E_NVD_CACHE_MISS"
    E_PROVENANCE_INCOMPLETE = "E_PROVENANCE_INCOMPLETE"
    E_HMAC_CHAIN_BROKEN = "E_HMAC_CHAIN_BROKEN"
    E_JOURNAL_WRITE_FAILED = "E_JOURNAL_WRITE_FAILED"
    E_DISK_FULL = "E_DISK_FULL"
    E_CLOCK_SKEW = "E_CLOCK_SKEW"
    E_PARTIAL_RUN = "E_PARTIAL_RUN"


@dataclass(frozen=True, slots=True)
class ErrorDefinition:
    """Specification operationnalisee d'un code d'erreur (docs/03 §5)."""

    code: ErrorCode
    trigger: str
    system_behavior: str
    user_message_template: str
    journal_trace_fields: tuple[str, ...]

    def format_message(self, **kwargs: Any) -> str:
        """Produit le message utilisateur selon le gabarit documentaire."""
        msg = self.user_message_template
        for k, v in kwargs.items():
            msg = msg.replace(f"[{k}]", str(v))
        return msg


ERROR_TAXONOMY: Mapping[ErrorCode, ErrorDefinition] = {
    ErrorCode.E_MODEL_UNAVAILABLE: ErrorDefinition(
        code=ErrorCode.E_MODEL_UNAVAILABLE,
        trigger="aucun nœud vLLM ne répond",
        system_behavior="bascule nœud, puis abandon du run",
        user_message_template="Service d'identification indisponible. Les photos ont été conservées ; relancez l'analyse.",
        journal_trace_fields=("stage", "nodes_tried"),
    ),
    ErrorCode.E_VLM_TIMEOUT: ErrorDefinition(
        code=ErrorCode.E_VLM_TIMEOUT,
        trigger="dépassement du délai par image",
        system_behavior="retry ×2 avec backoff, puis image marquée",
        user_message_template="Analyse trop longue sur cette photo. Résultat partiel.",
        journal_trace_fields=("image_id", "duration"),
    ),
    ErrorCode.E_VLM_INVALID_JSON: ErrorDefinition(
        code=ErrorCode.E_VLM_INVALID_JSON,
        trigger="Guided Decoding échoue (sortie non conforme)",
        system_behavior="1 retry avec prompt réparateur ; sinon échec de l'image",
        user_message_template="Réponse du modèle inexploitable. Photo non analysée.",
        journal_trace_fields=("raw_response_truncated",),
    ),
    ErrorCode.E_IMAGE_UNREADABLE: ErrorDefinition(
        code=ErrorCode.E_IMAGE_UNREADABLE,
        trigger="décodage impossible / format",
        system_behavior="rejet immédiat, pas de retry",
        user_message_template="Fichier illisible ou non supporté.",
        journal_trace_fields=("sha256", "cause"),
    ),
    ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR: ErrorDefinition(
        code=ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR,
        trigger="≥ 2 objets saillants, ou cadrage inexploitable",
        system_behavior="rejet, pas de tentative d'identification",
        user_message_template="Plusieurs objets détectés. Reprenez une photo par objet.",
        journal_trace_fields=("detection_output",),
    ),
    ErrorCode.E_ADVERSARIAL_LABEL_SUSPECTED: ErrorDefinition(
        code=ErrorCode.E_ADVERSARIAL_LABEL_SUSPECTED,
        trigger="visible_text contient une formulation d'instruction",
        system_behavior="le texte n'est jamais exécuté ; run marqué suspect",
        user_message_template="Texte suspect détecté sur l'objet. Vérification humaine requise.",
        journal_trace_fields=("raw_text", "pattern"),
    ),
    ErrorCode.E_NO_IDENTIFICATION: ErrorDefinition(
        code=ErrorCode.E_NO_IDENTIFICATION,
        trigger="aucun tuple ne se dégage",
        system_behavior="sortie « non identifié »",
        user_message_template="Objet non identifié — vérification manuelle requise.",
        journal_trace_fields=("distribution",),
    ),
    ErrorCode.E_LOW_CONFIDENCE: ErrorDefinition(
        code=ErrorCode.E_LOW_CONFIDENCE,
        trigger="A < seuil bas",
        system_behavior="sortie « non identifié » (EF5)",
        user_message_template="Identification peu stable. Vérification manuelle requise.",
        journal_trace_fields=("agreement", "distribution"),
    ),
    ErrorCode.E_UNCALIBRATED_CONSENSUS: ErrorDefinition(
        code=ErrorCode.E_UNCALIBRATED_CONSENSUS,
        trigger="A élevé et R faible",
        system_behavior="« identifié avec réserve », jamais « identifié »",
        user_message_template="Résultat cohérent mais non retrouvé dans le référentiel. À vérifier manuellement.",
        journal_trace_fields=("agreement", "resolvability"),
    ),
    ErrorCode.E_NO_CPE_MATCH: ErrorDefinition(
        code=ErrorCode.E_NO_CPE_MATCH,
        trigger="meilleur score < seuil de résolvabilité",
        system_behavior="pas de CPE → pas de CVE ; jamais de CPE inventé",
        user_message_template="Objet identifié mais absent du référentiel NIST. Aucune CVE ne peut être rattachée.",
        journal_trace_fields=("top3_scores",),
    ),
    ErrorCode.E_CPE_AMBIGUOUS: ErrorDefinition(
        code=ErrorCode.E_CPE_AMBIGUOUS,
        trigger="écart top1−top2 < marge",
        system_behavior="propose les 2, force le HITL",
        user_message_template="Deux référentiels correspondent. Sélectionnez le bon.",
        journal_trace_fields=("top2_scores",),
    ),
    ErrorCode.E_NO_CVE: ErrorDefinition(
        code=ErrorCode.E_NO_CVE,
        trigger="0 CVE après recherche correcte",
        system_behavior="message non rassurant",
        user_message_template="Aucune CVE référencée pour ce produit au [date]. Cela ne signifie pas qu'il est exempt de vulnérabilités (version firmware non déterminée).",
        journal_trace_fields=("cpe", "snapshot", "n"),
    ),
    ErrorCode.E_NVD_UNAVAILABLE: ErrorDefinition(
        code=ErrorCode.E_NVD_UNAVAILABLE,
        trigger="snapshot absent/illisible",
        system_behavior="mode dégradé : identification seule",
        user_message_template="Base CVE locale indisponible. Analyse limitée à l'identification.",
        journal_trace_fields=("cache_status",),
    ),
    ErrorCode.E_NVD_CACHE_MISS: ErrorDefinition(
        code=ErrorCode.E_NVD_CACHE_MISS,
        trigger="CVE hors snapshot",
        system_behavior="marque explicitement",
        user_message_template="Recherche effectuée sur la base du [date] ; certaines CVE récentes peuvent manquer.",
        journal_trace_fields=("snapshot_sha256",),
    ),
    ErrorCode.E_PROVENANCE_INCOMPLETE: ErrorDefinition(
        code=ErrorCode.E_PROVENANCE_INCOMPLETE,
        trigger="un champ de provenance manque",
        system_behavior="écriture refusée (contrainte SQL)",
        user_message_template="Analyse refusée : traçabilité incomplète.",
        journal_trace_fields=("missing_field",),
    ),
    ErrorCode.E_HMAC_CHAIN_BROKEN: ErrorDefinition(
        code=ErrorCode.E_HMAC_CHAIN_BROKEN,
        trigger="vérification de chaîne échoue",
        system_behavior="run invalide, export bloqué",
        user_message_template="Intégrité du journal compromise. Export désactivé — contactez l'administrateur.",
        journal_trace_fields=("break_index", "expected", "computed"),
    ),
    ErrorCode.E_JOURNAL_WRITE_FAILED: ErrorDefinition(
        code=ErrorCode.E_JOURNAL_WRITE_FAILED,
        trigger="écriture journal impossible",
        system_behavior="arrêt du run (on ne produit pas de résultat non tracé)",
        user_message_template="Impossible d'enregistrer la trace. Analyse interrompue.",
        journal_trace_fields=("error",),
    ),
    ErrorCode.E_DISK_FULL: ErrorDefinition(
        code=ErrorCode.E_DISK_FULL,
        trigger="espace insuffisant",
        system_behavior="refus avant run",
        user_message_template="Espace de stockage insuffisant.",
        journal_trace_fields=("threshold", "available"),
    ),
    ErrorCode.E_CLOCK_SKEW: ErrorDefinition(
        code=ErrorCode.E_CLOCK_SKEW,
        trigger="horloge incohérente entre étapes",
        system_behavior="avertit, continue (seq fait foi)",
        user_message_template="",
        journal_trace_fields=("measured_delta",),
    ),
    ErrorCode.E_PARTIAL_RUN: ErrorDefinition(
        code=ErrorCode.E_PARTIAL_RUN,
        trigger="nœud perdu en cours",
        system_behavior="run marqué partiel, nodes_used mis à jour",
        user_message_template="Analyse terminée avec un nœud en moins ; résultats complets pour les photos traitées.",
        journal_trace_fields=("nodes", "lost_images"),
    ),
}


# --------------------------------------------------------------------------- #
# Entrées / sorties de couche
# --------------------------------------------------------------------------- #


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


FramingState = Literal["unverified", "ok", "rejected"]
"""État du cadrage d'une photo, au sens P1 « une photo = un objet » (docs/07 §5).

Trois valeurs, et la première n'est pas un feu vert : ``unverified`` dit que la
question **n'a pas été posée**, pas qu'elle a reçu une bonne réponse.
"""


@dataclass(frozen=True, slots=True)
class VLMTriageOutput:
    """Sortie brute du décodage contraint de triage (runner v6, docs/06 §22).

    Ne demande ni marque ni modèle :
    * ``view``     : objet entier vs détail / gros plan (isole les cartes mères)
    * ``category`` : catégorie parmi la taxonomie fermée (ou OTHER)
    * ``iot``      : l'objet est-il connecté ou non (cap tuteur 2026-10-05)
    * ``n_salient_objects`` : combien d'objets distincts la photo montre-t-elle

    ``n_salient_objects`` porte le principe P1 « une photo = un objet » (AC de
    ``docs/07`` §5) : deux objets dans la même photo, c'est deux vérités terrain
    pour un seul tuple de sortie, donc une marque attribuée au mauvais objet.

    **Trois états, jamais deux (corrigé le 2026-10-06) :**

    * ``None`` — la question **n'a pas été posée** au modèle. Le manifeste v6
      fige le schéma sur ``{view, category, iot}`` pour que la comparaison des
      144 photos avec v4 tienne à l'octet près : aucune mesure v6 publiée n'a
      répondu à cette question, et aucune ne prétend le contraire.
    * ``0`` ou ``>= 2`` — le cadre est inexploitable (voir ``screen_frame``).
    * ``1`` — le producteur a réellement posé la question et a obtenu ce nombre.

    La version précédente valait ``1`` par défaut. Le raisonnement — « rendre
    l'ajout non destructif envers des mesures antérieures » — était juste pour
    la compatibilité et **faux pour la sincérité** : un champ jamais demandé
    était indistinguable d'un champ vérifié, et un seul état portait deux sens.
    Le défaut est donc ``None``, parce que « non vérifié » n'est pas « conforme »
    (même classe de défaut qu'un décalage d'horloge invisible ou qu'une chaîne
    HMAC non revérifiée : une absence rendue comme une conformité). Une mesure
    v6 reste valide : elle est étiquetée pour ce qu'elle est.
    """

    view: ViewType
    category: Category
    iot: bool
    n_salient_objects: int | None = None


@dataclass(frozen=True, slots=True)
class ObjectTriage:
    """Résultat consolidé du triage visuel sur N photos d'un même objet."""

    object_id: str
    is_iot: bool                            # Décision finale : objet connecté d'intérêt ou non
    category: Category                      # Catégorie retenue
    iot_agreement: float                    # Accord sur is_iot in [0, 1]
    category_agreement: float               # Accord sur la catégorie in [0, 1]
    whole_view_ratio: float                 # Part des photos montrant l'objet entier in [0, 1]
    n_images: int
    framing: FramingState                   # Cadrage réellement vérifié ? (P1, docs/07 §5)
    category_distribution: Mapping[str, int]
    view_distribution: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CPECandidate:
    cpe_name: str               # cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*
    vendor: str
    product: str
    version: str | None
    category: Category
    lexical_score: float
    semantic_score: float | None
    score: float                # fusion documentée (docs/05)
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
    """Résultat consolidé sur N photos du **même** objet.

    Deux axes, jamais un seul (docs/05 §4.2) : ``agreement`` (A) mesure la
    stabilité inter-photos, ``resolvability`` (R) mesure si ce consensus
    existe dans le référentiel. La cellule « A élevé / R faible » est la
    signature d'un **consensus halluciné**.
    """

    brand: str | None
    model: str | None
    category: Category
    status: Status
    n_images: int
    agreement: float                        # A  in [0,1]
    resolvability: float                    # R  in [0,1]
    per_field_agreement: Mapping[str, float]
    distribution: Mapping[str, int]         # tuple -> nb d'occurrences
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


# --------------------------------------------------------------------------- #
# Découplage par protocole (injection de dépendance, testable sans GPU ni réseau)
# --------------------------------------------------------------------------- #


class TriageRunner(Protocol):
    """Premier filtre : vue, catégorie, « IoT ou non » (docs/06 §22, D16).

    Ne lit ni marque ni modèle — c'est la porte d'entrée de la chaîne : elle
    décide si l'objet a un intérêt (connecté) avant toute lecture d'étiquette.
    """

    def triage(self, image: ImageInput, *, prompt_version: str) -> VLMTriageOutput: ...


class VLMRunner(Protocol):
    def infer(self, image: ImageInput, *, prompt_version: str) -> VLMRawOutput: ...


class CPEResolver(Protocol):
    def resolve(self, ident: Identification, *, k: int = 3) -> Sequence[CPECandidate]: ...


class CVESearcher(Protocol):
    def search(self, cpe: CPECandidate, *, since: date) -> Sequence[CVEResult]: ...


class Journal(Protocol):
    def append(self, event: JournalEvent) -> str: ...   # -> hmac courant


class JournalWriteError(RuntimeError):
    """Écriture du journal impossible (docs/03 §5, ``E_JOURNAL_WRITE_FAILED``).

    Cette exception existe comme *type du contrat* et non comme détail de
    stockage : la règle est « on ne produit pas de résultat non tracé » (C5).
    Un journal qui n'a pas pu écrire doit interrompre le run, pas le dégrader
    en silence — un rapport sans trace est indiscernable d'un rapport fabriqué.

    Définie ici, dans la couche d'interface, pour que les implémentations
    (``storage.journal``) et les appelants (``pipeline.orchestrate``) partagent
    un type sans que le pipeline dépende d'un moteur de base de données.
    """

    code: ErrorCode = ErrorCode.E_JOURNAL_WRITE_FAILED
