#!/usr/bin/env python3
"""§22.3 — les métriques de triage calculées par la SEULE fonction de référence.

Pourquoi ce script existe
-------------------------
`iot_audit.modules.triage.benchmark_triage` implémente exactement les métriques
du §22.3 (rappel IoT, spécificité, exactitude de catégorie, intervalles de
Wilson) — et jusqu'ici **aucune** mesure ne l'appelait : `analyse-v6.py` et
`live_specificity_protocol.py` recalculent chacun leur morceau. C'est le défaut
« deuxième implémentation » déjà corrigé une fois sur la confiance (A recalculé
sans normalisation d'alias dans l'orchestrateur). Ce script ferme la boucle :
il rassemble les deux bras du protocole et appelle `benchmark_triage` **une
fois**, pour que le chiffre publié soit produit par la fonction testée.

Les deux bras, et leur asymétrie (déclarée, pas cachée)
------------------------------------------------------
* **IoT** : `evidence/2026-10-06/v6-triage-live/predictions-v6.json` — 48 objets
  connectés, 144 photos, run v6 en direct, barème gelé. Les prédictions de
  triage y sont déjà au format `{view, category, iot}`.
* **non-IoT** : `evidence/2026-10-06/specificity-protocol/specificity.json` —
  30 objets du quotidien, une photo chacun, run v6 en direct.

`n` diffère donc (48 contre 30) : les deux bornes de Wilson sont publiées avec
leur propre `n`, jamais sous une valeur agrégée trompeuse.

Dépendance déclarée : ce script lit des artefacts de run sous `evidence/`, que
`.gitignore` ne versionne pas (politique du dépôt : les preuves de run ne sont
pas redistribuées). Il sort en **code 2** avec un message explicite quand ils
sont absents — jamais un succès muet sur des données manquantes. Il n'est donc
pas exécuté en CI.

Usage :
    ./.venv-core/bin/python benchmarks/combined_triage_metrics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iot_audit.contracts import Category, ViewType, VLMTriageOutput  # noqa: E402

# La vérité terrain se lit dans le barème GELÉ, jamais dans `truth_category` :
# `effective_category` applique `TRUTH_CATEGORY_OVERRIDES` (google__nest_doorbell
# → ip_camera) et son docstring dit explicitement que tout regroupement doit
# passer par lui. Lire le champ brut comptait cet objet faux alors que le barème
# le compte juste (35/48 au lieu de 36/48).
from iot_audit.corpus.audit_grading import effective_category  # noqa: E402
from iot_audit.modules.triage import benchmark_triage  # noqa: E402

IOT_RUN = ROOT / "evidence" / "2026-10-06" / "v6-triage-live" / "predictions-v6.json"
NON_IOT_RUN = ROOT / "evidence" / "2026-10-06" / "specificity-protocol" / "specificity.json"


def _load_iot_arm() -> list[tuple[str, bool, Category, list[VLMTriageOutput]]]:
    """Objets connectés du run v6 gelé : un tuple par objet, une prédiction par photo."""
    rows = json.loads(IOT_RUN.read_text(encoding="utf-8"))
    by_object: dict[str, dict] = {}
    for r in rows:
        pred = r.get("pred") or {}
        if not pred or not r.get("sha256_ok", True):
            continue  # image non conforme: ne pas faire entrer une prédiction douteuse
        entry = by_object.setdefault(
            r["object_id"],
            {"truth_category": effective_category(r), "preds": []},
        )
        entry["preds"].append(
            VLMTriageOutput(
                view=ViewType(pred["view"]),
                category=Category(pred["category"]),
                iot=bool(pred["iot"]),
            )
        )

    out = []
    for object_id, entry in by_object.items():
        try:
            truth_cat = Category(entry["truth_category"])
        except ValueError:
            truth_cat = Category.OTHER
        out.append((object_id, True, truth_cat, entry["preds"]))
    return out


def _load_non_iot_arm() -> list[tuple[str, bool, Category, list[VLMTriageOutput]]]:
    """Objets non connectés mesurés : une photo par objet, vérité = `other`."""
    data = json.loads(NON_IOT_RUN.read_text(encoding="utf-8"))
    out = []
    for row in data["rows"]:
        if row.get("error"):
            continue
        out.append(
            (
                row["query"],
                False,
                Category.OTHER,
                [
                    VLMTriageOutput(
                        view=ViewType(row["view"]),
                        category=Category(row["category"]),
                        iot=bool(row["iot"]),
                    )
                ],
            )
        )
    return out


def main() -> int:
    missing = [p for p in (IOT_RUN, NON_IOT_RUN) if not p.is_file()]
    if missing:
        for p in missing:
            print(f"absent : {p}", file=sys.stderr)
        print(
            "\nArtefacts de run absents. Ce script mesure des runs déjà effectués ; "
            "il ne les refait pas. Voir evidence/2026-10-06/LIRE-MOI.md.",
            file=sys.stderr,
        )
        return 2

    iot = _load_iot_arm()
    non_iot = _load_non_iot_arm()
    print("=== Métriques de triage §22.3 — fonction de référence `benchmark_triage` ===")
    print(f"  bras IoT     : {len(iot)} objets connectés (run v6 gelé, 144 photos)")
    print(f"  bras non-IoT : {len(non_iot)} objets non connectés (protocole, 1 photo/objet)")

    m = benchmark_triage(iot + non_iot)

    def ic(pair: tuple[float, float]) -> str:
        return f"IC[{pair[0]:.3f};{pair[1]:.3f}]"

    print(f"\n  n objets                : {m.n_objects}")
    print(f"  rappel IoT              : {round(m.iot_recall * m.n_iot_true)}/{m.n_iot_true}"
          f" = {m.iot_recall:.3f}  {ic(m.iot_recall_ci)}")
    print(f"  spécificité IoT         : {round(m.iot_specificity * m.n_non_iot_true)}"
          f"/{m.n_non_iot_true} = {m.iot_specificity:.3f}  {ic(m.iot_specificity_ci)}")
    print(f"  exactitude catégorie    : {m.category_accuracy_on_iot:.3f}"
          f"  {ic(m.category_accuracy_on_iot_ci)}  (objets connectés, toutes conditions de texte)")
    print("\n  Rappel : l'exactitude de catégorie ci-dessus NE décompose PAS par visibilité")
    print("  du texte ; les chiffres par condition de texte sont dans docs/06 §22.2 et §22.7.")

    out = {
        "computed_by": "iot_audit.modules.triage.benchmark_triage",
        "arms": {
            "iot": {"n_objects": len(iot), "source": str(IOT_RUN.relative_to(ROOT))},
            "non_iot": {"n_objects": len(non_iot), "source": str(NON_IOT_RUN.relative_to(ROOT))},
        },
        "n_objects": m.n_objects,
        "n_iot_true": m.n_iot_true,
        "n_non_iot_true": m.n_non_iot_true,
        "iot_recall": m.iot_recall,
        "iot_recall_wilson": list(m.iot_recall_ci),
        "iot_specificity": m.iot_specificity,
        "iot_specificity_wilson": list(m.iot_specificity_ci),
        "category_accuracy_on_iot": m.category_accuracy_on_iot,
        "category_accuracy_on_iot_wilson": list(m.category_accuracy_on_iot_ci),
    }
    dest = NON_IOT_RUN.parent / "combined-22-3.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  écrit : {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
