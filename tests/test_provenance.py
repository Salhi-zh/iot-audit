"""Tests du producteur de provenance (docs/02 §154/§269, docs/03 §2, ENF5).

`Provenance` était déclaré, vérifié, refusé — et jamais **construit** : le refus
`E_PROVENANCE_INCOMPLETE` ne pouvait donc se déclencher que sur un objet fabriqué
à la main pour un test. `pipeline.provenance` est ce producteur manquant.

Ce que ces tests tiennent :

* les deux définitions d'empreinte sont **reproductibles à la main** (elles sont
  recalculées ici indépendamment du code) ;
* les poids du nœud sont **recalculés depuis ses empreintes par fichier**, et le
  résultat doit être celui que le nœud publie — c'est le contrôle qui empêche la
  définition de la station et celle du script de nœud de diverger en silence ;
* un champ non mesuré reste **vide** : il devient « manquant » pour le pré-vol,
  donc un refus de scellement, et jamais une valeur plausible ;
* la lecture du JSON du nœud rend `{}` (un trou) quand elle échoue, jamais un
  dictionnaire partiel complaisant.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from iot_audit.pipeline.preflight import missing_provenance_fields
from iot_audit.pipeline.provenance import (
    aggregate_weights_sha256,
    build_provenance,
    cpe_dict_version_id,
    load_node_provenance,
    nvd_snapshot_sha256,
)

#: Capture **réelle** du nœud zabeth21 (`~/vllm-env/provenance.json`,
#: 2026-10-06T15:10:48+02:00), telle que l'a écrite
#: `infra/scripts/node_write_provenance.sh`. Elle n'est pas décorative : c'est
#: l'artefact sur lequel l'agrégat des poids est vérifié ci-dessous.
FIXTURE = Path(__file__).parent / "fixtures" / "zabeth21-provenance-2026-10-06.json"


def _node_json() -> dict[str, object]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _nvd_db(path: Path, rows: list[tuple[str, str]]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE feed_versions (feed_name TEXT, sha256 TEXT)")
    con.executemany("INSERT INTO feed_versions VALUES (?, ?)", rows)
    con.commit()
    con.close()
    return path


def _cpe_db(path: Path, version_id: int | None) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE dictionary_versions (id INTEGER, source TEXT)")
    if version_id is not None:
        con.execute("INSERT INTO dictionary_versions VALUES (?, 'nvd')", (version_id,))
    con.commit()
    con.close()
    return path


def _station(tmp_path: Path) -> dict[str, object]:
    """Les entrées qui viennent de la station, pas du nœud."""
    return {
        "prompt_text": "TRIAGE PROMPT",
        "nvd_db": _nvd_db(tmp_path / "nvd.sqlite", [("nvdcve-2.0-2021.json.gz", "d" * 64)]),
        "cpe_db": _cpe_db(tmp_path / "cpe.sqlite", 3),
        "sampling_params": {"temperature": 0.0, "seed": 1234},
        "nodes_used": ("zabeth21",),
        "started_at": datetime(2026, 10, 6, 15, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 10, 6, 15, 10, tzinfo=UTC),
        "schema_version": "v6",
    }


# --------------------------------------------------------------------------- #
# Définition de l'agrégat des poids
# --------------------------------------------------------------------------- #


def test_aggregate_weights_sha256_est_la_definition_ecrite() -> None:
    files = {"b.safetensors": "b" * 64, "a.safetensors": "a" * 64}
    attendu = hashlib.sha256(
        f"{'a' * 64}  a.safetensors\n{'b' * 64}  b.safetensors\n".encode()
    ).hexdigest()
    assert aggregate_weights_sha256(files) == attendu


def test_aggregate_est_independant_de_l_ordre_du_dictionnaire() -> None:
    a = {"m-00002.safetensors": "2" * 64, "m-00001.safetensors": "1" * 64}
    b = {"m-00001.safetensors": "1" * 64, "m-00002.safetensors": "2" * 64}
    assert aggregate_weights_sha256(a) == aggregate_weights_sha256(b)


@pytest.mark.parametrize(
    "digest",
    ["", "non", "NON FAIT", "a" * 63, "a" * 65, "z" * 64, "/home/x/modele.safetensors"],
)
def test_aggregate_refuse_une_empreinte_qui_n_en_est_pas_une(digest: str) -> None:
    with pytest.raises(ValueError):
        aggregate_weights_sha256({"m.safetensors": digest})


def test_aggregate_refuse_un_ensemble_vide() -> None:
    with pytest.raises(ValueError):
        aggregate_weights_sha256({})


def test_l_agregat_du_noeud_est_recalculable_depuis_ses_empreintes_par_fichier() -> None:
    """L'invariant qui relie les deux moitiés du producteur.

    Le script de nœud et ce module calculent la même empreinte, dans deux
    langages différents. Si l'un des deux change de définition (ordre, nombre
    d'espaces, nom de fichier inclus ou non), ce test échoue — et c'est le seul
    endroit où la divergence serait visible avant de sceller un rapport.
    """
    node = _node_json()
    per_file = node["weights_files"]
    assert isinstance(per_file, dict)
    assert aggregate_weights_sha256(per_file) == node["weights_sha256"]  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Empreinte du snapshot NVD
# --------------------------------------------------------------------------- #


def test_nvd_empreinte_vide_quand_la_base_est_absente(tmp_path: Path) -> None:
    assert nvd_snapshot_sha256(tmp_path / "absent.sqlite") == ""


def test_nvd_empreinte_vide_quand_la_table_est_absente(tmp_path: Path) -> None:
    path = tmp_path / "nvd.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE autre (x TEXT)")
    con.commit()
    con.close()
    assert nvd_snapshot_sha256(path) == ""


def test_nvd_empreinte_vide_quand_la_table_est_vide(tmp_path: Path) -> None:
    assert nvd_snapshot_sha256(_nvd_db(tmp_path / "nvd.sqlite", [])) == ""


def test_nvd_empreinte_est_le_sha256_des_flux_tries(tmp_path: Path) -> None:
    path = _nvd_db(
        tmp_path / "nvd.sqlite",
        [("nvdcve-2.0-2022.json.gz", "e" * 64), ("nvdcve-2.0-2021.json.gz", "d" * 64)],
    )
    attendu = hashlib.sha256(
        f"{'nvdcve-2.0-2021.json.gz'}  {'d' * 64}\n{'nvdcve-2.0-2022.json.gz'}  {'e' * 64}\n".encode()
    ).hexdigest()
    assert nvd_snapshot_sha256(path) == attendu


def test_nvd_empreinte_ignore_les_lignes_sans_empreinte_valide(tmp_path: Path) -> None:
    """Une ligne dont l'empreinte n'en est pas une ne doit pas entrer dans le calcul."""
    path = _nvd_db(
        tmp_path / "nvd.sqlite",
        [("nvdcve-2.0-2021.json.gz", "d" * 64), ("archive-maison.json.gz", "inconnu")],
    )
    assert nvd_snapshot_sha256(path) == nvd_snapshot_sha256(
        _nvd_db(tmp_path / "propre.sqlite", [("nvdcve-2.0-2021.json.gz", "d" * 64)])
    )


# --------------------------------------------------------------------------- #
# Version du dictionnaire CPE
# --------------------------------------------------------------------------- #


def test_cpe_version_zero_quand_la_base_est_absente(tmp_path: Path) -> None:
    assert cpe_dict_version_id(tmp_path / "absent.sqlite") == 0


def test_cpe_version_zero_quand_la_table_est_absente(tmp_path: Path) -> None:
    path = tmp_path / "cpe.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE autre (x TEXT)")
    con.commit()
    con.close()
    assert cpe_dict_version_id(path) == 0


def test_cpe_version_zero_quand_la_table_est_vide(tmp_path: Path) -> None:
    assert cpe_dict_version_id(_cpe_db(tmp_path / "cpe.sqlite", None)) == 0


def test_cpe_version_est_le_maximum(tmp_path: Path) -> None:
    path = tmp_path / "cpe.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE dictionary_versions (id INTEGER, source TEXT)")
    con.executemany(
        "INSERT INTO dictionary_versions VALUES (?, 'nvd')", [(1,), (7,), (4,)]
    )
    con.commit()
    con.close()
    assert cpe_dict_version_id(path) == 7


# --------------------------------------------------------------------------- #
# Assemblage
# --------------------------------------------------------------------------- #


def test_build_provenance_sur_l_artefact_reel_ne_laisse_rien_manquant(tmp_path: Path) -> None:
    """D1-a : la révision du nœud est établie, donc le scellement n'est pas refusé."""
    prov = build_provenance(_node_json(), **_station(tmp_path))  # type: ignore[arg-type]
    assert missing_provenance_fields(prov) == ()
    assert prov.model_revision == "85acc985866e9240a9f9334e19903fbc7a2b7944"
    assert prov.weights_sha256 == "663eb1924045c67fae4342d3cafebed8d18355dd6c0d29aaeab79b4599da7813"
    assert prov.vllm_version == "0.29.0"
    assert prov.torch_version == "2.13.0+cu132"
    assert prov.nodes_used == ("zabeth21",)
    assert prov.sampling_params == {"temperature": 0.0, "seed": 1234}


def test_build_provenance_n_invente_ni_revision_ni_poids(tmp_path: Path) -> None:
    """Un JSON de nœud vide est un trou, pas un run en règle."""
    prov = build_provenance({}, **_station(tmp_path))  # type: ignore[arg-type]
    manquants = missing_provenance_fields(prov)
    assert "model_revision" in manquants
    assert "weights_sha256" in manquants
    assert "vllm_version" in manquants
    assert "torch_version" in manquants
    assert prov.model_revision == ""
    assert prov.weights_sha256 == ""


def test_build_provenance_traite_non_fait_comme_un_trou(tmp_path: Path) -> None:
    node = _node_json()
    node["model_revision"] = "NON FAIT"
    node["weights_files"] = {}
    node["weights_sha256"] = "NON FAIT"
    prov = build_provenance(node, **_station(tmp_path))  # type: ignore[arg-type]
    assert prov.model_revision == ""
    assert prov.weights_sha256 == ""
    assert "model_revision" in missing_provenance_fields(prov)


def test_build_provenance_retombe_sur_l_agregat_du_noeud_si_les_fichiers_sont_illisibles(
    tmp_path: Path,
) -> None:
    node = _node_json()
    node["weights_files"] = {"model-00001-of-00002.safetensors": "tronque"}
    prov = build_provenance(node, **_station(tmp_path))  # type: ignore[arg-type]
    assert prov.weights_sha256 == node["weights_sha256"]


def test_build_provenance_empreinte_le_prompt_reellement_envoye(tmp_path: Path) -> None:
    entree = _station(tmp_path)
    entree["prompt_text"] = "le prompt envoyé"
    prov = build_provenance(_node_json(), **entree)  # type: ignore[arg-type]
    assert prov.prompt_sha256 == hashlib.sha256(
        "le prompt envoyé".encode()
    ).hexdigest()


def test_build_provenance_prompt_vide_est_un_trou(tmp_path: Path) -> None:
    entree = _station(tmp_path)
    entree["prompt_text"] = ""
    prov = build_provenance(_node_json(), **entree)  # type: ignore[arg-type]
    assert prov.prompt_sha256 == ""
    assert "prompt_sha256" in missing_provenance_fields(prov)


def test_build_provenance_sans_base_nvd_ni_cpe_laisse_les_champs_vides(tmp_path: Path) -> None:
    entree = _station(tmp_path)
    entree["nvd_db"] = tmp_path / "absent-nvd.sqlite"
    entree["cpe_db"] = tmp_path / "absent-cpe.sqlite"
    prov = build_provenance(_node_json(), **entree)  # type: ignore[arg-type]
    manquants = missing_provenance_fields(prov)
    assert "nvd_snapshot_sha256" in manquants
    assert prov.cpe_dict_version_id == 0
    assert "cpe_dict_version_id" in manquants


# --------------------------------------------------------------------------- #
# Lecture du JSON du nœud
# --------------------------------------------------------------------------- #


def test_load_node_provenance_lit_un_fichier_local(tmp_path: Path) -> None:
    path = tmp_path / "provenance.json"
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_node_provenance(path)["model_revision"] == (
        "85acc985866e9240a9f9334e19903fbc7a2b7944"
    )


def test_load_node_provenance_absent_rend_un_dictionnaire_vide(tmp_path: Path) -> None:
    assert load_node_provenance(tmp_path / "absent.json") == {}


def test_load_node_provenance_json_invalide_rend_un_dictionnaire_vide(tmp_path: Path) -> None:
    path = tmp_path / "provenance.json"
    path.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    assert load_node_provenance(path) == {}


def test_load_node_provenance_json_non_objet_rend_un_dictionnaire_vide(tmp_path: Path) -> None:
    path = tmp_path / "provenance.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_node_provenance(path) == {}


def _faux_ssh(tmp_path: Path, *, sortie: str, code: int) -> Path:
    """Un `ssh` de laboratoire : il ignore ses arguments et rend la sortie voulue."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ssh"
    script.write_text(
        f"#!/bin/sh\ncat <<'FIN'\n{sortie}\nFIN\nexit {code}\n", encoding="utf-8"
    )
    script.chmod(0o755)
    return bin_dir


def test_load_node_provenance_via_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = _faux_ssh(
        tmp_path, sortie=FIXTURE.read_text(encoding="utf-8"), code=0
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert load_node_provenance("ssh:zabeth21")["hostname"] == "zabeth21"


def test_load_node_provenance_ssh_en_echec_rend_un_dictionnaire_vide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un nœud muet doit produire un refus de scellement, pas un run plausible."""
    bin_dir = _faux_ssh(tmp_path, sortie="", code=255)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert load_node_provenance("ssh:zabeth21") == {}


def test_load_node_provenance_sans_hote_rend_un_dictionnaire_vide() -> None:
    assert load_node_provenance("ssh:") == {}


def test_load_node_provenance_ssh_non_lancable_rend_un_dictionnaire_vide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un `ssh` absent de la machine ne doit pas lever : c'est un trou, pas un plantage."""
    import iot_audit.pipeline.provenance as prov

    def _boom(*args: object, **kwargs: object) -> object:
        raise OSError("ssh introuvable")

    monkeypatch.setattr(prov.subprocess, "run", _boom)
    assert load_node_provenance("ssh:zabeth21") == {}


def test_load_node_provenance_fichier_illisible_rend_un_dictionnaire_vide(
    tmp_path: Path,
) -> None:
    """Fichier présent mais non lisible (droits) : `{}` plutôt qu'une exception."""
    path = tmp_path / "provenance.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o000)
    try:
        if os.access(path, os.R_OK):  # compte privilégié : le test ne peut rien prouver
            pytest.skip("lecture possible malgré les droits (compte privilégié)")
        assert load_node_provenance(path) == {}
    finally:
        path.chmod(0o644)


def test_nvd_empreinte_vide_si_le_fichier_n_est_pas_une_base(tmp_path: Path) -> None:
    """Un fichier qui n'est pas du SQLite est un trou de provenance, pas un plantage."""
    path = tmp_path / "nvd.sqlite"
    path.write_bytes(b"ceci n'est pas une base SQLite")
    assert nvd_snapshot_sha256(path) == ""


def test_cpe_version_zero_si_le_fichier_n_est_pas_une_base(tmp_path: Path) -> None:
    path = tmp_path / "cpe.sqlite"
    path.write_bytes(b"ceci n'est pas une base SQLite")
    assert cpe_dict_version_id(path) == 0


def test_nvd_empreinte_vide_si_sqlite_refuse_d_ouvrir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQLite indisponible : empreinte vide, jamais une exception qui remonte au run."""
    import iot_audit.pipeline.provenance as prov

    def _boom(*args: object, **kwargs: object) -> object:
        raise sqlite3.Error("refus d'ouverture")

    path = _nvd_db(tmp_path / "nvd.sqlite", [("nvdcve-2.0-2021.json.gz", "d" * 64)])
    monkeypatch.setattr(prov.sqlite3, "connect", _boom)
    assert nvd_snapshot_sha256(path) == ""


def test_cpe_version_zero_si_sqlite_refuse_d_ouvrir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import iot_audit.pipeline.provenance as prov

    def _boom(*args: object, **kwargs: object) -> object:
        raise sqlite3.Error("refus d'ouverture")

    path = _cpe_db(tmp_path / "cpe.sqlite", 3)
    monkeypatch.setattr(prov.sqlite3, "connect", _boom)
    assert cpe_dict_version_id(path) == 0


def test_cpe_version_zero_si_l_identifiant_n_est_pas_un_entier(tmp_path: Path) -> None:
    """`MAX(id)` textuel : `0` (non établi) plutôt qu'une exception de conversion."""
    path = tmp_path / "cpe.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE dictionary_versions (id, source)")
    con.execute("INSERT INTO dictionary_versions VALUES ('nvd-2026', 'nvd')")
    con.commit()
    con.close()
    assert cpe_dict_version_id(path) == 0
