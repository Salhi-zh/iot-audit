"""Marque restituée depuis le texte imprimé — extraction, jamais invention.

Le défaut, mesuré sur deux corpus **disjoints**
------------------------------------------------
Quand le modèle transcrit du texte, la majorité de ses échecs de marque sont des
champs ``brand`` **VIDES**, pas des marques fausses :

===========================  =========  ============  ==================
corpus                       échecs     dont vides    dont marque fausse
===========================  =========  ============  ==================
Openverse (220 images)       67         60            6
run gelé v4 (144 images)     48         38            9
===========================  =========  ============  ==================

Le prompt du projet **ordonne** l'abstention (« *an invented brand is worse than
an empty answer* »). Le modèle obéit — et jette l'information qu'il vient de
lire : sur l'échantillon disjoint, **22 des 67 échecs portent la marque exacte
dans le `visible_text` que le modèle a lui-même transcrit**, avec un champ
`brand` néanmoins vide.

Ce que cette fonction fait, et ce qu'elle ne fait pas
-----------------------------------------------------
Elle ne devine rien. Elle n'est appelée que lorsque le champ `brand` est **vide**
(jamais pour contredire une marque annoncée), et elle ne propose un vendeur que
si les **deux** conditions tiennent :

1. le vendeur apparaît, en mot entier, dans le texte que le modèle a lui-même
   transcrit (`visible_text`) — c'est une **restitution**, pas une supposition ;
2. il appartient au **lexique curé du périmètre** (`identity.BRAND_ALIASES`,
   ``corpus.identity``) — le même tableau que l'extraction d'étiquette du corpus,
   volontairement restreint aux marques réellement présentes dans les cinq
   catégories du projet.

Le second point n'est pas cosmétique : mesuré, le lexique CPE complet
(1 596 vendeurs matériels, `adversarial.load_vendor_lexicon`) rend **17/23**
justes sur le même périmètre, contre **21/22** pour le lexique curé. L'écart est
fait de noms de **composants** (« Texas Instruments » sérigraphié sur une carte
mère) que le lexique de périmètre ne contient pas — un vendeur de composant n'est
pas la marque de l'appareil.

L'arbitrage, quand plusieurs vendeurs du lexique cohabitent dans le texte, n'est
**pas** inventé ici : c'est la règle documentée d'`identity.extract_brand`,
**l'alias le plus long gagne** (« tp-link » bat « tp »), départagée à longueur
égale par l'ordre du lexique — déterministe et auditable. Ce module ne réécrit
pas cette règle, il l'appelle.

Coût mesuré (mêmes images, même barème)
---------------------------------------
============================  ============  =============  =================
corpus                        marque juste  remplies       dont justes
============================  ============  =============  =================
run gelé v4 (144 images)      46 -> 55      9              9
Openverse disjoint (220)      81 -> 102     22             21
============================  ============  =============  =================

Soit **+9 et +21 images pour une seule marque fausse au total**. À comparer à la
variante « prompt agressif », qui gagne +24 mais fabrique **40** marques fausses
(7 → 40) : la restitution par lexique achète le même rappel sans payer AC5.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from iot_audit.corpus.identity import extract_brand

__all__ = ["recover_brand_from_text"]


def recover_brand_from_text(visible_texts: Iterable[str | None]) -> str | None:
    """Vendeur du périmètre nommé dans les textes transcrits, sinon ``None``.

    ``visible_texts`` : les transcriptions des photos du **même** objet. Chaque
    texte est lu par ``extract_brand`` (forme canonique + règle « l'alias le plus
    long gagne ») ; le vote porte ensuite sur ces formes canoniques, pour que les
    orthographes d'un même vendeur soient **une seule classe**. Le départage des
    ex æquo entre classes est la **première rencontrée** — la même règle que
    ``corpus.metrics.modal`` et ``Orchestrator._modal``, choisie parce qu'elle est
    *observée* et donc révisable par un humain plutôt que par l'ordre d'un
    dictionnaire.

    Renvoie ``None`` si aucun texte n'est disponible, ou si aucun vendeur du
    périmètre n'y figure : l'appelant laisse alors le champ vide, comme le
    modèle.
    """
    classes: Counter[str] = Counter()
    for text in visible_texts:
        if not text:
            continue
        canon, _alias = extract_brand(text)
        if canon:
            classes[canon] += 1
    if not classes:
        return None
    # ``most_common`` départage par ordre d'insertion (Counter) : première classe
    # rencontrée à égalité. Explicite pour la même raison que dans `metrics.modal`.
    return classes.most_common(1)[0][0]
