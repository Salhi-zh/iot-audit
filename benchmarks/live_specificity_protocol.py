#!/usr/bin/env python3
"""Protocole de SPÉCIFICITÉ « IoT ou non » — objets NON connectés (docs/06 §22.3).

Pourquoi ce script existe
-------------------------
La directive du tuteur (2026-10-05, docs/06 §22.1) demande deux réponses tirées
de l'apparence seule : (a) l'objet est-il un objet connecté ? (b) sa catégorie.
Le corpus du projet est 100 % connecté (48/48) : le **rappel** IoT se mesure
dessus (`evidence/2026-10-06/v6-triage-live/`, 47/48), mais la **spécificité**
— la capacité à dire « non connecté » — ne s'y mesure pas du tout. Ce script
collecte la moitié manquante : N objets du quotidien sans électronique réseau.

Ce qui est mesuré, et sous quel nom
-----------------------------------
1. ``specificity_raw``          : le vote du modèle (champ ``iot``, sortie v6).
2. ``specificity_consolidated`` : la décision DÉPLOYÉE après la règle
   rappel-d'abord de ``consolidate_triage`` (un fragment seul ne prouve pas
   l'absence ⇒ alerte par défaut). C'est ce chiffre qui coûte un regard humain.
3. ``specificity_whole_view``   : le vote brut restreint aux photos classées
   ``view=whole`` — ce que donnerait la consigne de prise de vue du protocole.

Robustesse de la mesure (chaîne réelle, pas de simulation)
----------------------------------------------------------
Wikimedia plafonne les requêtes anonymes (429 constatés en direct) et le portier
du campus coupe les tunnels SSH. Les images sont donc **mises en cache sur
disque** (``corpus/.cache/specificity-objects/``, non versionné) : une coupure
ne coûte que les appels restants, jamais la collecte. L'endpoint vLLM est
**vérifié avant** la phase de triage : mieux vaut échouer en une seconde qu'en
vingt-six délais d'attente.

Limites DÉCLARÉES (ne pas lire ceci comme le protocole complet)
---------------------------------------------------------------
* §22.3 prescrit **deux conditions de texte** (« texte imprimé lisible » /
  « non lisible ») et un drapeau ``text_visible`` gelé par OCR **avant** toute
  prédiction. Ici il n'y a qu'**une photo par objet** et **aucun drapeau OCR** :
  la moitié non-IoT est mesurée sans la variable de texte. La moitié IoT, elle,
  porte déjà le drapeau gelé (corpus 2026-09-15).
* §22.3 prescrit 30 connectés + 30 non connectés. Le rappel est mesuré sur les
  **48** objets connectés du corpus gelé (n supérieur), pas sur 30.
* Les cibles §22.3 (rappel ≥ 0,95 ; catégorie borne basse ≥ 0,70) restent
  soumises à l'arbitrage du tuteur (Q9). Ce script ne les invente pas : il
  **mesure** et publie les intervalles de Wilson.

Ce script échoue seulement si la mesure n'a pas pu être faite (moins de N objets
valides, ou plus de 20 % d'échecs du modèle) — jamais parce qu'un chiffre
déplairait. Un chiffre bas est un résultat.

Usage :
    infra/scripts/tunnel_vllm.sh start
    ./.venv-core/bin/python benchmarks/live_specificity_protocol.py --n 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from live_vlm_orchestrator import HTTPVLM  # noqa: E402

from iot_audit.contracts import Category, ViewType, VLMTriageOutput  # noqa: E402

# La convention d'accès à Wikimedia du projet (User-Agent identifiant + cadence)
# est reprise telle quelle : une seule politique, une seule source.
from iot_audit.corpus.commons import MIN_INTERVAL_S, USER_AGENT  # noqa: E402
from iot_audit.modules.confidence import wilson  # noqa: E402
from iot_audit.modules.triage import consolidate_triage  # noqa: E402

DEFAULT_CACHE = ROOT / "corpus" / ".cache" / "specificity-objects"

# Objets du quotidien SANS électronique réseau. Une requête = un objet.
# Volontairement variés en forme et en matière : un filtre qui dirait « non
# connecté » à tort rencontrerait une forme inconnue, pas une variante du même
# objet. Les deux derniers servent de réserve si une collecte échoue.
QUERIES: list[str] = [
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
    "acoustic guitar white background",
    "bicycle white background",
    "backpack white background",
    "wool hat white background",
    "mechanical alarm clock white background",
    "umbrella white background",
    "stainless steel kettle white background",
    "scissors white background",
    "claw hammer white background",
    "skateboard white background",
    "toothbrush white background",
    "bath towel white background",
    "wooden pencil white background",
    "frying pan white background",
    "wine glass white background",
    "leather wallet white background",
    "paper notebook white background",
    "broom white background",
    "tennis racket white background",
    "analog wristwatch white background",
    "sunglasses white background",
    "wooden cutting board white background",
    "wooden ladder white background",
    "metal bucket white background",
]


def _api_get(url: str, *, attempts: int = 4, base_sleep: float | None = None) -> bytes:
    """GET Wikimedia avec cadence et repli — la collecte est lente par dessein.

    Wikimedia plafonne les requêtes anonymes : constaté en direct, HTTP 429 à
    partir du ~10e appel consécutif. On respecte donc MIN_INTERVAL_S (la valeur
    du projet, 1,2 s, réglable par ``IOT_AUDIT_API_INTERVAL``) et on retente avec
    un retrait croissant.
    """
    pause = MIN_INTERVAL_S if base_sleep is None else base_sleep
    last: Exception | None = None
    for attempt in range(attempts):
        time.sleep(pause * (attempt + 1))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            code = getattr(exc, "code", type(exc).__name__)
            print(f"       {code} -> nouvelle tentative ({attempt + 1}/{attempts})")
    assert last is not None
    raise last


def _meta_value(meta: dict, key: str) -> str | None:
    """Valeur texte d'un champ ``extmetadata`` de Commons (ou None)."""
    value = (meta.get(key) or {}).get("value")
    return str(value) if value is not None else None


def _cache_paths(cache_dir: Path, query: str) -> tuple[Path, Path]:
    """Un objet du cache est identifié par sa requête, pas par sa position."""
    key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{key}.jpg", cache_dir / f"{key}.json"


def _download_one(query: str, dest: Path) -> dict | None:
    """Une photo Commons pour la requête, avec sa provenance (licence, URL, sha256)."""
    api = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": "3",
        "gsrnamespace": "6", "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata|sha1", "iiurlwidth": "640", "format": "json",
    })
    payload = json.loads(_api_get(api))
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        url = info.get("thumburl") or info.get("url")
        try:
            dest.write_bytes(_api_get(url))
        except Exception:
            continue
        if dest.stat().st_size <= 2000:
            continue
        meta = info.get("extmetadata") or {}
        return {
            "query": query,
            "path": dest,
            "source_url": info.get("descriptionurl") or url,
            "image_url": url,
            "license": _meta_value(meta, "LicenseShortName"),
            "artist": _meta_value(meta, "Artist"),
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        }
    return None


def collect_one(query: str, cache_dir: Path, *, offline: bool = False) -> dict | None:
    """Collecte (ou retrouve dans le cache) l'objet associé à une requête.

    Le cache rend la mesure reprenable : une coupure du portier ou un 429 de
    Wikimedia ne fait perdre que les objets non encore collectés.
    """
    img_path, meta_path = _cache_paths(cache_dir, query)
    if img_path.is_file() and img_path.stat().st_size > 2000 and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {"query": query, "path": img_path, "from_cache": True, **meta}
    if offline:
        return None
    item = _download_one(query, img_path)
    if item is None:
        return None
    meta_path.write_text(
        json.dumps(
            {k: v for k, v in item.items() if k != "path"},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    return {**item, "from_cache": False}


def _preflight(endpoint: str) -> None:
    """Vérifie l'endpoint vLLM AVANT la phase de triage.

    Une coupure du portier produisait auparavant un délai d'attente par objet :
    vingt-six attentes pour un seul câble débranché. On échoue une fois, vite.
    """
    base = endpoint.rsplit("/v1/", 1)[0]
    url = f"{base}/v1/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:
        raise SystemExit(
            f"Endpoint vLLM injoignable ({url}) : {type(exc).__name__}: {exc}\n"
            "Rouvrir le tunnel puis relancer : infra/scripts/tunnel_vllm.sh start"
        ) from exc
    models = [m.get("id") for m in (payload.get("data") or [])]
    print(f"    endpoint vérifié : {url} — modèles {models}")


def _triage_with_retry(vlm: HTTPVLM, stub: object, *, attempts: int = 3) -> object:
    """Un tunnel instable ne doit pas transformer une photo en échec définitif."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return vlm.triage(stub, prompt_version="v6")  # type: ignore[arg-type]
        except Exception as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(3 * (attempt + 1))
    assert last is not None
    raise last


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18000/v1/chat/completions")
    parser.add_argument("--n", type=int, default=30, help="nombre d'objets non connectés visé")
    parser.add_argument(
        "--out", type=Path,
        default=ROOT / "evidence" / "2026-10-06" / "specificity-protocol",
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--offline", action="store_true",
        help="n'utiliser que le cache d'images (aucune requête Wikimedia)",
    )
    parser.add_argument(
        "--collect-only", action="store_true",
        help="remplir le cache d'images puis s'arrêter (ne touche pas au vLLM)",
    )
    args = parser.parse_args(argv)

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== Protocole de spécificité — {args.n} objets NON connectés ===")
    print(f"    cache images : {args.cache_dir}")
    print(f"    sortie       : {args.out}\n")

    # ------------------------------------------------------------ 1. collecte
    print("--- 1. collecte (Wikimedia Commons, licence libre, provenance jointe) ---")
    collected: list[dict] = []
    for query in QUERIES:
        if len(collected) >= args.n:
            break
        try:
            item = collect_one(query, args.cache_dir, offline=args.offline)
        except Exception as exc:
            print(f"  --   {query:<44s} collecte : {type(exc).__name__}")
            continue
        if item is None:
            print(f"  --   {query:<44s} pas d'image exploitable")
            continue
        collected.append(item)
        origin = "cache" if item["from_cache"] else "réseau"
        print(f"  ok   {query:<44s} {item['sha256'][:12]}  {item['license']}  [{origin}]")

    print(f"\n  objets disponibles : {len(collected)}")
    if args.collect_only:
        # La collecte (réseau Wikimedia, fragile) et la mesure (vLLM, fragile)
        # sont deux phases séparées : les rejouer ensemble ferait perdre la
        # première à chaque coupure de la seconde.
        print("  --collect-only : collecte terminée, phase vLLM non lancée.")
        return 0 if len(collected) >= args.n else 1

    # ------------------------------------------------------- 2. triage v6 live
    print("\n--- 2. triage v6 en direct (apparence seule, ni marque ni modèle) ---")
    _preflight(args.endpoint)
    vlm = HTTPVLM(args.endpoint)
    rows: list[dict] = []
    for item in collected:
        stub = type("I", (), {"image_id": item["query"], "path": item["path"]})()
        row = {
            "query": item["query"],
            "sha256": item["sha256"],
            "source_url": item["source_url"],
            "license": item["license"],
            "view": None, "category": None, "iot": None, "error": None,
        }
        try:
            tri = _triage_with_retry(vlm, stub)
            row.update(view=tri.view.value, category=tri.category.value, iot=tri.iot)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]
        rows.append(row)
        if row["error"]:
            print(f"  {item['query']:<44s} ERREUR {row['error'][:60]}")
        else:
            print(f"  {item['query']:<44s} view={row['view']:<7s} "
                  f"cat={row['category']:<14s} iot={row['iot']}")

    valid = [r for r in rows if r["error"] is None]
    errors = [r for r in rows if r["error"] is not None]

    # ------------------------------------------------- 3. les trois mesures
    print("\n--- 3. spécificité : trois lectures de la même mesure ---")

    raw_tn = [r for r in valid if not r["iot"] and r["category"] == "other"]
    raw_fp = [r for r in valid if r["iot"] or r["category"] != "other"]
    n = len(valid)
    spec_raw = len(raw_tn) / n if n else 0.0
    ci_raw = wilson(len(raw_tn), n) if n else (0.0, 1.0)
    print(f"  3a. vote BRUT du modèle     : {len(raw_tn)}/{n} = {spec_raw:.3f} "
          f"IC[{ci_raw[0]:.3f};{ci_raw[1]:.3f}]")
    for r in raw_fp:
        print(f"       fausse alerte brute   : {r['query']:<40s} "
              f"view={r['view']} cat={r['category']} iot={r['iot']}")

    cons_tn = 0
    for r in valid:
        preds = [VLMTriageOutput(
            view=ViewType(r["view"]),
            category=Category(r["category"]),
            iot=bool(r["iot"]),
        )]
        if not consolidate_triage(r["query"], preds).is_iot:
            cons_tn += 1
    spec_cons = cons_tn / n if n else 0.0
    ci_cons = wilson(cons_tn, n) if n else (0.0, 1.0)
    print(f"  3b. décision CONSOLIDÉE     : {cons_tn}/{n} = {spec_cons:.3f} "
          f"IC[{ci_cons[0]:.3f};{ci_cons[1]:.3f}]   (coût déployé)")
    print(f"       alertes à vérifier d'un œil : {n - cons_tn}/{n} — "
          "se réduit en photographiant l'objet ENTIER (consigne §22.3)")

    whole = [r for r in valid if r["view"] == "whole"]
    w_tn = [r for r in whole if not r["iot"] and r["category"] == "other"]
    spec_whole = len(w_tn) / len(whole) if whole else None
    ci_whole = wilson(len(w_tn), len(whole)) if whole else (0.0, 1.0)
    shown_whole = "nan" if spec_whole is None else f"{spec_whole:.3f}"
    print(f"  3c. vote brut, vue GLOBALE  : {len(w_tn)}/{len(whole)} = {shown_whole} "
          f"IC[{ci_whole[0]:.3f};{ci_whole[1]:.3f}]")

    detail = [r for r in valid if r["view"] == "detail"]
    print(f"      ventilation des vues     : whole={len(whole)} detail={len(detail)} "
          f"sur {n} objets")
    print("      lecture : la spécificité consolidée basse des fragments est un coût "
          "ASSUMÉ de la règle rappel-d'abord, pas un défaut du modèle.")

    # ------------------------------------------------------------ 4. verdict
    print("\n=== VERDICT ===")
    checks = [
        (f"≥ {args.n} objets non connectés mesurés", n >= args.n, f"n={n}"),
        ("échecs du modèle < 20 %", len(errors) <= max(1, len(rows) // 5),
         f"{len(errors)}/{len(rows)}"),
        ("au moins un objet en vue globale", len(whole) >= 1, f"whole={len(whole)}"),
    ]
    failed = [name for name, ok, _ in checks if not ok]
    for name, ok, detail_txt in checks:
        print(f"  {'OK ' if ok else 'ECART'}  {name} — {detail_txt}")

    # ------------------------------------------------------------ 5. preuves
    args.out.mkdir(parents=True, exist_ok=True)
    result = {
        "protocol": "docs/06 §22.3 — moitié NON connectée (sans condition de texte, déclaré)",
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint_model": "qwen2.5-vl-7b (vLLM GPTQ-Int4, zabeth21 via tunnel portier)",
        "prompt_version": "v6",
        "n_valid": n,
        "n_errors": len(errors),
        "specificity_raw": spec_raw, "specificity_raw_wilson": list(ci_raw),
        "specificity_consolidated": spec_cons,
        "specificity_consolidated_wilson": list(ci_cons),
        "specificity_whole_view_only": spec_whole,
        "specificity_whole_view_only_wilson": None if spec_whole is None else list(ci_whole),
        "n_whole": len(whole), "n_detail": len(detail),
        "rows": [{k: v for k, v in r.items()} for r in rows],
        "iot_recall_reference": {
            "value": "47/48 = 0.979",
            "wilson": [0.891, 0.996],
            "source": "evidence/2026-10-06/v6-triage-live (48 objets connectés, corpus gelé)",
        },
        "limits": [
            "une photo par objet, aucune condition de texte (drapeau OCR absent) "
            "— §22.3 en prescrit deux ; limite déclarée, non contournée",
            "cibles §22.3 (rappel ≥ 0,95 ; catégorie LB ≥ 0,70) en attente de "
            "l'arbitrage tuteur Q9 : ce script mesure, il ne fixe pas la cible",
        ],
    }
    out_file = args.out / "specificity.json"
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  preuves écrites : {out_file}")
    print("  Rappel : images non redistribuées ; URL, licence et sha256 joints "
          "(le corpus est citable par URL).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
