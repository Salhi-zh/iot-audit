"""Normalisation de chaînes, canonisation de version et mapping de catégorie.

Implémente les spécifications de :
- docs/04-data-pipelines.md §1.4
- docs/05-matching-and-confidence.md §2.3
- docs/07-verification-plan.md §4.1 (tests critiques)
"""

from __future__ import annotations

import re
import unicodedata

from iot_audit.contracts import Category

__all__ = [
    "ALIASES",
    "CATEGORY_RULES",
    "OVERRIDES",
    "canon_vendor",
    "canon_version",
    "classify",
    "cpe_token_to_display",
    "embed_text",
    "normalize_display",
    "split_version",
]

_PARENS = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_VERSION_RX = re.compile(r"^(?:v|ver|version)?\s*(\d+)(?:[._](\d+))?$")

ALIASES: dict[str, str] = {
    "d link": "dlink",
    "tp link": "tp-link",
    "hewlett packard": "hp",
}


def normalize_display(s: str) -> str:
    """'TP-Link (EU) Archer C7 v2' -> 'tp link archer c7 v2'."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = _PARENS.sub(" ", s.lower())
    s = _NON_ALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def canon_vendor(raw: str) -> str:
    """Canonicalise le nom de vendeur à l'aide des alias connus."""
    n = normalize_display(raw)
    return ALIASES.get(n, n)


def canon_version(tok: str) -> str | None:
    """'v2' | '2.0' | '2' | 'ver2' -> '2'. Renvoie None si non reconnaissable."""
    if not tok:
        return None
    m = _VERSION_RX.match(tok.strip().lower())
    if not m:
        return None
    major, minor = m.group(1), m.group(2)
    return major if minor in (None, "0") else f"{major}.{minor}"


def split_version(model_norm: str) -> tuple[str, str | None]:
    """Détache un suffixe de version : 'archer c7 v2' -> ('archer c7', '2')."""
    toks = model_norm.split()
    if len(toks) >= 2:
        v = canon_version(toks[-1])
        if v is not None:
            return " ".join(toks[:-1]), v
    return model_norm, None


def cpe_token_to_display(t: str) -> str:
    """Jeton CPE -> affichage : 'archer_c7' -> 'archer c7', '\\!' -> '!'."""
    return t.replace("\\", "").replace("_", " ").strip()


def embed_text(vendor: str, product: str, version: str | None, cat: Category) -> str:
    """Texte indexé pour les embeddings (D4). Doit être DÉRIVÉ, jamais saisi."""
    v = cpe_token_to_display(vendor)
    p = cpe_token_to_display(product)
    ver = f" {version}" if version and version not in {"*", "-"} else ""
    return f"{v} {p}{ver} {cat.value.replace('_', ' ')}".strip()


# Mapping curé. Ordonné : la PREMIÈRE règle qui matche gagne (précédence explicite).
CATEGORY_RULES: list[tuple[Category, re.Pattern[str]]] = [
    (Category.CAMERA, re.compile(r"\b(camera|ipcam|ip cam|nvr|dvr|dome|ptz|webcam)\b")),
    (
        Category.ROUTER,
        re.compile(
            r"\b(router|gateway|access point|wireless ap|modem|firewall|switch|mesh|repeater|extender)\b"
        ),
    ),
    (Category.BULB, re.compile(r"\b(bulb|light|lamp|led strip|dimmer|smart light)\b")),
    (Category.SPEAKER, re.compile(r"\b(speaker|soundbar|audio|voice assistant|display)\b")),
    (Category.PLUG, re.compile(r"\b(plug|socket|outlet|relay|power strip|smart switch)\b")),
]

# Désambiguïsation : 'smart switch' est un plug, pas un switch réseau.
OVERRIDES: dict[str, Category] = {
    "smart switch": Category.PLUG,
    "smart plug": Category.PLUG,
}


def classify(vendor: str, product: str) -> Category:
    """Dérive la catégorie d'équipement depuis le vendeur et le produit CPE."""
    hay = f"{cpe_token_to_display(vendor)} {cpe_token_to_display(product)}".lower()
    for needle, cat in OVERRIDES.items():
        if needle in hay:
            return cat
    for cat, pattern in CATEGORY_RULES:
        if pattern.search(hay):
            return cat
    return Category.OTHER
