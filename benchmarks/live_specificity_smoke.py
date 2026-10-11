#!/usr/bin/env python3
"""Test EN DIRECT n°3 — fumée de SPÉCIFICITÉ : objets NON connectés.

Le corpus du projet est 100 % IoT (48/48) : le taux de fausses alertes n'a
jamais été mesuré (docs/06 §22.3 : « non mesurable ici — corpus mixte à
collecter »). Ce test de fumée comble provisoirement le trou avec ~10 photos
d'objets du quotidien (mug, livre, chaise, stylo, plante, chaussure…)
téléchargées depuis Wikimedia Commons, poussées dans le triage v6 **live**.

Mesure : combien de ces objets NON connectés déclenchent malgré tout une
alerte IoT (`is_iot=True` ou catégorie IoT) — la **spécificité** du premier
filtre D16. Avec la règle rappel-d'abord, un objet non connecté photographié
en DÉTAIL SEUL déclenche par construction une fausse alerte (coût assumé :
un regard humain). Ce test quantifie le coût réel sur des photos ordinaires.

Ce n'est PAS le protocole §22.3 (60 objets, 2 conditions de texte, IC) :
c'est une sonde de fumée, publiée comme telle.

Usage :
    ssh -fN -L 18000:172.26.145.71:8000 zabeth21
    ./.venv-core/bin/python benchmarks/live_specificity_smoke.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from live_vlm_orchestrator import HTTPVLM  # noqa: E402

ENDPOINT = "http://127.0.0.1:18000/v1/chat/completions"
UA = "iot-audit-measure/0.1 (academic; specificity-smoke)"

# Recherches Commons : objets du quotidien sans électronique réseau.
QUERIES = [
    "ceramic coffee mug white background",
    "hardcover book closed white background",
    "wooden chair white background",
    "ballpoint pen white background",
    "potted plant white background",
    "leather shoe white background",
    "ceramic bowl white background",
    "wooden spoon white background",
    "cotton t-shirt white background",
    "glass water bottle white background",
]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'OK ' if ok else 'ECART'}  {name}" + (f" — {detail}" if detail else ""))


def fetch_image(query: str, dest_dir: Path, idx: int) -> Path | None:
    """Une photo Commons par requête (API MediaWiki, licence libre)."""
    api = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": "3",
        "gsrnamespace": "6", "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata", "iiurlwidth": "640", "format": "json",
    })
    req = urllib.request.Request(api, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        url = info.get("thumburl") or info.get("url")
        dest = dest_dir / f"noniot-{idx:02d}.jpg"
        try:
            rreq = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(rreq, timeout=30) as r:
                dest.write_bytes(r.read())
            return dest
        except Exception:
            continue
    return None


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="specificity-"))
    print(f"=== Fumée de spécificité — objets NON connectés ({work}) ===\n")

    # --------------------------------------------------- 1. collecte photos
    print("--- 1. collecte (Wikimedia Commons) ---")
    photos: list[tuple[str, Path]] = []
    for i, q in enumerate(QUERIES):
        p = fetch_image(q, work, i)
        if p is not None and p.stat().st_size > 2000:
            photos.append((q, p))
            print(f"  ok   {q}")
        else:
            print(f"  --   {q} : pas d'image exploitable")
    check("collecte : ≥ 8 photos", len(photos) >= 8, f"{len(photos)}/{len(QUERIES)}")

    if not photos:
        check("spécificité mesurable", False, "aucune photo")
        return 1

    # --------------------------------------------------- 2. triage v6 live
    print("\n--- 2. triage v6 live (zabeth21 via tunnel :18000) ---")
    vlm = HTTPVLM(ENDPOINT)
    rows = []
    for q, path in photos:
        stub = type("I", (), {"image_id": q, "path": path})()
        try:
            tri = vlm.triage(stub, prompt_version="v6")
            rows.append((q, tri.view.value, tri.category.value, tri.iot, None))
            print(f"  {q:<42s} view={tri.view.value:<7s} cat={tri.category.value:<14s} "
                  f"iot={tri.iot}")
        except Exception as exc:
            rows.append((q, "ERROR", "", False, type(exc).__name__))
            print(f"  {q:<42s} ERREUR {type(exc).__name__}")

    valid = [r for r in rows if r[4] is None]
    errors = [r for r in rows if r[4] is not None]

    # --------------------------------------------------- 3. spécificité
    # Deux décisions mesurées, et il faut les publier TOUTES LES DEUX :
    #   (a) le vote brut du modèle (sortie v6) ;
    #   (b) la décision DÉPLOYÉE après consolidation (règle rappel-d'abord :
    #       un fragment seul ne prouve pas l'absence ⇒ alerte par défaut).
    # C'est (b) qui coûte un regard humain en exploitation ; (a) dit si le
    # modèle sait dire « non connecté ».
    from iot_audit.contracts import Category, ViewType, VLMTriageOutput
    from iot_audit.modules.triage import consolidate_triage

    print("\n--- 3a. spécificité — vote BRUT du modèle ---")
    false_alerts = [r for r in valid if r[3] or r[2] != "other"]
    true_negatives = [r for r in valid if not r[3] and r[2] == "other"]
    n = len(valid)
    spec = len(true_negatives) / n if n else 0.0
    print(f"  vrais négatifs   : {len(true_negatives)}/{n} = {spec:.3f}")
    for q, view, cat, iot, _e in false_alerts:
        print(f"    fausse alerte : {q} -> view={view} cat={cat} iot={iot}")
    check("spécificité brute ≥ 0,70 (fumée, ≥ 8 photos valides)", n >= 8 and spec >= 0.70,
          f"{len(true_negatives)}/{n} = {spec:.3f}")
    check("échecs VLM < 20 %", len(errors) <= max(1, len(photos) // 5),
          f"{len(errors)}/{len(photos)}")

    print("\n--- 3b. décision CONSOLIDÉE (règle rappel-d'abord) ---")
    # Contrat réel de la règle (docs/06 §22.3, run v6 du 2026-10-06) :
    #   * vue GLOBALE non-IoT unanime ⇒ négatif établi (garantie vérifiable) ;
    #   * fragment seul ⇒ alerte par défaut : un gros plan ne distingue pas une
    #     tasse d'une carte mère de routeur (9 faux négatifs Zyxel mesurés).
    # Le coût des fragments est un chiffre PUBLIÉ, pas un critère : il se règle
    # en photographiant l'objet entier, pas en assouplissant la règle.
    cons_true_neg = 0
    cons_false_alert = 0
    whole_neg_ok = 0
    whole_neg_total = 0
    for q, view, cat, iot, _e in valid:
        preds = [VLMTriageOutput(
            view=ViewType(view),
            category=Category(cat if cat in {c.value for c in Category} else "other"),
            iot=iot,
        )]
        dec = consolidate_triage(q, preds)
        if view == "whole" and not iot and cat == "other":
            whole_neg_total += 1
            whole_neg_ok += int(not dec.is_iot)
        if dec.is_iot:
            cons_false_alert += 1
            print(f"    alerte (attendue pour un fragment) : {q} view={view}")
        else:
            cons_true_neg += 1
    cons_spec = cons_true_neg / n if n else 0.0
    print(f"  vrais négatifs consolidés : {cons_true_neg}/{n} = {cons_spec:.3f}")
    print(f"  coût des fragments (alertes) : {cons_false_alert}/{n} — se réduit en "
          f"photographiant l'objet entier")
    check("vue globale non-IoT ⇒ négatif consolidé (contrat de la règle)",
          whole_neg_total > 0 and whole_neg_ok == whole_neg_total,
          f"{whole_neg_ok}/{whole_neg_total}")

    # ventilation par type de vue (règle rappel-d'abord : détail ⇒ alerte)
    whole = [r for r in valid if r[1] == "whole"]
    detail = [r for r in valid if r[1] == "detail"]
    w_spec = sum(1 for r in whole if not r[3] and r[2] == "other") / len(whole) if whole else float("nan")
    d_spec = sum(1 for r in detail if not r[3] and r[2] == "other") / len(detail) if detail else float("nan")
    print(f"  vote brut — vue globale : {w_spec:.3f} ({len(whole)} photos)")
    print(f"  vote brut — détail      : {d_spec:.3f} ({len(detail)} photos)")

    print("\n=== VERDICT ===")
    failed = [n2 for n2, ok, _ in RESULTS if not ok]
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} contrôles tenus")
    for n2 in failed:
        print("  ECART:", n2)
    print("  Rappel : sonde de fumée, pas le protocole §22.3 (60 objets, IC).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
