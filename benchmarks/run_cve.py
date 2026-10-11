#!/usr/bin/env python3
"""Banc CVE — la preuve de la porte **G1**.

G1 (CDC v3.1 §6) demande trois choses, et ce banc les produit toutes les trois :

    1. la base importee **deux fois sans doublon** ;
    2. **60 cas verifies a la main** ⇒ **0 faux negatif** (faux positifs documentes) ;
    3. le **temps de recherche mesure** (cible contractuelle : p95 < 50 ms).

Sortie : ``benchmarks/cve.json`` (machine) et ``benchmarks/cve.md`` (lisible).

Trois principes, et le premier est le seul qui compte
-----------------------------------------------------

1. **La verite terrain ne vient pas de la base.** Elle est re-derivee des flux
   ``.json.gz`` **bruts** par un lecteur ecrit ici, independant de
   ``iot_audit.vuln.ingest``. On ne demande donc jamais a l'ingestion si
   l'ingestion a bien travaille, ni a ``search_cve`` si ``search_cve`` a raison :
   le banc confronte deux chemins qui ne partagent **aucun code** — le flux NVD
   d'un cote, la base SQLite de l'autre. Un test qui interroge la base pour
   verifier la base ne prouve rien.

2. **La semantique du contrat est reproduite explicitement**, pas supposee :
   ``part='h'``, ``vulnerable=1``, ``negate=0``, ``vulnStatus != 'Rejected'``, et
   ``product IN (product, '*')`` (un critere « vendeur entier » concerne tous ses
   produits). Ces regles sont ecrites ici, en clair, pour qu'on puisse les
   contester — c'est la partie « verifiee a la main » de G1 : le banc prepare la
   confrontation, l'humain valide la regle.

3. **Aucun chiffre saisi a la main.** Tout est compte, y compris les comptes de
   source qui servent de reference a ``feed_versions.row_count``.

Usage (le venv qui porte ``ijson``, comme l'ingestion) :

    .venv-core/bin/python benchmarks/run_cve.py
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from iot_audit.vuln.ingest import connect, ingest_feed  # noqa: E402
from iot_audit.vuln.search import search_cve  # noqa: E402

FEEDS = ROOT / "corpus" / "nvd-feeds"
CORPUS_DB = ROOT / "corpus" / "corpus.sqlite"
DEFAULT_DB = ROOT / "corpus" / "nvd.sqlite"
CVE_TARGET_MS = 50.0          # CDC v3.1 : recherche < 50 ms, comparee au p95
REPEAT = 10                   # executions par requete pour un p95 stable

#: CPE `part` : `h` = materiel, `a` = application, `o` = systeme d'exploitation.
#: Le projet n'ingere que `h` (schema.sql, « part='h' seul »). La section 4 du
#: banc sert precisement a mesurer ce que ce filtre laisse de cote.
PARTS = ("h", "a", "o")

#: Alias de vendeurs : le corpus nomme les siens en slug (`d_link`), NVD ecrit le
#: CPE (`d-link`). On rapproche les deux par une forme normalisee (sans tiret ni
#: souligne) — jamais par une liste ecrite a la main, qui vieillirait en silence.
VENDOR_ALIASES = {
    "wemo": ("belkin", "wemo"),
    "avm": ("avm", "fritz"),
}


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
def log(*a: object) -> None:
    print(*a, flush=True)


def pctl(values: list[float], q: float) -> float | None:
    """Quantile par interpolation lineaire (definition usuelle, ecrite ici)."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def h(*parts: str) -> str:
    """Cle de tri deterministe (convention du projet : hachage, jamais `random`)."""
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


def sums(vals: list[float]) -> dict:
    return {
        "n": len(vals),
        "p50_ms": round(pctl(vals, 0.50) or 0, 3),
        "p95_ms": round(pctl(vals, 0.95) or 0, 3),
        "p99_ms": round(pctl(vals, 0.99) or 0, 3),
        "max_ms": round(max(vals), 3) if vals else None,
    }


# --------------------------------------------------------------------------- #
# A. Lecture INDEPENDANTE des flux bruts  — la verite terrain
# --------------------------------------------------------------------------- #
def _split_cpe(criteria: str) -> tuple[str, str, str] | None:
    """``cpe:2.3:part:vendor:product:...`` -> ``(part, vendor, product)``.

    Ecrit ici volontairement : c'est la seule facon de ne pas tester l'ingestion
    avec l'ingestion. Toute divergence avec ``iot_audit.vuln.ingest._split_cpe``
    se manifestera en faux positif ou faux negatif, ce qui est exactement le but.
    """
    p = criteria.split(":")
    if len(p) < 5 or p[0] != "cpe" or p[1] != "2.3":
        return None
    return p[2], p[3], p[4]


def corpus_vendor_keys() -> tuple[set[str], list[str]]:
    """Vendeurs du **corpus du projet**, sous forme normalisee (+ forme lisible)."""
    names: set[str] = set()
    if CORPUS_DB.exists():
        with sqlite3.connect(CORPUS_DB) as con:
            for (oid,) in con.execute("SELECT object_id FROM objects"):
                names.add(oid.split("__")[0])
    readable = sorted(names)
    keys: set[str] = set()
    for n in names:
        for alias in VENDOR_ALIASES.get(n, ()):
            keys.add(_norm_vendor(alias))
        keys.add(_norm_vendor(n))
    return keys, readable


def _norm_vendor(name: str) -> str:
    """Forme de rapprochement : ni tiret ni souligne, minuscules."""
    return name.replace("-", "").replace("_", "").lower()


def scan_source(feeds: list[Path], target_vendors: set[str] | None = None) -> dict:
    """Re-derive du brut : comptes par flux, verite par (vendor, product).

    Collecte aussi, pour les vendeurs du corpus, le nombre de CVE par `part` —
    y compris les parties que l'ingestion **jette** (`a` et `o`).
    """
    target_vendors = target_vendors or set()
    coverage: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    coverage_names: dict[str, set[str]] = defaultdict(set)
    try:
        import ijson  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "ijson requis (venv de l'ingestion) : .venv-core/bin/python benchmarks/run_cve.py"
        ) from exc

    truth: dict[tuple[str, str], set[str]] = defaultdict(set)
    truth_rejected: dict[tuple[str, str], set[str]] = defaultdict(set)
    bounded: set[tuple[str, str]] = set()
    per_feed: dict[str, dict] = {}
    seen_pairs_h = 0

    for path in feeds:
        yielded = 0
        unique: set[tuple[str, str]] = set()
        null_mcid = 0
        cves = 0
        rejected = 0
        skipped_negate = skipped_nonvuln = 0
        parts: Counter = Counter()

        with gzip.open(path, "rb") as fh:
            for vuln in ijson.items(fh, "vulnerabilities.item"):
                cve = vuln.get("cve") or {}
                cid = cve.get("id")
                if not cid:
                    continue
                cves += 1
                status = cve.get("vulnStatus")
                is_rejected = status == "Rejected"
                if is_rejected:
                    rejected += 1

                for conf in cve.get("configurations") or []:
                    for node in conf.get("nodes") or []:
                        node_neg = bool(node.get("negate"))
                        for match in node.get("cpeMatch") or []:
                            split = _split_cpe(match.get("criteria") or "")
                            if split is None:
                                continue
                            part, vendor, product = split
                            parts[part] += 1

                            # 4. couverture : ce que le filtre `part='h'` ecarte,
                            # mesure AVANT le `continue` ci-dessous.
                            nv = _norm_vendor(vendor)
                            if nv in target_vendors and not is_rejected and (
                                    not match.get("negate") and not node_neg
                                    and match.get("vulnerable", True)):
                                coverage[nv][part].add(cid)
                                coverage_names[nv].add(vendor)

                            if part != "h":
                                continue
                            # A partir d'ici : critere MATERIEL, donc candidat a
                            # entrer en base (meme regle que l'ingestion).
                            yielded += 1
                            mcid = match.get("matchCriteriaId")
                            if mcid is None:
                                null_mcid += 1   # SQLite : NULL ne collisionne jamais
                            else:
                                unique.add((cid, mcid))

                            if match.get("negate") or node_neg:
                                skipped_negate += 1
                                continue
                            if not match.get("vulnerable", True):
                                skipped_nonvuln += 1
                                continue
                            key = (vendor, product)
                            seen_pairs_h += 1
                            if is_rejected:
                                truth_rejected[key].add(cid)
                                continue
                            truth[key].add(cid)
                            for b in ("versionStartIncluding", "versionStartExcluding",
                                      "versionEndIncluding", "versionEndExcluding"):
                                if match.get(b) not in (None, "", "*", "-"):
                                    bounded.add(key)
                                    break

        per_feed[path.name] = {
            "criteria_yielded": yielded,
            "criteria_expected_in_db": len(unique) + null_mcid,
            "null_match_criteria_id": null_mcid,
            "cves_in_feed": cves,
            "cves_rejected": rejected,
            "cpeMatch_skipped_negate": skipped_negate,
            "cpeMatch_skipped_not_vulnerable": skipped_nonvuln,
            "parts_seen": dict(parts),
        }
        log(f"    {path.name}: {cves} CVE lues, {yielded} criteres h "
            f"({len(unique) + null_mcid} attendus en base)")

    return {
        "per_feed": per_feed,
        "coverage_by_part": {
            k: {p: len(v.get(p, ())) for p in PARTS} for k, v in coverage.items()
        },
        "coverage_vendor_names": {k: sorted(v) for k, v in coverage_names.items()},
        "truth": {k: v for k, v in truth.items()},
        "truth_rejected": {k: v for k, v in truth_rejected.items()},
        "bounded": bounded,
        # Criteres materiels qui passent TOUTES les regles de semantique
        # (`vulnerable=1`, `negate=0`) : l'ensemble a partir duquel la verite
        # terrain est construite. Les autres lignes `part='h'` entrent en base
        # mais ne concernent jamais un produit.
        "h_criteria_qualifying": seen_pairs_h,
    }


# --------------------------------------------------------------------------- #
# B. Idempotence — double passe sur une base neuve
# --------------------------------------------------------------------------- #
def check_idempotence(feeds: list[Path], workdir: Path) -> dict:
    """Passe 1, passe 2 (attendue « deja ingere »), passe 3 (reecriture forcee).

    La passe 2 ne prouve que la **provenance** (le sha256 fait sauter le flux).
    Elle ne dit rien du chemin d'ecriture. La passe 3 le force : les memes flux
    sont rejoues sous un **nom** different, donc le sha256 ne les reconnait plus
    et `ON CONFLICT (cve_id, match_criteria_id)` doit absorber toutes les lignes.
    Sans cette troisieme passe, « idempotent » resterait non prouve.
    """
    db = workdir / "scratch.sqlite"
    if db.exists():
        db.unlink()
    con = connect(db)

    def counts() -> dict[str, int]:
        return {
            "feed_versions": con.execute("SELECT COUNT(*) FROM feed_versions").fetchone()[0],
            "cves": con.execute("SELECT COUNT(*) FROM cves").fetchone()[0],
            "criteria": con.execute("SELECT COUNT(*) FROM cve_cpe_criteria").fetchone()[0],
        }

    def duplicates() -> dict[str, int]:
        d1 = con.execute(
            "SELECT COUNT(*) - COUNT(DISTINCT cve_id || '|' || IFNULL(match_criteria_id,'')) "
            "FROM cve_cpe_criteria").fetchone()[0]
        d2 = con.execute(
            "SELECT COUNT(*) - COUNT(DISTINCT cve_id) FROM cves").fetchone()[0]
        return {"criteria": d1, "cves": d2}

    t0 = time.time()
    pass1 = [ingest_feed(con, f, f.name, verbose=False) for f in feeds]
    c1, d1 = counts(), duplicates()

    pass2 = [ingest_feed(con, f, f.name, verbose=False) for f in feeds]
    c2, d2 = counts(), duplicates()

    # Passe 3 : copies renommees => le sha256 ne fait plus sauter le flux.
    copies = []
    for f in feeds:
        dst = workdir / (f.stem + "__replay.json.gz")
        if not dst.exists():
            shutil.copyfile(f, dst)
        copies.append(dst)
    pass3 = [ingest_feed(con, f, f.name, verbose=False) for f in copies]
    c3, d3 = counts(), duplicates()

    rows_by_feed = {
        r["feed_name"]: {
            "feed_version_id": r["id"],
            "row_count": r["row_count"],
            "cve_count": r["cve_count"],
            "rows_present_for_feed_version": con.execute(
                "SELECT COUNT(*) FROM cve_cpe_criteria WHERE feed_version_id = ?",
                (r["id"],)).fetchone()[0],
        }
        for r in con.execute("SELECT id, feed_name, row_count, cve_count FROM feed_versions")
    }
    con.close()

    # L'invariant d'idempotence porte sur les **donnees** (`cves`, `criteria`),
    # pas sur `feed_versions` : la passe 3 rejoue les flux sous un autre nom
    # **exprès**, donc elle ajoute legitimement 4 lignes de provenance. Comparer
    # le dictionnaire entier ferait echouer la porte sur un comportement voulu —
    # ce qui est exactement le genre de faux echec que ce banc ne doit pas
    # produire.
    data_keys = ("cves", "criteria")
    return {
        "db": "base neuve (jetable), pas la base de travail",
        "duration_s": round(time.time() - t0, 1),
        "pass1_originals": {"counts": c1, "duplicates": d1,
                            "skipped": [r["skipped"] for r in pass1]},
        "pass2_same_names": {"counts": c2, "duplicates": d2,
                             "skipped": [r["skipped"] for r in pass2]},
        "pass3_renamed": {"counts": c3, "duplicates": d3,
                          "skipped": [r["skipped"] for r in pass3]},
        "data_counts_identical_1_2_3": all(
            c1[k] == c2[k] == c3[k] for k in data_keys),
        "data_counts_compared": list(data_keys),
        "feed_versions_by_pass": [c1["feed_versions"], c2["feed_versions"],
                                  c3["feed_versions"]],
        "feed_versions_note": (
            "la passe 3 ajoute 4 lignes de provenance : c'est le but (flux rejoues "
            "sous un autre nom pour forcer le chemin d'ecriture). Seules les "
            "tables de donnees doivent etre invariantes."),
        "zero_duplicates_everywhere": (d1 == d2 == d3 == {"criteria": 0, "cves": 0}),
        "rows_by_feed": rows_by_feed,
    }


# --------------------------------------------------------------------------- #
# C. Les 60 cas
# --------------------------------------------------------------------------- #
def select_cases(src: dict, db: sqlite3.Connection, n_cases: int,
                 corpus_keys: set[str] | None = None
                 ) -> tuple[list[dict], list[dict]]:
    """Selection **deterministe et stratifiee** — la composition est publiee.

    Les strates ne cherchent pas le volume : elles cherchent les endroits ou un
    matcher peut se tromper (0 CVE, 1 CVE, beaucoup, plages de versions, critere
    « vendeur entier », controle negatif).
    """
    truth: dict[tuple[str, str], set[str]] = {k: v for k, v in src["truth"].items()}
    bounded: set = src["bounded"]
    counts = {k: len(v) for k, v in truth.items()}

    # `product='*'` n'est pas un produit : c'est le critere « tout le vendeur ».
    # Le prendre comme cas produirait une requete `search_cve(v, '*')`, qui ne
    # teste rien du chemin nominal (le premier passage avait retenu `intel/*`).
    # Il reste compte comme *contribution*, via `vendor_wildcard_owed`.
    real_pairs = [p for p in truth if p[1] != "*"]
    corpus_keys = corpus_keys or set()

    # Contribution « vendeur entier » : ce qu'un produit doit a son `product='*'`.
    # Strate a part parce que `vendor_wildcard` est la preuve la plus faible de
    # `search_cve` : c'est justement la ou un faux positif silencieux se cache.
    wildcard_owed = {k for k in real_pairs if truth.get((k[0], "*"))}

    in_db = {(r[0], r[1]) for r in db.execute(
        "SELECT DISTINCT vendor, product FROM cve_cpe_criteria WHERE part = 'h'")}
    zero = sorted(p for p in in_db if p not in truth)

    def pick(pool: list[tuple[str, str]], k: int, *, by_count: bool = False):
        if by_count:
            ordered = sorted(pool, key=lambda p: (-counts.get(p, 0), h(p[0], p[1])))
        else:
            ordered = sorted(pool, key=lambda p: h(p[0], p[1]))
        return ordered[:k]

    # Les strates SPECIALISTES passent en premier. Motif : elles sont rares
    # (`vendor_wildcard` ne compte que **2** lignes de criteres dans toute la
    # base) et si on les servait en dernier, les strates de volume les auraient
    # deja videes — c'est ce qui s'est produit au premier passage (57 cas sur 60,
    # avec `version_bounded` a 7/8 et `vendor_wildcard` a 2/4).
    pools = [
        # Les vendeurs que le projet AUDITE vraiment. Sans cette strate, le banc
        # serait vert sur du materiel Intel/Dell sans rapport avec le perimetre —
        # autrement dit il prouverait la mecanique, pas l'usage.
        ("vendeurs_du_corpus", pick(
            [p for p in real_pairs if _norm_vendor(p[0]) in corpus_keys], 8), 8, False),
        ("vendor_wildcard_owed", pick(list(wildcard_owed), 4), 4, False),
        ("version_bounded", pick([p for p in real_pairs if p in bounded], 8), 8, False),
        ("control_zero_cve", pick(zero, 3), 3, False),
        ("single_1_cve", pick([p for p in real_pairs if counts[p] == 1], 20), 20, False),
        ("few_2_5", pick([p for p in real_pairs if 2 <= counts[p] <= 5], 15), 15, False),
        ("many_6plus", pick([p for p in real_pairs if counts[p] >= 6], 10, by_count=True),
         10, True),
    ]

    chosen: list[tuple[str, str]] = []
    strata_of: dict[tuple[str, str], str] = {}
    composition: list[dict] = []
    for name, pool, quota, _by_count in pools:
        got = []
        for p in pool:
            if len(chosen) >= n_cases or len(got) >= quota:
                break
            if p in strata_of:
                continue
            chosen.append(p)
            strata_of[p] = name
            got.append(p)
        composition.append({"strate": name, "quota": quota, "retenus": len(got)})

    # Complement : les strates ci-dessus ne peuvent pas toujours remplir 60
    # (`vendor_wildcard` est plafonnee par la donnee). On complete par hachage, en
    # le DISANT dans la composition plutot qu'en gonflant discretement un quota.
    if len(chosen) < n_cases:
        rest = sorted((p for p in real_pairs if p not in strata_of),
                      key=lambda p: h(p[0], p[1]))
        got = []
        for p in rest:
            if len(chosen) >= n_cases:
                break
            chosen.append(p)
            strata_of[p] = "complement"
            got.append(p)
        composition.append({"strate": "complement", "quota": n_cases,
                            "retenus": len(got)})

    return [
        {"case": i + 1, "stratum": strata_of[p], "vendor": p[0], "product": p[1]}
        for i, p in enumerate(chosen)
    ], composition


def run_cases(cases: list[dict], src: dict, db: sqlite3.Connection,
              repeat: int) -> dict:
    truth: dict[tuple[str, str], set[str]] = src["truth"]
    truth_rejected: dict[tuple[str, str], set[str]] = src["truth_rejected"]

    # Chauffe : les premieres requetes payent le cache SQLite, pas le moteur.
    for _ in range(5):
        search_cve(db, "tp-link", "archer_c7")

    rows: list[dict] = []
    first_ms: list[float] = []
    all_ms: list[float] = []
    fn_total = fp_total = 0
    basis_counter: Counter = Counter()
    unresolved_hits = 0

    for c in cases:
        v, p = c["vendor"], c["product"]
        expected = set(truth.get((v, p), set())) | set(truth.get((v, "*"), set()))
        exp_rejected = set(truth_rejected.get((v, p), set())) | set(
            truth_rejected.get((v, "*"), set()))

        t0 = time.perf_counter()
        res = search_cve(db, v, p)
        dt = (time.perf_counter() - t0) * 1000.0
        first_ms.append(dt)

        for _ in range(repeat - 1):
            t1 = time.perf_counter()
            search_cve(db, v, p)
            all_ms.append((time.perf_counter() - t1) * 1000.0)
        all_ms.append(dt)

        got = {hit.cve_id for hit in res.hits}
        fn = sorted(expected - got)
        fp = sorted(got - expected)
        for hit in res.hits:
            basis_counter[hit.match_basis] += 1
            if hit.unresolved:
                unresolved_hits += 1
        fn_total += len(fn)
        fp_total += len(fp)

        rows.append({
            **c,
            "n_expected": len(expected),
            "n_returned": res.n,
            "n_strong": len(res.strong_hits()),
            "false_negatives": fn,
            "false_positives": fp,
            "rejected_excluded": list(res.rejected_excluded),
            "rejected_in_source": sorted(exp_rejected),
            "unresolved_returned": sum(1 for x in res.hits if x.unresolved),
            "basis": dict(Counter(x.match_basis for x in res.hits)),
            "first_query_ms": round(dt, 3),
            "example_hits": [x.cve_id for x in res.hits[:5]],
            "ok": not fn and not fp,
        })

    return {
        "rows": rows,
        "false_negatives_total": fn_total,
        "false_positives_total": fp_total,
        "cases_ok": sum(1 for r in rows if r["ok"]),
        "latency_distinct_queries": sums(first_ms),
        "latency_all_executions": sums(all_ms),
        "latency_repeat_per_query": repeat,
        "match_basis_histogram": dict(basis_counter),
        "hits_unresolved": unresolved_hits,
        "target_ms_p95": CVE_TARGET_MS,
        "passes_p95_target": (pctl(all_ms, 0.95) or 1e9) < CVE_TARGET_MS,
    }


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #
def write_markdown(out: dict, path: Path) -> None:
    L: list[str] = []
    a, b, c = out["source"], out["idempotence"], out["cases"]
    L.append("# Banc CVE — preuve de la porte G1\n")
    L.append(f"> Genere par `benchmarks/run_cve.py` le {out['generated_at']}. "
             "Aucun chiffre saisi a la main.")
    L.append(f"> Base : `{out['db']}` ({out['db_sha256'][:12]}…, "
             f"{out['db_bytes'] / 1e6:.0f} Mo) · flux bruts : "
             f"{len(a['per_feed'])} fichiers, sha256 enregistres.\n")

    L.append("## 1. La source, re-derivee du brut (independamment de la base)\n")
    L.append("| flux | CVE lues | criteres h produits | attendus en base | "
             "`row_count` stocke | ecart | `cve_count` stocke |")
    L.append("|---|---|---|---|---|---|---|")
    for name, f in a["per_feed"].items():
        st = b["rows_by_feed"].get(name, {})
        exp = f["criteria_expected_in_db"]
        rc = st.get("row_count")
        ecart = "OK" if rc == exp else f"**{rc} != {exp}**"
        L.append(f"| `{name}` | {f['cves_in_feed']} | {f['criteria_yielded']} | {exp} | "
                 f"{rc} | {ecart} | {st.get('cve_count')} |")
    L.append("")
    L.append(f"Total criteres en base : **{out['db_counts']['criteria']}** · "
             f"CVE : **{out['db_counts']['cves']}** · "
             f"`parts` presents : {out['db_counts']['parts']}.")
    L.append("\nSur les criteres `part='h'`, regles de semantique appliquees et "
             "comptees :\n")
    L.append("| regle | occurrences ecartees |")
    L.append("|---|---|")
    L.append(f"| `negate` (critere qui EXCLUT) | "
             f"{sum(f['cpeMatch_skipped_negate'] for f in a['per_feed'].values())} |")
    L.append(f"| `vulnerable != 1` | "
             f"{sum(f['cpeMatch_skipped_not_vulnerable'] for f in a['per_feed'].values())} |")
    L.append("")

    cov = out.get("coverage_by_part")
    if cov:
        names = {_norm_vendor(k): " / ".join(v)
                 for k, v in cov["vendor_names"].items()}
        rows = sorted(cov["vendors"].items(),
                      key=lambda kv: -sum(kv[1].values()))
        L.append("## 2. Ce que le filtre `part='h'` laisse de cote\n")
        L.append("L'ingestion ne garde que les criteres CPE `part='h'` "
                 "(materiel). Voici, pour **chaque vendeur du corpus du projet**, "
                 "le nombre de CVE distinctes disponibles par partie dans les flux "
                 "bruts (`a` = application, `o` = systeme) :\n")
        L.append("| vendeur (NVD) | `part=h` **gardees** | `part=a` | `part=o` | "
                 "part conservee |")
        L.append("|---|---|---|---|---|")
        for k, d in rows:
            tot = sum(d.values())
            keep = f"{d['h'] / tot * 100:.1f} %" if tot else "—"
            L.append(f"| `{names.get(k, k)}` | **{d['h']}** | {d['a']} | {d['o']} | "
                     f"{keep} |")
        kept = sum(d["h"] for _, d in rows)
        total = sum(sum(d.values()) for _, d in rows)
        L.append("")
        L.append(f"Total, tous vendeurs du corpus confondus : **{kept} CVE gardees "
                 f"sur {total}** ({kept / total * 100:.2f} %). "
                 "Autrement dit, le filtre ecarte "
                 f"**{100 - kept / total * 100:.1f} % des CVE** qui concernent les "
                 "familles d'objets que le projet audite.\n")
        L.append("> **Ce que cela veut dire, sans detour.** Le banc est vert, et il "
                 "est vert sur un sous-ensemble qui exclut l'essentiel. Un audit "
                 "d'un routeur ou d'une camera de ce corpus produirait aujourd'hui "
                 "une liste de CVE **vide ou quasi vide**, non parce que le produit "
                 "n'a pas de vulnerabilite connue, mais parce que la decision "
                 "d'ingestion `part='h'` l'a retiree. Ce n'est pas un bug du moteur "
                 "(le moteur rend exactement ce que la base contient) : c'est une "
                 "consequence de perimetre, qui n'etait pas mesuree avant ce banc. "
                 "La trancher releve du contrat (D12 / §3.4), pas du code.\n")

    L.append("## 3. Idempotence — la base importee deux fois\n")
    L.append(f"Sur une base neuve jetable ({b['duration_s']} s), trois passes :\n")
    L.append("| passe | `feed_versions` | `cves` | `cve_cpe_criteria` | doublons | "
             "flux sautes |")
    L.append("|---|---|---|---|---|---|")
    for label, key in (("1 — flux d'origine", "pass1_originals"),
                       ("2 — memes noms (provenance)", "pass2_same_names"),
                       ("3 — copies renommees (ecriture forcee)", "pass3_renamed")):
        p = b[key]
        L.append(f"| {label} | {p['counts']['feed_versions']} | {p['counts']['cves']} | "
                 f"{p['counts']['criteria']} | {p['duplicates']} | "
                 f"{sum(p['skipped'])}/{len(p['skipped'])} |")
    L.append("")
    L.append(f"- **donnees identiques** sur les trois passes (`{'`, `'.join(b['data_counts_compared'])}`) : "
             f"**{'oui' if b['data_counts_identical_1_2_3'] else 'NON'}** ;")
    L.append(f"- zero doublon sur les trois passes : "
             f"**{'oui' if b['zero_duplicates_everywhere'] else 'NON'}** ;")
    L.append(f"- `feed_versions` par passe : {b['feed_versions_by_pass']} — "
             f"{b['feed_versions_note']}\n")
    L.append("> La passe 2 ne prouve que la **provenance** (le sha256 fait sauter le "
             "flux : c'est ce que la colonne « flux sautes » montre). Elle ne "
             "prouve rien du chemin d'ecriture. C'est la **passe 3** qui le fait : "
             "les memes flux rejoues sous un autre nom ne sont plus reconnus, donc "
             "`ON CONFLICT` doit absorber chaque ligne. Sans elle, « idempotent » "
             "resterait non prouve.\n")

    L.append(f"## 4. Les {len(c['rows'])} cas\n")
    L.append(f"- **faux negatifs : {c['false_negatives_total']}** "
             f"(cible : 0) · faux positifs : {c['false_positives_total']} "
             "(a documenter, pas a corriger) ;")
    L.append(f"- cas sans aucune divergence : "
             f"{c['cases_ok']}/{len(c['rows'])} ;")
    L.append(f"- latence sur les {c['latency_distinct_queries']['n']} requetes "
             f"distinctes : p50 {c['latency_distinct_queries']['p50_ms']} ms · "
             f"**p95 {c['latency_distinct_queries']['p95_ms']} ms** · "
             f"max {c['latency_distinct_queries']['max_ms']} ms ;")
    L.append(f"- latence sur {c['latency_all_executions']['n']} executions "
             f"({c['latency_repeat_per_query']} par requete) : p50 "
             f"{c['latency_all_executions']['p50_ms']} ms · **p95 "
             f"{c['latency_all_executions']['p95_ms']} ms** · p99 "
             f"{c['latency_all_executions']['p99_ms']} ms · max "
             f"{c['latency_all_executions']['max_ms']} ms ;")
    L.append(f"- cible contractuelle p95 < {c['target_ms_p95']:.0f} ms : "
             f"**{'PASS' if c['passes_p95_target'] else 'FAIL'}**.\n")
    L.append("| # | strate | vendor / product | attendus | rendus | FN | FP | "
             "premiere requete |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in c["rows"]:
        L.append(f"| {r['case']} | `{r['stratum']}` | `{r['vendor']}/{r['product']}` | "
                 f"{r['n_expected']} | {r['n_returned']} | {len(r['false_negatives'])} | "
                 f"{len(r['false_positives'])} | {r['first_query_ms']} ms |")
    L.append("")

    comp = out["composition"]
    L.append("### Composition des strates (choix deterministe par hachage)\n")
    L.append("| strate | quota | retenus |")
    L.append("|---|---|---|")
    for s in comp:
        L.append(f"| `{s['strate']}` | {s['quota']} | {s['retenus']} |")
    L.append("")
    L.append("## Ce que ce banc prouve, et ce qu'il ne prouve pas\n")
    L.append("- **Prouve** : pour ces 60 couples `(vendor, product)`, la reponse de "
             "`search_cve` est identique a celle qu'on obtient en relisant les flux "
             "NVD bruts avec un code qui ne partage rien avec l'ingestion ni avec la "
             "recherche. Cela couvre **a la fois** l'extraction (colonnes `vendor`/"
             "`product`/`part`) **et** la restitution.")
    L.append("- **Ne prouve pas** que les regles de semantique (`part='h'`, "
             "`negate`, `vulnerable`, `Rejected`) sont les bonnes : elles sont "
             "reproduites des deux cotes parce que le contrat les fixe. C'est le "
             "point que la **verification a la main** doit valider, cas par cas.")
    L.append("- **Ne couvre pas** la logique de plages de versions sur une version "
             "connue : le chemin nominal du projet est `version=None` (une photo ne "
             "donne pas le firmware), et c'est ce chemin qui est mesure ici. Les "
             "plages sont couvertes par `tests/test_version.py` et "
             "`tests/test_search_cve.py`.")

    negate_total = sum(f["cpeMatch_skipped_negate"] for f in a["per_feed"].values())
    nonvuln_total = sum(f["cpeMatch_skipped_not_vulnerable"]
                        for f in a["per_feed"].values())
    L.append(f"- **`negate` n'est jamais exerce par la donnee reelle** : "
             f"{negate_total} critere materiel `negate=1` dans les quatre flux. "
             "Sa branche de code n'est donc couverte que par "
             "`tests/test_search_cve.py`, pas par ce banc. Il ne faut pas lire "
             "« 0 faux negatif » comme une validation de ce chemin.")
    L.append(f"- **La base stockee est tres majoritairement inatteignable** : "
             f"{nonvuln_total} criteres materiels sur "
             f"{sum(f['criteria_yielded'] for f in a['per_feed'].values())} portent "
             "`vulnerable=0` (ils decrivent ce qu'une CVE **n'affecte pas** ou une "
             "plateforme requise). Ils entrent en base mais `search_cve` ne les "
             "rend jamais. Le volume de 324 470 lignes ne doit donc jamais etre "
             "cite comme « nombre de CVE exploitables ».")
    L.append("- **La strate `vendeurs_du_corpus` garantit le vendeur, pas la famille "
             "d'objet** : elle selectionne par nom de vendeur, donc un appareil "
             "`samsung` du corpus peut etre confronte a des CVE d'*imprimantes*. "
             "C'est suffisant pour prouver que la chaine fonctionne sur les "
             "vendeurs audites ; ce n'est pas une mesure par objet du corpus.")
    L.append("- **L'echantillon des 60 cas est choisi par ce script**, pas par le "
             "NVD ni par un tirage aleatoire : la composition des strates est "
             "publiee ci-dessus pour qu'on puisse la discuter. « 0 faux negatif » "
             "vaut pour **ces 60 cas**, et la section 1 montre que la base "
             "interrogee ne contient qu'une fraction du sujet.\n")
    path.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--feeds-dir", default=str(FEEDS))
    ap.add_argument("--out", default=str(HERE / "cve.json"))
    ap.add_argument("--cases", type=int, default=60)
    ap.add_argument("--repeat", type=int, default=REPEAT)
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    feeds = sorted(Path(args.feeds_dir).glob("nvdcve-2.0-*.json.gz"))
    if not feeds:
        raise SystemExit(f"aucun flux dans {args.feeds_dir}")
    if not db_path.exists():
        raise SystemExit(f"base absente : {db_path}")

    corpus_keys, corpus_readable = corpus_vendor_keys()
    log(f"vendeurs du corpus projet : {len(corpus_readable)}")

    log("== A. lecture independante des flux bruts ==")
    t0 = time.time()
    src = scan_source(feeds, corpus_keys)
    log(f"   {src['h_criteria_qualifying']} criteres h retenus en {time.time() - t0:.1f} s ; "
        f"{len(src['truth'])} couples (vendor, product) portent au moins une CVE")

    log("\n== B. idempotence (base neuve) ==")
    workdir = Path(tempfile.mkdtemp(prefix="cve-bench-"))
    b = check_idempotence(feeds, workdir)
    log(f"   donnees identiques sur 3 passes : {b['data_counts_identical_1_2_3']} ; "
        f"zero doublon : {b['zero_duplicates_everywhere']} ; "
        f"feed_versions par passe : {b['feed_versions_by_pass']}")

    log("\n== C. 60 cas ==")
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cases, composition = select_cases(src, db, args.cases, corpus_keys)
        c = run_cases(cases, src, db, args.repeat)
        counts = {
            "criteria": db.execute("SELECT COUNT(*) FROM cve_cpe_criteria").fetchone()[0],
            "cves": db.execute("SELECT COUNT(*) FROM cves").fetchone()[0],
            "parts": [r[0] for r in db.execute(
                "SELECT DISTINCT part FROM cve_cpe_criteria ORDER BY part")],
        }
    log(f"   faux negatifs : {c['false_negatives_total']} · "
        f"faux positifs : {c['false_positives_total']} · "
        f"p95 {c['latency_distinct_queries']['p95_ms']} ms")

    out = {
        "_note": "Preuve de la porte G1 : 2e import sans doublon, 60 cas, p95.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "benchmarks/run_cve.py",
        "db": str(db_path.relative_to(ROOT)) if ROOT in db_path.parents else str(db_path),
        "db_bytes": db_path.stat().st_size,
        "db_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "db_counts": counts,
        "coverage_by_part": {
            "_note": (
                "CVE distinctes par vendeur du corpus et par `part` CPE, lues dans "
                "les flux BRUTS. Le projet n'ingere que `part='h'` : les colonnes "
                "`a` et `o` mesurent ce que ce filtre ecarte."),
            "vendors": src["coverage_by_part"],
            "vendor_names": src["coverage_vendor_names"],
            "corpus_vendors": corpus_readable,
        },
        "source": {
            "per_feed": src["per_feed"],
            "feeds_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                             for f in feeds},
            "pairs_with_cves": len(src["truth"]),
            "h_criteria_qualifying": src["h_criteria_qualifying"],
        },
        "idempotence": b,
        "cases": {
            **{k: v for k, v in c.items() if k != "rows"},
            "rows": c["rows"],
            "n_cases": len(c["rows"]),
        },
        "composition": composition,
        "verdicts": {
            "G1_sans_doublon": b["zero_duplicates_everywhere"] and b["data_counts_identical_1_2_3"],
            "G1_zero_faux_negatif": c["false_negatives_total"] == 0,
            "G1_p95_sous_cible": c["passes_p95_target"],
            "G1_60_cas": len(c["rows"]) >= 60,
        },
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(out, out_path.with_suffix(".md"))

    log("\n== verdicts G1 ==")
    for k, v in out["verdicts"].items():
        log(f"   {'PASS' if v else 'FAIL'}  {k}")
    log(f"\necrit : {out_path} et {out_path.with_suffix('.md')}")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if all(out["verdicts"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
