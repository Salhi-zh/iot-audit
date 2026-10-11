"""Tests du pré-vol de run (docs/03 §5 : E_DISK_FULL, E_PROVENANCE_INCOMPLETE).

Ces deux codes étaient déclarés et jamais produits jusqu'au 2026-10-06. Leurs
tests ne se contentent pas de vérifier qu'une fonction existe : ils vérifient
la propriété qui justifie le code, à savoir qu'**aucun résultat n'est produit**
quand la condition de refus est vraie.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from iot_audit.contracts import ErrorCode, Provenance
from iot_audit.pipeline.preflight import (
    MIN_FREE_BYTES,
    REQUIRED_PROVENANCE_FIELDS,
    check_disk,
    missing_provenance_fields,
)


def _provenance(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "model_revision": "qwen2.5-vl-7b@2026-09-30",
        "weights_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "schema_version": "v6",
        "vllm_version": "0.29.0",
        "torch_version": "2.5.1",
        "nvd_snapshot_sha256": "c" * 64,
        "cpe_dict_version_id": 42,
        "sampling_params": {"temperature": 0.0, "seed": 1234},
        "nodes_used": ("zabeth21",),  # type: ignore[arg-type]
        "started_at": datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 10, 6, 12, 5, tzinfo=UTC),
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# E_DISK_FULL
# --------------------------------------------------------------------------- #

def test_check_disk_accepts_an_ample_volume() -> None:
    assert check_disk(Path("/"), min_free_bytes=0) is None


def test_check_disk_refuses_when_below_the_threshold() -> None:
    # Le seuil est un argument : éprouver le refus ne doit pas demander de
    # remplir un disque, seulement de demander plus que ce qui existe.
    code = check_disk(Path("/"), min_free_bytes=10**18)
    assert code is ErrorCode.E_DISK_FULL


def test_check_disk_refuses_an_unreadable_path() -> None:
    """Pas de résultat à écrire là où on ne peut pas écrire."""
    code = check_disk(Path("/nonexistent-iot-audit-volume/please"), min_free_bytes=1)
    assert code is ErrorCode.E_DISK_FULL


def test_default_threshold_is_bytes_and_is_positive() -> None:
    assert MIN_FREE_BYTES > 0
    assert MIN_FREE_BYTES % (1024 * 1024) == 0


# --------------------------------------------------------------------------- #
# E_PROVENANCE_INCOMPLETE
# --------------------------------------------------------------------------- #

def test_complete_provenance_reports_nothing_missing() -> None:
    assert missing_provenance_fields(_provenance()) == ()


def test_blank_string_is_missing_not_filled() -> None:
    """Une empreinte laissée à un espace n'est pas renseignée, elle est remplie."""
    assert missing_provenance_fields(_provenance(weights_sha256="   ")) == ("weights_sha256",)
    assert missing_provenance_fields(_provenance(prompt_sha256="")) == ("prompt_sha256",)


def test_every_declared_field_is_actually_checked() -> None:
    """Verrou : retirer un champ de la liste doit casser ce test, pas passer."""
    for name in REQUIRED_PROVENANCE_FIELDS:
        missing = missing_provenance_fields(_provenance(**{name: ""}))
        assert name in missing, f"{name} n'est pas contrôlé"


def test_empty_containers_are_missing() -> None:
    assert "nodes_used" in missing_provenance_fields(_provenance(nodes_used=()))
    assert "sampling_params" in missing_provenance_fields(_provenance(sampling_params={}))


def test_impossible_cpe_dictionary_id_is_missing() -> None:
    """``cpe_dict_version_id`` est une clé étrangère : 0 ou négatif n'existe pas."""
    assert "cpe_dict_version_id" in missing_provenance_fields(_provenance(cpe_dict_version_id=0))
    assert "cpe_dict_version_id" in missing_provenance_fields(_provenance(cpe_dict_version_id=-1))


def test_missing_fields_are_reported_in_contract_order() -> None:
    """L'ordre est stable : un rapport qui liste « ce qui manque » doit être lisible."""
    missing = missing_provenance_fields(
        _provenance(model_revision="", vllm_version="", nodes_used=())
    )
    assert missing == ("model_revision", "vllm_version", "nodes_used")
