"""Comparaison de versions pour les plages NVD (docs/04 §2.3, CDS §9.2).

Pourquoi un module a part, et pourquoi il est teste :

La logique de plage NVD (`versionStartIncluding`, `versionEndExcluding`...) ne
s'evalue **pas** en SQL : un `LIKE` ignore `NEGATE` et une comparaison de chaines
classe `"1.10"` avant `"1.9"`. On evalue donc en Python, et ce code devient la
piece la plus testable du pipeline CVE.

Regles implementees (volontairement conservatrices) :

1. `*` ou `-` ou vide  -> version non contrainte : la fonction de plage ne
   filtre pas. C'est le cas dominant des criteres "produit entier".
2. Une version est decoupee en **runs** numeriques et alphabetiques. Un run
   numerique se compare **numeriquement** (`9 < 10`), un run alphabetique
   alphabetiquement. C'est ce qui corrige le piege classique des chaines.
3. Ce decoupage donne un **ordre total deterministe** sur toutes les chaines
   comparables : `compare()` ne renvoie `None` que lorsqu'un cote est
   *non contraint* (`*`, `-`, vide). Il ne devine donc jamais a moitie : soit
   deux formes sont ordonnees par les regles ci-dessus, soit la comparaison
   n'a pas de sens parce qu'il n'y a rien a comparer.
4. Un suffixe de pre-release (`-beta`, `_rc1`, `alpha`) est **inferieur** a la
   version nue : `1.2.3-beta < 1.2.3`. Motif : les flux NVD publient des CVE sur
   des versions pre-release, et une release finale ne doit jamais etre declaree
   inferieure a sa beta.

Limite assumee : deux schemes de nommage etrangers l'un a l'autre (un semver
face a une date) sont ordonnes par ces regles sans que l'ordre ait un sens
metier. C'est le comportement des outils reels (grype, osv-scanner) et il est
**prefere** a un `None` qui transformerait chaque comparaison exotique en
incertitude. Le garde-fou du projet n'est pas ici : il est dans `unresolved`,
qui marque l'incertitude *qui compte* (version firmware inconnue).
"""

from __future__ import annotations

import re

__all__ = [
    "UNCONSTRAINED",
    "compare",
    "is_unconstrained",
    "within_range",
]

#: Valeurs qui, dans un CPE ou un critere NVD, signifient « n'importe quelle version ».
UNCONSTRAINED = frozenset({"*", "-", "", None})

_RUNS = re.compile(r"(\d+|[a-zA-Z]+)")
_PRE_RELEASE = ("alpha", "beta", "rc", "pre", "dev", "snapshot", "nightly")


def is_unconstrained(version: str | None) -> bool:
    """``True`` si la version ne contraint rien (``*``, ``-``, vide)."""
    return version in UNCONSTRAINED or (isinstance(version, str) and version.strip() in {"*", "-", ""})


def _normalise(version: str) -> str:
    """Retire un prefixe ``v``/``ver`` et les espaces — rien de plus.

    On ne canonicalise **pas** agressivement : ``2.0`` et ``2.0.0`` sont deux
    chaines distinctes dans NVD, et les confondre ferait entrer une CVE dans une
    plage ou elle n'est pas.
    """
    v = version.strip()
    if v[:1] in {"v", "V"} and len(v) > 1 and v[1].isdigit():
        v = v[1:]
    return v


def _split_prerelease(v: str) -> tuple[str, str]:
    """Decoupe ``base`` / ``suffixe de pre-release`` (semver : ``-`` => prerelease).

    ``1.2.3-beta`` -> ``("1.2.3", "beta")`` ; ``1.2.3`` -> ``("1.2.3", "")``.
    Sans separateur, un jeton connu (``rc``, ``alpha``...) fait office de coupe :
    ``1.2.3rc1`` -> ``("1.2.3", "rc1")``.
    """
    for sep in ("-", "_"):
        if sep in v:
            base, _, pre = v.partition(sep)
            return base, pre
    for tok in _PRE_RELEASE:
        idx = v.find(tok)
        if idx > 0:
            return v[:idx], v[idx:]
    return v, ""


def _runs(segment: str) -> tuple[tuple[int, object], ...]:
    """Runs de ``segment`` : numeriques compares en nombre, alpha en texte."""
    return tuple(
        (0, int(run)) if run.isdigit() else (1, run) for run in _RUNS.findall(segment)
    )


def _key(version: str) -> tuple:
    """Cle de tri a trois niveaux, dans cet ordre :

    1. **la base versionnee** — c'est la comparaison qui domine : ``1.9.9-beta``
       est *au-dessus* de ``1.0`` (meme si c'est une beta) ;
    2. **ran de pre-release** — une prerelease n'est inferieure a la release
       que si leurs bases sont **egales** : ``1.2.3-beta < 1.2.3`` ;
    3. **les runs du suffixe** — ``alpha < beta < rc``.

    L'erreur classique (placer le ran de prerelease en tete de cle) classe toute
    beta sous n'importe quelle release, y compris des versions inferieures : ce
    test est verrouille par ``test_range_prerelease_inside_range``.
    """
    v = _normalise(version).lower()
    base, pre = _split_prerelease(v)
    return (_runs(base), 0 if pre else 1, _runs(pre))


def compare(a: str | None, b: str | None) -> int | None:
    """Compare deux versions. Renvoie ``-1``, ``0``, ``1``, ou ``None``.

    ``None`` signifie « rien a comparer » : l'un des cotes est *non contraint*
    (``*``, ``-``, vide). Ce n'est pas une indecision sur deux versions reelles —
    voir la limite assumee en tete de module.
    """
    if is_unconstrained(a) or is_unconstrained(b):
        return None
    if _normalise(a) == _normalise(b):
        return 0
    ka, kb = _key(a), _key(b)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    # Memes runs apres normalisation (ex. "1.0" vs "1.0.") : egales.
    return 0


def within_range(
    version: str | None,
    *,
    start_incl: str | None = None,
    start_excl: str | None = None,
    end_incl: str | None = None,
    end_excl: str | None = None,
) -> bool | None:
    """Teste l'appartenance d'une version a une plage NVD.

    Renvoie :
      * ``True``  — toutes les bornes evaluees sont satisfaites ;
      * ``False`` — au moins une borne est **violee** (donc exclue a coup sur) ;
      * ``None``  — la version testee elle-meme est **non contrainte** (``*``,
                    ``None``, vide) : le cas nominal du projet, ou le firmware
                    de l'exemplaire photographie n'est pas determine. L'appelant
                    publie alors l'incertitude (`unresolved`) au lieu de
                    trancher.

    Cette signature a trois etats est ce qui empeche le mode de defaillance le
    plus courant d'un matcher de CVE : transformer une incertitude en
    « non concerne » silencieux, c'est-a-dire en faux negatif.
    """
    if is_unconstrained(version):
        return None

    indeterminate = False

    for bound, strict, is_lower in (
        (start_incl, False, True),
        (start_excl, True, True),
        (end_incl, False, False),
        (end_excl, True, False),
    ):
        if is_unconstrained(bound):
            continue
        c = compare(version, bound)
        if c is None:
            indeterminate = True
            continue
        ok = (c > 0 if strict else c >= 0) if is_lower else (c < 0 if strict else c <= 0)
        if not ok:
            return False

    return None if indeterminate else True
