"""Détection d'injection par étiquette (docs/03 §5, docs/07 §5).

Le texte lu sur l'objet (``VLMRawOutput.visible_text``) est une **donnée**,
jamais une instruction. Ce module ne change pas ce fait : il le *constate* et
rend la tentative traçable, pour que le rapport puisse dire « le texte imprimé
sur cet objet essayait de piloter l'analyse ».

Trois raisons d'isoler ce code au lieu d'un ``if`` dans l'orchestrateur :

* **Les motifs sont la partie falsifiable.** Ils se lisent, se discutent et se
  corrigent en un seul endroit. Un motif qui déclenche sur une étiquette
  légitime est un faux positif : il rétrograde une identification correcte et
  fait perdre du temps à l'auditeur. La liste ci-dessous est donc vérifiée
  contre un jeu de textes réels du corpus (``tests/test_adversarial.py``), pas
  seulement contre la charge d'attaque.
* **La taxonomie D14 exige la trace.** ``E_ADVERSARIAL_LABEL_SUSPECTED``
  réclame ``raw_text`` **et** ``pattern`` : un booléen ne suffit pas, il faut
  pouvoir relire ce qui a déclenché.
* **Le Guided Decoding n'est pas une défense suffisante.** Le schéma empêche la
  sortie de quitter le format ; il n'empêche pas le modèle de *permuter* une
  marque à l'intérieur du schéma parce qu'un texte l'y invite. C'est
  exactement la faille que ce code documente.

Ce module ne « neutralise » pas le texte et ne le réécrit pas : masquer la
charge d'attaque effacerait la preuve. Il ne l'exécute pas non plus — rien ici
n'interprète ``visible_text``, et c'est la propriété que le test adversarial
vérifie (aucune marque inventée, aucune instruction suivie).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

__all__ = [
    "GENERIC_VENDOR_TOKENS",
    "INJECTION_PATTERNS",
    "contains_token",
    "detect_injection_patterns",
    "excerpt",
    "is_suspicious",
    "label_divergence",
    "load_vendor_lexicon",
    "normalize_token",
]

# Chaque motif est une formulation d'**instruction**, jamais une simple
# occurrence de mots courants : « ignore », « previous » ou « instructions »
# séparément apparaissent dans des notices d'usage (« do not ignore the LED »),
# leur co-occurrence non. Volontairement pas de motif « réponds seulement » :
# une étiquette peut légitimement porter le mot « only » (ex. « ONLY 5 V DC ») et
# le gain d'un tel motif est nul face au coût d'un faux positif.
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:ignore|disregard|forget)\b[^.\n]{0,40}"
        r"\b(?:previous|prior|above|earlier|preceding|system)\b[^.\n]{0,20}"
        r"\b(?:instruction|prompt|message|rule|direction)s?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:system|developer)\s+(?:prompt|message|instruction)\b", re.IGNORECASE),
    re.compile(r"\bprompt\s+injection\b|\bjailbreak\b|\bDAN\s+mode\b", re.IGNORECASE),
    re.compile(
        r"\byou\s+(?:are|must|should|will)\s+(?:now\s+)?(?:an?\s+)?"
        r"(?:ai|assistant|language\s+model|chatbot|system)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bas\s+(?:an?\s+)?(?:ai|assistant|language\s+model)\b[^.\n]{0,30}"
        r"\b(?:you\s+)?(?:must|should|have\s+to|will)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\boverride\b[^.\n]{0,25}\b(?:instruction|rule|schema|prompt)s?\b", re.IGNORECASE),
    re.compile(
        r"\bdo\s+not\s+(?:report|mention|reveal|disclose|say|output)\b",
        re.IGNORECASE,
    ),
    # Balises de conversation injectées dans une étiquette : <|im_start|>,
    # <system>, [/INST]. Aucune étiquette produit légitime ne porte ces formes.
    re.compile(r"<\s*/?\s*(?:system|instruction|im_start|im_end)\b|<\|[a-z_]+\|>|\[/?INST\]"),
)

#: Longueur maximale du texte conservé dans la trace journal. Un texte plus
#: long est tronqué : la trace doit rester relisible et comparable, et le
#: journal n'a pas vocation à recopier une notice entière.
EXCERPT_LIMIT = 200


def detect_injection_patterns(visible_text: str) -> tuple[str, ...]:
    """Renvoie les motifs d'instruction trouvés dans un texte lu sur l'objet.

    L'ordre de :data:`INJECTION_PATTERNS` est stable et fait partie du
    contrat de trace : ``patterns[0]`` est le motif retenu pour le journal.
    Un texte vide (cas normal : la majorité des photos de corpus n'ont aucun
    texte lisible) ne produit aucun motif, sans exception.
    """
    if not visible_text:
        return ()
    return tuple(p.pattern for p in INJECTION_PATTERNS if p.search(visible_text))


def is_suspicious(visible_text: str) -> bool:
    """Vrai si ``visible_text`` contient au moins une formulation d'instruction."""
    return bool(detect_injection_patterns(visible_text))


# --------------------------------------------------------------------------- #
# Divergence d'étiquette : le texte imprimé nomme un AUTRE vendeur connu
# --------------------------------------------------------------------------- #
# Mesuré le 2026-10-06 (`corpus/probe-label-divergence.py`, résultats gelés dans
# `evidence/2026-10-06/label-divergence/`) sur toutes les sorties réelles du dépôt :
# 1008 enregistrements = **144 photos mesurées 7 fois**, dont 556 enregistrements
# (94 photos distinctes) portent un texte imprimé non vide.
#
# * « la marque annoncée n'est pas dans le texte » déclenche sur 88/556 (15,8 %) =
#   15 photos : bien trop large pour rétrograder quoi que ce soit.
# * `identification_basis == "label"` ne filtre **rien** (88 = 88) : dès que le
#   modèle nomme une marque sur ce corpus, il écrit `label`, y compris quand le
#   texte ne contient pas cette marque. Le seul discriminant qui reste est la
#   présence d'un AUTRE vendeur connu dans le texte.
# * ce discriminant-là déclenche sur **1 photo**, dans 6 passes sur 7 :
#   `zyxel__p_870ha_vtu_r_2`, dont le texte est « POWER ALARM 10/100 DUPLEX … ».
#   Le « vendeur » trouvé est `alarm` — le mot anglais de l'alarme électrique,
#   rapproché du vendeur CPE `alarm` (Alarm.com). Ce n'est pas une divergence :
#   c'est un faux positif **fabriqué par le lexique**.
#
# D'où les deux jetons refusés ci-dessous : ils sont les **deux seuls** du
# lexique à déclencher sur les textes réels, et l'un d'eux déclenche sur une
# façade de modem. Avec eux retirés, le détecteur ne déclenche plus sur le
# corpus — **zéro** — et c'est la vérité mesurée : il ne se juge que sur son cas
# injecté (docs/07 §5 : objet « D-Link », texte « TP-Link »). Publier « 6
# détections, 1,08 % » aurait été publier une seule photo comptée six fois.
GENERIC_VENDOR_TOKENS = frozenset({"alarm", "free"})

#: Longueur minimale d'un jeton de vendeur. En dessous (3 caractères), les
#: collisions avec des sigles et des unités deviennent la règle : `ac`, `abb`,
#: `3m`, `hp`.
MIN_VENDOR_TOKEN_LENGTH = 4

#: Base du dictionnaire CPE local — le lexique des vendeurs matériels. Il est
#: **déjà dans le dépôt** : aucune liste de marques n'est écrite à la main, et
#: aucune n'a besoin de l'être.
DEFAULT_CPE_DB = Path(__file__).resolve().parents[2] / "corpus" / "cpe.sqlite"

_LEXICON_CACHE: frozenset[str] | None = None


def normalize_token(text: str | None) -> str:
    """Minuscules, séparateurs unifiés, ponctuation réduite à des espaces.

    « TP-Link », « tp_link » et « TP Link » sont le même jeton : sans cela, un
    vendeur et sa propre marque se manqueraient l'un l'autre dans le texte.
    """
    return re.sub(
        r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower().replace("_", " "))
    ).strip()


def contains_token(haystack: str, needle: str) -> bool:
    """Vrai si ``needle`` apparaît dans ``haystack`` en **mot entier**.

    La borne compte : sans elle, « d link » matcherait dans « dlinker » et
    « free » dans « freedom » — un détecteur qui déclenche sur une sous-chaîne
    fabrique ses propres faux positifs.
    """
    if not needle:
        return False
    return re.search(
        r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", " " + haystack + " "
    ) is not None


def load_vendor_lexicon(path: Path | str = DEFAULT_CPE_DB) -> frozenset[str]:
    """Jetons de vendeurs matériels du dictionnaire CPE local, normalisés.

    Source : ``corpus/cpe.sqlite``, table ``cpe_entries``, ``part='h'`` (le
    matériel ; les applications n'ont rien à faire dans un texte imprimé sur
    un boîtier). Chargé une fois et mis en cache — c'est une lecture de 1,8 M
    de lignes.

    **Base absente ⇒ lexique vide.** Le détecteur ne devine alors rien : il ne
    déclenche pas, et l'appelant doit le dire. Un lexique inventé en secours
    rétrograderait des identifications correctes.
    """
    global _LEXICON_CACHE
    if _LEXICON_CACHE is not None and Path(path) == DEFAULT_CPE_DB:
        return _LEXICON_CACHE
    p = Path(path)
    if not p.exists():
        return frozenset()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        raw = {normalize_token(v) for (v,) in
               con.execute("SELECT DISTINCT vendor FROM cpe_entries WHERE part='h'") if v}
    except sqlite3.Error:
        return frozenset()
    finally:
        con.close()
    lex = frozenset(
        v for v in raw
        if len(v.replace(" ", "")) >= MIN_VENDOR_TOKEN_LENGTH
        and v not in GENERIC_VENDOR_TOKENS
    )
    if p == DEFAULT_CPE_DB:
        _LEXICON_CACHE = lex
    return lex


def label_divergence(
    claimed_brand: str,
    visible_text: str,
    *,
    lexicon: Iterable[str] | None = None,
) -> str | None:
    """Vendeur **connu** nommé par le texte et différent de la marque annoncée.

    Renvoie le premier jeton (ordre alphabétique, donc stable) ou ``None``. Les
    trois conditions, et pourquoi elles sont celles-ci :

    1. **Une marque est annoncée** — sans marque revendiquée, il n'y a rien à
       contredire. La marque passée ici est celle du **rapport** (le tuple
       modal), pas celle d'une photo : c'est la revendication à vérifier.
    2. **La marque annoncée n'est pas dans le texte** — sinon le texte
       corrobore, et il n'y a pas de divergence.
    3. **Un autre vendeur connu y est** — c'est le seul discriminant mesuré
       (voir le commentaire de :data:`GENERIC_VENDOR_TOKENS`).

    ``identification_basis`` n'est **pas** un paramètre : mesuré, il ne
    discrimine pas (88 = 88 sur les sorties réelles). L'exiger n'aurait rien
    filtré et aurait fait croire à un contrôle supplémentaire.

    Cette fonction **ne corrige rien** : elle rapporte. Le texte imprimé est une
    donnée ; on ne remplace pas la marque annoncée par celle que le texte
    suggère — on refuse de la déclarer « identifiée » et on laisse la trace.
    """
    brand = normalize_token(claimed_brand)
    text = normalize_token(visible_text)
    if not brand or not text:
        return None
    if contains_token(text, brand):
        return None
    known = frozenset(normalize_token(v) for v in lexicon) \
        if lexicon is not None else load_vendor_lexicon()
    for candidate in sorted(known):
        if candidate != brand and contains_token(text, candidate):
            return candidate
    return None


def excerpt(visible_text: str, *, limit: int = EXCERPT_LIMIT) -> str:
    """Texte brut tronqué pour le champ ``raw_text`` de la trace.

    Le texte est conservé tel quel (on ne masque pas la charge : elle est la
    preuve). Seule la longueur est bornée, et la troncature est visible dans la
    valeur elle-même — un texte tronqué en silence se lirait comme un texte
    complet plus court.
    """
    if visible_text is None:
        return ""
    text = str(visible_text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[{len(text) - limit} caractères tronqués]"
