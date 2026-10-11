"""Tests unitaires et d'intégration du journal HMAC (docs/07 §4.3, A7, A7b).

Vérifie :
1. Ajout séquentiel et intégrité nominale d'une chaîne HMAC ;
2. Détection d'altération à l'index exact pour 6 scénarios d'altération :
   - Altération du payload
   - Altération du code d'événement
   - Altération de l'étape (stage)
   - Altération du run_id
   - Altération de l'horodatage
   - Remplacement de l'empreinte HMAC courante
3. Rejet par triggers SQLite des tentatives de modification (UPDATE) ou suppression (DELETE) ;
4. Rejet des numéros de séquence non monotones ou désordonnés ;
5. Test de la limite du modèle de menace (A7b) : un détenteur de clé PEUT reconstruire une chaîne valide ;
6. Compatibilité avec le protocole ``contracts.Journal`` et ``JournalEvent``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from iot_audit.contracts import Journal, JournalEvent, JournalWriteError
from iot_audit.storage.journal import (
    SQLiteJournal,
    append_hmac_entry,
    ensure_journal_schema,
    load_dev_key,
    rebuild_chain_with_key,
    verify_chain,
    verify_chain_detailed,
)


@pytest.fixture()
def tmp_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    ensure_journal_schema(con)
    yield con
    con.close()


def test_append_and_verify_valid_chain(tmp_db: sqlite3.Connection) -> None:
    for i in range(5):
        current_hmac = append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
        assert isinstance(current_hmac, str) and len(current_hmac) == 64

    ok, bad_idx = verify_chain(tmp_db)
    assert ok is True
    assert bad_idx is None


def test_alteration_is_detected_at_exact_index(tmp_db: sqlite3.Connection) -> None:
    for i in range(5):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    assert verify_chain(tmp_db) == (True, None)

    # contourne les triggers temporairement pour simuler une corruption disque brute
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET payload='{\"i\":999}' WHERE seq=2")

    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 2


def test_alteration_code_detected(tmp_db: sqlite3.Connection) -> None:
    for i in range(4):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"step": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET code='TAMPERED' WHERE seq=1")

    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 1


def test_alteration_stage_detected(tmp_db: sqlite3.Connection) -> None:
    for i in range(3):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET stage='cve' WHERE seq=0")

    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 0


def test_alteration_run_id_detected(tmp_db: sqlite3.Connection) -> None:
    for i in range(4):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET run_id='r2' WHERE seq=3")

    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 3


def test_alteration_occurred_at_detected(tmp_db: sqlite3.Connection) -> None:
    for i in range(3):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET occurred_at='1970-01-01T00:00:00' WHERE seq=2")

    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 2


def test_alteration_hmac_detected(tmp_db: sqlite3.Connection) -> None:
    for i in range(3):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET current_hmac='a'*64 WHERE seq=1")

    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 1


def test_alteration_prev_hmac_or_seq_detected(tmp_db: sqlite3.Connection) -> None:
    # Teste la détection d'une rupture du pointeur prev_hmac et de saut de séquence
    for i in range(3):
        append_hmac_entry(
            tmp_db,
            run_id="r1",
            seq=i,
            stage="infer",
            code="OK",
            payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER IF EXISTS trg_hmac_no_update")

    # Rupture prev_hmac
    tmp_db.execute("UPDATE hmac_chain SET prev_hmac='b'*64 WHERE seq=2")
    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 2

    # Saut de séquence seq (à nouveau DROP TRIGGER car verify_chain recrée les triggers)
    tmp_db.execute("DROP TRIGGER IF EXISTS trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET seq=99 WHERE seq=2")
    ok, bad = verify_chain(tmp_db)
    assert ok is False
    assert bad == 99


def test_delete_is_blocked_by_trigger(tmp_db: sqlite3.Connection) -> None:
    append_hmac_entry(tmp_db, run_id="r1", seq=0, stage="infer", code="OK", payload={})
    with pytest.raises(sqlite3.IntegrityError, match="append-only: deletes forbidden"):
        tmp_db.execute("DELETE FROM hmac_chain WHERE seq=0")


def test_update_is_blocked_by_trigger(tmp_db: sqlite3.Connection) -> None:
    append_hmac_entry(tmp_db, run_id="r1", seq=0, stage="infer", code="OK", payload={"a": 1})
    with pytest.raises(sqlite3.IntegrityError, match="append-only: updates forbidden"):
        tmp_db.execute("UPDATE hmac_chain SET payload='{\"a\":2}' WHERE seq=0")


def test_sequence_must_be_monotone(tmp_db: sqlite3.Connection) -> None:
    append_hmac_entry(tmp_db, run_id="r1", seq=0, stage="infer", code="OK", payload={})
    with pytest.raises(ValueError, match="Non-monotone seq: got 2, expected 1"):
        append_hmac_entry(tmp_db, run_id="r1", seq=2, stage="infer", code="OK", payload={})


def test_hmac_chain_can_be_forged_by_key_holder(tmp_db: sqlite3.Connection) -> None:
    """Démontre que le HMAC seul n'offre AUCUNE non-répudiation (A7b).

    Ce test doit RÉUSSIR : il documente la limite du modèle de menace.
    C'est ce qui justifie l'ajout d'Ed25519 (D11).
    """
    for i in range(4):
        append_hmac_entry(tmp_db, run_id="r1", seq=i, stage="infer", code="OK", payload={"i": i})

    # l'auditeur altère une ligne
    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET payload='{\"i\":999}' WHERE seq=1")

    # sans la clé, verify_chain détecte l'altération
    ok, bad = verify_chain(tmp_db)
    assert ok is False and bad == 1

    # mais avec la clé secrète, l'auditeur peut reconstruire une chaîne parfaitement valide
    forged = rebuild_chain_with_key(tmp_db, key=load_dev_key())
    assert verify_chain(forged) == (True, None)


def test_sqlite_journal_next_seq_is_global_across_runs(tmp_db: sqlite3.Connection) -> None:
    """La séquence est une propriété de la chaîne, pas d'un run.

    Deux runs (ou deux orchestrateurs) partagent la même table : un compteur
    local repartant à zéro casserait la chaîne au second run.
    """
    journal = SQLiteJournal(tmp_db)
    now = datetime.now(UTC)
    assert journal.next_seq() == 0
    journal.append(JournalEvent(run_id="run-a", seq=0, stage="s", code="OK", payload={}, occurred_at=now))
    journal.append(JournalEvent(run_id="run-a", seq=1, stage="s", code="OK", payload={}, occurred_at=now))
    # un second run reprend la même chaîne, sans repartir à zéro
    assert journal.next_seq() == 2
    journal.append(JournalEvent(run_id="run-b", seq=2, stage="s", code="OK", payload={}, occurred_at=now))
    assert verify_chain(tmp_db) == (True, None)


def test_sqlite_journal_implements_protocol(tmp_db: sqlite3.Connection) -> None:
    journal: Journal = SQLiteJournal(tmp_db)
    now = datetime.now(UTC)
    ev = JournalEvent(
        run_id="run-42",
        seq=0,
        stage="infer",
        code="OK",
        payload={"brand": "tp-link", "model": "archer_c7"},
        occurred_at=now,
    )
    sig = journal.append(ev)
    assert isinstance(sig, str) and len(sig) == 64
    assert verify_chain(tmp_db) == (True, None)


# --------------------------------------------------------------------------- #
# E_JOURNAL_WRITE_FAILED : « on ne produit pas de résultat non tracé » (C5)
# --------------------------------------------------------------------------- #

def test_sqlite_error_is_translated_into_journal_write_error(
    tmp_db: sqlite3.Connection,
) -> None:
    """Un driver en panne n'est pas une erreur de driver pour l'appelant.

    C'est un « la trace n'existe pas », donc un « le résultat ne doit pas
    exister non plus ». Le seul moyen de le dire à l'orchestrateur sans lui
    faire importer ``sqlite3`` est de traduire l'erreur ici.
    """
    journal = SQLiteJournal(tmp_db)
    now = datetime.now(UTC)
    tmp_db.close()  # panne du stockage : plus aucune écriture possible

    with pytest.raises(JournalWriteError) as excinfo:
        journal.append(
            JournalEvent(run_id="run-a", seq=0, stage="s", code="OK", payload={},
                         occurred_at=now)
        )

    assert excinfo.value.code.value == "E_JOURNAL_WRITE_FAILED"
    assert "impossible d'écrire le journal" in str(excinfo.value)
    assert "stage='s'" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Diagnostic de rupture : attendu vs calculé (docs/03 §5)
# --------------------------------------------------------------------------- #

def test_verify_chain_detailed_gives_expected_and_computed(
    tmp_db: sqlite3.Connection,
) -> None:
    """Savoir qu'un journal est cassé ne suffit pas : il faut savoir en quoi."""
    for i in range(4):
        append_hmac_entry(
            tmp_db, run_id="r1", seq=i, stage="infer", code="OK", payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    assert verify_chain_detailed(tmp_db) == (True, None, "", "")

    tmp_db.execute("DROP TRIGGER trg_hmac_no_update")
    tmp_db.execute("UPDATE hmac_chain SET payload='{\"i\":999}' WHERE seq=2")

    ok, index, expected, computed = verify_chain_detailed(tmp_db)
    assert ok is False and index == 2
    assert expected and computed
    assert expected != computed
    assert len(expected) == 64 and len(computed) == 64


def test_verify_chain_detailed_reports_a_sequence_gap(tmp_db: sqlite3.Connection) -> None:
    """Une entrée manquante est une rupture : le trou change ce qui a été écrit."""
    for i in range(3):
        append_hmac_entry(
            tmp_db, run_id="r1", seq=i, stage="infer", code="OK", payload={"i": i},
            occurred_at=f"2026-10-06T10:00:0{i}",
        )
    tmp_db.execute("DROP TRIGGER trg_hmac_no_delete")
    tmp_db.execute("DELETE FROM hmac_chain WHERE seq=1")

    ok, index, expected, computed = verify_chain_detailed(tmp_db)
    assert ok is False
    assert index == 2
    assert expected == "seq=1" and computed == "seq=2"
    # le vérificateur public garde exactement le même verdict
    assert verify_chain(tmp_db) == (False, 2)
