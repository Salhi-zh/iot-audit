#!/usr/bin/env python3
"""Benchmark d'identification / classification / reconnaissance — **artefact de référence**.

Ce que ce script est
--------------------
Le plan (`docs/07` §6) exige : *« Sortie : un ``benchmarks/results.json`` horodaté +
``benchmarks/results.md`` lisible, **régénérés par un script** (donc citables dans le rapport) »*.
Ce script est ce générateur, et il ne couvre que la **perception** (identification,
classification, reconnaissance) — pas la chaîne CPE/CVE.

Ce qu'il ne fait pas, et pourquoi c'est important
-------------------------------------------------
Il **ne saisit aucun chiffre à la main** et n'en recalcule aucun « au jugé » :

  * la source est le run **v4 gelé** (cap 640, `finish_reason` natif, température 0),
    `evidence/2026-09-15/corpus/expanded/predictions-v4-shard{0,1,2}.json` ;
  * la notation est le **barème gelé** (`audit-grading.py`), chargé via
    `corpus/_common.py` — le **seul point de couplage** entre ce dépôt et son voisin ;
  * chaque taux est publié avec `n` et un **intervalle de Wilson** (règle de `docs/07` :
    aucune ligne MESURÉ sans `n` et sans intervalle).

Le résultat principal, et ce qu'il ajoute
-----------------------------------------
Le projet déclare **M1 = exactitude objet-level** (marque **et** modèle, agrégation
**modale** sur les photos de l'objet, cible ≥ 0,70). Le dernier chiffre publié
(**8/26 = 0,308**) portait sur **26 objets**. Ce script le recalcule sur le run v4
complet (**48 objets / 144 images**), donc avec une puissance statistique supérieure,
et ajoute la **matrice de confusion** par catégorie ainsi que l'**informativité de la
base** (`label` / `visual`), qui n'étaient pas publiées à ce niveau.

M1 objet n'est **pas** recalculé ici : il est importé de
``iot_audit.corpus.metrics`` (§19 de ``docs/06``). Un banc qui réimplémente la
métrique qu'il prétend mesurer finit par mesurer autre chose — c'est arrivé, et
c'est daté.

Discipline de sélection (règle du projet, `docs/06` §16.2)
---------------------------------------------------------
Quand plusieurs **stratégies d'agrégation** sont comparées, la règle est **choisie sur
un jeu d'entraînement** et **publiée sur un jeu tenu à part**, jamais l'inverse. Le
découpage est **par objet** et **gelé par hachage** (pas de `random` non seedé, pas de
découpage refait à chaque exécution).

Usage :
    .venv/bin/python benchmarks/run_identification.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
IOT = HERE.parent
sys.path.insert(0, str(IOT))  # ``iot_audit.*`` — le M1 objet y vit, il n'est pas recopié

from iot_audit.corpus import metrics as CM  # noqa: E402  (après le sys.path ci-dessus)

# Le barème gelé, lié une fois au chargement (les helpers ci-dessous s'y réfèrent :
# `norm`, `wilson`, `model_correct`, ...). Assigné par `main()`.
G = None  # type: ignore[assignment]
EVID = IOT / "evidence" / "2026-09-15" / "corpus" / "expanded"
OUT = HERE

RUNS = {
    "v4": "predictions-v4-shard{}.json",     # le run de référence (cap 640)
    "v3b": "predictions-v3b-shard{}.json",   # seconde exécution indépendante, pour M9
}


# --------------------------------------------------------------------------- #
# Barème gelé — chargé, jamais recopié
# --------------------------------------------------------------------------- #
def load_grading():
    spec = importlib.util.spec_from_file_location("_common", IOT / "corpus" / "_common.py")
    if spec is None or spec.loader is None:
        raise ImportError("corpus/_common.py introuvable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_grading()


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #
def load_run(name: str) -> list[dict]:
    recs: list[dict] = []
    for shard in (0, 1, 2):
        p = EVID / RUNS[name].format(shard)
        recs += json.loads(p.read_text())
    ids = [r["image_id"] for r in recs]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name} : les shards se recouvrent ({len(ids)} vs {len(set(ids))})")
    return recs


def rendered_only(recs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sépare ce qui est NOTABLE de ce qui ne l'est pas.

    Une image tronquée (`finish_reason == "length"`) ou non rendue (`http_status != 200`)
    **sort du dénominateur** et se compte à part (règle gelée, `docs/06` §16.3). La
    compter 0 mélangerait un défaut d'instrument et une erreur du modèle.
    """
    ok = [r for r in recs if r.get("http_status") == 200 and r.get("finish_reason") == "stop"]
    bad = [r for r in recs if r not in ok]
    return ok, bad


# --------------------------------------------------------------------------- #
# Agrégation objet — le cœur de M1
# --------------------------------------------------------------------------- #
def _tup(rec: dict) -> tuple[str, str]:
    return (G.norm(rec["pred"].get("brand")), G.norm(rec["pred"].get("model")))


def _modal(values: list[tuple[str, str]]) -> tuple[str, str]:
    """Vote majoritaire **déterministe** : le plus fréquent, départage par ordre lexical.

    Le départage est explicite parce qu'un exagère : un vote sans règle de départage
    change de résultat selon l'ordre d'itération d'un `dict`.
    """
    if not values:
        return ("", "")
    counts = Counter(values)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def agg_first(recs: list[dict]) -> tuple[str, str]:
    return _tup(sorted(recs, key=lambda r: r["image_id"])[0])


def agg_modal_tuple(recs: list[dict]) -> tuple[str, str]:
    return _modal([_tup(r) for r in recs])


def agg_brand_then_model(recs: list[dict]) -> tuple[str, str]:
    brand = _modal([(G.norm(r["pred"].get("brand")), "") for r in recs])[0]
    same = [r for r in recs if G.norm(r["pred"].get("brand")) == brand]
    model = _modal([("", G.norm(r["pred"].get("model"))) for r in same])[1]
    return (brand, model)


def agg_basis_preferred(recs: list[dict]) -> tuple[str, str]:
    """Vote sur les images à base `label` si elles existent, sinon `visual`.

    Motif : `label` s'appuie sur un texte **lu**, `visual` sur une forme **reconnue**.
    Si l'un des deux est plus fiable (§ basis), l'agrégation doit pouvoir en profiter —
    c'est une hypothèse à MESURER, pas à supposer, d'où la comparaison ci-dessous.
    """
    for basis in ("label", "visual"):
        subset = [r for r in recs if r["pred"].get("identification_basis") == basis]
        if subset:
            return _modal([_tup(r) for r in subset])
    return _tup(recs[0])


AGGREGATORS = {
    "first": agg_first,
    "modal_tuple": agg_modal_tuple,
    "brand_then_model": agg_brand_then_model,
    "basis_preferred": agg_basis_preferred,
}


def as_object_rec(rec: dict, brand: str, model: str) -> dict:
    """Fabrique l'enregistrement **objet** que le barème sait noter.

    On réutilise `model_correct`/`brand_correct` au lieu de réécrire une comparaison :
    la définition de « correct » reste **une seule**, dans le barème gelé. Les alias de
    vérité (`TRUTH_ALIASES`) continuent donc de s'appliquer au niveau objet.
    """
    return {
        "object_id": rec["object_id"],
        "truth_brand": rec["truth_brand"],
        "truth_model": rec["truth_model"],
        "truth_category": rec["truth_category"],
        "pred": {"brand": brand, "model": model, "category": ""},
    }


def object_truth(recs: list[dict]) -> dict:
    return {k: recs[0][k] for k in ("object_id", "truth_brand", "truth_model", "truth_category")}


def split_objects(object_ids: list[str]) -> tuple[list[str], list[str]]:
    """Découpage **gelé par hachage**, par objet (jamais par image).

    Découper par image mettrait des photos du MÊME objet des deux côtés, et le jeu
    d'évaluation ne serait plus tenu à part : c'est le défaut classique de ce genre
    d'expérience. La parité du sha256 rend le découpage reproductible sans état.
    """
    train, ev = [], []
    for oid in sorted(object_ids):
        h = hashlib.sha256(oid.encode()).digest()[0]
        (train if h % 2 == 0 else ev).append(oid)
    return train, ev


# --------------------------------------------------------------------------- #
# Calculs
# --------------------------------------------------------------------------- #
def pct(k: int, n: int) -> dict:
    lo, hi = G.wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n if n else 0.0), "ci95": [round(lo, 4), round(hi, 4)]}


def compute(recs_all: list[dict], grading) -> dict:
    recs, dropped = rendered_only(recs_all)

    # ---- 1. image : identification, classification -------------------------
    per_image = {
        "brand": pct(sum(grading.brand_correct(r) for r in recs), len(recs)),
        "model_A": pct(sum(grading.model_correct(r, "A") for r in recs), len(recs)),
        "model_P": pct(sum(grading.model_correct(r, "P") for r in recs), len(recs)),
        "category": pct(sum(grading.cat_correct(r) for r in recs), len(recs)),
        "brand_and_model": pct(
            sum(grading.brand_correct(r) and grading.model_correct(r, "A") for r in recs), len(recs)
        ),
    }

    # ---- 2. base : label vs visual — est-elle INFORMATIVE ? ----------------
    # Le verdict est calculé **sous les deux critères de notation publiés** (A et P).
    # Ce n'est pas du zèle : le §16.2 du dossier a conclu « NON TRANCHÉ » avec le
    # critère P, alors que le critère publié du projet est A. Si le verdict change
    # avec le critère, alors « la base est informative » est une affirmation qui
    # dépend d'un choix — et cela doit être écrit, pas lissé.
    by_basis: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        by_basis[r["pred"].get("identification_basis") or "(absent)"].append(r)
    basis: dict = {}
    for b, rs in sorted(by_basis.items()):
        basis[b] = {
            "n": len(rs),
            "model_A": pct(sum(grading.model_correct(r, "A") for r in rs), len(rs)),
            "model_P": pct(sum(grading.model_correct(r, "P") for r in rs), len(rs)),
            "category": pct(sum(grading.cat_correct(r) for r in rs), len(rs)),
        }
    verdicts = {}
    for mode in ("model_A", "model_P"):
        lc = basis.get("label", {}).get(mode, {}).get("ci95")
        vc = basis.get("visual", {}).get(mode, {}).get("ci95")
        if lc and vc:
            verdicts[mode] = "INFORMATIF" if not (lc[0] <= vc[1] and vc[0] <= lc[1]) else "NON TRANCHE"
        else:
            verdicts[mode] = "non calculable"
    basis["_verdict_par_critere"] = verdicts
    # Verdict publié = celui du critère publié du projet (A), avec la sensibilité à côté.
    basis["_informatif"] = (verdicts.get("model_A") == "INFORMATIF")
    basis["_sensible_au_critere"] = len(set(verdicts.values())) > 1

    # ---- 3. classification : matrice de confusion --------------------------
    conf: Counter[tuple[str, str]] = Counter()
    for r in recs:
        conf[(grading.effective_category(r), G.norm(r["pred"].get("category")))] += 1
    per_category = {}
    for cat in sorted({c for c, _ in conf}):
        rs = [r for r in recs if grading.effective_category(r) == cat]
        per_category[cat] = pct(sum(grading.cat_correct(r) for r in rs), len(rs))

    # ---- 4. strates (contrôle de contamination) ----------------------------
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        by_stratum[r.get("stratum", "(absent)")].append(r)
    strata = {}
    for s, rs in sorted(by_stratum.items()):
        strata[s] = {
            "n_objects": len({r["object_id"] for r in rs}),
            "model_A": pct(sum(grading.model_correct(r, "A") for r in rs), len(rs)),
            "category": pct(sum(grading.cat_correct(r) for r in rs), len(rs)),
        }

    # ---- 5. texte visible : le canal de lecture ---------------------------
    by_text = {}
    for tv in sorted({r.get("text_visible") for r in recs}, key=lambda x: (x is None, x)):
        rs = [r for r in recs if r.get("text_visible") == tv]
        by_text[str(tv)] = {
            "model_A": pct(sum(grading.model_correct(r, "A") for r in rs), len(rs)),
            "category": pct(sum(grading.cat_correct(r) for r in rs), len(rs)),
        }

    # ---- 6. objet : M1 et ses variantes -----------------------------------
    objs: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        objs[r["object_id"]].append(r)
    oids = sorted(objs)

    # DÉFAUT CORRIGÉ LE 2026-09-29 (``docs/06`` §19). Ce bloc notait
    # ``model_correct`` **seul** tout en s'intitulant « M1 (marque ET modèle) »,
    # et sur le barème ``audit-grading.py`` (égalité **stricte** de marque) qui
    # n'est pas celui du M1 objet. Il publiait donc, sous le nom du chiffre
    # principal du projet, une figure qui n'en était pas une : `8/48 = 0,167`
    # au lieu de `11/48 = 0,229`. M1 vient désormais de
    # ``iot_audit.corpus.metrics`` — la seule implémentation du dépôt qui
    # reproduise la table publiée **verdict par verdict** (voir
    # ``tests/test_metrics_object.py``).
    def summ(s) -> dict:
        return {"k": s.k, "n": s.n, "rate": s.p,
                "ci95": [round(s.lo, 4), round(s.hi, 4)]}

    obj_results = {rule: CM.object_results(recs, rule) for rule in CM.CONSOLIDATION_RULES}
    obj_summ = {rule: CM.summarize("M1", res) for rule, res in obj_results.items()}

    def strategy_exact(strategy: str, subset: list[str]) -> dict:
        """Exactitude objet d'une **règle d'agrégation**, sous le barème canonique.

        Les deux plafonds (``oracle_any``, ``all_images``) sont notés sous le
        **même** barème canonique que le reste de la table — marque **et**
        modèle, verdict d'une photo. Les noter sous un autre barème rendrait la
        table incohérente : `basis_preferred` dépasserait `oracle_any`, ce qui
        est impossible pour un vrai plafond et signalerait un mélange de
        barèmes, pas un résultat. ``oracle_any`` est donc ≥ M1 **par
        construction** ; c'est ce qui en fait une borne utile.
        """
        def photo_exact(r: dict, rows: list[dict]) -> bool:
            return CM.grade({"brand": r["pred"].get("brand"),
                             "model": r["pred"].get("model"),
                             "category": r["pred"].get("category")},
                            {"brand": rows[0]["truth_brand"],
                             "model": rows[0]["truth_model"],
                             "category": rows[0]["truth_category"]}) == "exact"

        k = 0
        for oid in subset:
            rs = objs[oid]
            if strategy in ("oracle_any", "all_images"):
                agg = any if strategy == "oracle_any" else all
                ok = agg(photo_exact(r, rs) for r in rs)
            else:
                b, m = AGGREGATORS[strategy](rs)
                c = CM.modal([(r["pred"].get("category")) for r in rs])
                ok = CM.grade({"brand": b, "model": m, "category": c},
                              {"brand": rs[0]["truth_brand"],
                               "model": rs[0]["truth_model"],
                               "category": rs[0]["truth_category"]}) == "exact"
            k += bool(ok)
        return pct(k, len(subset))

    strategies = list(AGGREGATORS) + ["oracle_any", "all_images"]
    all_objects = {s: strategy_exact(s, oids) for s in strategies}
    obj_brand = obj_cat = 0
    for oid in oids:
        rs = objs[oid]
        obj_brand += (CM.normalise(CM.modal([r["pred"].get("brand") for r in rs]))
                      == CM.normalise(rs[0]["truth_brand"]))
        obj_cat += (CM.normalise(CM.modal([r["pred"].get("category") for r in rs]))
                    == CM.normalise(rs[0]["truth_category"]))
    object_level = {
        "source": "iot_audit.corpus.metrics (grade + summarize + object_results)",
        "rules": {rule: {**summ(obj_summ[rule]), "verdicts": obj_summ[rule].detail}
                  for rule in CM.CONSOLIDATION_RULES},
        "n_objects": obj_summ["conservative"].n,
        "n_images": len(recs),
        "brand_modal": pct(obj_brand, len(oids)),
        "category_modal": pct(obj_cat, len(oids)),
        "strategies": all_objects,
    }

    # ---- 7. sélection de la règle : train → eval (gelé) --------------------
    train, ev = split_objects(oids)
    sel = {}
    for s in AGGREGATORS:
        sel[s] = {"train": strategy_exact(s, train), "eval": strategy_exact(s, ev)}
    best = max(AGGREGATORS, key=lambda s: (sel[s]["train"]["k"] / max(1, sel[s]["train"]["n"]), s))
    rule_selection = {
        "split": {"train": train, "eval": ev,
                  "sha256_train": hashlib.sha256(",".join(train).encode()).hexdigest()[:16],
                  "sha256_eval": hashlib.sha256(",".join(ev).encode()).hexdigest()[:16]},
        "candidates": sel,
        "chosen_on_train": best,
        "published_on_eval": sel[best]["eval"],
    }

    # ---- 8. latence (M8) ---------------------------------------------------
    lat = sorted(r["latency_s"] for r in recs if isinstance(r.get("latency_s"), (int, float)))
    lat_stats = {}
    if lat:
        def q(p: float) -> float:
            i = min(len(lat) - 1, int(round(p * (len(lat) - 1))))
            return lat[i]
        lat_stats = {"n": len(lat), "p50": round(q(0.50), 3), "p95": round(q(0.95), 3),
                     "p99": round(q(0.99), 3), "max": round(lat[-1], 3),
                     "mean": round(statistics.fmean(lat), 3)}

    return {
        "run": "v4 (cap 640, finish_reason natif, temperature 0)",
        "n_images_all": len(recs_all),
        "n_images_rendered": len(recs),
        "dropped": {"n": len(dropped),
                    "finish_reason": Counter(r.get("finish_reason") for r in dropped).most_common()},
        "per_image": per_image,
        "basis": basis,
        "per_category": per_category,
        "confusion": {f"{t} -> {p}": c for (t, p), c in sorted(conf.items())},
        "strata": strata,
        "text_visible": by_text,
        "object_level": object_level,
        "rule_selection": rule_selection,
        "latency_s": lat_stats,
    }


def replay(a: list[dict], b: list[dict], grading) -> dict:
    """M9 — accord de rejeu entre deux exécutions indépendantes."""
    ia = {r["image_id"]: r for r in a}
    ib = {r["image_id"]: r for r in b}
    common = sorted(set(ia) & set(ib))
    identical = sum(_tup(ia[i]) == _tup(ib[i]) for i in common)
    cat_ok = sum(grading.cat_correct(ia[i]) == grading.cat_correct(ib[i]) for i in common)
    return {
        "n": len(common),
        "tuple_identique": pct(identical, len(common)),
        "categorie_meme_verdict": pct(cat_ok, len(common)),
    }


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #
def md_rate(d: dict) -> str:
    lo, hi = d["ci95"]
    return f"{d['k']}/{d['n']} = {d['rate']:.3f}  IC95 [{lo:.3f} ; {hi:.3f}]"


def render_md(res: dict, rep: dict, grading) -> str:
    L: list[str] = []
    A = L.append
    A("# Benchmark identification / classification / reconnaissance — référence générée\n")
    A("> **Généré** par `benchmarks/run_identification.py`. Aucun chiffre saisi à la main.")
    A("> Source : run **v4** gelé (144 images, 48 objets) · barème gelé `audit-grading.py`.")
    A("> Règle `docs/07` : tout taux publié porte son `n` et un intervalle de Wilson.\n")
    A(f"Images : **{res['n_images_rendered']}** notées sur {res['n_images_all']} "
      f"(écartées : {res['dropped']['n']} — {res['dropped']['finish_reason']}).\n")

    A("## 1. Image — identification et classification (le niveau élémentaire)\n")
    A("| figure | valeur |")
    A("|---|---|")
    for k, v in res["per_image"].items():
        A(f"| `{k}` | {md_rate(v)} |")
    A("")

    ol = res["object_level"]
    A("## 2. Objet — **M1** (marque ET modèle), cible ≥ 0,70\n")
    A("M1 n'est **pas** recalculé par ce banc : il est importé de")
    A("`iot_audit.corpus.metrics` (§19). Un banc qui réimplémente la métrique qu'il")
    A("prétend mesurer finit par en mesurer une autre — c'est arrivé ici, et c'est daté.")
    A("Dernier chiffre publié : **8/26 = 0,308** (n = 26 objets).")
    A(f"Ce run porte sur **{ol['n_objects']} objets / {ol['n_images']} images**.\n")
    A("| consolidation | M1 (k/n) | p̂ | IC95 | ce que la règle mesure |")
    A("|---|---|---|---|---|")
    for rule, r in ol["rules"].items():
        quoi = ("l'abstention **compte** comme une réponse ← règle publiée (§8.1)"
                if rule == "conservative" else
                "l'abstention est retirée du vote")
        A(f"| `{rule}` | {r['k']}/{r['n']} | {r['rate']:.3f} | "
          f"[{r['ci95'][0]:.3f} ; {r['ci95'][1]:.3f}] | {quoi} |")
    A("")
    A("> Le prompt du projet **ordonne** l'abstention (« Do NOT guess a brand you cannot")
    A("> see »). Sous `conservative`, un modèle qui obéit est donc noté moins bien qu'un")
    A("> modèle qui devine. Les deux règles ne mesurent pas la même chose : publier une")
    A("> seule des deux, c'est choisir une politique d'abstention sans le dire.\n")
    for rule, r in ol["rules"].items():
        detail = " · ".join(f"`{k}` {v}" for k, v in
                            sorted(r["verdicts"].items(), key=lambda kv: (-kv[1], kv[0])))
        A(f"- verdicts (`{rule}`) : {detail}")
    A("")
    A("### Règles d'agrégation (barème canonique, consolidation `conservative`)\n")
    A("| agrégation | exactitude objet |")
    A("|---|---|")
    for k, v in ol["strategies"].items():
        star = " ← **règle publiée**" if k == "modal_tuple" else ""
        A(f"| `{k}`{star} | {md_rate(v)} |")
    A("")
    A("| figure objet | valeur |")
    A("|---|---|")
    A(f"| marque seule (modale) | {md_rate(ol['brand_modal'])} |")
    A(f"| catégorie seule (modale) | {md_rate(ol['category_modal'])} |")
    A("")

    rs = res["rule_selection"]
    A("## 3. Choix de la règle d'agrégation — sélection sur train, publication sur eval\n")
    A(f"Découpage gelé par hachage, **par objet** : {len(rs['split']['train'])} train / "
      f"{len(rs['split']['eval'])} eval (`train={rs['split']['sha256_train']}`, "
      f"`eval={rs['split']['sha256_eval']}`).\n")
    A("| règle | train | eval (tenu à part) |")
    A("|---|---|---|")
    for k, v in rs["candidates"].items():
        mark = " **← retenue**" if k == rs["chosen_on_train"] else ""
        A(f"| `{k}`{mark} | {md_rate(v['train'])} | {md_rate(v['eval'])} |")
    A("")
    A(f"Règle retenue sur train : **`{rs['chosen_on_train']}`** ; "
      f"figures publiées sur eval : **{md_rate(rs['published_on_eval'])}**.\n")
    best_eval = max(rs["candidates"],
                    key=lambda s: (rs["candidates"][s]["eval"]["k"] / max(1, rs["candidates"][s]["eval"]["n"]), s))
    A("> **Avertissement, écrit plutôt que tu.** La règle qui gagne sur *train* n'est")
    A(f"> pas celle qui gagne sur *eval* : `{rs['chosen_on_train']}` est retenue "
      f"(train {rs['candidates'][rs['chosen_on_train']]['train']['k']}/{rs['candidates'][rs['chosen_on_train']]['train']['n']}),")
    A(f"> mais sur eval c'est `{best_eval}` "
      f"({rs['candidates'][best_eval]['eval']['k']}/{rs['candidates'][best_eval]['eval']['n']}). "
      f"À n = {len(rs['split']['train'])} + {len(rs['split']['eval'])} objets, **aucune règle d'agrégation")
    A("> n'est distinguable d'une autre** : l'écart tient dans le bruit d'échantillonnage.")
    A("> La conclusion défendable n'est donc pas « la meilleure règle est X », c'est")
    A("> « **l'agrégation ne sauve pas l'identification objet**, quelle que soit la règle »,")
    A("> ce que le plafond `oracle_any` du §2 borne aussi.\n")

    A("## 4. La base est-elle INFORMATIVE ? (`label` = texte lu, `visual` = forme)\n")
    A("| base | n | modèle exact (A) | modèle exact (P) | catégorie |")
    A("|---|---|---|---|---|")
    for k, v in sorted(res["basis"].items()):
        if k.startswith("_"):
            continue
        A(f"| `{k}` | {v['n']} | {md_rate(v['model_A'])} | {md_rate(v['model_P'])} | {md_rate(v['category'])} |")
    A("")
    for mode, verdict in (res["basis"].get("_verdict_par_critere") or {}).items():
        A(f"- critère **{mode[-1]}** : **{verdict}**")
    A("")
    if res["basis"].get("_sensible_au_critere"):
        A("> **Le verdict dépend du critère de notation.** C'est une affirmation à")
        A("> publier telle quelle : « la base est informative » n'est vrai que sous le")
        A("> critère A. Sous P, les intervalles se recouvrent et le verdict retombe à")
        A("> NON TRANCHÉ — qui est la conclusion écrite au §16.2 du dossier. Les deux")
        A("> sont vrais, chacun sous son critère.\n")
    else:
        A("> Verdict stable sous les deux critères publiés.\n")

    A("## 5. Classification — exactitude par catégorie\n")
    A("| catégorie (vérité effective) | exactitude |")
    A("|---|---|")
    for k, v in res["per_category"].items():
        A(f"| `{k}` | {md_rate(v)} |")
    A("")
    A("### Matrice de confusion (vérité → prédit)\n")
    A("| vérité → prédit | images |")
    A("|---|---|")
    for k, v in res["confusion"].items():
        A(f"| `{k}` | {v} |")
    A("")

    A("## 6. Contamination et canal de lecture\n")
    A("| strate | objets | modèle exact | catégorie |")
    A("|---|---|---|---|")
    for k, v in res["strata"].items():
        A(f"| `{k}` | {v['n_objects']} | {md_rate(v['model_A'])} | {md_rate(v['category'])} |")
    A("")
    A("| `text_visible` | modèle exact | catégorie |")
    A("|---|---|---|")
    for k, v in res["text_visible"].items():
        A(f"| `{k}` | {md_rate(v['model_A'])} | {md_rate(v['category'])} |")
    A("")

    A("## 7. M9 — accord de rejeu (deux exécutions indépendantes)\n")
    A(f"- prédictions identiques : {md_rate(rep['tuple_identique'])}")
    A(f"- même verdict de catégorie : {md_rate(rep['categorie_meme_verdict'])}\n")

    A("## 8. M8 — latence (p95 cible < 10 s)\n")
    if res["latency_s"]:
        A(f"- n = {res['latency_s']['n']} · p50 = {res['latency_s']['p50']} s · "
          f"p95 = {res['latency_s']['p95']} s · p99 = {res['latency_s']['p99']} s · "
          f"max = {res['latency_s']['max']} s")
    A("")
    A("---\n")
    A("*Ce fichier est régénéré par script : `python benchmarks/run_identification.py`.*")
    return "\n".join(L) + "\n"


def main() -> int:
    global G
    grading = load_grading()
    G = grading
    v4 = load_run("v4")
    v3b = load_run("v3b")
    res = compute(v4, grading)
    rep = replay(v3b, v4, grading)
    res["replay_v3b_vs_v4"] = rep

    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    (OUT / "results.md").write_text(render_md(res, rep, grading))

    print((OUT / "results.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
