#!/usr/bin/env python3
"""Test EN DIRECT n°1 — orchestrateur de bout en bout contre le vLLM RÉEL.

Contrairement à ``benchmarks/e2e_live_run.py`` (fakes déterministes), ce test
pilote le **vrai** service vLLM (Qwen2.5-VL-7B GPTQ-Int4) sur un nœud zabeth,
via un tunnel SSH local géré par `infra/scripts/tunnel_vllm.sh` :

    photo réelle (corpus gelé)
      → triage {view, category, iot}   [vLLM réel, schéma contraint v6]
      → identification {brand, model}  [vLLM réel, schéma contraint v3]
      → confiance (A, R)               [orchestrateur]
      → résolution CPE → recherche CVE [SQLite local]
      → journal HMAC chaîné → scellement Ed25519 → CLI tiers verify_report.py

Usage :
    infra/scripts/tunnel_vllm.sh start        # auto-réparant, ne meurt pas à la 1re coupure
    ./.venv-core/bin/python benchmarks/live_vlm_orchestrator.py [--endpoint URL]
"""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import urllib.request
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
from iot_audit.storage.journal import SQLiteJournal, ensure_journal_schema, verify_chain  # noqa: E402
from iot_audit.storage.seal import generate_ed25519_keypair, get_chain_head, sign_report  # noqa: E402

CTX = ssl.create_default_context()
FIXED_CLOCK = datetime.now(UTC)

TRIAGE_PROMPT = (
    "You are an IoT triage system. Look at the photograph and answer three questions only, "
    "from the object itself. Do not read or report any brand name or printed text.\n"
    '1) "view": is the picture showing the WHOLE device, or only a DETAIL of it -- a part, '
    "a close-up, a circuit board, a connector, a label?\n"
    '2) "category": the device type, chosen from the closed list: smart_plug, ip_camera, '
    'smart_bulb, router_ap, smart_speaker, other. Use "other" when the object is not a '
    "connected device, or when this view does not let you tell.\n"
    '3) "iot": true if the object shown is a connected device (it can communicate over a '
    "network), false otherwise. Judge from the object's appearance, not from any text.\n"
    "Answer only with the requested fields."
)

TRIAGE_SCHEMA = {
    "type": "object",
    "required": ["view", "category", "iot"],
    "additionalProperties": False,
    "properties": {
        "view": {"enum": ["whole", "detail"]},
        "category": {"enum": ["smart_plug", "ip_camera", "smart_bulb",
                              "router_ap", "smart_speaker", "other"]},
        "iot": {"type": "boolean"},
    },
}

#: Paramètres d'échantillonnage **réellement envoyés** (le corps de la requête
#: est construit dans `_ask`). Ils sont nommés ici plutôt que recopiés dans le
#: corps pour que la provenance d'un run (`pipeline.provenance.build_provenance`)
#: décrive ce qui a été envoyé, et non une copie qui dériverait en silence.
TRIAGE_SAMPLING = {"temperature": 0.0, "seed": 1234, "max_tokens": 640}
IDENT_SAMPLING = {"temperature": 0.0, "seed": 1234, "max_tokens": 512}

IDENT_PROMPT = "Identify the device: brand, model, category."

IDENT_SCHEMA = {
    "type": "object",
    "required": ["brand", "model", "category", "visible_text",
                 "identification_status", "evidence_image_region"],
    "additionalProperties": False,
    "properties": {
        "brand": {"type": "string", "maxLength": 64},
        "model": {"type": "string", "maxLength": 64},
        "category": {"enum": ["smart_plug", "ip_camera", "smart_bulb",
                              "router_ap", "smart_speaker", "other"]},
        "visible_text": {"type": "string", "maxLength": 512},
        "identification_status": {"enum": ["identified", "partial", "unidentifiable"]},
        "evidence_image_region": {"type": "string", "maxLength": 128},
    },
}

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'OK ' if ok else 'ECART'}  {name}" + (f" — {detail}" if detail else ""))


class HTTPVLM:
    """Adaptateur vLLM réel : parle au service via /v1/chat/completions."""

    def __init__(self, endpoint: str, model: str = "qwen2.5-vl-7b") -> None:
        self.endpoint = endpoint
        self.model = model
        self.n_calls = 0

    def _ask(self, image_path: Path, prompt: str, schema: dict) -> dict:
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        sampling = IDENT_SAMPLING if schema is IDENT_SCHEMA else TRIAGE_SAMPLING
        body = {
            "model": self.model,
            "temperature": sampling["temperature"],
            "seed": sampling["seed"],
            # max_tokens doit couvrir le JSON entier, sinon finish_reason=length
            # et le contenu tronqué ne se relit pas (défaut trouvé en live :
            # homepod coupé à 256 tokens -> JSONDecodeError).
            "max_tokens": sampling["max_tokens"],
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                {"type": "text", "text": prompt},
            ]}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "out", "schema": schema,
                                                "strict": True}},
        }
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120, context=CTX) as resp:
                payload = json.load(resp)
        except (TimeoutError, urllib.error.URLError) as exc:
            raise TimeoutError(f"vLLM injoignable ou lent : {exc}") from exc
        self.n_calls += 1
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            # modèle entré dans une boucle de répétition (\t\n…) — défaut réel
            # observé en live sur homepod : ce n'est pas un délai mais une sortie
            # inexploitable (taxonomie : E_VLM_INVALID_JSON)
            raise ValueError("réponse tronquée ou en boucle (finish_reason=length)")
        return json.loads(choice["message"]["content"])

    def triage(self, image: ImageInput, *, prompt_version: str) -> VLMTriageOutput:
        out = self._ask(image.path, TRIAGE_PROMPT, TRIAGE_SCHEMA)
        # Le nombre d'objets n'est pas demandé par le prompt v6 : le champ est
        # donc absent, et ``None`` dit « non vérifié » — pas « un objet ». Un
        # futur prompt qui pose la question (v7) rend la valeur ici sans qu'une
        # ligne bouge, parce qu'un défaut silencieux serait à nouveau le défaut.
        n_raw = out.get("n_salient_objects")
        return VLMTriageOutput(
            view=ViewType(out["view"]),
            category=Category(out["category"]),
            iot=bool(out["iot"]),
            n_salient_objects=None if n_raw is None else int(n_raw),
        )

    def infer(self, image: ImageInput, *, prompt_version: str) -> VLMRawOutput:
        out = self._ask(image.path, IDENT_PROMPT, IDENT_SCHEMA)
        return VLMRawOutput(
            brand=out.get("brand", ""),
            model=out.get("model", ""),
            category=Category(out.get("category", "other")),
            visible_text=out.get("visible_text", ""),
            evidence_image_region=out.get("evidence_image_region", ""),
            confidence_self=0.0,
        )


class EmptySearcher:
    """Recherche CVE sans base locale : rend explicitement une liste vide."""

    def search(self, cpe: CPECandidate, *, since: date) -> list[CVEResult]:
        return []


class CPEPool:
    """Bassin de candidats CPE depuis le vrai dictionnaire NIST (``corpus/cpe.sqlite``)."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def __call__(self, brand: str | None, model: str, category: object, k: int) -> list[CPECandidate]:
        from rapidfuzz import fuzz

        from iot_audit.pipeline.normalize import canon_vendor, normalize_display

        v = canon_vendor(brand or "").replace(" ", "-")
        rows = self.con.execute(
            """
            SELECT vendor, product, version FROM cpe_entries
            WHERE part = 'h' AND vendor = ?
            LIMIT 400
            """,
            (v,),
        ).fetchall()
        if not rows:
            # pas de vendeur : pas de candidat inventé (docs/05 §3.2)
            return []
        m = normalize_display(model)
        scored = []
        for vendor, product, version in rows:
            prod_disp = (product or "").replace("_", " ")
            s = fuzz.token_set_ratio(m, prod_disp) / 100.0
            if s < 0.45:
                continue
            scored.append((s, CPECandidate(
                cpe_name=f"cpe:2.3:h:{vendor}:{product}:{version or '*'}:*:*:*:*:*:*:*",
                vendor=vendor, product=product, version=version,
                category=Category.OTHER, lexical_score=s, semantic_score=None,
                score=s, strategy="lexical",
            )))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [c for _s, c in scored[:k * 4]]


class CVEDB:
    """Recherche CVE sur la base NVD locale du dépôt (benchmarks/run_cve.py)."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def search(self, cpe: CPECandidate, *, since: date) -> list[CVEResult]:
        rows = self.con.execute(
            """
            SELECT DISTINCT c.cve_id, c.cvss_v3_score, c.cvss_v3_severity, c.published
            FROM cve_cpe_criteria k JOIN cves c ON c.cve_id = k.cve_id
            WHERE k.vendor = ? AND k.product = ?
              AND (k.version IS NULL OR k.version IN ('*', ?))
            LIMIT 20
            """,
            (cpe.vendor, cpe.product, cpe.version or "*"),
        ).fetchall()
        # NVD publie `2022-02-18T20:15:17.633` (millisecondes) :
        # `date.fromisoformat` sur la chaîne entière lève ValueError — un défaut
        # réel trouvé par ce test live, qui était avalé en E_NVD_UNAVAILABLE.
        # La date seule (10 premiers caractères) est ce que le contrat porte.
        return [CVEResult(
            cve_id=r[0], cvss_v3_score=r[1], severity=r[2],
            published=date.fromisoformat(r[3][:10]) if r[3] else date.min,
            match_basis="exact_product", criteria_used=(cpe.cpe_name,),
            cache_status="hit",
        ) for r in rows]


def img_from_record(rec: dict, images_dir: Path) -> ImageInput | None:
    """Construit un ImageInput depuis une entrée du manifeste runner v6."""
    import hashlib

    dest = images_dir / (hashlib.sha1(rec["image_id"].encode()).hexdigest() + ".jpg")
    if not dest.exists():
        return None
    return ImageInput(
        image_id=rec["image_id"], path=dest, sha256=rec.get("sha256_local", ""),
        stratum=Stratum(rec.get("stratum", "review")),
        source_url=rec.get("url", ""), license=rec.get("license", ""),
        retrieved_at=FIXED_CLOCK, width=0, height=0,
        text_visible=bool(rec.get("text_visible")),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:18000/v1/chat/completions")
    ap.add_argument("--images-dir", default=str(Path.home() / "iot-corpus-measure/images"))
    ap.add_argument("--n", type=int, default=4, help="nombre de photos à traiter")
    args = ap.parse_args()

    # ------------------------------------------------- portée : photos réelles
    runner_src = ROOT / "corpus" / "runner6-v6-triage.py"
    ns: dict = {}
    exec(compile(runner_src.read_text(encoding="utf-8").split("def fetch")[0],
                 str(runner_src), "exec"), ns)
    items = ns["MANIFEST"]["items"]
    images_dir = Path(args.images_dir)

    # sélection : 2 objets IoT variés + 1 objet non connecté si présent
    chosen: list[ImageInput] = []
    seen_objs: set[str] = set()
    for rec in items:
        im = img_from_record(rec, images_dir)
        if im is None or rec["object_id"] in seen_objs:
            continue
        seen_objs.add(rec["object_id"])
        chosen.append(im)
        if len(chosen) >= args.n:
            break
    if not chosen:
        print("ERREUR : aucune image trouvée dans", images_dir, file=sys.stderr)
        return 2

    vlm = HTTPVLM(args.endpoint)
    print(f"=== Test live orchestrateur — {len(chosen)} photo(s), endpoint {args.endpoint} ===")

    work = Path(tempfile.mkdtemp(prefix="live-orch-"))
    con = sqlite3.connect(work / "journal.sqlite")
    ensure_journal_schema(con)

    nvd_path = ROOT / "corpus" / "nvd.sqlite"
    nvd = sqlite3.connect(nvd_path) if nvd_path.exists() else None
    if nvd is not None:
        n_cve = nvd.execute("SELECT COUNT(*) FROM cves").fetchone()[0]
        print(f"base NVD locale : {nvd_path} ({n_cve} CVE)")

    cpe_path = ROOT / "corpus" / "cpe.sqlite"
    cpe_db = sqlite3.connect(cpe_path) if cpe_path.exists() else None
    if cpe_db is not None:
        n_cpe = cpe_db.execute("SELECT COUNT(*) FROM cpe_entries WHERE part='h'").fetchone()[0]
        print(f"dictionnaire CPE : {cpe_path} ({n_cpe} entrées hardware)")

    orch = Orchestrator(
        triage_runner=vlm, vlm_runner=vlm,
        pool_provider=CPEPool(cpe_db) if cpe_db is not None else (lambda b, m, c, k: []),
        searcher=CVEDB(nvd) if nvd is not None else EmptySearcher(),
        journal=SQLiteJournal(con),
        clock=lambda: FIXED_CLOCK,
    )

    # ------------------------------------------------------------- run réel
    from collections import defaultdict
    by_obj: dict[str, list[ImageInput]] = defaultdict(list)
    for im in chosen:
        # remonte à l'objet via le manifeste
        for rec in items:
            if rec["image_id"] == im.image_id:
                by_obj[rec["object_id"]].append(im)
                break

    for oid, imgs in by_obj.items():
        print(f"\n--- objet : {oid} ({len(imgs)} photo(s)) ---")
        out = orch.run_object(RunConfig(run_id="live-orch"), oid, imgs)
        tri = out.triage
        print(f"    triage : is_iot={tri.is_iot} cat={tri.category.value} "
              f"view_whole={tri.whole_view_ratio:.2f}")
        if out.identification is not None:
            ident = out.identification
            print(f"    ident  : brand={ident.brand!r} model={ident.model!r} "
                  f"status={ident.status.value} A={ident.agreement:.2f} R={ident.resolvability:.2f}")
        print(f"    cpe    : {[c.cpe_name for c in out.cpe_candidates]}")
        print(f"    cves   : {[c.cve_id for c in out.cves]}")
        print(f"    erreurs: {[e.value for e in out.error_codes]}")
        check(f"{oid} : run sans crash", True,
              f"iot={tri.is_iot} err={[e.value for e in out.error_codes]}")

    # --------------------------------------------------- intégrité + scellé
    ok_chain, bad = verify_chain(con)
    check("journal HMAC vérifié (vLLM réel)", ok_chain and bad is None)

    n_calls = vlm.n_calls
    check("appels vLLM réels effectués", n_calls > 0, f"n={n_calls}")

    priv, pub = generate_ed25519_keypair()
    head, ln = get_chain_head(con)
    report = sign_report(
        con=con, report_id="live-orch-1", run_id="live-orch",
        created_at=FIXED_CLOCK.isoformat(),
        payload={"head": head, "n_images": len(chosen), "n_vlm_calls": n_calls},
        private_key=priv,
    )
    rf = work / "report.json"
    rf.write_text(report.to_json(), encoding="utf-8")
    # Sans clé de confiance : auto-cohérence seulement (code 3, jamais « authentique »)
    res = subprocess.run([sys.executable, str(ROOT / "verify_report.py"), str(rf)],
                         capture_output=True, text=True)
    check("CLI tiers sans clé : verdict PARTIEL (origine non prouvée)",
          res.returncode == 3 and "[PARTIEL]" in res.stderr, res.stderr.strip()[:80])

    # Avec la clé publique de l'auditeur : authenticité prouvée
    res_key = subprocess.run(
        [sys.executable, str(ROOT / "verify_report.py"), str(rf),
         "--pubkey", report.public_key_b64],
        capture_output=True, text=True,
    )
    check("CLI tiers avec clé de confiance : authentique", res_key.returncode == 0,
          res_key.stdout.strip()[:80])

    print("\n=== VERDICT ===")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} contrôles tenus")
    for n in failed:
        print("  ECART:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
