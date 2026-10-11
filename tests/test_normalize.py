"""Tests unitaires de normalisation, versions et catégories (docs/07 §4.1).

Vérifie :
1. `normalize_display` sur les parenthèses, majuscules et accents ;
2. `canon_version` sur les formats usuels ('v2', '2.0', 'ver2', '2.1') ;
3. `split_version` et ses pièges ('cam v2 pro' vs 'archer c7 v2') ;
4. Désambiguïsation de catégorie ('smart switch' -> PLUG, 'switch' -> ROUTER) ;
5. Formatage de `embed_text` et nettoyage de jetons CPE (`cpe_token_to_display`).
"""

from __future__ import annotations

import pytest

from iot_audit.contracts import Category
from iot_audit.pipeline.normalize import (
    canon_vendor,
    canon_version,
    classify,
    cpe_token_to_display,
    embed_text,
    normalize_display,
    split_version,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TP-Link (EU) Archer C7 v2", "tp link archer c7 v2"),
        ("D-Link", "d link"),
        ("  HikVision  ", "hikvision"),
        ("Netgear (US) N300", "netgear n300"),
    ],
)
def test_normalize_display(raw: str, expected: str) -> None:
    assert normalize_display(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v2", "2"),
        ("2.0", "2"),
        ("2", "2"),
        ("ver2", "2"),
        ("2.1", "2.1"),
        ("v10", "10"),
        ("pro", None),
        ("", None),
        ("   ", None),
    ],
)
def test_canon_version(raw: str, expected: str | None) -> None:
    assert canon_version(raw) == expected


def test_split_version_detaches_trailing_version() -> None:
    assert split_version("archer c7 v2") == ("archer c7", "2")
    assert split_version("archer c7") == ("archer c7", None)
    # Piège identifié dans docs/07 §4.1 : 'v2' suivi d'un mot non-version ne doit pas tronquer
    assert split_version("cam v2 pro") == ("cam v2 pro", None)


def test_canon_vendor_alias() -> None:
    assert canon_vendor("TP-Link (US)") == "tp-link"
    assert canon_vendor("D-Link") == "dlink"
    assert canon_vendor("UnknownBrand") == "unknownbrand"


def test_classify_disambiguation() -> None:
    # 'smart switch' est un smart plug / relay, pas un switch réseau
    assert classify("tp-link", "kasa_smart_switch") == Category.PLUG
    # 'switch' seul est un équipement réseau / router
    assert classify("cisco", "catalyst_switch_2960") == Category.ROUTER
    # Autres familles
    assert classify("hikvision", "ipcam_dome_2cd2143") == Category.CAMERA
    assert classify("philips", "hue_white_bulb") == Category.BULB
    assert classify("amazon", "echo_dot_speaker") == Category.SPEAKER
    assert classify("various", "gadget_xyz") == Category.OTHER


def test_cpe_token_to_display() -> None:
    assert cpe_token_to_display("archer_c7") == "archer c7"
    assert cpe_token_to_display("f\\@st_3686") == "f@st 3686"
    assert cpe_token_to_display("test\\!device") == "test!device"


def test_embed_text_derivation() -> None:
    txt = embed_text("tp-link", "archer_c7", "2.0", Category.ROUTER)
    assert txt == "tp-link archer c7 2.0 router ap"

    txt_no_ver = embed_text("tp-link", "archer_c7", "*", Category.ROUTER)
    assert txt_no_ver == "tp-link archer c7 router ap"
