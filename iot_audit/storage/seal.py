"""Signature asymétrique Ed25519 et vérification d'intégrité de rapport (D11, D14).

Modèle de menace (docs/02 §D11, docs/07 §4.4) :
- Le HMAC protège l'intégrité applicative en cours d'exécution.
- La clé HMAC étant symétrique et stockée sur le serveur d'audit,
  le détenteur de la clé peut forger une chaîne valide (prouvé en A7b).
- Pour l'export externe opposable (client, régulateur, tribunal), la tête de chaîne
  HMAC ainsi que le payload du rapport sont signés par une clé privée Ed25519.
- La clé publique Ed25519 est publiée dans le rapport / certificat, et un
  tiers vérificateur (verify_report.py) peut prouver l'authenticité et l'intégrité
  SANS avoir accès à la base de données ni à la clé secrète HMAC.
"""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from iot_audit.contracts import ErrorCode, Provenance
from iot_audit.pipeline.preflight import missing_provenance_fields
from iot_audit.storage.journal import (
    DEFAULT_DEV_KEY,
    GENESIS_HMAC,
    verify_chain_detailed,
)

__all__ = [
    "ChainBrokenError",
    "ExportedReport",
    "ProvenanceIncompleteError",
    "generate_ed25519_keypair",
    "get_chain_head",
    "sign_report",
    "verify_exported_report",
]


class ChainBrokenError(RuntimeError):
    """La chaîne HMAC est rompue : l'export est bloqué (docs/03 §5, ``E_HMAC_CHAIN_BROKEN``).

    Avant le 2026-10-06, ``sign_report`` scellait n'importe quelle base, chaîne
    rompue comprise. La signature Ed25519 était donc valide sur un journal dont
    on savait — ou dont on n'avait pas vérifié — qu'il avait été altéré : le
    rapport prouvait qu'une donnée venait de nous, pas qu'elle était
    inaltérée. La taxonomie déclarait « run invalide, export bloqué » sans que
    rien ne bloque.
    """

    code: ErrorCode = ErrorCode.E_HMAC_CHAIN_BROKEN

    def __init__(self, break_index: int | None, expected: str, computed: str) -> None:
        self.break_index = break_index
        self.expected = expected
        self.computed = computed
        super().__init__(
            f"{ErrorCode.E_HMAC_CHAIN_BROKEN.value}: chaîne rompue à l'index "
            f"{break_index} (attendu={expected!r}, calculé={computed!r})"
        )


class ProvenanceIncompleteError(ValueError):
    """Provenance incomplète : écriture refusée (docs/03 §5, ``E_PROVENANCE_INCOMPLETE``).

    Un rapport scellé sans empreinte de poids, sans SHA de prompt ou sans
    révision de modèle est opposable mais irreproductible : il ne peut pas être
    rejoué, donc il ne peut pas être défendu. Le refus est ici, à l'endroit où
    la non-répudiation est engagée, et pas dans un formulaire.
    """

    code: ErrorCode = ErrorCode.E_PROVENANCE_INCOMPLETE

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(
            f"{ErrorCode.E_PROVENANCE_INCOMPLETE.value}: "
            f"champ(s) de provenance manquant(s) : {', '.join(missing)}"
        )


@dataclass(frozen=True, slots=True)
class ExportedReport:
    """Structure d'un rapport exporté et scellé."""

    report_id: str
    run_id: str
    created_at: str
    chain_head_hmac: str
    chain_length: int
    payload: dict[str, Any]
    threat_model_statement: str
    public_key_b64: str
    signature_b64: str

    def to_json(self) -> str:
        data = {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "chain_head_hmac": self.chain_head_hmac,
            "chain_length": self.chain_length,
            "payload": self.payload,
            "threat_model_statement": self.threat_model_statement,
            "public_key_b64": self.public_key_b64,
            "signature_b64": self.signature_b64,
        }
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> ExportedReport:
        data = json.loads(raw)
        return cls(
            report_id=data["report_id"],
            run_id=data["run_id"],
            created_at=data["created_at"],
            chain_head_hmac=data["chain_head_hmac"],
            chain_length=data["chain_length"],
            payload=data["payload"],
            threat_model_statement=data["threat_model_statement"],
            public_key_b64=data["public_key_b64"],
            signature_b64=data["signature_b64"],
        )


THREAT_MODEL_STATEMENT = (
    "Ce rapport est scellé par signature Ed25519 sur la tête de chaîne HMAC "
    "et l'empreinte canonique de son contenu. Le HMAC garantit la consistance séquentielle "
    "interne ; la signature asymétrique garantit la non-répudiation et permet "
    "la vérification tierce sans divulgation de secrets (docs/02 D11)."
)


def generate_ed25519_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Génère une nouvelle paire de clés Ed25519."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


def get_chain_head(con: sqlite3.Connection) -> tuple[str, int]:
    """Extrait le HMAC de tête et le nombre d'entrées du journal.

    Retourne (current_hmac, count). Si la table est vide, retourne (GENESIS_HMAC, 0).
    """
    row = con.execute(
        "SELECT current_hmac, seq FROM hmac_chain ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return GENESIS_HMAC, 0
    return str(row[0]), int(row[1]) + 1


def _provenance_to_dict(prov: Provenance) -> dict[str, Any]:
    """Provenance -> bloc sérialisable, embarqué dans le payload scellé.

    Elle est mise **dans** le payload signé, pas à côté : une provenance
    transportée hors de la signature Ed25519 resterait modifiable par qui veut
    faire passer un run pour reproductible.
    """
    return {
        "model_revision": prov.model_revision,
        "weights_sha256": prov.weights_sha256,
        "prompt_sha256": prov.prompt_sha256,
        "schema_version": prov.schema_version,
        "vllm_version": prov.vllm_version,
        "torch_version": prov.torch_version,
        "nvd_snapshot_sha256": prov.nvd_snapshot_sha256,
        "cpe_dict_version_id": prov.cpe_dict_version_id,
        "sampling_params": dict(prov.sampling_params),
        "nodes_used": list(prov.nodes_used),
        "started_at": prov.started_at.isoformat(),
        "finished_at": prov.finished_at.isoformat(),
    }


def _canonical_bytes_for_signing(
    report_id: str,
    run_id: str,
    created_at: str,
    chain_head_hmac: str,
    chain_length: int,
    payload: Mapping[str, Any],
) -> bytes:
    """Construit la chaîne canonique scellée par la signature."""
    canonical_dict = {
        "report_id": report_id,
        "run_id": run_id,
        "created_at": created_at,
        "chain_head_hmac": chain_head_hmac,
        "chain_length": chain_length,
        "payload": payload,
    }
    raw = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return raw.encode("utf-8")


def sign_report(
    con: sqlite3.Connection,
    report_id: str,
    run_id: str,
    created_at: str,
    payload: dict[str, Any],
    private_key: ed25519.Ed25519PrivateKey,
    *,
    provenance: Provenance | None = None,
    hmac_key: bytes = DEFAULT_DEV_KEY,
    verify_integrity: bool = True,
) -> ExportedReport:
    """Signe un rapport avec la clé privée Ed25519 en liant la tête de chaîne HMAC.

    Deux refus précèdent la signature, dans cet ordre — la traçabilité d'abord,
    la répudiation ensuite :

    * chaîne HMAC rompue  -> :class:`ChainBrokenError` (``E_HMAC_CHAIN_BROKEN``) ;
      l'export est bloqué, pas « dégradé » ;
    * provenance incomplète -> :class:`ProvenanceIncompleteError`
      (``E_PROVENANCE_INCOMPLETE``), quand une provenance est fournie.

    ``verify_integrity=False`` existe pour un seul usage : exporter un journal
    *pour le réparer*, cas où l'on sait déjà qu'il est cassé. Ce n'est pas un
    réglage de confort, et le paramètre est nommé pour qu'il se voie dans le
    code appelant.

    ``hmac_key`` est celui de la chaîne : vérifier l'intégrité avec une autre clé
    déclarerait « rompue » toute chaîne valide.
    """
    if provenance is not None:
        missing = missing_provenance_fields(provenance)
        if missing:
            raise ProvenanceIncompleteError(missing)
        payload = {**payload, "provenance": _provenance_to_dict(provenance)}

    if verify_integrity:
        ok, break_index, expected, computed = verify_chain_detailed(con, hmac_key)
        if not ok:
            raise ChainBrokenError(break_index, expected, computed)

    head_hmac, count = get_chain_head(con)

    signing_bytes = _canonical_bytes_for_signing(
        report_id=report_id,
        run_id=run_id,
        created_at=created_at,
        chain_head_hmac=head_hmac,
        chain_length=count,
        payload=payload,
    )

    signature = private_key.sign(signing_bytes)
    pub_key = private_key.public_key()
    pub_bytes = pub_key.public_bytes_raw()

    return ExportedReport(
        report_id=report_id,
        run_id=run_id,
        created_at=created_at,
        chain_head_hmac=head_hmac,
        chain_length=count,
        payload=payload,
        threat_model_statement=THREAT_MODEL_STATEMENT,
        public_key_b64=base64.b64encode(pub_bytes).decode("ascii"),
        signature_b64=base64.b64encode(signature).decode("ascii"),
    )


def verify_exported_report(
    report: ExportedReport | str | bytes,
    expected_public_key: ed25519.Ed25519PublicKey | str | bytes | None = None,
) -> bool:
    """Vérifie l'authenticité et l'intégrité d'un rapport exporté.

    Peut être exécuté de manière totalement isolée par un tiers (docs/02 D11) :
    ne requiert ni la base SQLite ni la clé HMAC secrète.
    """
    if isinstance(report, bytes):
        report = report.decode("utf-8", errors="replace")
    if isinstance(report, str):
        try:
            report_obj = ExportedReport.from_json(report)
        except (ValueError, KeyError, TypeError):
            return False
    elif isinstance(report, ExportedReport):
        report_obj = report
    else:
        return False

    try:
        pub_raw = base64.b64decode(report_obj.public_key_b64)
        if len(pub_raw) != 32:
            return False
        pub = ed25519.Ed25519PublicKey.from_public_bytes(pub_raw)

        if expected_public_key is not None:
            if isinstance(expected_public_key, str):
                expected_bytes = base64.b64decode(expected_public_key)
            elif isinstance(expected_public_key, bytes):
                expected_bytes = expected_public_key
            elif isinstance(expected_public_key, ed25519.Ed25519PublicKey):
                expected_bytes = expected_public_key.public_bytes_raw()
            else:
                return False

            if pub_raw != expected_bytes:
                return False

        sig = base64.b64decode(report_obj.signature_b64)

        signing_bytes = _canonical_bytes_for_signing(
            report_id=report_obj.report_id,
            run_id=report_obj.run_id,
            created_at=report_obj.created_at,
            chain_head_hmac=report_obj.chain_head_hmac,
            chain_length=report_obj.chain_length,
            payload=report_obj.payload,
        )

        pub.verify(sig, signing_bytes)
        return True
    except (InvalidSignature, ValueError, TypeError, KeyError, binascii.Error):
        # Entrée hostile ou incohérente : un vérificateur tier ne doit jamais
        # lever, mais il ne doit pas non plus masquer un défaut de programme.
        # Seuls les échecs d'entrée attendus sont convertis en « faux ».
        return False
