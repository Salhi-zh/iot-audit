"""Verrous sur les outils du run à l'échelle (`corpus/`).

Ces scripts ne font pas partie de la barre mypy/ruff, mais leurs règles de
notation **chiffrent des résultats publiés** : une régression silencieuse y
serait pire que dans le cœur. Ce qui est verrouillé ici :

* `m1_stratum` — sans ce filtre, M1 est contaminé par la strate marque-seule
  (`grade` rend `exact` quand la vérité n'a pas de modèle) : mesuré, cela
  publiait 0,305 là où le périmètre M1 vaut 0,217.
* la préservation des sections manuelles par `--out` : le grader régénère son
  bloc, jamais le contexte/limites écrits à la main.
* `brand_channel` : la part « récupérable » (marque de vérité présente dans le
  texte transcrit) est le levier de `label_brand.py`.
* `refill_cache` : manifestes liste OU dict (plantage réel en run), et rejet
  des corps tronqués (`Content-Length`) — cause des 2 JPEG Mapillary coupés.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "corpus" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


grade_scale_run = _load("grade_scale_run")
refill_cache = _load("refill_cache")
scale_distributed = _load("scale_distributed")


def _rec(image_id: str, brand: str, model: str, text: str = "") -> dict:
    return {
        "image_id": image_id,
        "object_id": f"obj::{model or brand}",
        "truth_brand": brand,
        "truth_model": model,
        "http_status": 200,
        "pred": {"brand": brand if text else "", "model": model if text else "",
                 "category": "other", "visible_text": text,
                 "identification_basis": "label" if text else "none"},
    }


class TestM1Stratum:
    def test_exclut_la_strate_sans_modele(self):
        recs = [_rec("a", "tp-link", "archer c6"),
                _rec("b", "tp-link", ""),
                _rec("c", "asus", "")]
        kept = grade_scale_run.m1_stratum(recs)
        assert [r["image_id"] for r in kept] == ["a"]

    def test_la_contamination_gonfle_bien_le_total(self):
        # Deux objets : un vrai (doit entrer), un marque-seule dont `grade`
        # rendrait `exact` par construction (ne doit jamais entrer).
        recs = [_rec("a1", "tp-link", "archer c6", text="tp-link"),
                _rec("b1", "kasa", "", text="kasa"),
                _rec("b2", "kasa", "", text="kasa")]
        kept = grade_scale_run.m1_stratum(recs)
        assert {r["object_id"] for r in kept} == {"obj::archer c6"}
        assert len(kept) == 1        # b1/b2 : 2 images écartées, 1 objet faux en moins


class TestBrandChannel:
    def test_recuperable_marque_dans_le_texte_transcrit(self):
        def case(image_id, text, brand_pred):
            r = _rec(image_id, "tp-link", "", text=text)
            r["pred"]["brand"] = brand_pred
            return r
        recs = [
            case("e", "", ""),                      # sans texte
            case("f", "Routeur TP-Link Archer", ""),  # vide mais texte lu
            case("g", "ASUS RT-AX55", "asus"),        # fausse, non récupérable
            case("h", "modèle TP-Link HS110", "d-link"),  # fausse mais récupérable
            case("i", "TP-Link", "tp-link"),          # juste
        ]
        ch = grade_scale_run.brand_channel(recs)
        tl = ch["texte_lu"]
        assert tl["n"] == 4
        assert tl["k"] == 1
        assert tl["empty"] == 1                 # f
        assert tl["wrong"] == 2                 # g + h
        assert tl["recoverable"] == 2           # f (vide) + h (fausse)
        assert ch["sans_texte"]["n"] == 1


class TestPreservationDesSections:
    def test_le_grader_ne_derase_pas_le_suffixe_manuel(self, tmp_path):
        marqueur = "<!-- sections manuelles -->"
        suffixe = f"{marqueur}\n\n## Contexte et périmètre\nTexte à la main.\n"
        out = tmp_path / "SYNTHESE.md"
        out.write_text("ancêtre" + suffixe, encoding="utf-8")

        preds = tmp_path / "preds.json"
        preds.write_text(json.dumps([_rec("a", "tp-link", "archer c6",
                                         text="tp-link")]),
                         encoding="utf-8")
        grade_scale_run.main(["--preds", str(preds), "--out", str(out)])

        text = out.read_text(encoding="utf-8")
        assert "prédictions brutes : 1" in text      # bloc régénéré
        assert "ancêtre" not in text                 # la partie générée a bougé…
        assert "Texte à la main." in text            # …mais le suffixe survit
        assert text.index(marqueur) < text.index("Texte à la main.")

    def test_sans_marqueur_le_fichier_est_remplace(self, tmp_path):
        out = tmp_path / "SYNTHESE.md"
        out.write_text("contenu obsolète sans marqueur", encoding="utf-8")
        preds = tmp_path / "preds.json"
        preds.write_text(json.dumps([_rec("a", "tp-link", "archer c6")]),
                         encoding="utf-8")
        grade_scale_run.main(["--preds", str(preds), "--out", str(out)])
        assert "contenu obsolète" not in out.read_text(encoding="utf-8")


class TestCorpsDeReponse:
    def test_corps_complet_accepte(self):
        class R:
            headers = {"Content-Length": "3"}
            def read(self):
                return b"abc"
        assert refill_cache.read_complete(R()) == b"abc"

    def test_corps_tronque_rejette(self):
        class R:
            headers = {"Content-Length": "10"}
            def read(self):
                return b"abc"       # coupé de 7 octets, sans erreur HTTP
        with pytest.raises(ValueError, match="tronqué"):
            refill_cache.read_complete(R())

    def test_sans_content_length_on_fait_confiance(self):
        class R:
            headers = {}
            def read(self):
                return b"abc"
        assert refill_cache.read_complete(R()) == b"abc"


class TestFormesDeManifeste:
    def test_manifeste_liste(self):
        assert len(refill_cache.iter_items([{"image_id": "a"}])) == 1

    def test_manifeste_dict_items_et_brand_only(self):
        man = {"items": [{"image_id": "a"}], "brand_only": [{"image_id": "b"}]}
        assert [it["image_id"] for it in refill_cache.iter_items(man)] == ["a", "b"]

    def test_scale_distributed_accepte_la_liste(self):
        # Le manifeste de refetch est une liste : `man["items"]` plantait en run.
        ids = [it["image_id"] for it in
               scale_distributed.select_items([{"image_id": "a"}], True)]
        assert ids == ["a"]

    def test_scale_distributed_dict_sans_puis_avec_brand_only(self):
        man = {"items": [{"image_id": "a"}], "brand_only": [{"image_id": "b"}]}
        assert [it["image_id"] for it in
                scale_distributed.select_items(man, False)] == ["a"]
        assert [it["image_id"] for it in
                scale_distributed.select_items(man, True)] == ["a", "b"]
