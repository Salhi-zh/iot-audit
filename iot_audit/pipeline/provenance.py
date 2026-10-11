"""Assemblage de la provenance d'un run (docs/02 §154/§269, docs/03 §2, ENF5).

`Provenance` était déclaré, vérifié et **refusé** (`pipeline.preflight`,
`storage.seal`) — mais **jamais construit** : le refus `E_PROVENANCE_INCOMPLETE`
ne pouvait donc se déclencher que sur un objet fabriqué à la main pour un test.
Ce module est le producteur manquant, et il a une forme précise parce que la
donnée a une forme précise :

* **Elle naît sur le nœud** — version de vLLM, de torch, empreinte des poids,
  révision du modèle. Le nœud la mesure déjà
  (`infra/scripts/node_write_provenance.sh`, bloc `ENV_STATUS.md` du §8.3) mais
  l'écrivait en **markdown**, donc illisible par une machine. Le script écrit
  désormais aussi `provenance.json`.
* **Elle se complète sur la station** — empreinte du snapshot NVD, version du
  dictionnaire CPE, empreinte du prompt réellement envoyé. Ces trois-là sont des
  faits de la station, pas du nœud, et les calculer sur le nœud serait mesurer
  autre chose.
* **Elle ne s'assemble qu'ici**, au moment du scellement.

Deux règles tenues par le code, et pas seulement écrites dans un commentaire :

1. **Aucun champ n'est deviné.** Un champ non observable reste **vide** (`\"\"`),
   ce que `preflight.missing_provenance_fields` sait lire, et ce que
   `storage.seal.sign_report` refuse de signer. Mettre une valeur plausible à la
   place d'une mesure transforme une garantie de reproductibilité en décoration.
2. **Chaque empreinte a sa définition écrite.** `sha256` sans définition n'est
   pas vérifiable : « l'empreinte du snapshot NVD » ne veut rien dire tant qu'on
   n'a pas dit *de quoi* exactement (les octets des flux ? leur liste triée ? les
   deux ?). Les deux définitions du module — :func:`nvd_snapshot_sha256` et
   :func:`aggregate_weights_sha256` — sont donc reproduisibles à la main, et
   elles sont écrites ici plutôt que sous-entendues.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from iot_audit.contracts import Provenance

__all__ = [
    "NODE_PROVENANCE_FIELDS",
    "NODE_PROVENANCE_SSH_PATH",
    "aggregate_weights_sha256",
    "build_provenance",
    "cpe_dict_version_id",
    "load_node_provenance",
    "nvd_snapshot_sha256",
]

#: Où le service de nœud publie sa provenance
#: (`infra/scripts/node_write_provenance.sh`, écrit à côté de `ENV_STATUS.md`).
NODE_PROVENANCE_SSH_PATH = "~/vllm-env/provenance.json"

#: Champs que le nœud doit fournir, et le nom sous lequel il les publie dans
#: `~/vllm-env/provenance.json`. Un champ absent du JSON du nœud devient une
#: chaîne vide dans `Provenance` : c'est ce que le pré-vol compte comme manquant.
NODE_PROVENANCE_FIELDS: Mapping[str, str] = {
    "model_revision": "model_revision",
    "weights_sha256": "weights_sha256",
    "vllm_version": "vllm_version",
    "torch_version": "torch_version",
}

_HEX = set("0123456789abcdef")


def _looks_like_sha256(value: object) -> bool:
    """Un sha256 est 64 caractères hexadécimaux, ni plus ni moins.

    La vérification de forme n'est pas cosmétique : elle attrape le champ
    « rempli » mais faux — une valeur tronquée par un `cut` disgracieux, un
    chemin recopié à la place d'une empreinte, ou un `NON FAIT` en français
    écrit dans un champ d'empreinte. Ces trois-là ont tous l'air renseignés.
    """
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= _HEX


def load_node_provenance(source: str | Path, *, timeout: float = 20.0) -> dict[str, Any]:
    """Lit le `provenance.json` d'un nœud : un chemin local, ou ``ssh:<hôte>``.

    Le JSON du nœud est la seule source des quatre champs qui ne s'observent pas
    depuis la station (`model_revision`, `weights_sha256`, `vllm_version`,
    `torch_version`) ; les inventer serait le défaut que tout ce module existe
    pour empêcher.

    Rend **`{}`** dès que la lecture échoue — hôte injoignable, fichier absent,
    JSON invalide, objet JSON de forme inattendue. Un dictionnaire vide n'est pas
    « un run sans provenance » : c'est un trou, et
    :func:`~iot_audit.pipeline.preflight.missing_provenance_fields` compte alors
    les quatre champs du nœud comme manquants, ce qui fait refuser le scellement.
    Rendre un dictionnaire partiel avec des valeurs de repli plausible serait le
    seul vrai danger ici : il produirait un rapport scellé qui a l'air complet.
    """
    src = str(source).strip()
    if src.startswith("ssh:"):
        host = src[4:].strip()
        if not host:
            return {}
        try:
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host,
                 f"cat {NODE_PROVENANCE_SSH_PATH}"],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0:
            return {}
        text = proc.stdout
    else:
        path = Path(src)
        if not path.is_file():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


def aggregate_weights_sha256(files: Mapping[str, str]) -> str:
    """Empreinte des poids à partir de l'empreinte de chaque fichier.

    **Définition, pour qu'elle soit vérifiable :** `sha256` de la concaténation
    des lignes `"<sha256>  <nom_de_fichier>\\n"`, **triées par nom de fichier**.
    L'ordre est imposé (et non celui du disque) pour que deux machines qui
    portent les mêmes octets produisent la même empreinte ; les deux espaces
    entre l'empreinte et le nom reproduisent la sortie de `sha256sum`, pour
    qu'une vérification manuelle avec l'outil système donne le même résultat.

    Un fichier dont l'empreinte n'est pas un sha256 valide fait échouer la
    fonction : agréger un champ vide produirait une empreinte d'apparence
    normale qui ne décrit rien.
    """
    if not files:
        raise ValueError("aucun fichier de poids : empreinte non calculable")
    lines = []
    for name in sorted(files):
        digest = files[name]
        if not _looks_like_sha256(digest):
            raise ValueError(f"empreinte invalide pour {name!r} : {digest!r}")
        lines.append(f"{digest.lower()}  {name}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def nvd_snapshot_sha256(db_path: str | Path) -> str:
    """Empreinte du snapshot NVD vu par le run (docs/02 D13).

    **Définition :** `sha256` de la concaténation des lignes
    `"<feed_name>  <sha256>\\n"` de la table `feed_versions`, **triées par nom de
    flux**. C'est l'ensemble des flux *et* leur contenu qui est figé, pas les
    octets du fichier SQLite (qui varient au moindre `VACUUM` sans qu'aucune CVE
    n'ait changé, et ne varient pas quand une CVE change sans ingestion).

    Base absente, table absente, table vide : **chaîne vide**, jamais une
    empreinte par défaut. Une empreinte calculée sur rien ressemblerait à une
    empreinte valide, et c'est exactement ce que le refus de scellement existe
    pour empêcher.
    """
    path = Path(db_path)
    if not path.is_file():
        return ""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return ""
    try:
        rows = con.execute(
            "SELECT feed_name, sha256 FROM feed_versions ORDER BY feed_name"
        ).fetchall()
    except sqlite3.Error:
        return ""
    finally:
        con.close()
    pairs = [
        (str(name), str(digest).lower())
        for name, digest in rows
        if name and _looks_like_sha256(digest)
    ]
    if not pairs:
        return ""
    payload = "".join(f"{name}  {digest}\n" for name, digest in pairs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cpe_dict_version_id(db_path: str | Path) -> int:
    """Identifiant du dictionnaire CPE utilisé, `0` s'il n'est pas établissable.

    `0` (et non `1`) parce que `preflight.missing_provenance_fields` refuse
    `<= 0` : un dictionnaire non identifié est un trou de provenance, pas la
    première version.
    """
    path = Path(db_path)
    if not path.is_file():
        return 0
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        row = con.execute("SELECT MAX(id) FROM dictionary_versions").fetchone()
    except sqlite3.Error:
        return 0
    finally:
        con.close()
    if not row or row[0] is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def build_provenance(
    node_json: Mapping[str, Any],
    *,
    prompt_text: str,
    nvd_db: str | Path,
    cpe_db: str | Path,
    sampling_params: Mapping[str, Any],
    nodes_used: Sequence[str],
    started_at: datetime,
    finished_at: datetime,
    schema_version: str,
) -> Provenance:
    """Assemble la provenance d'un run à partir de ses trois origines.

    ``node_json`` est le contenu de ``provenance.json`` écrit par le nœud (voir
    ``infra/scripts/node_write_provenance.sh``). Ses champs non conformes sont
    ramenés à ``\"\"`` — donc comptés manquants par le pré-vol — au lieu d'être
    recopiés tels quels : un « NON ÉTABLIE » dans un champ d'empreinte est un
    aveu, pas une empreinte, et le contrat n'a pas de place pour un aveu.

    ``prompt_text`` est le prompt **réellement envoyé** au modèle, pas celui du
    manifeste : si les deux diffèrent, c'est le premier qui décrit le run.
    """
    values: dict[str, str] = {}
    for key in NODE_PROVENANCE_FIELDS:
        raw = node_json.get(key)
        text = raw.strip() if isinstance(raw, str) else ""
        values[key] = text if text and text.upper() != "NON FAIT" else ""

    # Les poids sont **recalculés** depuis les empreintes par fichier quand le
    # nœud les publie : c'est la seule façon de vérifier que l'agrégat annoncé
    # décrit bien les fichiers annoncés. L'agrégat du nœud n'est utilisé qu'en
    # dernier recours, et seulement s'il a la forme d'un sha256.
    weights = ""
    per_file = node_json.get("weights_files")
    if isinstance(per_file, Mapping) and per_file:
        try:
            weights = aggregate_weights_sha256(
                {str(name): str(digest) for name, digest in per_file.items()}
            )
        except ValueError:
            weights = ""
    if not weights and _looks_like_sha256(values["weights_sha256"]):
        weights = values["weights_sha256"].lower()

    return Provenance(
        model_revision=values["model_revision"],
        weights_sha256=weights,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        if prompt_text else "",
        schema_version=schema_version.strip() if isinstance(schema_version, str) else "",
        vllm_version=values["vllm_version"],
        torch_version=values["torch_version"],
        nvd_snapshot_sha256=nvd_snapshot_sha256(nvd_db),
        cpe_dict_version_id=cpe_dict_version_id(cpe_db),
        sampling_params=dict(sampling_params),
        nodes_used=tuple(nodes_used),
        started_at=started_at,
        finished_at=finished_at,
    )
