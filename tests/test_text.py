"""Tests des primitives textuelles partagées (``iot_audit/text.py``).

Ce module existe par **déduplication** : ``normalise`` y a remplacé quatre
copies, ``strip_html`` quatre autres, ``now_iso`` deux. Il était couvert à
69 % — donc ``strip_html`` et ``now_iso`` n'étaient **jamais** exécutés par la
suite, alors qu'ils alimentent la provenance des images Commons. Une fonction
partagée que personne n'appelle directement est exactement celle dont on ne
s'aperçoit pas qu'elle est cassée : les tests ci-dessous l'appellent pour elle,
pas à travers trois couches.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from iot_audit.text import normalise, now_iso, strip_html

# --------------------------------------------------------------------------- #
# normalise — la normalisation de comparaison du projet (docs/05 §2.2)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TP-Link Archer_C7", "tp link archer c7"),
        ("  DIR-600  ", "dir 600"),
        ("DSL-524T", "dsl 524t"),
        ("P.870HA", "p 870ha"),        ("Nest\xa0Hello", "nest hello"),        # espace insécable : séparateur

        ("Café", "caf"),                        # accents : points de code non-ASCII
        ("ÉTÉ 2026", "t 2026"),
        ("", ""),
        ("___", ""),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_normalise_tolere_none() -> None:
    """``None`` ne doit pas produire ``"none"`` : ce serait une marque valide."""
    assert normalise(None) == ""
    assert "none" not in normalise(None)


# --------------------------------------------------------------------------- #
# strip_html — les ``extmetadata`` Commons en contiennent
# --------------------------------------------------------------------------- #

def test_strip_html_retire_les_balises() -> None:
    assert strip_html("<b>Nest</b> <i>Hello</i>") == "Nest Hello"


def test_strip_html_tolere_none_et_non_textuel() -> None:
    """Défaut évité : ``str(None)`` vaudrait ``"None"``, une valeur *présente*."""
    assert strip_html(None) == ""
    assert strip_html(42) == "42"
    assert strip_html("") == ""


def test_strip_html_rogne_les_espaces_autour() -> None:
    assert strip_html("  <p>x</p>  ") == "x"


# --------------------------------------------------------------------------- #
# now_iso — horodatage de provenance
# --------------------------------------------------------------------------- #

def test_now_iso_est_utc_a_la_seconde() -> None:
    """UTC explicite, sans microseconde, et *analysable* comme tel.

    À la seconde parce que ces valeurs vont en base et sont comparées entre
    nœuds : la microseconde ne sert qu'à rendre deux runs « différents » sans
    raison. Le suffixe ``+00:00`` est ce qui permet au vérificateur tiers de
    l'analyser sans supposer le fuseau.
    """
    value = now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.microsecond == 0
    assert value.endswith("+00:00")


def test_now_iso_est_monotone_entre_deux_appels() -> None:
    assert now_iso() <= now_iso()
