#!/usr/bin/env python3
"""Compare un run de perception à la référence gelée, et publie l'écart.

Pourquoi un script dédié alors que ``run_identification.py`` existe
------------------------------------------------------------------
Parce que la question n'est pas « combien vaut ce run » mais « **qu'est-ce qui
change**, et est-ce que ça change pour de bonnes raisons ». Ce script ne
réimplémente donc **aucune** métrique : il importe ``run_identification`` et
appelle ``compute()``, la même fonction qui produit les figures publiées. Un
écart calculé par un second code ne serait pas un écart, ce serait une seconde
opinion.

Protocole, et pourquoi il est contraignant
------------------------------------------
1. **La référence est le run gelé v4** (144 images, 48 objets), jamais un run
   intermédiaire. **M1 vient de `iot_audit.corpus.metrics`** : réimplémenter la
   métrique ici a déjà produit un faux écart (voir §19 de `docs/06`).
2. **Le découpage objet est gelé par hachage** (``split_objects`` du banc) :
   23 objets d'apprentissage / 25 de publication. Le gain est **lu sur les 25
   objets tenus à part**, qui n'ont servi ni à diagnostiquer ni à choisir la
   variante. Le sous-ensemble d'apprentissage est publié à côté, pour montrer
   l'écart entre les deux — c'est là qu'un sur-ajustement se verrait.
3. **Les critères A *et* P sont publiés côte à côte.** Le critère P neutralise
   l'artefact de séparateur (`dir 600` vs `DIR-600`) ; publier A seul ferait
   passer une simple différence d'écriture pour une reconnaissance.
4. **Les effets de bord sont mesurés**, pas espérés : une variante qui remplit
   la marque plus souvent doit être jugée aussi sur les marques **fausses**
   qu'elle ajoute.

Usage :
    python3 benchmarks/run_variant_eval.py \
        --baseline evidence/2026-09-15/corpus/expanded/predictions-v4-shard{0,1,2}.json \
        --variant  evidence/2026-09-29/recognition-v5/predictions.json \
        --tag v5
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"module non chargeable : {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bench = _load("bench_ident", HERE / "run_identification.py")
common = _load("_common", ROOT / "corpus" / "_common.py")
GRADING = common.load_grading()
bench.G = GRADING          # les agrégateurs du banc passent par ce global

# M1 objet n'est pas recalculé ici : il est importé du dépôt (§19 de docs/06).
from iot_audit.corpus import metrics as CM  # noqa: E402


def load_sharded(pattern: str) -> list[dict]:
    """Charge un run gelé éclaté en shards (``{0,1,2}``), ou un fichier unique."""
    if "{0}" in pattern:
        recs: list[dict] = []
        for i in (0, 1, 2):
            recs += json.loads(Path(pattern.replace("{0}", str(i))).read_text())
        return recs
    return json.loads(Path(pattern).read_text())


def obj_metrics(recs: list[dict]) -> dict:
    """M1 au niveau objet — **importé**, pas recalculé (§19).

    Comme ``run_identification.compute()``, ce script ne réimplémente plus M1 :
    il appelle ``iot_audit.corpus.metrics``. La version antérieure notait le
    modèle seul *sous l'étiquette* M1 et sur le barème ``audit-grading`` : elle
    a publié un écart qui n'existait pas (`8/48` au lieu de `11/48`).
    """
    objs: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        objs[r["object_id"]].append(r)
    oids = sorted(objs)

    out: dict = {"n_objets": len(oids), "source": "iot_audit.corpus.metrics"}
    for rule in CM.CONSOLIDATION_RULES:
        s = CM.summarize("M1", CM.object_results(recs, rule))
        out[rule] = {"k": s.k, "n": s.n, "rate": s.p,
                     "ci95": [round(s.lo, 4), round(s.hi, 4)], "verdicts": s.detail}

    # Règles d'agrégation concurrentes, sous le barème canonique.
    def rate(strategy: str) -> dict:
        """Même barème canonique pour **toutes** les lignes, plafonds compris.

        Noter `oracle_any` sous un autre barème le rendrait inférieur à une
        règle d'agrégation, c'est-à-dire inutile comme plafond : un mélange de
        barèmes se lit comme un résultat.
        """
        def photo_exact(r: dict, rows: list[dict]) -> bool:
            return CM.grade({"brand": r["pred"].get("brand"),
                             "model": r["pred"].get("model"),
                             "category": r["pred"].get("category")},
                            {"brand": rows[0]["truth_brand"],
                             "model": rows[0]["truth_model"],
                             "category": rows[0]["truth_category"]}) == "exact"

        k = 0
        for oid in oids:
            rs = objs[oid]
            if strategy in ("oracle_any", "all_images"):
                agg = any if strategy == "oracle_any" else all
                ok = agg(photo_exact(r, rs) for r in rs)
            else:
                b, m = bench.AGGREGATORS[strategy](rs)
                c = CM.modal([r["pred"].get("category") for r in rs])
                ok = CM.grade({"brand": b, "model": m, "category": c},
                              {"brand": rs[0]["truth_brand"],
                               "model": rs[0]["truth_model"],
                               "category": rs[0]["truth_category"]}) == "exact"
            k += bool(ok)
        return bench.pct(k, len(oids))

    for s in list(bench.AGGREGATORS) + ["oracle_any", "all_images"]:
        out[f"agregation_{s}"] = rate(s)

    brand = cat = 0
    for oid in oids:
        rs = objs[oid]
        brand += (CM.normalise(CM.modal([r["pred"].get("brand") for r in rs]))
                  == CM.normalise(rs[0]["truth_brand"]))
        cat += (CM.normalise(CM.modal([r["pred"].get("category") for r in rs]))
                == CM.normalise(rs[0]["truth_category"]))
    out["marque_seule_modal"] = bench.pct(brand, len(oids))
    out["categorie_seule_modal"] = bench.pct(cat, len(oids))
    return out


def per_object_pass(recs: list[dict], rule: str = "conservative") -> dict[str, bool]:
    """Un objet « passe » si le verdict canonique vaut ``exact``.

    Passe par ``iot_audit.corpus.metrics`` : le découpage train/eval et les
    bascules « gagné/perdu » portent donc sur **la même** définition que M1.
    """
    return {r.object_id: r.verdict == "exact"
            for r in CM.object_results(recs, rule)}


def side_effects(recs: list[dict]) -> dict:
    """Ce que la variante fait *en plus* : marques remplies, et marques fausses."""
    n = len(recs)
    filled = sum(1 for r in recs if (r["pred"].get("brand") or "").strip())
    right = sum(1 for r in recs if GRADING.brand_correct(r))
    wrong = sum(1 for r in recs
                if (r["pred"].get("brand") or "").strip() and not GRADING.brand_correct(r))
    empty_model = sum(1 for r in recs if not (r["pred"].get("model") or "").strip())
    return {
        "marque_non_vide": bench.pct(filled, n),
        "marque_juste": bench.pct(right, n),
        "marque_FAUSSE": bench.pct(wrong, n),
        "modele_vide": bench.pct(empty_model, n),
        "precision_marque": round(right / filled, 4) if filled else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", default=str(
        ROOT / "evidence/2026-09-15/corpus/expanded/predictions-v4-shard{0}.json"))
    ap.add_argument("--variant", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    base = load_sharded(args.baseline)
    var = load_sharded(args.variant)
    ib = {r["image_id"]: r for r in base}
    iv = {r["image_id"]: r for r in var}
    if set(ib) != set(iv):
        raise SystemExit(f"périmètres différents : {len(set(ib) ^ set(iv))} images")
    if len(ib) != 144:
        raise SystemExit(f"perimètre inattendu : {len(ib)} images (144 attendues)")
    base, var = [ib[i] for i in sorted(ib)], [iv[i] for i in sorted(iv)]

    cb, cv = bench.compute(base, GRADING), bench.compute(var, GRADING)
    ob, ov = obj_metrics(base), obj_metrics(var)

    # découpage gelé par objet
    train, ev = bench.split_objects(sorted({r["object_id"] for r in base}))
    pb, pv = per_object_pass(base), per_object_pass(var)
    split = {
        "train": {"n": len(train),
                  "baseline": sum(pb[o] for o in train), "variante": sum(pv[o] for o in train)},
        "eval": {"n": len(ev),
                 "baseline": sum(pb[o] for o in ev), "variante": sum(pv[o] for o in ev)},
    }

    flips_up = sorted(o for o in pv if pv[o] and not pb[o])
    flips_down = sorted(o for o in pv if not pv[o] and pb[o])
    changed = sorted(i for i in ib
                     if json.dumps(ib[i].get("pred"), sort_keys=True)
                     != json.dumps(iv[i].get("pred"), sort_keys=True))

    out = {
        "_note": f"Écart du run « {args.tag} » par rapport à la référence gelée v4.",
        "tag": args.tag,
        "baseline": args.baseline,
        "variant": args.variant,
        "criterion_note": "A = égalité stricte (critère publié du contrat) ; "
                          "P = séparateur neutralisé (tiret/souligné = espace)",
        "image": {"baseline": cb["per_image"], "variante": cv["per_image"],
                  "brand_and_model_P": {
                      "baseline": bench.pct(sum(
                          GRADING.brand_correct(r) and GRADING.model_correct(r, "P")
                          for r in base), len(base)),
                      "variante": bench.pct(sum(
                          GRADING.brand_correct(r) and GRADING.model_correct(r, "P")
                          for r in var), len(var)),
                  }},
        "objet": {"baseline": ob, "variante": ov},
        "decoupage_gele": split,
        "effets_de_bord": {"baseline": side_effects(base), "variante": side_effects(var)},
        "images_changees": len(changed),
        "objets_gagnes": flips_up,
        "objets_perdus": flips_down,
        "details_objets_gagnes": [
            {"object_id": o,
             "verite": f"{ib[[i for i in ib if ib[i]['object_id'] == o][0]]['truth_brand']}"
                       f" / {ib[[i for i in ib if ib[i]['object_id'] == o][0]]['truth_model']}",
             "baseline": bench.agg_modal_tuple([ib[i] for i in ib if ib[i]["object_id"] == o]),
             "variante": bench.agg_modal_tuple([iv[i] for i in iv if iv[i]["object_id"] == o])}
            for o in flips_up],
    }
    out["_verdict"] = {
        "gagne_des_objets": len(flips_up) > len(flips_down),
        "gagne_sur_eval": split["eval"]["variante"] > split["eval"]["baseline"],
        "n_pertes": len(flips_down),
    }

    outp = Path(args.out) if args.out else HERE / f"recognition-{args.tag}.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    def line(label: str, b: dict, v: dict) -> str:
        return (f"| {label} | {b['k']}/{b['n']} = {b['rate']:.3f} | "
                f"{v['k']}/{v['n']} = {v['rate']:.3f} | "
                f"{(v['rate'] - b['rate']) * 100:+.1f} pt |")

    L = [f"# Écart du run `{args.tag}` par rapport à la référence gelée v4\n",
         "> Généré par `benchmarks/run_variant_eval.py`. Barème gelé, "
         "`compute()` du banc (métriques identiques à la publication).",
         f"> Variante : `{Path(args.variant).name}` · "
         f"images modifiées : **{len(changed)}/144**.\n",
         "## Image (n = 144)\n", "| figure | v4 gelé | variante | écart |", "|---|---|---|---|"]
    for k in ("brand", "model_A", "model_P", "category"):
        L.append(line(f"`{k}`", cb["per_image"][k], cv["per_image"][k]))
    L.append(line("`brand` ET `model` (A)", cb["per_image"]["brand_and_model"],
                  cv["per_image"]["brand_and_model"]))
    L.append(line("`brand` ET `model` (P)", out["image"]["brand_and_model_P"]["baseline"],
                  out["image"]["brand_and_model_P"]["variante"]))

    L += ["", "## Objet — **M1** (marque ET modèle), `iot_audit.corpus.metrics`\n",
          "| figure | v4 gelé | variante | écart |", "|---|---|---|---|"]
    for rule in CM.CONSOLIDATION_RULES:
        L.append(line(f"M1 `{rule}`", ob[rule], ov[rule]))
    for k in ("agregation_modal_tuple", "agregation_oracle_any", "agregation_first",
              "marque_seule_modal", "categorie_seule_modal"):
        L.append(line(f"`{k}`", ob[k], ov[k]))
    L.append("")
    L.append(f"`n_objets` = {ob['n_objets']} des deux côtés. "
             f"Rappel : `conservative` compte l'abstention comme une réponse "
             f"(règle publiée) ; `answered` ne compte que les réponses.\n")

    L += ["## Découpage objet gelé (23 train / 25 eval)\n",
          "| sous-ensemble | v4 gelé | variante | écart |", "|---|---|---|---|"]
    for name in ("train", "eval"):
        s = split[name]
        L.append(f"| {name} ({s['n']} objets) | {s['baseline']}/{s['n']} = "
                 f"{s['baseline'] / s['n']:.3f} | {s['variante']}/{s['n']} = "
                 f"{s['variante'] / s['n']:.3f} | "
                 f"{(s['variante'] - s['baseline']) / s['n'] * 100:+.1f} pt |")
    L.append("\n> La figure publiable est celle du sous-ensemble **eval**, tenu à "
             "part du diagnostic.\n")

    L += ["## Effets de bord (marque)\n", "| figure | v4 gelé | variante |", "|---|---|---|"]
    sb, sv = out["effets_de_bord"]["baseline"], out["effets_de_bord"]["variante"]
    for k in ("marque_non_vide", "marque_juste", "marque_FAUSSE", "modele_vide"):
        L.append(f"| `{k}` | {sb[k]['k']}/{sb[k]['n']} = {sb[k]['rate']:.3f} | "
                 f"{sv[k]['k']}/{sv[k]['n']} = {sv[k]['rate']:.3f} |")
    L.append(f"| précision de la marque (justes / non vides) | "
             f"{sb['precision_marque']} | {sv['precision_marque']} |")

    L += ["", f"## Objets gagnés ({len(flips_up)}) et perdus ({len(flips_down)})\n"]
    for d in out["details_objets_gagnes"]:
        L.append(f"- ✅ `{d['object_id']}` (vérité `{d['verite']}`) : "
                 f"modal {d['baseline']} → **{d['variante']}**")
    for o in flips_down:
        L.append(f"- ❌ `{o}` : perdu")
    L.append("")
    Path(outp).with_suffix(".md").write_text("\n".join(L), encoding="utf-8")

    print("\n".join(L))
    print(f"\nécrit : {outp} et {outp.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
