"""Ancre les empreintes scellées de `evidence/2026-09-15` dans l'histoire git.

Pourquoi ce fichier existe
--------------------------
L'artefact `evidence/2026-09-15/contrat-v3-et-nodes.json` scelle par sha256
quatre fichiers `corpus/` **tels qu'ils existaient à la session 18**, et affirme
que « régénérer runner3-v3.py redonne le même sha256 — vérifié ».

Une passe de style du 2026-09-29 avait éloigné les fichiers de leurs empreintes ;
les octets scellés ont été **restitués le 2026-10-07** (décision explicite,
voir `corpus/NOTE-lint-2026-10-07.md`). Ces tests verrouillent les trois
propriétés qui font la preuve :

* **les fichiers vivants** portent exactement l'empreinte publiée — le scellé se
  vérifie sans archéologie, sur le dépôt de travail lui-même ;
* l'empreinte existe aussi **dans l'histoire git** — si l'histoire était
  réécrite, ces tests échouent ;
* la promesse de l'artefact est vraie : **régénérer `runner3-v3.py` redonne le
  même sha256** (le générateur scellé relit `runner2-v2.py` inchangé).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTEFACT = ROOT / "evidence" / "2026-09-15" / "contrat-v3-et-nodes.json"

FICHIERS_SELLES = (
    "corpus/runner3-v3.py",
    "corpus/runner3b-v3-640.py",
    "corpus/probe-token-budget.py",
    "corpus/make_runner_v3.py",
)


def _git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def _empreintes() -> dict:
    return json.loads(ARTEFACT.read_text(encoding="utf-8"))["artefacts_et_empreintes"]


def _versions_commitees(path: str) -> dict[str, bytes]:
    """Toutes les versions committées de `path`, hashées par empreinte sha256."""
    if not (ROOT / ".git").exists():
        pytest.skip("hors dépôt git : l'ancre des empreintes est invérifiable")
    commits = _git("rev-list", "--all", "--", path).decode().split()
    versions: dict[str, bytes] = {}
    for commit in commits:
        blob = _git("show", f"{commit}:{path}")
        versions[hashlib.sha256(blob).hexdigest()] = blob
    return versions


class TestFichiersVivants:
    @pytest.mark.parametrize("path", FICHIERS_SELLES)
    def test_le_fichier_courant_a_exactement_l_empreinte_scellee(self, path):
        scellee = _empreintes()[path]
        courant = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert courant == scellee, (
            f"{path} a dérivé de son empreinte scellée {scellee[:16]}… : la "
            "preuve de la session 18 ne se vérifie plus sur le fichier vivant. "
            "Toute retouche de ces fichiers casse le scellé — les règles de lint "
            "qui les visent sont gelées dans pyproject.toml pour cette raison."
        )

    def test_regenerer_runner3_redonne_l_empreinte_scellee(self, tmp_path):
        import subprocess
        import sys
        out = tmp_path / "runner3-regen.py"
        subprocess.run(
            [sys.executable, "corpus/make_runner_v3.py", "--out", str(out)],
            cwd=ROOT, capture_output=True, check=True)
        calcule = hashlib.sha256(out.read_bytes()).hexdigest()
        assert calcule == _empreintes()["corpus/runner3-v3.py"], (
            "régénérer runner3-v3.py ne redonne plus l'empreinte scellée : la "
            "chaîne runner2-v2.py → make_runner_v3.py est rompue, alors que "
            "l'artefact de la session 18 affirme qu'elle est déterministe."
        )


class TestAncreDesEmpreintes:
    @pytest.mark.parametrize("path", FICHIERS_SELLES)
    def test_l_empreinte_scellee_existe_dans_l_histoire(self, path):
        scellee = _empreintes()[path]
        versions = _versions_commitees(path)
        assert scellee in versions, (
            f"aucune version committée de {path} ne porte l'empreinte scellée "
            f"{scellee[:16]}… : l'histoire a été réécrite (ou le fichier n'a "
            "jamais été commité tel qu'il a été scellé). La preuve de la "
            "session 18 n'est plus vérifiable."
        )

    def test_le_prompt_v3_scelle_correspond_au_manifeste_du_runner3_selon(self):
        scellee = _empreintes()["corpus/runner3-v3.py"]
        versions = _versions_commitees("corpus/runner3-v3.py")
        assert scellee in versions, "runner3-v3.py scellé introuvable dans l'histoire"
        m = re.search(r'MANIFEST = json\.loads\(r"""(.*?)"""\)',
                      versions[scellee].decode("utf-8"), re.S)
        assert m, "manifeste introuvable dans le runner3 scellé"
        prompt = json.loads(m.group(1))["prompt"]
        calcule = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        assert calcule == _empreintes()["prompt_v3_sha256"], (
            "le prompt_v3_sha256 publié ne correspond pas au prompt du "
            "runner3 scellé : l'artefact de preuve et le scellé divergent."
        )
