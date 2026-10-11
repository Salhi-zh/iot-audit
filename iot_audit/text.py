"""Primitives textuelles partagées par plusieurs modules du corpus.

Ce module existe par **déduplication**, pas par fonctionnalité : avant lui, le
même normaliseur de texte existait en quatre exemplaires (``identity._norm``,
``cpe.norm``, ``ocrtext.normalise`` et une copie locale dans ``metrics.grade``),
le même nettoyage HTML en quatre autres, et ``now_iso`` en deux.

Le danger n'était pas la longueur du code mais la **divergence silencieuse** :
une correction appliquée à l'une des copies ne l'était pas aux autres, et deux
modules se mettaient alors à comparer des chaînes normalisées différemment — un
défaut qui ne se voit qu'après recomptage des métriques.

Volontairement sans dépendance : ``import re`` et ``datetime``, rien d'autre.
``metrics`` peut donc s'en servir sans perdre sa propriété d'être utilisable
seul (docs/07).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

_SPACERS = re.compile(r"[^a-z0-9]+")
_TAGS = re.compile(r"<[^>]+>")


def normalise(text: str) -> str:
    """Minuscules, un seul espace entre les lexèmes, bords rognés.

    C'est **la** normalisation de comparaison du projet : identités, requêtes
    CPE et textes OCR passent tous par ici, sinon deux modules compareraient des
    formes différentes (docs/05 §2.2).

    ``re.sub`` traite les points de code non-ASCII comme des séparateurs : les
    accents tombent donc avec les apostrophes et les tirets, ce qui est le
    comportement voulu pour comparer des libellés de produits.
    """
    return _SPACERS.sub(" ", (text or "").lower()).strip()


def strip_html(text: object) -> str:
    """Retire les balises et rogne — les ``extmetadata`` Commons en contiennent.

    Tolère ``None`` et les valeurs non textuelles : renvoie ``""`` plutôt qu'une
    chaîne ``"None"``, qui polluerait silencieusement la provenance.
    """
    if text is None:
        return ""
    return _TAGS.sub("", str(text)).strip()


def now_iso() -> str:
    """Horodatage ISO-8601 en UTC, à la seconde.

    À la seconde (et non à la microseconde) parce que ces valeurs finissent en
    base et sont comparées entre nœuds : la précision supplémentaire ne sert
    qu'à rendre deux runs « différents » sans raison.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()
