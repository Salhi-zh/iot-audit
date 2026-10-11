"""Serveur local de l'interface — l'opérateur clique au lieu de taper des commandes.

Ce que ce serveur est, et ce qu'il n'est pas
--------------------------------------------
Ce n'est **pas** une API produit : il n'écoute que sur ``127.0.0.1``, il n'a ni
authentification ni utilisateur, et il ne sert qu'au poste de l'auditeur. C'est
la version cliquable de ce que l'opérateur faisait à la main :
``tunnel_vllm.sh status``, ``pytest``, ``ruff``, ``mypy``,
``selftest/check-tunnel-scope.sh``, le banc live et ``verify_report.py``.

Deux règles de conception, toutes deux dans les documents :

* **docs/05 §4 (règle de conception)** — « l'UI affiche (A, R) *et* la
  distribution. Le score unique n'existe que pour trier une liste. » Le serveur
  ne calcule donc **aucun** score composite : il transmet ``agreement``,
  ``resolvability``, ``per_field_agreement`` et ``distribution`` tels que
  l'orchestrateur les a produits.
* **docs/03 §3 (C2)** — la confiance est calculée par l'orchestrateur, jamais par
  la couche d'affichage. Ce fichier ne réimplémente ni ``wilson`` ni l'accord :
  il appelle ``Orchestrator.run_object`` et sérialise le résultat.

Pourquoi les runs longs sont des *jobs*
----------------------------------------
Un run live dure des minutes et un ``pytest`` complet des dizaines de secondes :
une requête HTTP synchrone expirerait ou bloquerait l'affichage, et l'opérateur
perdrait la sortie au moment précis où elle devient intéressante (l'échec). Les
travaux s'exécutent donc dans un fil, la sortie est conservée ligne à ligne, et
la page l'interroge. Un run échoué garde sa trace : c'est la même exigence que
« on ne produit pas de résultat non tracé » (C5), appliquée aux commandes.

Sécurité, en une phrase : les commandes lancées sont une **liste fixe** écrite
ici, jamais composée à partir de la requête HTTP. Un identifiant d'objet est
validé contre le manifeste avant usage, et il n'y a aucun passage par un shell.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import threading
import traceback
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATIC_DIR = Path(__file__).resolve().parent / "static"
#: Les artefacts de run vont sous ``logs/`` : déjà ignoré par git, donc aucune
#: retouche de ``.gitignore`` — et un fichier de travail n'a rien à y faire.
RUNS_DIR = ROOT / "logs" / "ui-runs"
IMAGES_DIR = Path.home() / "iot-corpus-measure" / "images"
TUNNEL = ROOT / "infra" / "scripts" / "tunnel_vllm.sh"
RUNNER_MANIFEST = ROOT / "corpus" / "runner6-v6-triage.py"
VENV_BIN = ROOT / ".venv-core" / "bin"
#: Où lire la provenance du nœud : `ssh:<hôte>` ou un chemin local (voir
#: `pipeline.provenance.load_node_provenance`). Sans elle, les quatre champs que
#: la station ne peut pas mesurer restent des trous — et un run scellé sans
#: provenance dit, dans son propre payload, qu'il n'est pas reproductible.
DEFAULT_NODE_PROVENANCE = os.environ.get("IOT_AUDIT_NODE_PROVENANCE", "ssh:zabeth21")
DEFAULT_ENDPOINT = "http://127.0.0.1:18000/v1/chat/completions"

#: Fichiers servis, et eux seuls. Pas de résolution de chemin depuis la requête :
#: une liste blanche de trois noms ne peut pas traverser l'arborescence.
STATIC_WHITELIST = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

MAX_IMAGES_PER_OBJECT = 6


# --------------------------------------------------------------------------- #
# Travaux (jobs)
# --------------------------------------------------------------------------- #
@dataclass
class Job:
    """Un travail lancé par l'interface et suivi par l'opérateur.

    ``log`` est conservé intégralement, sans troncature : la sortie d'un échec
    est la raison d'être de ce mécanisme, la couper reviendrait à la perdre.
    """

    id: str
    kind: str
    title: str
    argv: list[str] = field(default_factory=list)
    state: str = "running"          # running | done | failed
    exit_code: int | None = None
    log: list[str] = field(default_factory=list)
    result: Any = None
    started_at: str = ""
    finished_at: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "argv": self.argv,
            "state": self.state,
            "exit_code": self.exit_code,
            "log": self.log,
            "result": self.result,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def _new_job(kind: str, title: str, argv: list[str] | None = None) -> Job:
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind=kind,
        title=title,
        argv=argv or [],
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    with JOBS_LOCK:
        JOBS[job.id] = job
    return job


def _log(job: Job, line: str) -> None:
    with JOBS_LOCK:
        job.log.append(line.rstrip("\n"))


def _finish(job: Job, state: str, exit_code: int | None) -> None:
    with JOBS_LOCK:
        job.state = state
        job.exit_code = exit_code
        job.finished_at = datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Commandes : liste fixe, jamais composée depuis la requête
# --------------------------------------------------------------------------- #
def python_exe() -> str:
    """L'interpréteur du projet s'il existe, sinon celui qui fait tourner ce serveur."""
    cand = VENV_BIN / "python"
    return str(cand) if cand.exists() else sys.executable


def gate_argv(name: str) -> list[str] | None:
    """Les portes de vérification, telles que le dépôt les documente.

    Ces listes sont recopiées de la sortie de ``README.md`` / ``docs/07 §7`` :
    l'interface lance *ces* commandes-là, pas des variantes — une porte qui ne
    vérifie pas ce que la CI vérifie ne vaut rien.
    """
    py = python_exe()
    ruff = str(VENV_BIN / "ruff")
    gates: dict[str, list[str]] = {
        "tests": [py, "-m", "pytest", "-q"],
        "lint": [ruff, "check", "iot_audit", "verify_report.py", "benchmarks", "tests"],
        "types": [py, "-m", "mypy"],
        "tunnel-scope": ["bash", "infra/selftest/check-tunnel-scope.sh"],
        "live-e2e": [py, "benchmarks/live_vlm_orchestrator.py"],
    }
    return gates.get(name)


def run_command_job(job: Job, argv: list[str]) -> None:
    """Exécute une commande fixe en flux, ligne à ligne (pas de shell)."""
    _log(job, f"$ {' '.join(argv)}")
    try:
        proc = subprocess.Popen(
            argv, cwd=str(ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
    except FileNotFoundError as exc:
        _log(job, f"!! commande introuvable : {exc}")
        _finish(job, "failed", None)
        return
    assert proc.stdout is not None
    for line in proc.stdout:
        _log(job, line)
    code = proc.wait()
    _finish(job, "done" if code == 0 else "failed", code)


def spawn_command_job(kind: str, title: str, argv: list[str]) -> Job:
    job = _new_job(kind, title, argv)
    threading.Thread(
        target=run_command_job, args=(job, argv), name=f"job-{job.id}", daemon=True
    ).start()
    return job


# --------------------------------------------------------------------------- #
# Tunnel : l'état réel, pas la présence d'un processus
# --------------------------------------------------------------------------- #
def tunnel_argv(action: str) -> list[str]:
    return ["bash", str(TUNNEL), action]


def tunnel_state() -> dict[str, Any]:
    """Renvoie la sortie du script de tunnel, plus sa lecture structurée.

    La page affiche le texte brut *et* des champs : le texte brut parce qu'il
    vient d'un script que l'opérateur connaît, les champs pour la mise en
    couleur. Un tunnel mort doit se voir comme mort — un listener présent ne
    prouve rien, c'est mesuré (en-tête de ``infra/scripts/tunnel_vllm.sh``).
    """
    try:
        res = subprocess.run(
            tunnel_argv("status"), cwd=str(ROOT), capture_output=True, text=True, timeout=30
        )
        output = (res.stdout + res.stderr).strip()
        reachable = "OK" in res.stdout and res.returncode == 0
        return {
            "reachable": reachable,
            "exit_code": res.returncode,
            "output": output,
            "model": _model_from_status(output),
            "command": " ".join(tunnel_argv("status")),
        }
    except Exception as exc:  # script absent, non exécutable, délai dépassé
        return {
            "reachable": False, "exit_code": None,
            "output": f"!! impossible d'exécuter le script de tunnel : {exc}",
            "model": None, "command": " ".join(tunnel_argv("status")),
        }


def _model_from_status(output: str) -> str | None:
    marker = "model '"
    if marker in output:
        return output.split(marker, 1)[1].split("'", 1)[0]
    return None


def endpoint_answers(endpoint: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    """Le tunnel répond-il réellement ? Une requête HTTP, pas un socket ouvert."""
    base = endpoint.split("/v1/")[0]
    url = f"{base}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    ids = [m.get("id") for m in payload.get("data", [])]
    return bool(ids), ", ".join(str(i) for i in ids) or "aucun modèle annoncé"


# --------------------------------------------------------------------------- #
# Corpus : le manifeste gelé, lu comme le banc live le lit
# --------------------------------------------------------------------------- #
def load_manifest_items() -> list[dict[str, Any]]:
    """Extrait le manifeste v6 du runner gelé.

    Le mécanisme est celui du banc live vérifié
    (``benchmarks/live_vlm_orchestrator.py``) : on exécute l'en-tête du fichier
    jusqu'à ``def fetch`` pour récupérer ``MANIFEST``. Recopier ce manifeste
    ailleurs produirait une seconde vérité terrain — le défaut que ce dépôt
    traque partout ailleurs.
    """
    src = RUNNER_MANIFEST.read_text(encoding="utf-8").split("def fetch")[0]
    namespace: dict[str, Any] = {}
    exec(compile(src, str(RUNNER_MANIFEST), "exec"), namespace)  # noqa: S102
    return list(namespace["MANIFEST"]["items"])


def _cached_image(image_id: str) -> Path:
    import hashlib

    return IMAGES_DIR / (hashlib.sha1(image_id.encode()).hexdigest() + ".jpg")


def corpus_summary() -> dict[str, Any]:
    """Objets du corpus, avec le nombre de photos réellement en cache local."""
    try:
        items = load_manifest_items()
    except Exception as exc:
        return {"error": f"manifeste illisible : {exc}", "objects": [], "n_images_cached": 0}

    by_object: dict[str, dict[str, Any]] = {}
    n_cached = 0
    for rec in items:
        oid = rec["object_id"]
        entry = by_object.setdefault(
            oid,
            {
                "object_id": oid,
                "brand": rec.get("truth_brand"),
                "model": rec.get("truth_model"),
                "category": rec.get("truth_category"),
                "strata": [],
                "n_images": 0,
                "n_cached": 0,
                "text_visible_any": False,
            },
        )
        entry["n_images"] += 1
        if rec.get("stratum") not in entry["strata"]:
            entry["strata"].append(rec.get("stratum"))
        if rec.get("text_visible"):
            entry["text_visible_any"] = True
        if _cached_image(rec["image_id"]).exists():
            entry["n_cached"] += 1
            n_cached += 1

    objects = sorted(by_object.values(), key=lambda o: o["object_id"])
    return {
        "manifest": str(RUNNER_MANIFEST.relative_to(ROOT)),
        "prompt_version": "v6",
        "images_dir": str(IMAGES_DIR),
        "n_objects": len(objects),
        "n_images": len(items),
        "n_images_cached": n_cached,
        "objects": objects,
    }


def db_summary() -> dict[str, Any]:
    """Taille des bases locales — sans elles, la chaîne s'arrête au CPE."""
    out: dict[str, Any] = {}
    for name in ("cpe.sqlite", "nvd.sqlite", "corpus.sqlite"):
        path = ROOT / "corpus" / name
        if not path.exists():
            out[name] = None
            continue
        out[name] = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size}
    return out


# --------------------------------------------------------------------------- #
# Run live : le vrai orchestrateur, sur de vraies photos
# --------------------------------------------------------------------------- #
def _load_harness() -> Any:
    """Charge le banc live vérifié comme une bibliothèque.

    ``benchmarks/`` n'est pas un paquet installable et n'a pas à le devenir : on
    charge le fichier par chemin. L'alternative — réécrire ici un client HTTP
    vLLM et un bassin CPE — serait une **seconde** implémentation du chemin
    mesuré, c'est-à-dire exactement ce que le projet refuse ailleurs.
    """
    path = ROOT / "benchmarks" / "live_vlm_orchestrator.py"
    spec = importlib.util.spec_from_file_location("iot_audit_live_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identification_json(ident: Any) -> dict[str, Any] | None:
    """Sérialise l'identification **sans rien recalculer** (docs/03 §3, C2)."""
    if ident is None:
        return None
    return {
        "brand": ident.brand,
        "model": ident.model,
        "category": ident.category.value,
        "status": ident.status.value,
        "agreement": ident.agreement,
        "resolvability": ident.resolvability,
        "per_field_agreement": dict(ident.per_field_agreement),
        "distribution": dict(ident.distribution),
        "n_images": ident.n_images,
        "cpe_candidates": [
            {
                "cpe_name": c.cpe_name,
                "vendor": c.vendor,
                "product": c.product,
                "version": c.version,
                "score": c.score,
                "lexical_score": c.lexical_score,
                "semantic_score": c.semantic_score,
                "strategy": c.strategy,
            }
            for c in ident.cpe_candidates
        ],
        "cves": [
            {
                "cve_id": c.cve_id,
                "cvss_v3_score": c.cvss_v3_score,
                "severity": c.severity,
                "published": c.published.isoformat(),
                "match_basis": c.match_basis,
                "cache_status": c.cache_status,
            }
            for c in ident.cves
        ],
    }


def _triage_json(tri: Any) -> dict[str, Any]:
    return {
        "is_iot": tri.is_iot,
        "category": tri.category.value,
        "iot_agreement": tri.iot_agreement,
        "category_agreement": tri.category_agreement,
        "whole_view_ratio": tri.whole_view_ratio,
        "n_images": tri.n_images,
        # Cadrage : « unverified » n'est pas une conformité, et l'écrire vaut
        # mieux que de le laisser déduire de l'absence de code d'erreur.
        "framing": tri.framing,
        "category_distribution": dict(tri.category_distribution),
        "view_distribution": dict(tri.view_distribution),
    }


def _node_name_from_source(source: str) -> str:
    """L'hôte nommé par la source de provenance, `""` si elle n'en nomme aucun."""
    return source[4:].strip() if source.startswith("ssh:") else ""


def run_pipeline_job(job: Job, payload: dict[str, Any]) -> None:
    """Exécute la chaîne complète sur les objets demandés, puis scelle et vérifie."""
    started_at = datetime.now(UTC)
    try:
        endpoint = str(payload.get("endpoint") or DEFAULT_ENDPOINT)
        # La source de provenance est un paramètre du run, et non une constante
        # figée : un opérateur qui change de nœud doit pouvoir le dire ici.
        node_provenance_source = str(
            payload.get("node_provenance") or DEFAULT_NODE_PROVENANCE
        )

        # 0. Le tunnel répond-il ? La panne n°1 de ce projet est silencieuse :
        #    un benchmark qui ne joint pas le modèle ressemble à un benchmark qui
        #    n'a rien produit. Ici, elle est dite avant de consommer du temps.
        answers, detail = endpoint_answers(endpoint)
        _log(job, f"endpoint {endpoint} -> {'joignable' if answers else 'INJOIGNABLE'} ({detail})")
        if not answers:
            _log(job, "!! le service ne répond pas : démarrer le tunnel (onglet Infra) puis relancer.")
            _finish(job, "failed", None)
            return

        items = load_manifest_items()
        by_object: dict[str, list[dict[str, Any]]] = {}
        for rec in items:
            by_object.setdefault(rec["object_id"], []).append(rec)

        requested = [str(o) for o in payload.get("object_ids", [])]
        unknown = [o for o in requested if o not in by_object]
        if unknown:
            _log(job, f"!! objet(s) inconnu(s) du manifeste, ignorés : {unknown}")
        selected = [o for o in requested if o in by_object]
        if not selected:
            _log(job, "!! aucun objet valide sélectionné.")
            _finish(job, "failed", None)
            return

        max_images = int(payload.get("max_images") or 3)
        max_images = max(1, min(MAX_IMAGES_PER_OBJECT, max_images))

        from iot_audit.pipeline.orchestrate import Orchestrator, RunConfig
        from iot_audit.storage.journal import SQLiteJournal, ensure_journal_schema, verify_chain
        from iot_audit.storage.seal import generate_ed25519_keypair, get_chain_head, sign_report

        harness = _load_harness()
        work = RUNS_DIR / job.id
        work.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(work / "journal.sqlite")
        ensure_journal_schema(con)

        cpe_path = ROOT / "corpus" / "cpe.sqlite"
        nvd_path = ROOT / "corpus" / "nvd.sqlite"
        cpe_db = sqlite3.connect(cpe_path) if cpe_path.exists() else None
        nvd_db = sqlite3.connect(nvd_path) if nvd_path.exists() else None
        _log(job, f"dictionnaire CPE : {'absent' if cpe_db is None else cpe_path.name}")
        _log(job, f"base NVD : {'absente' if nvd_db is None else nvd_path.name}")

        # Un seul client HTTP pour les deux étapes : c'est un objet sans état
        # (il ne garde que l'URL), et en construire deux ferait deux pools de
        # connexions pour rien.
        vlm = harness.HTTPVLM(endpoint)
        orch = Orchestrator(
            triage_runner=vlm,
            vlm_runner=vlm,
            pool_provider=harness.CPEPool(cpe_db) if cpe_db is not None
            else (lambda b, m, c, k: []),
            searcher=harness.CVEDB(nvd_db) if nvd_db is not None
            else harness.EmptySearcher(),
            journal=SQLiteJournal(con),
            # Horloge réelle : l'opérateur regarde un run, pas une reproduction.
            clock=lambda: datetime.now(UTC),
        )

        # Un seul `RunConfig` pour le run et pour sa provenance : la version du
        # prompt de triage doit être celle qui a été envoyée, pas une constante
        # recopiée à côté du code qui l'envoie.
        config = RunConfig(run_id=job.id)

        results: list[dict[str, Any]] = []
        for oid in selected:
            images = []
            for rec in by_object[oid]:
                im = harness.img_from_record(rec, IMAGES_DIR)
                if im is not None:
                    images.append(im)
                if len(images) >= max_images:
                    break
            if not images:
                _log(job, f"!! {oid} : aucune image en cache local, objet ignoré")
                continue
            _log(job, f"--- {oid} : {len(images)} photo(s) ---")
            out = orch.run_object(config, oid, images)
            tri = _triage_json(out.triage)
            ident = _identification_json(out.identification)
            _log(
                job,
                f"    triage iot={tri['is_iot']} cat={tri['category']}"
                f" | A={'-' if ident is None else format(ident['agreement'], '.2f')}"
                f" R={'-' if ident is None else format(ident['resolvability'], '.2f')}"
                f" | erreurs={[e.value for e in out.error_codes]}",
            )
            results.append(
                {
                    "object_id": oid,
                    "truth": {
                        "brand": by_object[oid][0].get("truth_brand"),
                        "model": by_object[oid][0].get("truth_model"),
                        "category": by_object[oid][0].get("truth_category"),
                    },
                    "n_images_ok": out.n_images_ok,
                    "n_images_failed": out.n_images_failed,
                    "triage": tri,
                    "identification": ident,
                    "error_codes": [e.value for e in out.error_codes],
                }
            )

        rows = con.execute(
            "SELECT seq, stage, code, payload, occurred_at FROM hmac_chain ORDER BY seq ASC"
        ).fetchall()
        chain_ok, break_index = verify_chain(con)
        head_hmac, chain_length = get_chain_head(con)

        # ---------------------------------------------------------- provenance
        # Assembler la provenance (docs/02 §154), puis refuser de présenter un
        # run complet quand elle ne l'est pas. Les quatre champs que la station
        # ne peut pas mesurer viennent du nœud ; les autres sont mesurés ici.
        from iot_audit.pipeline.preflight import missing_provenance_fields
        from iot_audit.pipeline.provenance import build_provenance, load_node_provenance
        from iot_audit.storage.runs import (
            ensure_analysis_runs_schema,
            record_analysis_run,
        )

        node_json = load_node_provenance(node_provenance_source)
        _log(job, f"provenance nœud : {node_provenance_source} -> "
                  f"{'lue' if node_json else 'ILLISIBLE (champs du nœud manquants)'}")
        node_name = str(node_json.get("hostname") or "") or _node_name_from_source(
            node_provenance_source
        )
        provenance = build_provenance(
            node_json,
            prompt_text=str(getattr(harness, "TRIAGE_PROMPT", "")),
            nvd_db=nvd_path,
            cpe_db=cpe_path,
            sampling_params=dict(getattr(harness, "TRIAGE_SAMPLING", {})),
            nodes_used=(node_name,) if node_name else (),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            schema_version=config.triage_prompt_version,
        )
        missing = missing_provenance_fields(provenance)
        if missing:
            for champ in missing:
                _log(job, f"!! provenance : {champ} non établi")
            _log(job, "!! le rapport est scellé SANS provenance : il le déclare "
                      "dans son payload signé, et il n'est pas reproductible.")
        else:
            ensure_analysis_runs_schema(con)
            record_analysis_run(
                con, run_id=job.id, provenance=provenance,
                triage_scope=config.triage_prompt_version,
            )
            _log(job, f"provenance complète : révision {provenance.model_revision[:12]}…"
                      f" | poids {provenance.weights_sha256[:12]}…"
                      f" | nœud {node_name}")

        priv, _pub = generate_ed25519_keypair()
        report = sign_report(
            con=con,
            report_id=f"ui-{job.id}",
            run_id=job.id,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            payload={
                "objects": results,
                # Ce que le rapport ne décrit pas, il le dit — dans le payload
                # signé, donc non retirable après coup.
                "provenance_status": "incomplete" if missing else "complete",
                "provenance_missing": list(missing),
            },
            private_key=priv,
            provenance=None if missing else provenance,
        )
        report_path = work / "report.json"
        report_path.write_text(report.to_json(), encoding="utf-8")
        _log(job, f"rapport scellé : {report_path}")

        verify = _verify_report_verdicts(report_path, report.public_key_b64)
        for name, verdict in verify.items():
            _log(job, f"    {name} : code={verdict['exit_code']} {verdict['summary']}")

        job.result = {
            "run_id": job.id,
            "endpoint": endpoint,
            "max_images_per_object": max_images,
            "provenance": {
                "status": "incomplete" if missing else "complete",
                "missing": list(missing),
                "model_revision": provenance.model_revision,
                "weights_sha256": provenance.weights_sha256,
                "vllm_version": provenance.vllm_version,
                "torch_version": provenance.torch_version,
                "nodes_used": list(provenance.nodes_used),
                "source": node_provenance_source,
            },
            "objects": results,
            "journal": [
                {"seq": r[0], "stage": r[1], "code": r[2], "payload": json.loads(r[3]),
                 "occurred_at": r[4]}
                for r in rows
            ],
            "chain": {"ok": bool(chain_ok), "break_index": break_index,
                      "head_hmac": head_hmac, "length": chain_length},
            "report": {
                "path": str(report_path.relative_to(ROOT)),
                "chain_head_hmac": report.chain_head_hmac,
                "chain_length": report.chain_length,
                "public_key_b64": report.public_key_b64,
                "verify": verify,
            },
        }
        # Le résultat survit à un rechargement de page. Sans cela, l'opérateur
        # qui actualise (ou rouvre l'onglet) perd le run qu'il vient de payer en
        # minutes de GPU : personne ne garde une interface qui efface son
        # travail sur F5. Le pointeur nomme le run courant ; le résultat reste
        # dans le dossier du run, donc les runs précédents restent lisibles.
        (work / "result.json").write_text(
            json.dumps(job.result, ensure_ascii=False), encoding="utf-8"
        )
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / "last-run.json").write_text(
            json.dumps({"run_id": job.id}), encoding="utf-8"
        )
        _finish(job, "done", 0)
    except Exception:
        _log(job, traceback.format_exc())
        _finish(job, "failed", None)


def last_run_payload() -> dict[str, Any]:
    """Le dernier run terminé, ou une absence explicite.

    L'absence est renvoyée comme telle (``{"run": None}``) et non comme une
    erreur : une interface neuve n'a pas de dernier run, ce n'est pas un défaut.
    """
    pointer = RUNS_DIR / "last-run.json"
    if not pointer.exists():
        return {"run": None}
    try:
        run_id = json.loads(pointer.read_text(encoding="utf-8"))["run_id"]
        result = json.loads((RUNS_DIR / str(run_id) / "result.json").read_text(encoding="utf-8"))
    except (ValueError, KeyError, OSError) as exc:
        return {"run": None, "warning": f"dernier run illisible : {exc}"}
    return {"run": result}


def _verify_report_verdicts(report_path: Path, public_key_b64: str) -> dict[str, dict[str, Any]]:
    """Les deux verdicts du CLI tiers : sans clé (auto-cohérence) et avec clé.

    Ce sont les deux lignes qui comptent dans ``docs/07 §4.4`` : sans clé publiée
    le document ne prouve que sa cohérence interne (code 3, jamais un succès),
    avec la clé de l'auditeur il prouve son authenticité (code 0).
    """
    py = python_exe()
    out: dict[str, dict[str, Any]] = {}
    for name, extra in (("sans_cle_de_confiance", []), ("avec_cle_de_confiance",
                                                       ["--pubkey", public_key_b64])):
        try:
            res = subprocess.run(
                [py, "verify_report.py", str(report_path), *extra],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60,
            )
            summary = (res.stdout + res.stderr).strip().splitlines()
            out[name] = {
                "exit_code": res.returncode,
                "summary": summary[-1] if summary else "",
            }
        except Exception as exc:
            out[name] = {"exit_code": None, "summary": f"!! {exc}"}
    return out


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "iot-audit-ui"
    protocol_version = "HTTP/1.1"

    # ---------------- utilitaires ----------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # L'UI ne charge rien d'extérieur : cette politique rend la promesse
        # exécutable par le navigateur plutôt que déclarative.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _local_only(self) -> bool:
        """Refuse un ``Host`` qui n'est pas local (anti-DNS-rebinding).

        Un serveur qui écoute sur ``127.0.0.1`` reste joignable par un nom de
        domaine qui résout vers ``127.0.0.1`` : sans ce contrôle, une page
        hostile ouverte dans le même navigateur pourrait piloter les commandes.
        """
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in {"127.0.0.1", "localhost", "[::1]", "::1"}

    def log_message(self, fmt: str, *args: Any) -> None:
        # Journal concis : la console du serveur doit rester lisible.
        sys.stderr.write(f"[ui] {self.address_string()} {fmt % args}\n")

    # ---------------- routes ----------------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in STATIC_WHITELIST:
            name, ctype = STATIC_WHITELIST[path]
            target = STATIC_DIR / name
            if not target.exists():
                self._send(500, b"static file missing", "text/plain; charset=utf-8")
                return
            self._send(200, target.read_bytes(), ctype)
            return
        if not self._local_only():
            self._json({"error": "host non local refusé"}, 403)
            return
        if path == "/api/state":
            self._json(self.state())
            return
        if path == "/api/last-run":
            self._json(last_run_payload())
            return
        if path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            if job is None:
                self._json({"error": "travail inconnu"}, 404)
                return
            self._json(job.public())
            return
        self._json({"error": "route inconnue"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._local_only():
            self._json({"error": "host non local refusé"}, 403)
            return
        path = self.path.split("?", 1)[0]
        parts = [p for p in path.split("/") if p]
        # /api/tunnel/<action>
        if parts[:2] == ["api", "tunnel"] and len(parts) == 3:
            action = parts[2]
            if action not in {"status", "start", "stop", "restart"}:
                self._json({"error": f"action inconnue : {action}"}, 400)
                return
            job = spawn_command_job(f"tunnel:{action}", f"tunnel {action}",
                                    tunnel_argv(action))
            self._json({"job_id": job.id}, 202)
            return
        # /api/gate/<name>
        if parts[:2] == ["api", "gate"] and len(parts) == 3:
            argv = gate_argv(parts[2])
            if argv is None:
                self._json({"error": f"porte inconnue : {parts[2]}"}, 400)
                return
            job = spawn_command_job(f"gate:{parts[2]}", f"porte {parts[2]}", argv)
            self._json({"job_id": job.id}, 202)
            return
        # /api/run
        if parts == ["api", "run"]:
            payload = self._body()
            job = _new_job("run", "run live")
            threading.Thread(
                target=run_pipeline_job, args=(job, payload),
                name=f"job-{job.id}", daemon=True,
            ).start()
            self._json({"job_id": job.id}, 202)
            return
        # /api/verify — re-vérifie un scellé déjà produit
        if parts == ["api", "verify"]:
            payload = self._body()
            run_id = str(payload.get("run_id") or "")
            report_path = RUNS_DIR / run_id / "report.json"
            if not report_path.exists():
                self._json({"error": f"scellé introuvable : {report_path}"}, 404)
                return
            pubkey = str(payload.get("public_key_b64") or "")
            extra = ["--pubkey", pubkey] if pubkey else []
            job = spawn_command_job(
                "verify", f"vérifier {run_id}",
                [python_exe(), "verify_report.py", str(report_path), *extra],
            )
            self._json({"job_id": job.id}, 202)
            return
        self._json({"error": "route inconnue"}, 404)

    # ---------------- état ----------------
    @staticmethod
    def state() -> dict[str, Any]:
        return {
            "repo": str(ROOT),
            "python": python_exe(),
            "endpoint_default": DEFAULT_ENDPOINT,
            "tunnel": tunnel_state(),
            "corpus": corpus_summary(),
            "databases": db_summary(),
            "runs_dir": str(RUNS_DIR.relative_to(ROOT)),
            "served_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Interface locale iot-audit (navigateur).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="ouvrir le navigateur au démarrage")
    args = ap.parse_args(argv)

    # Un port occupé doit se dire en une phrase, pas en traceback de socketserver :
    # c'est le premier échec que rencontre un opérateur qui a déjà une instance
    # ouverte (mesuré le 2026-10-06 : un autre service écoutait déjà sur 8765).
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(
            f"!! impossible d'écouter sur 127.0.0.1:{args.port} ({exc}).\n"
            f"   Un autre service (ou une autre instance de cette interface) occupe "
            f"le port.\n   Relancer avec un autre port, par exemple :\n"
            f"     python -m iot_audit.ui.server --port {args.port + 1}",
            file=sys.stderr,
        )
        return 2
    url = f"http://127.0.0.1:{args.port}/"
    # ``flush=True`` : la sortie standard est bufferisée dès qu'elle n'est pas un
    # terminal (redirection, systemd, terminal détaché). Sans cela, l'adresse à
    # ouvrir n'apparaît nulle part alors que le serveur tourne — exactement la
    # classe de panne silencieuse que ce dépôt corrige ailleurs.
    print(f"iot-audit UI : {url}", flush=True)
    print(f"  dépôt     : {ROOT}", flush=True)
    print(f"  tunnel    : {'répond' if tunnel_state()['reachable'] else 'NE RÉPOND PAS'}",
          flush=True)
    print("  Ctrl+C pour arrêter.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt.", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
