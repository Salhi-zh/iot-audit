"""Table ``analysis_runs`` : la provenance d'un run, en base (docs/02 §154/§269).

`docs/02` promet deux choses depuis la rédaction :

> `analysis_runs` porte : `model_revision`, `weights_sha256`, `prompt_sha256`,
> `schema_version`, `vllm_version`, `torch_version`, `nvd_snapshot_sha256`,
> `cpe_dict_version_id`, `sampling_params_json`. **Une contrainte SQL empêche un
> run sans provenance.** (§154)

> Preuve. Test de schéma : `INSERT` sans provenance → rejet. (§156)

La table n'existait dans **aucun** schéma du dépôt : `iot_audit/vuln/schema.sql`
porte quatre tables, toutes côté CVE, et `iot_audit/corpus/schema.sql` sept tables
de mesure. Le document promettait donc une garantie que rien ne tenait. Ce module
la tient — et il la tient **au même endroit que le scellement**, pas dans un
formulaire : `record_analysis_run` refuse d'écrire un run dont la provenance
serait incomplète, avec le **même** verdict que `seal.sign_report`, appelé par le
même prédicat (`preflight.missing_provenance_fields`). Deux jeux de règles pour
la même garantie finiraient par diverger, et c'est le plus permissif qui
gagnerait en silence.

Contraintes portées par le schéma, et pas seulement par le code :

* toutes les colonnes de provenance sont ``NOT NULL`` et non vides
  (``CHECK (length(...) > 0)``) — une chaîne vide n'est pas une empreinte ;
* `cpe_dict_version_id > 0` : `0` est ce que rend une base absente, donc un aveu,
  pas une version ;
* `sampling_params_json` doit être du JSON **objet** (``json_valid`` +
  ``json_type = 'object'``). Un `temperature` recopié en texte libre n'est pas un
  paramètre d'échantillonnage rejouable.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from iot_audit.contracts import Provenance
from iot_audit.pipeline.preflight import missing_provenance_fields
from iot_audit.storage.seal import ProvenanceIncompleteError

__all__ = [
    "ANALYSIS_RUNS_SCHEMA",
    "analysis_run_row",
    "ensure_analysis_runs_schema",
    "record_analysis_run",
]

#: Les colonnes de provenance sont celles de `docs/02` §154 et §269, dans le même
#: ordre que le contrat `Provenance` — pour qu'une lecture côte à côte du code et
#: du document ne demande pas de traduction.
ANALYSIS_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    model_revision TEXT NOT NULL CHECK (length(trim(model_revision)) > 0),
    weights_sha256 TEXT NOT NULL CHECK (length(weights_sha256) = 64),
    prompt_sha256 TEXT NOT NULL CHECK (length(prompt_sha256) = 64),
    schema_version TEXT NOT NULL CHECK (length(trim(schema_version)) > 0),
    vllm_version TEXT NOT NULL CHECK (length(trim(vllm_version)) > 0),
    torch_version TEXT NOT NULL CHECK (length(trim(torch_version)) > 0),
    nvd_snapshot_sha256 TEXT NOT NULL CHECK (length(nvd_snapshot_sha256) = 64),
    cpe_dict_version_id INTEGER NOT NULL CHECK (cpe_dict_version_id > 0),
    sampling_params_json TEXT NOT NULL
        CHECK (json_valid(sampling_params_json) AND json_type(sampling_params_json) = 'object'),
    nodes_used TEXT NOT NULL CHECK (length(trim(nodes_used)) > 0),
    triage_scope TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    chain_head_hmac TEXT
);

CREATE INDEX IF NOT EXISTS ix_analysis_runs_started ON analysis_runs (started_at);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_revision ON analysis_runs (model_revision);
"""


def ensure_analysis_runs_schema(con: sqlite3.Connection) -> None:
    """Crée ``analysis_runs`` si elle n'existe pas (idempotent)."""
    con.executescript(ANALYSIS_RUNS_SCHEMA)


def record_analysis_run(
    con: sqlite3.Connection,
    *,
    run_id: str,
    provenance: Provenance,
    triage_scope: str | None = None,
    chain_head_hmac: str | None = None,
    recorded_at: datetime | None = None,
) -> None:
    """Écrit la ligne de provenance d'un run, ou refuse.

    Le refus est **le même** que celui du scellement :
    :class:`~iot_audit.storage.seal.ProvenanceIncompleteError`, portant la liste
    des champs manquants. Écrire la ligne quand même, avec des blancs, rendrait
    la contrainte de `docs/02` §154 décorative — et pire, rendrait un run
    irréproductible *indiscernable* d'un run reproductible.

    ``chain_head_hmac`` reste nul à l'écriture : la ligne est enregistrée à
    l'ouverture du run, la tête de chaîne n'existe qu'au scellement. Le lier ici
    obligerait à écrire après coup dans une table de provenance, et une
    provenance réécrite n'est plus une provenance.
    """
    missing = missing_provenance_fields(provenance)
    if missing:
        raise ProvenanceIncompleteError(missing)

    con.execute(
        """
        INSERT INTO analysis_runs (
            run_id, model_revision, weights_sha256, prompt_sha256, schema_version,
            vllm_version, torch_version, nvd_snapshot_sha256, cpe_dict_version_id,
            sampling_params_json, nodes_used, triage_scope, started_at, finished_at,
            recorded_at, chain_head_hmac
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            provenance.model_revision,
            provenance.weights_sha256,
            provenance.prompt_sha256,
            provenance.schema_version,
            provenance.vllm_version,
            provenance.torch_version,
            provenance.nvd_snapshot_sha256,
            provenance.cpe_dict_version_id,
            json.dumps(dict(provenance.sampling_params), sort_keys=True),
            ",".join(provenance.nodes_used),
            triage_scope,
            provenance.started_at.isoformat(),
            provenance.finished_at.isoformat(),
            (recorded_at or datetime.now(UTC)).isoformat(timespec="seconds"),
            chain_head_hmac,
        ),
    )
    con.commit()


def analysis_run_row(con: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    """Relit la provenance d'un run, telle qu'elle a été enregistrée.

    Rend ``None`` si le run n'a pas de ligne : un rapport peut exister sans
    ligne (runs d'avant cette table), et le dire vaut mieux que rendre un
    dictionnaire vide qui se lirait comme un run sans provenance.
    """
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["sampling_params"] = json.loads(out.pop("sampling_params_json"))
    return out
