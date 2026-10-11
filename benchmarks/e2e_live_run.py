#!/usr/bin/env python3
"""Exécution en direct de la chaîne complète (docs/03 §2, D11, D16).

Bout en bout, avec de vrais composants de stockage :
  photo → triage {view, category, iot} → identification {brand, model}
        → confiance (A, R) → résolution CPE → recherche CVE
        → journal HMAC chaîné sur SQLite réel
        → rapport scellé Ed25519 → vérification par le CLI tiers verify_report.py

Les composants GPU (vLLM) sont remplacés par des fakes déterministes — c'est la
configuration de test prescrite (docs/07 §7 : « aucune CI ne doit exiger un GPU »).
Tout le reste (SQLite, chaîne HMAC, signature, CLI tiers) est réel.

Sortie : un verdict ligne par ligne + code retour 0 si tout est tenu.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iot_audit.contracts import (  # noqa: E402
    Category,
    CPECandidate,
    CVEResult,
    ImageInput,
    Stratum,
    ViewType,
    VLMRawOutput,
    VLMTriageOutput,
)
from iot_audit.pipeline.orchestrate import Orchestrator, RunConfig  # noqa: E402
from iot_audit.storage.journal import (  # noqa: E402
    SQLiteJournal,
    ensure_journal_schema,
    verify_chain,
)
from iot_audit.storage.seal import generate_ed25519_keypair, get_chain_head, sign_report  # noqa: E402

FIXED_CLOCK = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'OK ' if ok else 'ECART'}  {name}" + (f" — {detail}" if detail else ""))


class FakeTriage:
    def triage(self, image: ImageInput, *, prompt_version: str) -> VLMTriageOutput:
        if image.image_id == "mug":
            return VLMTriageOutput(view=ViewType.WHOLE, category=Category.OTHER, iot=False)
        return VLMTriageOutput(view=ViewType.WHOLE, category=Category.ROUTER, iot=True)


class FakeVLM:
    def infer(self, image: ImageInput, *, prompt_version: str) -> VLMRawOutput:
        return VLMRawOutput(
            brand="TP-Link", model="Archer C7", category=Category.ROUTER,
            visible_text="", evidence_image_region="", confidence_self=0.9,
        )


class FakeSearcher:
    def search(self, cpe: CPECandidate, *, since: date) -> list[CVEResult]:
        return [CVEResult(
            cve_id="CVE-2024-12345", cvss_v3_score=8.1, severity="HIGH",
            published=date(2024, 5, 1), match_basis="exact_product",
            criteria_used=(cpe.cpe_name,), cache_status="hit",
        )]


def img(name: str) -> ImageInput:
    return ImageInput(
        image_id=name, path=Path(f"/tmp/{name}.jpg"), sha256="0" * 64,
        stratum=Stratum.REVIEW, source_url="https://example.org/x.jpg",
        license="CC-BY", retrieved_at=FIXED_CLOCK, width=640, height=480,
        text_visible=False,
    )


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="e2e-live-"))
    print(f"=== E2E live — espace de travail : {work} ===")

    # ---------------------------------------------------------- journal SQLite
    con = sqlite3.connect(work / "journal.sqlite")
    ensure_journal_schema(con)

    orch = Orchestrator(
        triage_runner=FakeTriage(),
        vlm_runner=FakeVLM(),
        pool_provider=lambda b, m, c, k: [
            CPECandidate(
                cpe_name="cpe:2.3:h:tp-link:archer_c7:2.0:*:*:*:*:*:*:*",
                vendor="tp-link", product="archer_c7", version="2.0",
                category=Category.ROUTER, lexical_score=1.0,
                semantic_score=None, score=1.0, strategy="lexical",
            )
        ],
        searcher=FakeSearcher(),
        journal=SQLiteJournal(con),
        clock=lambda: FIXED_CLOCK,
    )

    # ------------------------------------------------- 1. objet non connecté
    print("\n--- 1. objet non connecté (D16 : arrêt avant lecture de marque) ---")
    out_mug = orch.run_object(RunConfig(run_id="run-live"), "coffee-mug", [img("mug")])
    check("NON_IOT : pas d'identification", out_mug.identification is None)
    check("NON_IOT : pas de CVE", out_mug.cves == ())
    codes_after_mug = [row[0] for row in con.execute("SELECT code FROM hmac_chain").fetchall()]
    check("NON_IOT : journal NON_IOT présent", "NON_IOT" in codes_after_mug)

    # ------------------------------------------------------- 2. objet connecté
    print("\n--- 2. objet connecté (chaîne complète) ---")
    out_router = orch.run_object(
        RunConfig(run_id="run-live"), "router-1", [img("photo-1"), img("photo-2")]
    )
    ident = out_router.identification
    check("triage : IoT détecté", out_router.triage.is_iot is True)
    check("identification : statut IDENTIFIED", ident is not None
          and ident.status.value == "identified")
    check("confiance : A = 1.0 (2 photos concordantes)", ident is not None
          and ident.agreement == 1.0, f"A={ident.agreement if ident else '-'}")
    check("confiance : R = 1.0 (CPE exact)", ident is not None
          and ident.resolvability == 1.0, f"R={ident.resolvability if ident else '-'}")
    check("CPE : archer_c7 retenu", bool(out_router.cpe_candidates)
          and out_router.cpe_candidates[0].product == "archer_c7")
    check("CVE : 1 CVE trouvée", len(out_router.cves) == 1
          and out_router.cves[0].cve_id == "CVE-2024-12345")
    check("erreurs : aucune", out_router.error_codes == ())

    # ------------------------------------------------- 3. intégrité du journal
    print("\n--- 3. journal HMAC chaîné (SQLite réel) ---")
    ok_chain, bad = verify_chain(con)
    check("chaîne HMAC vérifiée", ok_chain and bad is None, f"rupture à {bad}")
    n_events = con.execute("SELECT COUNT(*) FROM hmac_chain").fetchone()[0]
    check("événements présents", n_events >= 6, f"n={n_events}")
    head_hmac, chain_len = get_chain_head(con)
    check("tête de chaîne cohérente", head_hmac == out_router.journal_head_hmac)

    # immutabilité : UPDATE refusé par trigger
    try:
        con.execute("UPDATE hmac_chain SET code='TAMPER' WHERE seq=0")
        check("trigger append-only (UPDATE refusé)", False, "UPDATE accepté !")
    except sqlite3.IntegrityError:
        check("trigger append-only (UPDATE refusé)", True)

    # --------------------------------------------------- 4. scellement Ed25519
    print("\n--- 4. rapport scellé Ed25519 + vérification tierce ---")
    priv, pub = generate_ed25519_keypair()
    payload = {
        "object_id": "router-1",
        "triage": {"is_iot": True, "category": "router_ap"},
        "identification": {
            "brand": "TP-Link", "model": "Archer C7", "status": "identified",
            "agreement": 1.0, "resolvability": 1.0,
        },
        "cves": [c.cve_id for c in out_router.cves],
        "chain_head_hmac": head_hmac,
    }
    report = sign_report(
        con=con, report_id="rep-live-1", run_id="run-live",
        created_at="2026-10-06T12:05:00Z", payload=payload, private_key=priv,
    )
    check("rapport : tête de chaîne liée", report.chain_head_hmac == head_hmac)
    check("rapport : longueur de chaîne liée", report.chain_length == chain_len)

    report_file = work / "report.json"
    report_file.write_text(report.to_json(), encoding="utf-8")

    # Sans clé de confiance : le CLI ne prouve que l'auto-cohérence du document
    res = subprocess.run(
        [sys.executable, str(ROOT / "verify_report.py"), str(report_file)],
        capture_output=True, text=True,
    )
    check("CLI tiers sans clé : verdict PARTIEL (origine non prouvée)",
          res.returncode == 3 and "[PARTIEL]" in res.stderr, res.stderr.strip()[:90])

    # Avec la clé de l'auditeur : authenticité prouvée
    res_key = subprocess.run(
        [sys.executable, str(ROOT / "verify_report.py"), str(report_file),
         "--pubkey", report.public_key_b64],
        capture_output=True, text=True,
    )
    check("CLI tiers avec clé de confiance : authentique", res_key.returncode == 0,
          res_key.stdout.strip()[:90])

    # Une autre clé publique : refus (clé de confiance non concordante)
    _, other_pub = generate_ed25519_keypair()
    other_b64 = base64.b64encode(other_pub.public_bytes_raw()).decode("ascii")
    res_wrong = subprocess.run(
        [sys.executable, str(ROOT / "verify_report.py"), str(report_file),
         "--pubkey", other_b64],
        capture_output=True, text=True,
    )
    check("CLI tiers : clé de confiance non concordante refusée", res_wrong.returncode == 1)

    # altération du rapport -> échec attendu, même sous la clé de confiance
    tampered = json.loads(report_file.read_text(encoding="utf-8"))
    tampered["payload"]["cves"].append("CVE-2024-99999")
    (work / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")
    res2 = subprocess.run(
        [sys.executable, str(ROOT / "verify_report.py"), str(work / "tampered.json"),
         "--pubkey", report.public_key_b64],
        capture_output=True, text=True,
    )
    check("CLI tiers : altération détectée sous clé de confiance", res2.returncode == 1)

    # --------------------------------------------- 5. dégradation NVD coupée
    print("\n--- 5. mode dégradé (NVD indisponible) ---")

    class DownSearcher:
        def search(self, cpe: CPECandidate, *, since: date):
            raise RuntimeError("nvd offline")

    orch_down = Orchestrator(
        triage_runner=FakeTriage(), vlm_runner=FakeVLM(),
        pool_provider=orch._pool, searcher=DownSearcher(),
        journal=SQLiteJournal(con), clock=lambda: FIXED_CLOCK,
    )
    out_down = orch_down.run_object(RunConfig(run_id="run-live"), "router-2", [img("photo-3")])
    from iot_audit.contracts import ErrorCode
    check("NVD coupé : E_NVD_UNAVAILABLE", ErrorCode.E_NVD_UNAVAILABLE in out_down.error_codes)
    check("NVD coupé : identification conservée", out_down.identification is not None)
    ok2, _ = verify_chain(con)
    check("chaîne intacte après dégradation", ok2)

    # ---------------------------------------------- 6. provenance du run
    print("\n--- 6. provenance (docs/02 §154 : aucun run sans provenance) ---")
    from iot_audit.pipeline.preflight import missing_provenance_fields
    from iot_audit.pipeline.provenance import build_provenance, load_node_provenance
    from iot_audit.storage.runs import ensure_analysis_runs_schema, record_analysis_run
    from iot_audit.storage.seal import ProvenanceIncompleteError

    # Le prompt de triage est lu à sa source (le harness qui l'envoie) plutôt que
    # recopié : une copie qui dérive donnerait une empreinte qui décrit un autre
    # prompt que celui du run.
    sys.path.insert(0, str(ROOT / "benchmarks"))
    from live_vlm_orchestrator import TRIAGE_PROMPT, TRIAGE_SAMPLING  # noqa: E402

    node_source = os.environ.get("IOT_AUDIT_NODE_PROVENANCE", "")
    node_json = load_node_provenance(node_source) if node_source else {}
    entree = {
        "prompt_text": TRIAGE_PROMPT,
        "nvd_db": ROOT / "corpus" / "nvd.sqlite",
        "cpe_db": ROOT / "corpus" / "cpe.sqlite",
        "sampling_params": dict(TRIAGE_SAMPLING),
        "nodes_used": ("e2e-bench",),
        "started_at": FIXED_CLOCK,
        "finished_at": datetime(2026, 10, 6, 12, 5, tzinfo=UTC),
        "schema_version": "v6",
    }

    prov_vide = build_provenance({}, **entree)
    check("nœud muet : la provenance reste incomplète",
          "model_revision" in missing_provenance_fields(prov_vide))
    try:
        sign_report(
            con=con, report_id="rep-prov-refus", run_id="run-live",
            created_at="2026-10-06T12:06:00Z", payload={"x": 1},
            private_key=generate_ed25519_keypair()[0], provenance=prov_vide,
        )
        check("provenance incomplète : scellement refusé", False, "scellé quand même !")
    except ProvenanceIncompleteError as exc:
        check("provenance incomplète : scellement refusé", True,
              f"{len(exc.missing)} champ(s) manquant(s)")

    # Les empreintes NVD et la version du dictionnaire CPE sont mesurées **ici**, et
    # les bases correspondantes ne sont pas versionnées (elles pèsent des Go). Sans
    # elles, la provenance ne peut pas être complète — et un banc qui planterait là
    # dirait « erreur » là où la bonne réponse est « non mesurable dans cet
    # environnement ». C'est pour ça que ce cas est distingué au lieu d'être levé.
    bases = [ROOT / "corpus" / "nvd.sqlite", ROOT / "corpus" / "cpe.sqlite"]
    if node_source and all(p.is_file() for p in bases):
        provenance = build_provenance(node_json, **entree)
        manquants = missing_provenance_fields(provenance)
        check("provenance du nœud réellement lue", bool(node_json), node_source)
        check("provenance complète : rien ne manque", not manquants, ", ".join(manquants))
        # Tout ce qui suit suppose une provenance complète : on le dit avant de
        # l'écrire en base, parce que `record_analysis_run` refuse une provenance
        # incomplète — et cette exception, dans un banc, serait un plantage et non
        # un verdict.
        if not manquants:
            ensure_analysis_runs_schema(con)
            record_analysis_run(con, run_id="run-live", provenance=provenance,
                                triage_scope="v6")
            report_prov = sign_report(
                con=con, report_id="rep-live-prov", run_id="run-live",
                created_at="2026-10-06T12:07:00Z", payload={"objects": []},
                private_key=priv, provenance=provenance,
            )
            # La provenance voyage **dans** le payload signé (seal.sign_report), donc
            # modifier la révision après coup invalide la signature.
            bloc = report_prov.payload.get("provenance", {})
            check("rapport scellé : révision liée sous la signature",
                  bloc.get("model_revision") == provenance.model_revision,
                  str(bloc.get("model_revision")))
            check("analysis_runs : la ligne existe (docs/02 §154)",
                  con.execute("SELECT COUNT(*) FROM analysis_runs WHERE run_id='run-live'").fetchone()[0] == 1)
    elif node_source:
        absentes = ", ".join(p.name for p in bases if not p.is_file())
        print(f"  (base(s) de la station absente(s) : {absentes} — la provenance ne peut")
        print("   pas être complète ici ; les contrôles ci-dessus éprouvent le refus, pas ce run)")
    else:
        print("  (provenance nœud non fournie : les deux contrôles ci-dessus éprouvent")
        print("   le mécanisme, pas ce run — relancer avec IOT_AUDIT_NODE_PROVENANCE=ssh:<hôte>)")

    # ----------------------------------------------------------- verdict
    print("\n=== VERDICT ===")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} contrôles tenus")
    if failed:
        for n in failed:
            print("  ECART:", n)
        return 1
    print("  Chaîne complète vérifiée en direct : triage → identification → confiance")
    print("  → CPE → CVE → journal HMAC → scellement Ed25519 → vérification tierce.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
