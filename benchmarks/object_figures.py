#!/usr/bin/env python3
"""Rapport **canonique** des figures objet d'un run — pour auditer `docs/06`.

Pourquoi cet outil
------------------
Les figures objet publiées avant le 2026-09-29 (§8, §9, §10, §14 de `docs/06`)
ont été produites par des *heredocs éphémères*, avec une règle de consolidation
qui n'a jamais été committée (`docs/06` §19.3). Impossible, donc, de savoir
lesquelles sont encore valides sans les recalculer **toutes** avec la seule
implémentation du dépôt (`iot_audit.corpus.metrics`).

Cet outil ne remplace pas `run_identification.py` (qui mesure un run contre sa
référence gelée) : il recalcule une **liste de figures nommées** pour un fichier
de prédictions quelconque, afin de comparer ligne à ligne ce qui est écrit dans
`docs/06`. Il imprime du Markdown, collable tel quel dans un avenant.

Figures produites
-----------------
* `M1 conservative` / `M1 answered` — la métrique du projet, les deux règles ;
* `M1b modèle seul`, `M1c catégorie seule` — les variantes du §8.1, au niveau
  **objet** (consolidation champ par champ, puis comparaison) ;
* `oracle_any` — plafond « une photo juste suffit » (borne du §17.2) ;
* par **strate** et par **catégorie** — les ventilations du §10 et du §14 ;
* par **`text_visible`** — aux niveaux image *et* objet (le canal, §19.4) ;
* `M6` si l'on passe un fichier de perturbations (variantes `kind=`).

Sémantique des comparaisons : celles de `metrics.grade` (marque, modèle et
catégorie *inclusive substring*, normalisées par `iot_audit.text.normalise`),
c'est-à-dire le barème du M1 objet — **pas** celui de `audit-grading.py`.

Usage :
    python3 benchmarks/object_figures.py \\
        --predictions evidence/2026-09-14/corpus/predictions-zabeth22.json \\
        --label "v1 — 26 objets (2026-09-14)"
    python3 benchmarks/object_figures.py \\
        --predictions evidence/2026-09-14/corpus/bench-zabeth22.json \\
        --perturbations --label "v1 + perturbations (M6)"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from iot_audit.corpus import metrics as M  # noqa: E402
from iot_audit.text import normalise  # noqa: E402


# --------------------------------------------------------------------------- #
# Comparaisons — même sémantique que metrics.grade, exposée champ par champ
# --------------------------------------------------------------------------- #
def _sub(a: str, b: str) -> bool:
    """Inclusion bidirectionnelle normalisée — la règle de `metrics.grade`."""
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def brand_ok(pred: str, truth: str) -> bool:
    return _sub(normalise(pred), normalise(truth))


def model_ok(pred: str, truth: str) -> bool:
    """`grade` considère « exact » quand la vérité n'a pas de modèle, dès que la marque passe."""
    pt, tt = normalise(pred), normalise(truth)
    if not tt:
        return True
    return _sub(pt, tt)


def cat_ok(pred: str, truth: str) -> bool:
    return bool(pred) and bool(truth) and normalise(pred) == normalise(truth)


# --------------------------------------------------------------------------- #
def load(path: Path) -> list[dict]:
    recs = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in recs
            if r.get("http_status", 200) == 200 and isinstance(r.get("pred"), dict)]


def group(recs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        out[r["object_id"]].append(r)
    for rows in out.values():
        rows.sort(key=lambda r: r.get("image_id", ""))   # ordre prescrit (§19.3)
    return dict(sorted(out.items()))


def row(k: int, n: int) -> str:
    if not n:
        return f"{k}/0 = —"
    lo, hi = M.wilson(k, n)
    return f"{k}/{n} = {k / n:.3f} IC95 [{lo:.3f} ; {hi:.3f}]"


def obj_rates(objs: dict[str, list[dict]], rule: str) -> dict[str, int]:
    """k par figure, consolidation `rule`, comparaisons champ par champ."""
    k = Counter()
    for _oid, rows in objs.items():
        p = M.consolidate_object(rows, rule)
        tb, tm = rows[0]["truth_brand"], rows[0]["truth_model"]
        tc = rows[0]["truth_category"]
        b, m, c = brand_ok(p["brand"], tb), model_ok(p["model"], tm), cat_ok(p["category"], tc)

        def m_ok(r: dict, _tm: str = tm) -> bool:
            return model_ok((r["pred"] or {}).get("model", ""), _tm)

        def bm_ok(r: dict, _tb: str = tb) -> bool:
            return (brand_ok((r["pred"] or {}).get("brand", ""), _tb) and m_ok(r))

        k["M1"] += b and m
        k["M1b"] += m
        k["M1c"] += c
        # Noms EXACTEMENT ceux du tableau §8.1 de `docs/06`, pour que la
        # comparaison ligne à ligne soit possible sans interprétation.
        k["M1_modele_sur_au_moins_1_photo"] += any(m_ok(r) for r in rows)
        k["M1_marque_et_modele_sur_au_moins_1_photo"] += any(bm_ok(r) for r in rows)
        k["toutes_les_photos"] += all(bm_ok(r) for r in rows)
    return k


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--predictions", required=True, type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--perturbations", action="store_true",
                    help="ventile par `kind` (M6) au lieu du tableau global")
    ap.add_argument("--variant", default=None,
                    help="ne garde qu'un `variant` (ex. CURVE, BASE-V1) — les fichiers "
                         "de banc mélangent plusieurs exécutions sous les mêmes `kind`")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    recs = load(args.predictions)
    if args.variant:
        recs = [r for r in recs if r.get("variant") == args.variant]
        if not recs:
            raise SystemExit(f"aucun enregistrement de variant {args.variant!r} dans "
                             f"{args.predictions}")
    objs = group(recs)
    label = args.label or args.predictions.name
    print(f"# Figures objet canoniques — {label}\n")
    print(f"Source : `{args.predictions}`" + (f" · variant `{args.variant}`" if args.variant else ""))
    print(f"Images notées **{len(recs)}** · objets **{len(objs)}** · "
          f"barème `iot_audit.corpus.metrics` (et non `audit-grading.py`)\n")

    out: dict = {"label": label, "source": str(args.predictions),
                 "n_images": len(recs), "n_objects": len(objs)}

    # ---- global -------------------------------------------------------- #
    print("## Global\n")
    print("| figure | n | `conservative` | `answered` |")
    print("|---|---|---|---|")
    n = len(objs)
    kc, ka = obj_rates(objs, "conservative"), obj_rates(objs, "answered")
    for fig, desc in (("M1", "marque **et** modèle"),
                      ("M1b", "modèle seul"),
                      ("M1c", "catégorie seule"),
                      ("M1_modele_sur_au_moins_1_photo", "modèle juste sur ≥ 1 photo"),
                      ("M1_marque_et_modele_sur_au_moins_1_photo",
                       "marque ET modèle sur ≥ 1 photo (plafond)"),
                      ("toutes_les_photos", "toutes les photos justes")):
        print(f"| `{fig}` ({desc}) | {n} | {row(kc[fig], n)} | {row(ka[fig], n)} |")
        out[fig] = {"conservative": kc[fig], "answered": ka[fig], "n": n}
    print()

    dist_c = Counter(r.verdict for r in M.object_results(recs, "conservative"))
    dist_a = Counter(r.verdict for r in M.object_results(recs, "answered"))
    print("Verdicts `conservative` : " +
          " · ".join(f"`{k}` {v}" for k, v in sorted(dist_c.items(), key=lambda kv: (-kv[1], kv[0]))))
    print()
    print("Verdicts `answered` : " +
          " · ".join(f"`{k}` {v}" for k, v in sorted(dist_a.items(), key=lambda kv: (-kv[1], kv[0]))))
    print()
    print("> ⚠️ `M1b` / `M1c` sont **au niveau objet** : consolidation champ par champ, puis\n"
          "> comparaison du seul champ considéré. Ce ne sont donc **pas** les mêmes nombres\n"
          "> que les taux image du §8.2 (qui ne consolident rien).\n")
    out["verdicts"] = {"conservative": dict(dist_c), "answered": dict(dist_a)}

    # ---- ventilations -------------------------------------------------- #
    def breakdown(title: str, keyfn, rows: list[dict] | None = None) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for oid, rs in objs.items():
            groups[keyfn(rs[0])].append(oid)
        print(f"## {title}\n")
        print("| groupe | objets | `M1` conserv. | `M1` répondu | `M1b` | `M1c` |")
        print("|---|---|---|---|---|---|")
        for g in sorted(groups):
            sub = {o: objs[o] for o in groups[g]}
            kcc, kaa = obj_rates(sub, "conservative"), obj_rates(sub, "answered")
            print(f"| `{g}` | {len(sub)} | {row(kcc['M1'], len(sub))} | "
                  f"{row(kaa['M1'], len(sub))} | {row(kcc['M1b'], len(sub))} | "
                  f"{row(kcc['M1c'], len(sub))} |")
        print()

    breakdown("Par strate", lambda r: r.get("stratum", ""))
    breakdown("Par catégorie", lambda r: r.get("truth_category", ""))
    breakdown("Par `text_visible`", lambda r: f"text_visible={int(bool(r.get('text_visible')))}")

    # ---- canal, au niveau image --------------------------------------- #
    print("## Canal de lecture, au niveau image\n")
    print("| text_visible | images | marque juste | marque non vide | modèle juste | catégorie juste |")
    print("|---|---|---|---|---|---|")
    for tv in (1, 0):
        sub = [r for r in recs if int(bool(r.get("text_visible"))) == tv]
        if not sub:
            continue
        nb = sum(brand_ok((r["pred"] or {}).get("brand", ""), r["truth_brand"]) for r in sub)
        nm = sum(model_ok((r["pred"] or {}).get("model", ""), r["truth_model"]) for r in sub)
        nc = sum(cat_ok((r["pred"] or {}).get("category", ""), r["truth_category"]) for r in sub)
        filled = sum(1 for r in sub if ((r["pred"] or {}).get("brand") or "").strip())
        print(f"| {tv} | {len(sub)} | {row(nb, len(sub))} | {row(filled, len(sub))} | "
              f"{row(nm, len(sub))} | {row(nc, len(sub))} |")
    print()

    # ---- M6 ------------------------------------------------------------ #
    if args.perturbations or "kind" in (recs[0] if recs else {}):
        print("## M6 — robustesse aux perturbations (niveau objet)\n")
        kinds = sorted({r.get("kind") for r in recs if r.get("kind")})
        print("| variante | n objets | `M1` conserv. | Δ | `M1b` | Δ |")
        print("|---|---|---|---|---|---|")
        base_m1 = base_m1b = None
        for kind in kinds:
            sub_recs = [r for r in recs if r.get("kind") == kind]
            sub = group(sub_recs)
            kk = obj_rates(sub, "conservative")
            m1, m1b, nn = kk["M1"], kk["M1b"], len(sub)
            if kind == "base":
                base_m1, base_m1b = m1, m1b
            # Convention de `docs/06` §9.3 : Δ = base − variante, donc une
            # **baisse** s'écrit **positive**. La reproduire exactement est le
            # but de l'outil ; un signe inversé ferait relire tout un tableau.
            d1 = "" if base_m1 is None else f"{(base_m1 - m1) / nn * 100:+.1f} pt"
            d2 = "" if base_m1b is None else f"{(base_m1b - m1b) / nn * 100:+.1f} pt"
            print(f"| `{kind}` | {nn} | {row(m1, nn)} | {d1} | {row(m1b, nn)} | {d2} |")
        print("\n> Cible M6 : |Δ| ≤ 15 pt au nominal. Un Δ **positif** est une **baisse**.\n")

    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"écrit : {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
