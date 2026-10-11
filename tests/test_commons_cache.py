"""Verrouille le **nommage du cache disque** de `CommonsClient`.

Pourquoi ce fichier existe
--------------------------
Le nom du fichier de cache était ``re.sub(r"[^A-Za-z0-9]+", "_", key)[:110]``.
Deux clés distinctes qui partagent leurs 110 premiers caractères écrivent donc
dans **le même fichier**, et la seconde lit la réponse de la première.

Ce n'est pas une hypothèse : le défaut a été observé, mesuré, sur le même motif,
dans `corpus/harvest_flat.py`. Les clés d'un appel ``imageinfo`` par lots de 50
titres commencent par

    action=query|format=json|formatversion=2|iiprop=url|size|mime|sha1|…|
    iiurlwidth=1280|prop=imageinfo|titles=File:…

dont la forme normalisée fait **à elle seule** ~110 caractères : la partie
``titles=`` était entièrement coupée, tous les lots produisaient le même nom, et
le manifeste « 3 008 images » ne contenait que **47 fichiers réels**, répétés 64
fois. Un chiffre publié reposait donc sur un cache qui répondait à côté.

Ce que ces tests protègent : la propriété « deux clés distinctes ⇒ deux
fichiers », et le fait qu'un aller-retour ``_cache_put``/``_cache_get`` ne peut
pas rendre la valeur d'une autre clé. Ils ne testent **pas** le format des noms :
seule l'injectivité compte, et elle doit survivre à un changement de longueur.
"""

from __future__ import annotations

from pathlib import Path

from iot_audit.corpus.commons import CommonsClient


def _client(tmp_path: Path) -> CommonsClient:
    return CommonsClient(cache_dir=tmp_path)


def test_deux_cles_longues_du_meme_prefixe_ont_deux_fichiers(tmp_path: Path) -> None:
    """Le défaut : les 110 premiers caractères identiques ⇒ collision de nom."""
    client = _client(tmp_path)
    prefixe = "info::File:" + "A" * 200
    a = prefixe + "premier.jpg"
    b = prefixe + "second.jpg"
    assert a != b
    assert client._cache_path(a) != client._cache_path(b)


def test_les_cles_courtes_gardent_leur_nom(tmp_path: Path) -> None:
    """Le cache déjà payé reste valide : les clés courtes ne changent pas de nom.

    C'est la contrepartie explicite du correctif — désambigüiser *toutes* les
    clés aurait invalidé des heures de réponses déjà en cache pour aucun gain.
    """
    client = _client(tmp_path)
    assert client._cache_path("info::File:Court.jpg").name == "info_File_Court_jpg.json"
    assert client._cache_path("subcat::Category:Routers").name == \
        "subcat_Category_Routers.json"


def test_un_put_ne_se_lit_pas_sous_une_autre_cle(tmp_path: Path) -> None:
    """L'aller-retour : ce que le cache rend est ce qui a été écrit, pas autre chose."""
    client = _client(tmp_path)
    prefixe = "info::File:" + "B" * 200
    a = prefixe + "premier.jpg"
    b = prefixe + "second.jpg"
    client._cache_put(a, {"titre": "premier"})
    assert client._cache_get(a) == {"titre": "premier"}
    assert client._cache_get(b) is None
    client._cache_put(b, {"titre": "second"})
    assert client._cache_get(a) == {"titre": "premier"}
    assert client._cache_get(b) == {"titre": "second"}


def test_le_nom_reste_exploitable_a_l_oeil(tmp_path: Path) -> None:
    """L'empreinte est un *suffixe* : le début du nom dit encore quelle clé c'est."""
    client = _client(tmp_path)
    key = "info::File:" + "C" * 300 + ".jpg"
    name = client._cache_path(key).name
    assert name.startswith("info_File_CCC")
    assert len(name) > CommonsClient._CACHE_NAME_MAX
