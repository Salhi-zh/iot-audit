"""Tests de la logique de plages de versions (iot_audit/vuln/version.py).

Chaque test porte le piege historique qu'il verrouille : une comparaison de
chaines classique manquerait tous les cas `1.10` vs `1.9` et `beta` vs release.
"""

from __future__ import annotations

import pytest

from iot_audit.vuln.version import compare, is_unconstrained, within_range

# --------------------------------------------------------------------------- #
# compare() : ordre numerique, pas lexicographique
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("1.9", "1.10", -1),        # piege classique : '9' > '1' en lexicographie
        ("1.10", "1.9", 1),
        ("1.0", "1.0.1", -1),
        ("1.2.10", "1.2.9", 1),
        ("2.0", "2.0", 0),
        ("v1.2", "1.2", 0),          # prefixe v
        ("V3.1", "3.1", 0),
        ("1.2.3-beta", "1.2.3", -1),  # pre-release inferieure a la release
        ("1.2.3-alpha", "1.2.3-rc", -1),
        ("1.02", "1.2", 0),          # zeros non significatifs
    ],
)
def test_compare_ordering(a: str, b: str, expected: int) -> None:
    assert compare(a, b) == expected
    assert compare(b, a) == -expected  # antisymetrie


@pytest.mark.parametrize("unconstrained", ["*", "-", "", None])
def test_compare_none_when_nothing_to_compare(unconstrained: str | None) -> None:
    """Pas de version => rien a comparer : None, jamais un verdict faux."""
    assert compare(unconstrained, "1.0") is None
    assert compare("1.0", unconstrained) is None


def test_is_unconstrained_boundary() -> None:
    assert is_unconstrained("*") and is_unconstrained("-") and is_unconstrained("")
    assert is_unconstrained("   ") and is_unconstrained(None)
    assert not is_unconstrained("1.0")
    assert not is_unconstrained("0")


# --------------------------------------------------------------------------- #
# within_range() : contrat a trois etats
# --------------------------------------------------------------------------- #


def test_range_bounds_inclusive_and_exclusive() -> None:
    assert within_range("1.5", start_incl="1.0", end_excl="2.0") is True
    assert within_range("1.0", start_incl="1.0") is True       # borne inferieure incluse
    assert within_range("0.9", start_incl="1.0") is False      # sous la borne
    assert within_range("2.0", start_incl="1.0", end_excl="2.0") is False  # borne haute exclue
    assert within_range("2.5", end_incl="2.5") is True
    assert within_range("2.6", end_incl="2.5") is False
    assert within_range("1.5", start_excl="1.5") is False      # inferieur strict
    assert within_range("1.6", start_excl="1.5") is True


def test_range_unknown_version_is_none_not_false() -> None:
    """Le cas nominal du projet : firmware inconnu => incertitude publiee.

    Transformer ce None en False serait un faux negatif silencieux — le mode
    de defaillance le plus grave d'un moteur de CVE.
    """
    assert within_range(None, start_incl="1.0", end_excl="2.0") is None
    assert within_range("*", start_incl="1.0") is None


def test_range_no_bounds_means_in_range() -> None:
    assert within_range("9.9.9") is True


def test_range_multiple_bounds_all_must_hold() -> None:
    # 1.5 satisfait la borne basse mais viole la borne haute => False
    assert within_range("1.5", start_incl="1.0", end_incl="1.4") is False
    # 1.3 satisfait les deux => True
    assert within_range("1.3", start_incl="1.0", end_incl="1.4") is True


def test_range_prerelease_inside_range() -> None:
    assert within_range("1.9.9-beta", start_incl="1.0", end_excl="2.0") is True
