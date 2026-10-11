"""Tests pour le scellement Ed25519 et l'outil de vérification tiers (D11, docs/07 §4.4).

Couvre :
1. Génération de clés Ed25519
2. Signature de rapport avec extraction de tête HMAC
3. Vérification positive nominale
4. Échec de vérification sur altération de payload
5. Échec de vérification sur altération de run_id / report_id / dates
6. Échec de vérification sur altération de tête de chaîne HMAC
7. Échec de vérification en cas de mauvaise clé publique
8. Fonctionnement du CLI verify_report.py tiers sans clé privée ni base SQLite
"""

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from iot_audit.contracts import Provenance
from iot_audit.storage.journal import (
    GENESIS_HMAC,
    append_hmac_entry,
    ensure_journal_schema,
)
from iot_audit.storage.seal import (
    ChainBrokenError,
    ProvenanceIncompleteError,
    generate_ed25519_keypair,
    get_chain_head,
    sign_report,
    verify_exported_report,
)


@pytest.fixture
def journal_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    ensure_journal_schema(con)
    return con


def test_chain_head_empty_and_populated(journal_db: sqlite3.Connection) -> None:
    head, count = get_chain_head(journal_db)
    assert head == GENESIS_HMAC
    assert count == 0

    h0 = append_hmac_entry(
        journal_db, run_id="r1", seq=0, stage="infer", code="OK", payload={"x": 1}
    )
    head, count = get_chain_head(journal_db)
    assert head == h0
    assert count == 1

    h1 = append_hmac_entry(
        journal_db, run_id="r1", seq=1, stage="resolve", code="OK", payload={"x": 2}
    )
    head, count = get_chain_head(journal_db)
    assert head == h1
    assert count == 2


def test_sign_and_verify_nominal(journal_db: sqlite3.Connection) -> None:
    append_hmac_entry(
        journal_db, run_id="run-100", seq=0, stage="infer", code="OK", payload={"step": 1}
    )
    priv, pub = generate_ed25519_keypair()

    payload = {
        "device": "TP-Link Archer C7",
        "category": "router_ap",
        "cve_count": 3,
        "status": "identified",
    }

    report = sign_report(
        con=journal_db,
        report_id="rep-001",
        run_id="run-100",
        created_at="2026-10-06T12:00:00Z",
        payload=payload,
        private_key=priv,
    )

    assert report.report_id == "rep-001"
    assert report.chain_length == 1
    assert len(report.chain_head_hmac) == 64
    assert len(report.signature_b64) > 0

    # Vérification avec objet direct
    assert verify_exported_report(report) is True
    assert verify_exported_report(report, expected_public_key=pub) is True

    # Vérification avec JSON sérialisé
    json_str = report.to_json()
    assert verify_exported_report(json_str) is True
    assert verify_exported_report(json_str.encode("utf-8")) is True


@pytest.mark.parametrize(
    "tamper_field",
    [
        "report_id",
        "run_id",
        "created_at",
        "chain_head_hmac",
        "chain_length",
        "payload",
    ],
)
def test_export_is_not_forgeable_without_private_key(
    journal_db: sqlite3.Connection, tamper_field: str
) -> None:
    """Symétrique Ed25519 du test A7b (docs/07 §4.4).

    Toute altération du rapport scellé fait échouer verify_exported_report.
    """
    append_hmac_entry(
        journal_db, run_id="run-1", seq=0, stage="infer", code="OK", payload={"a": 1}
    )
    priv, pub = generate_ed25519_keypair()
    payload = {"brand": "D-Link", "cves": ["CVE-2024-1234"]}

    report = sign_report(
        con=journal_db,
        report_id="rep-1",
        run_id="run-1",
        created_at="2026-10-06T10:00:00Z",
        payload=payload,
        private_key=priv,
    )

    data = json.loads(report.to_json())

    # Altération ciblée
    if tamper_field == "payload":
        data["payload"]["cves"].append("CVE-2024-9999")
    elif tamper_field == "chain_length":
        data["chain_length"] = 999
    elif tamper_field == "chain_head_hmac":
        data["chain_head_hmac"] = "0" * 64
    else:
        data[tamper_field] = f"{data[tamper_field]}-tampered"

    tampered_json = json.dumps(data)
    assert verify_exported_report(tampered_json, expected_public_key=pub) is False


def test_verify_with_wrong_public_key(journal_db: sqlite3.Connection) -> None:
    priv1, pub1 = generate_ed25519_keypair()
    _, pub2 = generate_ed25519_keypair()

    report = sign_report(
        con=journal_db,
        report_id="rep-wrong-key",
        run_id="run-1",
        created_at="2026-10-06T10:00:00Z",
        payload={"v": 1},
        private_key=priv1,
    )

    # Vérification avec pub1 (objet, b64 str, bytes) -> OK
    assert verify_exported_report(report, expected_public_key=pub1) is True
    assert verify_exported_report(report, expected_public_key=report.public_key_b64) is True
    assert verify_exported_report(report, expected_public_key=pub1.public_bytes_raw()) is True

    # Vérification contre pub2 attendue -> Échec
    assert verify_exported_report(report, expected_public_key=pub2) is False
    assert verify_exported_report(report, expected_public_key=pub2.public_bytes_raw()) is False

    # Mauvais format de clé attendue
    assert verify_exported_report(report, expected_public_key=123) is False  # type: ignore[arg-type]


def test_verify_invalid_input() -> None:
    assert verify_exported_report("not-json") is False
    assert verify_exported_report(12345) is False  # type: ignore[arg-type]
    # Clé publique avec longueur invalide
    bad_key_json = json.dumps({
        "report_id": "r", "run_id": "r", "created_at": "d", "chain_head_hmac": "h",
        "chain_length": 1, "payload": {}, "threat_model_statement": "s",
        "public_key_b64": "AAAA", "signature_b64": "AAAA"
    })
    assert verify_exported_report(bad_key_json) is False


def test_cli_verify_report(tmp_path: Path, journal_db: sqlite3.Connection) -> None:
    priv, pub = generate_ed25519_keypair()
    report = sign_report(
        con=journal_db,
        report_id="rep-cli",
        run_id="run-cli",
        created_at="2026-10-06T11:00:00Z",
        payload={"result": "safe"},
        private_key=priv,
    )
    report_file = tmp_path / "report.json"
    report_file.write_text(report.to_json(), encoding="utf-8")

    # CLI sans clé de confiance : auto-cohérence seulement -> verdict PARTIEL.
    # La clé lue DANS le rapport ne prouve pas l'origine (un faussaire embarque
    # la sienne) : l'outil ne doit donc jamais annoncer « authentique » sans clé.
    res = subprocess.run(
        [sys.executable, "verify_report.py", str(report_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 3
    assert "[PARTIEL]" in res.stderr
    assert "[OK]" not in res.stdout

    # CLI avec la clé de l'auditeur : authenticité prouvée
    res_key = subprocess.run(
        [sys.executable, "verify_report.py", str(report_file), "--pubkey", report.public_key_b64],
        capture_output=True,
        text=True,
    )
    assert res_key.returncode == 0
    assert "[OK]" in res_key.stdout

    # Une clé de confiance non concordante est un échec, pas un avertissement
    _, other_pub = generate_ed25519_keypair()
    other_b64 = __import__("base64").b64encode(other_pub.public_bytes_raw()).decode("ascii")
    res_wrong = subprocess.run(
        [sys.executable, "verify_report.py", str(report_file), "--pubkey", other_b64],
        capture_output=True,
        text=True,
    )
    assert res_wrong.returncode == 1
    assert "[ECHEC]" in res_wrong.stderr

    # Altération du fichier : détectée même sans clé fournie
    report_file.write_text(report.to_json().replace("safe", "compromised"), encoding="utf-8")
    res_tampered = subprocess.run(
        [sys.executable, "verify_report.py", str(report_file)],
        capture_output=True,
        text=True,
    )
    assert res_tampered.returncode == 1
    assert "[ECHEC]" in res_tampered.stderr


def _complete_provenance(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "model_revision": "qwen2.5-vl-7b@2026-09-30",
        "weights_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "schema_version": "v6",
        "vllm_version": "0.29.0",
        "torch_version": "2.5.1",
        "nvd_snapshot_sha256": "c" * 64,
        "cpe_dict_version_id": 7,
        "sampling_params": {"temperature": 0.0, "seed": 1234},
        "nodes_used": ("zabeth21",),
        "started_at": datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 10, 6, 12, 5, tzinfo=UTC),
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def _tamper(con: sqlite3.Connection, seq: int, **columns: str) -> None:
    """Altération brute d'une entrée, triggers retirés (simule un disque trafiqué)."""
    con.execute("DROP TRIGGER trg_hmac_no_update")
    sets = ", ".join(f"{k}=?" for k in columns)
    con.execute(f"UPDATE hmac_chain SET {sets} WHERE seq=?", (*columns.values(), seq))


# --------------------------------------------------------------------------- #
# E_HMAC_CHAIN_BROKEN : sceller un journal rompu (correctif du 2026-10-06)
# --------------------------------------------------------------------------- #

def test_sign_report_refuses_a_broken_chain(journal_db: sqlite3.Connection) -> None:
    """Avant cette date, la signature scellait n'importe quelle base, rompue comprise.

    Le rapport prouvait alors qu'une donnée venait de nous, pas qu'elle était
    inaltérée — la taxonomie déclarait « export bloqué » sans que rien ne bloque.
    """
    for i in range(4):
        append_hmac_entry(
            journal_db, run_id="run-b", seq=i, stage="infer", code="OK", payload={"i": i}
        )
    _tamper(journal_db, 2, payload='{"i": 999}')
    priv, _ = generate_ed25519_keypair()

    with pytest.raises(ChainBrokenError) as excinfo:
        sign_report(
            con=journal_db, report_id="rep-broken", run_id="run-b",
            created_at="2026-10-06T12:00:00Z", payload={"result": "safe"},
            private_key=priv,
        )

    assert excinfo.value.break_index == 2
    # la trace exigée par docs/03 §5 : attendu ET calculé
    assert excinfo.value.expected and excinfo.value.computed
    assert excinfo.value.expected != excinfo.value.computed
    assert excinfo.value.code.value == "E_HMAC_CHAIN_BROKEN"


def test_a_valid_chain_is_still_signed(journal_db: sqlite3.Connection) -> None:
    """Contrôle négatif : le refus ne doit pas bloquer les journaux sains."""
    append_hmac_entry(
        journal_db, run_id="run-ok", seq=0, stage="infer", code="OK", payload={"i": 1}
    )
    priv, _ = generate_ed25519_keypair()
    report = sign_report(
        con=journal_db, report_id="rep-ok", run_id="run-ok",
        created_at="2026-10-06T12:00:00Z", payload={"result": "safe"}, private_key=priv,
    )
    assert verify_exported_report(report) is True


def test_declaring_the_chain_broken_is_possible_on_explicit_request(
    journal_db: sqlite3.Connection,
) -> None:
    """``verify_integrity=False`` : exporter un journal cassé pour le réparer."""
    for i in range(3):
        append_hmac_entry(
            journal_db, run_id="run-c", seq=i, stage="infer", code="OK", payload={"i": i}
        )
    _tamper(journal_db, 1, payload='{"i": 999}')
    priv, _ = generate_ed25519_keypair()

    report = sign_report(
        con=journal_db, report_id="rep-repair", run_id="run-c",
        created_at="2026-10-06T12:00:00Z", payload={"repair": True},
        private_key=priv, verify_integrity=False,
    )
    assert verify_exported_report(report) is True


# --------------------------------------------------------------------------- #
# E_PROVENANCE_INCOMPLETE : pas de scellé sans provenance
# --------------------------------------------------------------------------- #

def test_incomplete_provenance_is_refused_before_signing(journal_db: sqlite3.Connection) -> None:
    append_hmac_entry(
        journal_db, run_id="run-p", seq=0, stage="infer", code="OK", payload={"i": 1}
    )
    priv, _ = generate_ed25519_keypair()

    with pytest.raises(ProvenanceIncompleteError) as excinfo:
        sign_report(
            con=journal_db, report_id="rep-p", run_id="run-p",
            created_at="2026-10-06T12:00:00Z", payload={}, private_key=priv,
            provenance=_complete_provenance(weights_sha256=""),
        )
    assert excinfo.value.missing == ("weights_sha256",)
    assert excinfo.value.code.value == "E_PROVENANCE_INCOMPLETE"


def test_complete_provenance_travels_inside_the_signature(journal_db: sqlite3.Connection) -> None:
    """Une provenance hors signature resterait modifiable : elle va DANS le payload."""
    append_hmac_entry(
        journal_db, run_id="run-p2", seq=0, stage="infer", code="OK", payload={"i": 1}
    )
    priv, _ = generate_ed25519_keypair()
    report = sign_report(
        con=journal_db, report_id="rep-p2", run_id="run-p2",
        created_at="2026-10-06T12:00:00Z", payload={"result": "safe"}, private_key=priv,
        provenance=_complete_provenance(),
    )

    assert report.payload["provenance"]["weights_sha256"] == "a" * 64
    assert verify_exported_report(report) is True

    # modifier la provenance invalide la signature : elle est bien couverte
    forged = replace(
        report,
        payload={**report.payload, "provenance": {
            **report.payload["provenance"], "model_revision": "un-autre-modele",
        }},
    )
    assert verify_exported_report(forged) is False


# --------------------------------------------------------------------------- #
# Rapports forgés (A7b)
# --------------------------------------------------------------------------- #

def test_forged_report_is_self_consistent_but_not_authentic(
    journal_db: sqlite3.Connection,
) -> None:
    """Un rapport forgé se vérifie sous sa propre clé — et c'est tout.

    C'est la raison d'être du verdict PARTIEL : sans clé de confiance publiée
    par l'auditeur, `verify_exported_report` prouve la cohérence interne du
    document, jamais son origine (D11).
    """
    append_hmac_entry(
        journal_db, run_id="run-x", seq=0, stage="infer", code="OK", payload={"a": 1}
    )
    forger_priv, _ = generate_ed25519_keypair()
    _, trusted_pub = generate_ed25519_keypair()

    forged = sign_report(
        con=journal_db,
        report_id="rep-forged",
        run_id="run-x",
        created_at="2026-10-06T10:00:00Z",
        payload={"result": "safe"},
        private_key=forger_priv,
    )

    # Auto-cohérent : la signature correspond bien à la clé embarquée…
    assert verify_exported_report(forged) is True
    # …mais pas authentique sous la clé de l'auditeur.
    assert verify_exported_report(forged, expected_public_key=trusted_pub) is False
