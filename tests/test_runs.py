"""Tests de la table `analysis_runs` (docs/02 §154/§269 et sa preuve du §156).

docs/02 promet : « une contrainte SQL empêche un run sans provenance » et
« test de schéma : `INSERT` sans provenance → rejet ». Ces tests sont cette
preuve, et ils vérifient la garantie **aux deux niveaux** où elle peut se perdre :
le prédicat Python (`record_analysis_run` refuse) *et* la contrainte SQL (un
`INSERT` direct qui contournerait le module se fait refuser par la base).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from iot_audit.contracts import Provenance
from iot_audit.storage.runs import (
    analysis_run_row,
    ensure_analysis_runs_schema,
    record_analysis_run,
)
from iot_audit.storage.seal import ProvenanceIncompleteError

_START = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _prov(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "model_revision": "85acc985866e9240a9f9334e19903fbc7a2b7944",
        "weights_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "schema_version": "v6",
        "vllm_version": "0.29.0",
        "torch_version": "2.9.0",
        "nvd_snapshot_sha256": "c" * 64,
        "cpe_dict_version_id": 1,
        "sampling_params": {"temperature": 0.0, "seed": 1234, "max_tokens": 640},
        "nodes_used": ("zabeth21",),
        "started_at": _START,
        "finished_at": _START + timedelta(minutes=3),
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    ensure_analysis_runs_schema(con)
    return con


def test_schema_creation_is_idempotent() -> None:
    con = _con()
    ensure_analysis_runs_schema(con)
    ensure_analysis_runs_schema(con)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "analysis_runs" in tables


def test_a_complete_provenance_is_recorded_and_read_back() -> None:
    con = _con()
    record_analysis_run(con, run_id="r1", provenance=_prov(), triage_scope="triage-only")

    row = analysis_run_row(con, "r1")
    assert row is not None
    assert row["model_revision"] == "85acc985866e9240a9f9334e19903fbc7a2b7944"
    assert row["triage_scope"] == "triage-only"
    assert row["sampling_params"] == {"max_tokens": 640, "seed": 1234, "temperature": 0.0}
    assert row["nodes_used"] == "zabeth21"
    # La tête de chaîne n'existe qu'au scellement : elle reste nulle ici.
    assert row["chain_head_hmac"] is None


def test_a_run_without_a_row_reads_back_as_none_not_as_empty() -> None:
    """Un dictionnaire vide se lirait comme « run sans provenance »."""
    assert analysis_run_row(_con(), "jamais-ecrit") is None


@pytest.mark.parametrize(
    "missing_field",
    ["model_revision", "weights_sha256", "prompt_sha256", "vllm_version",
     "torch_version", "nvd_snapshot_sha256", "schema_version"],
)
def test_an_incomplete_provenance_is_refused_by_the_module(missing_field: str) -> None:
    """docs/02 §156 : le rejet est par champ, et il nomme le champ."""
    con = _con()
    with pytest.raises(ProvenanceIncompleteError) as exc:
        record_analysis_run(con, run_id="r2", provenance=_prov(**{missing_field: ""}))
    assert missing_field in exc.value.missing
    assert con.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 0


def test_a_run_without_nodes_or_sampling_is_refused() -> None:
    """Deux champs que le contrat protège sans les type « chaîne »."""
    con = _con()
    with pytest.raises(ProvenanceIncompleteError) as exc:
        record_analysis_run(con, run_id="r3", provenance=_prov(nodes_used=()))
    assert "nodes_used" in exc.value.missing

    with pytest.raises(ProvenanceIncompleteError) as exc:
        record_analysis_run(con, run_id="r4", provenance=_prov(sampling_params={}))
    assert "sampling_params" in exc.value.missing


def test_cpe_version_zero_is_a_hole_not_a_version() -> None:
    """`0` est ce que rend une base absente : c'est un aveu, pas une version."""
    con = _con()
    with pytest.raises(ProvenanceIncompleteError) as exc:
        record_analysis_run(con, run_id="r5", provenance=_prov(cpe_dict_version_id=0))
    assert "cpe_dict_version_id" in exc.value.missing


def test_the_sql_constraint_holds_against_a_direct_insert() -> None:
    """La garantie ne doit pas dépendre du module Python qui l'applique.

    Un `INSERT` écrit à la main, dans une autre partie du système ou dans une
    session `sqlite3` de dépannage, doit se faire refuser **par la base**. C'est
    ce que docs/02 §154 appelle « une contrainte SQL », et sans ce test le
    document ne serait tenu que par du code qu'on peut contourner.
    """
    con = _con()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO analysis_runs (run_id, model_revision, weights_sha256,"
            " prompt_sha256, schema_version, vllm_version, torch_version,"
            " nvd_snapshot_sha256, cpe_dict_version_id, sampling_params_json,"
            " nodes_used, started_at, finished_at, recorded_at)"
            " VALUES ('r6', '', 'a', 'b', 'v6', '0.29.0', '2.9.0', 'c', 1,"
            " '{}', 'zabeth21', '2026-10-06T09:00:00+00:00',"
            " '2026-10-06T09:03:00+00:00', '2026-10-06T09:03:00+00:00')"
        )


def test_the_sql_constraint_rejects_a_truncated_fingerprint() -> None:
    """Une empreinte tronquée a l'apparence d'une empreinte : 64 caractères, pas moins."""
    con = _con()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO analysis_runs (run_id, model_revision, weights_sha256,"
            " prompt_sha256, schema_version, vllm_version, torch_version,"
            " nvd_snapshot_sha256, cpe_dict_version_id, sampling_params_json,"
            " nodes_used, started_at, finished_at, recorded_at)"
            " VALUES ('r7', 'rev', 'a' || 'a', 'b', 'v6', '0.29.0', '2.9.0', 'c', 1,"
            " '{}', 'zabeth21', '2026-10-06T09:00:00+00:00',"
            " '2026-10-06T09:03:00+00:00', '2026-10-06T09:03:00+00:00')"
        )


def test_the_sql_constraint_rejects_non_object_sampling_params() -> None:
    """Un `temperature` en texte libre n'est pas un paramètre rejouable."""
    con = _con()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO analysis_runs (run_id, model_revision, weights_sha256,"
            " prompt_sha256, schema_version, vllm_version, torch_version,"
            " nvd_snapshot_sha256, cpe_dict_version_id, sampling_params_json,"
            " nodes_used, started_at, finished_at, recorded_at)"
            " VALUES ('r8', 'rev', 'a', 'b', 'v6', '0.29.0', '2.9.0', 'c', 1,"
            " '\"temperature 0\"', 'zabeth21', '2026-10-06T09:00:00+00:00',"
            " '2026-10-06T09:03:00+00:00', '2026-10-06T09:03:00+00:00')"
        )


def test_sampling_params_are_stored_as_sorted_json() -> None:
    """Relire la ligne doit redonner le même objet, indépendamment de l'ordre."""
    con = _con()
    record_analysis_run(con, run_id="r9", provenance=_prov())
    raw = con.execute(
        "SELECT sampling_params_json FROM analysis_runs WHERE run_id='r9'"
    ).fetchone()[0]
    assert raw == json.dumps({"temperature": 0.0, "seed": 1234, "max_tokens": 640},
                             sort_keys=True)
