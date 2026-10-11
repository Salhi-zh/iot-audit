"""Journal scellé HMAC-SHA256 (docs/03 §2, docs/07 §4.3, D11/D14).

Principes fondamentaux :
1. **Append-only applicatif** : Triggers SQLite interdisant UPDATE et DELETE
   sur la table ``hmac_chain``.
2. **Chaînage séquentiel** : H_k = HMAC_SHA256(key, H_{k-1} || payload_canonical).
   Pour k=0, H_{-1} est le genesis hash (64 zéros).
3. **Détection d'altération** : ``verify_chain`` identifie la première entrée
   altérée ou corrompue et retourne ``(False, bad_seq)``.
4. **Limite documentée du modèle de menace (A7b)** :
   Le HMAC étant symétrique, tout détenteur de la clé secrète PEUT reconstruire
   une chaîne valide. Cette propriété est démontrée par les tests et motive
   l'adjonction d'Ed25519 (D11).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from iot_audit.contracts import ErrorCode, JournalEvent, JournalWriteError

__all__ = [
    "DEFAULT_DEV_KEY",
    "GENESIS_HMAC",
    "append_hmac_entry",
    "compute_event_hmac",
    "ensure_journal_schema",
    "load_dev_key",
    "rebuild_chain_with_key",
    "serialize_payload",
    "verify_chain",
    "verify_chain_detailed",
]

DEFAULT_DEV_KEY = b"iot-audit-journal-dev-key-32b-secret!"
GENESIS_HMAC = "0" * 64

JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS hmac_chain (
    seq INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    code TEXT NOT NULL,
    payload TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    prev_hmac TEXT NOT NULL,
    current_hmac TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_hmac_no_update
BEFORE UPDATE ON hmac_chain
BEGIN
    SELECT RAISE(ABORT, 'hmac_chain is append-only: updates forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_hmac_no_delete
BEFORE DELETE ON hmac_chain
BEGIN
    SELECT RAISE(ABORT, 'hmac_chain is append-only: deletes forbidden');
END;
"""


def load_dev_key() -> bytes:
    """Clé de développement par défaut pour les tests et simulations locales."""
    return DEFAULT_DEV_KEY


def ensure_journal_schema(con: sqlite3.Connection) -> None:
    """Crée la table ``hmac_chain`` et ses triggers d'immutabilité."""
    con.executescript(JOURNAL_SCHEMA)


def serialize_payload(payload: Mapping[str, Any] | str) -> str:
    """Sérialisation canonique et déterministe pour HMAC."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_event_hmac(
    key: bytes,
    prev_hmac: str,
    seq: int,
    run_id: str,
    stage: str,
    code: str,
    payload_str: str,
    occurred_at: str,
) -> str:
    """Calcule le HMAC-SHA256 d'une entrée journal."""
    canonical_bytes = f"{prev_hmac}|{seq}|{run_id}|{stage}|{code}|{payload_str}|{occurred_at}".encode()
    return hmac.new(key, canonical_bytes, hashlib.sha256).hexdigest()


def append_hmac_entry(
    con: sqlite3.Connection,
    *,
    run_id: str,
    seq: int,
    stage: str,
    code: str,
    payload: Mapping[str, Any] | str,
    occurred_at: str | datetime | None = None,
    key: bytes = DEFAULT_DEV_KEY,
) -> str:
    """Ajoute une entrée chaînée dans ``hmac_chain`` et renvoie son HMAC courant."""
    ensure_journal_schema(con)

    if occurred_at is None:
        # Repli de développement uniquement : la chaîne, elle, reçoit toujours
        # l'horloge injectée par l'orchestrateur (C4). L'horodatage reste
        # **aware** — un mélange naïf/aware dans la même chaîne produirait un
        # ordre illisible pour un vérificateur tiers.
        occurred_at_str = datetime.now(UTC).isoformat()
    elif isinstance(occurred_at, datetime):
        occurred_at_str = occurred_at.isoformat()
    else:
        occurred_at_str = str(occurred_at)

    payload_str = serialize_payload(payload)

    row = con.execute(
        "SELECT seq, current_hmac FROM hmac_chain ORDER BY seq DESC LIMIT 1"
    ).fetchone()

    if row is None:
        expected_seq = 0
        prev_hmac = GENESIS_HMAC
    else:
        last_seq, prev_hmac = row[0], row[1]
        expected_seq = last_seq + 1

    if seq != expected_seq:
        raise ValueError(
            f"Non-monotone seq: got {seq}, expected {expected_seq}"
        )

    current_hmac = compute_event_hmac(
        key=key,
        prev_hmac=prev_hmac,
        seq=seq,
        run_id=run_id,
        stage=stage,
        code=code,
        payload_str=payload_str,
        occurred_at=occurred_at_str,
    )

    con.execute(
        """
        INSERT INTO hmac_chain
        (seq, run_id, stage, code, payload, occurred_at, prev_hmac, current_hmac)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (seq, run_id, stage, code, payload_str, occurred_at_str, prev_hmac, current_hmac),
    )
    con.commit()
    return current_hmac


def verify_chain_detailed(
    con: sqlite3.Connection,
    key: bytes = DEFAULT_DEV_KEY,
) -> tuple[bool, int | None, str, str]:
    """Vérifie la chaîne **et** rend le diagnostic de la première rupture.

    Renvoie ``(ok, index, expected, computed)``. ``verify_chain`` n'a que faire
    du diagnostic ; l'export scellé, lui, en a besoin : la taxonomie D14 exige
    que ``E_HMAC_CHAIN_BROKEN`` trace ``break_index``, ``expected`` et
    ``computed``, sinon on sait qu'un journal est cassé sans savoir *en quoi*.

    ``expected`` / ``computed`` désignent selon le cas :

    * index de séquence non monotone   -> le numéro attendu / lu ;
    * maillon de chaîne rompu          -> le HMAC précédent attendu / lu ;
    * HMAC recalculé différent du stocké -> le HMAC stocké / recalculé.

    Un seul calcul est fait ici, et ``verify_chain`` s'y appuie : deux
    vérificateurs qui divergeraient donneraient deux vérités sur la même
    preuve.
    """
    ensure_journal_schema(con)
    rows = con.execute(
        """
        SELECT seq, run_id, stage, code, payload, occurred_at, prev_hmac, current_hmac
        FROM hmac_chain ORDER BY seq ASC
        """
    ).fetchall()

    expected_prev = GENESIS_HMAC
    for expected_seq, (
        seq,
        run_id,
        stage,
        code,
        payload_str,
        occurred_at_str,
        prev_hmac,
        stored_hmac,
    ) in enumerate(rows):
        if seq != expected_seq:
            return False, seq, f"seq={expected_seq}", f"seq={seq}"
        if prev_hmac != expected_prev:
            return False, seq, expected_prev, str(prev_hmac)

        computed = compute_event_hmac(
            key=key,
            prev_hmac=prev_hmac,
            seq=seq,
            run_id=run_id,
            stage=stage,
            code=code,
            payload_str=payload_str,
            occurred_at=occurred_at_str,
        )
        if not hmac.compare_digest(stored_hmac, computed):
            return False, seq, str(stored_hmac), computed

        expected_prev = stored_hmac

    return True, None, "", ""


def verify_chain(
    con: sqlite3.Connection,
    key: bytes = DEFAULT_DEV_KEY,
) -> tuple[bool, int | None]:
    """Vérifie l'intégrité de la chaîne HMAC.

    Renvoie:
      ``(True, None)`` si la chaîne est entièrement intègre.
      ``(False, seq)`` où ``seq`` est l'index de la première entrée altérée.
    """
    ok, index, _expected, _computed = verify_chain_detailed(con, key)
    return ok, index


def rebuild_chain_with_key(
    con: sqlite3.Connection,
    key: bytes = DEFAULT_DEV_KEY,
) -> sqlite3.Connection:
    """Reconstruit une chaîne HMAC valide pour démontrer la limite du HMAC (A7b).

    Tout détenteur de la clé secrète PEUT forger une chaîne valide après altération.
    C'est pourquoi la chaîne doit être complétée par une signature asymétrique
    Ed25519 lors de l'export (D11).
    """
    rows = con.execute(
        """
        SELECT seq, run_id, stage, code, payload, occurred_at
        FROM hmac_chain ORDER BY seq ASC
        """
    ).fetchall()

    new_con = sqlite3.connect(":memory:")
    ensure_journal_schema(new_con)

    for seq, run_id, stage, code, payload_str, occurred_at_str in rows:
        append_hmac_entry(
            new_con,
            run_id=run_id,
            seq=seq,
            stage=stage,
            code=code,
            payload=payload_str,
            occurred_at=occurred_at_str,
            key=key,
        )

    return new_con


class SQLiteJournal:
    """Implémentation concrète du protocole contracts.Journal."""

    def __init__(self, con: sqlite3.Connection, key: bytes = DEFAULT_DEV_KEY) -> None:
        self.con = con
        self.key = key
        ensure_journal_schema(self.con)

    def next_seq(self) -> int:
        """Prochain index de séquence **global** de la chaîne.

        La séquence est une propriété de la chaîne, pas d'un run : plusieurs
        runs (ou plusieurs orchestrateurs) partagent la même table et la
        monotonicité est vérifiée à l'écriture. Un compteur local repartirait
        à zéro et casserait la chaîne — c'est cet accès unique qui rend la
        question impossible.
        """
        row = self.con.execute(
            "SELECT MAX(seq) FROM hmac_chain"
        ).fetchone()
        return 0 if row is None or row[0] is None else int(row[0]) + 1

    def append(self, event: JournalEvent) -> str:
        """Écrit une entrée, ou fait échouer le run (C5, ``E_JOURNAL_WRITE_FAILED``).

        Un ``sqlite3.Error`` (disque plein, base verrouillée, fichier effacé
        sous nos pieds) ne doit pas remonter à l'appelant comme une erreur de
        driver : il signifie que la trace n'existe pas, donc que le résultat ne
        doit pas exister non plus. Il est traduit en ``JournalWriteError``,
        seule forme que l'orchestrateur a besoin de connaître.
        """
        try:
            return append_hmac_entry(
                self.con,
                run_id=event.run_id,
                seq=event.seq,
                stage=event.stage,
                code=event.code,
                payload=event.payload,
                occurred_at=event.occurred_at,
                key=self.key,
            )
        except sqlite3.Error as exc:
            raise JournalWriteError(
                f"{ErrorCode.E_JOURNAL_WRITE_FAILED.value}: "
                f"impossible d'écrire le journal (stage={event.stage!r}, seq={event.seq}): {exc}"
            ) from exc
