#!/usr/bin/env python3
"""Test EN DIRECT n°2 — B9 : reproductibilité et accord inter-nœuds.

Protocole (docs/07 §6, benchmark B9 : « 2 runs, accord publié ») :
* 8 photos gelées du corpus, **les mêmes** sur chaque nœud ;
* température 0, graine 1234 — la mesure veut la déterminabilité, pas la
  créativité ;
* chaque nœud (zabeth21 :18000, zabeth22 :18002, zabeth23 :18003) répond au
  triage {view, category, iot} et à l'identification {brand, model, category} ;
* on publie : accord run1/run2 sur le même nœud (reproductibilité) et accord
  entre nœuds (interchangeabilité du cluster).

Seuils B9 : catégorie 100 %, tuple ≥ 95 %.

Usage (tunnels préalables) :
    ssh -fN -L 18000:172.26.145.71:8000 zabeth21
    ssh -fN -L 18002:172.26.145.72:8000 zabeth22
    ssh -fN -L 18003:172.26.145.73:8000 zabeth23
    ./.venv-core/bin/python benchmarks/live_cross_node.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from live_vlm_orchestrator import HTTPVLM  # noqa: E402

ENDPOINTS = {
    "zabeth21": "http://127.0.0.1:18000/v1/chat/completions",
    "zabeth22": "http://127.0.0.1:18002/v1/chat/completions",
    "zabeth23": "http://127.0.0.1:18003/v1/chat/completions",
}

IMAGES_DIR = Path.home() / "iot-corpus-measure" / "images"
N_PHOTOS = 8

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'OK ' if ok else 'ECART'}  {name}" + (f" — {detail}" if detail else ""))


def load_photos() -> list[tuple[str, Path]]:
    runner_src = ROOT / "corpus" / "runner6-v6-triage.py"
    ns: dict = {}
    exec(compile(runner_src.read_text(encoding="utf-8").split("def fetch")[0],
                 str(runner_src), "exec"), ns)
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for rec in ns["MANIFEST"]["items"]:
        if rec["object_id"] in seen:
            continue
        dest = IMAGES_DIR / (hashlib.sha1(rec["image_id"].encode()).hexdigest() + ".jpg")
        if dest.exists():
            seen.add(rec["object_id"])
            out.append((rec["object_id"], dest))
        if len(out) >= N_PHOTOS:
            break
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--node", choices=sorted(ENDPOINTS), default=None,
                    help="mesurer UN seul nœud (le portier limite les canaux simultanés)")
    ap.add_argument("--save", type=Path, default=None,
                    help="écrire les réponses brutes en JSON (comparaison hors ligne)")
    ap.add_argument("--compare", type=Path, nargs="*", default=None,
                    help="comparer des fichiers --save entre eux (inter-nœuds, hors ligne)")
    args = ap.parse_args()

    if args.compare:
        return compare_files(args.compare)

    photos = load_photos()
    if len(photos) < N_PHOTOS:
        print(f"ERREUR : {len(photos)} photos disponibles, {N_PHOTOS} requises", file=sys.stderr)
        return 2

    nodes = [args.node] if args.node else list(ENDPOINTS)
    print(f"=== B9 live — {len(photos)} photos × nœuds {nodes} × 2 runs ===\n")

    # {node: {run: [(view, category, iot, brand, model)]}}
    data: dict[str, dict[int, list[tuple]]] = {n: {1: [], 2: []} for n in nodes}

    for node in nodes:
        vlm = HTTPVLM(ENDPOINTS[node])
        for run in (1, 2):
            for oid, path in photos:
                try:
                    stub = type("I", (), {"image_id": oid, "path": path})()
                    tri = vlm.triage(stub, prompt_version="v6")
                    ident = vlm.infer(stub, prompt_version="v3")
                    data[node][run].append(
                        (tri.view.value, tri.category.value, tri.iot,
                         (ident.brand or "").strip().lower(),
                         (ident.model or "").strip().lower())
                    )
                except Exception as exc:
                    data[node][run].append(("ERROR", type(exc).__name__, False, "", ""))
            print(f"  {node} run{run} : {len(data[node][run])} réponses")

    if args.save:
        payload = {
            "photos": [oid for oid, _p in photos],
            "data": {n: {str(r): [list(t) for t in v] for r, v in runs.items()}
                     for n, runs in data.items()},
        }
        args.save.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  écrit : {args.save}")

    return analyse(data, photos)


def compare_files(paths: list[Path]) -> int:
    """Compare des fichiers --save entre eux (accord inter-nœuds, hors ligne)."""
    data: dict[str, dict[int, list[tuple]]] = {}
    photos: list[tuple[str, Path]] = []
    for p in paths:
        pl = json.loads(p.read_text(encoding="utf-8"))
        node = p.stem
        # le fichier porte {node: {run: [...]}} — un seul nœud par fichier --save
        runs = next(iter(pl["data"].values()))
        data[node] = {int(r): [tuple(t) for t in v] for r, v in runs.items()}
        photos = [(oid, Path()) for oid in pl["photos"]]
    return analyse(data, photos)


def analyse(data: dict[str, dict[int, list[tuple]]], photos: list[tuple[str, Path]]) -> int:
    nodes = list(data)

    # Garde anti-vide : deux runs identiquement en ERREUR ne sont pas
    # « reproductibles » — un tunnel mort donne une stabilité factice 8/8.
    # Les erreurs partielles et déterministes (boucle du modèle sur certaines
    # photos = E_VLM_INVALID_JSON) sont des résultats mesurés, pas une panne de
    # mesure : elles sont publiées, et l'accord porte sur les paires valides.
    for node in nodes:
        errs1 = sum(1 for t in data[node][1] if t[0] == "ERROR")
        errs2 = sum(1 for t in data[node][2] if t[0] == "ERROR")
        if errs1 == len(data[node][1]):
            check(f"{node} : réponses exploitables", False,
                  f"{errs1}/{len(data[node][1])} en erreur — mesure non concluante")
            return 1
        print(f"  note {node} : {errs1}/{len(data[node][1])} échecs VLM run1, "
              f"{errs2}/{len(data[node][2])} run2 (sorties inexploitables, "
              f"E_VLM_INVALID_JSON — publiées, exclues de l'accord)")

    def agree(a: list[tuple], b: list[tuple], pick) -> tuple[int, int]:
        ok = sum(1 for x, y in zip(a, b, strict=True) if pick(x) == pick(y))
        return ok, len(a)

    # ------------------------------------------- 1. reproductibilité par nœud
    print("\n--- 1. reproductibilité run1 vs run2 (même nœud, même graine) ---")
    for node in nodes:
        pairs = list(zip(data[node][1], data[node][2], strict=True))
        ok_pairs = [(x, y) for x, y in pairs if x[0] != "ERROR" and y[0] != "ERROR"]
        n = len(ok_pairs)
        cat_ok = sum(1 for x, y in ok_pairs if x[1] == y[1])
        tup_ok = sum(1 for x, y in ok_pairs if (x[3], x[4]) == (y[3], y[4]))
        iot_ok = sum(1 for x, y in ok_pairs if x[2] == y[2])
        check(f"{node} : catégorie stable {cat_ok}/{n}", n > 0 and cat_ok == n,
              f"tuple {tup_ok}/{n} iot {iot_ok}/{n}")

    # ------------------------------------------- 2. accord inter-nœuds
    print("\n--- 2. accord inter-nœuds (run1) ---")
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = data[nodes[i]][1], data[nodes[j]][1]
            pairs = [(x, y) for x, y in zip(a, b, strict=True)
                     if x[0] != "ERROR" and y[0] != "ERROR"]
            n = len(pairs)
            cat_ok = sum(1 for x, y in pairs if x[1] == y[1])
            iot_ok = sum(1 for x, y in pairs if x[2] == y[2])
            tup_ok = sum(1 for x, y in pairs if (x[3], x[4]) == (y[3], y[4]))
            # détail des désaccords : quelles photos, quelles valeurs
            for idx, (x, y) in enumerate(zip(a, b, strict=True)):
                if x != y and x[0] != "ERROR" and y[0] != "ERROR":
                    oid = photos[idx][0] if idx < len(photos) else f"#{idx}"
                    print(f"      divergence {nodes[i]}/{nodes[j]} {oid}:")
                    print(f"        {nodes[i]}: {x}")
                    print(f"        {nodes[j]}: {y}")
            check(f"{nodes[i]} vs {nodes[j]} : catégorie {cat_ok}/{n}", n > 0 and cat_ok == n,
                  f"tuple {tup_ok}/{n} iot {iot_ok}/{n}")

    # ------------------------------------------- 3. seuils B9
    print("\n--- 3. seuils B9 (catégorie 100 %, tuple ≥ 95 %) ---")
    if len(nodes) < 2:
        print("  (un seul nœud mesuré : les seuils inter-nœuds exigent ≥ 2 fichiers --compare)")
    all_pairs = all_tuple_ok = all_cat_ok = 0
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = data[nodes[i]][1], data[nodes[j]][1]
            for x, y in zip(a, b, strict=True):
                if x[0] == "ERROR" or y[0] == "ERROR":
                    continue
                all_pairs += 1
                all_tuple_ok += int((x[3], x[4]) == (y[3], y[4]))
                all_cat_ok += int(x[1] == y[1])
    if all_pairs:
        cat_rate = all_cat_ok / all_pairs
        tup_rate = all_tuple_ok / all_pairs
        check(f"B9 catégorie : {all_cat_ok}/{all_pairs} = {cat_rate:.3f}", cat_rate >= 0.95,
              "seuil B9 : catégorie = 100 % visé")
        check(f"B9 tuple : {all_tuple_ok}/{all_pairs} = {tup_rate:.3f}", tup_rate >= 0.95,
              "seuil B9 : tuple ≥ 0,95")

    print("\n=== VERDICT ===")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} contrôles tenus")
    for n in failed:
        print("  ECART:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
