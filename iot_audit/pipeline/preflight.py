"""Pré-vol d'un run : ce qui doit être refusé **avant** d'appeler un modèle.

Deux refus, deux codes de la taxonomie (docs/03 §5), et dans les deux cas la
même logique : un run qui échoue *après* avoir commencé coûte plus cher qu'un
run qui refuse de commencer.

``E_DISK_FULL`` — « refus avant run ».
    Un run qui manque d'espace en cours de route ne laisse pas « un résultat
    incomplet » : il laisse une chaîne HMAC tronquée et un rapport dont la
    traçabilité n'est plus vérifiable. Le refus coûte une relance ; la
    troncature coûte la seule chose que ce projet vend.

``E_PROVENANCE_INCOMPLETE`` — « écriture refusée ».
    Une empreinte de poids, un SHA de prompt ou une révision de modèle
    manquante rend le run irreproductible au sens d'ENF5. Un run
    irreproductible n'est pas un résultat, c'est une anecdote : il ne doit pas
    pouvoir être scellé (cf. ``storage.seal.sign_report``).

Ce module ne calcule rien qui dépende de l'heure, du réseau ou d'un modèle : il
est exécutable et testable hors ligne, ce qui permet de le vérifier avant de
dépendre de lui.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from iot_audit.contracts import ErrorCode, Provenance

__all__ = [
    "MIN_FREE_BYTES",
    "PreflightCheck",
    "REQUIRED_PROVENANCE_FIELDS",
    "check_disk",
    "missing_provenance_fields",
]

#: Seuil par défaut du refus pour espace insuffisant.
#:
#: 256 Mio n'est pas un chiffre rond décoratif : le journal SQLite en mode WAL
#: doit pouvoir écrire ses pages *et* être copié pour un export scellé, sur un
#: run qui produit jusqu'à quelques milliers d'entrées et des rapports associés.
#: Le seuil est un argument, pas une constante en dur dans l'appelant : un banc
#: de test doit pouvoir éprouver le refus sans remplir un disque.
MIN_FREE_BYTES = 256 * 1024 * 1024

#: Champs de ``Provenance`` dont l'absence invalide le run (docs/03 §2, ENF5).
#: ``nodes_used`` et ``sampling_params`` sont contrôlés à part : ce sont des
#: conteneurs, dont la vacuité ne se lit pas comme une chaîne vide.
REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "model_revision",
    "weights_sha256",
    "prompt_sha256",
    "schema_version",
    "vllm_version",
    "torch_version",
    "nvd_snapshot_sha256",
)

#: Signature d'un contrôle de pré-vol injectable dans l'orchestrateur.
#: ``None`` = rien à signaler ; un code = le run est refusé.
PreflightCheck = Callable[[], ErrorCode | None]


def check_disk(
    path: str | Path,
    *,
    min_free_bytes: int = MIN_FREE_BYTES,
) -> ErrorCode | None:
    """Refuse le run si l'espace libre sous ``path`` est sous le seuil.

    Renvoie ``ErrorCode.E_DISK_FULL`` si l'espace est insuffisant, ``None``
    sinon. Un chemin inaccessible est *aussi* un refus : il n'y a pas de
    résultat à écrire là où on ne peut pas écrire, et distinguer les deux cas
    laisserait passer un run non journalisable.
    """
    try:
        free = shutil.disk_usage(str(path)).free
    except OSError:
        return ErrorCode.E_DISK_FULL
    return ErrorCode.E_DISK_FULL if free < min_free_bytes else None


def missing_provenance_fields(prov: Provenance) -> tuple[str, ...]:
    """Liste les champs de provenance absents, dans l'ordre du contrat.

    « Absent » couvre la chaîne vide et la chaîne d'espaces : une empreinte
    laissée à ``\" \"`` n'est pas renseignée, elle est *remplie*. Un tuple vide
    signifie que la provenance est complète.
    """
    missing: list[str] = []
    for name in REQUIRED_PROVENANCE_FIELDS:
        value = getattr(prov, name, None)
        if not isinstance(value, str) or not value.strip():
            missing.append(name)

    if not prov.nodes_used:
        missing.append("nodes_used")
    if not prov.sampling_params:
        missing.append("sampling_params")
    if prov.cpe_dict_version_id is None or prov.cpe_dict_version_id <= 0:
        missing.append("cpe_dict_version_id")

    return tuple(missing)
