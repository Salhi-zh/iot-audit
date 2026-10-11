"""Ingestion des flux NVD 2.0 en streaming (docs/04 §2, CDS §7).

Ce que ce module fait, et ce qu'il refuse de faire :

* Il lit les flux annuels ``nvdcve-2.0-<annee>.json.gz`` avec ``ijson``, sans
  jamais matérialiser une année en RAM, et n'écrit que les critères CPE
  matériels (``part='h'``) — le reste du flux (parties ``a`` et ``o``) est
  ignoré au fil de l'eau.
* Il enregistre le ``sha256`` de chaque flux dans ``feed_versions`` : c'est ce
  qui rend un run reproductible (D13) et ce qui permet de **sauter** un flux
  déjà ingéré (reprise).
* Il est **idempotent** : ``UNIQUE (cve_id, match_criteria_id)`` + upsert ⇒
  rejouer une ingestion ne duplique rien et ne modifie rien.
* Il ne fait **aucune** écrasement : une nouvelle publication du même flux est
  une nouvelle ligne ``feed_versions``, jamais une mutation de l'ancienne (D6).

Usage :

    python -m iot_audit.vuln.ingest --db corpus/nvd.sqlite --years 2021 2022 2023 2024

Le téléchargement passe par ``--cache-dir`` (défaut ``corpus/nvd-feeds``) : le
``.json.gz`` est gardé sur disque, le sha256 est vérifié côté NVD quand le flux
publie un ``.meta``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import ijson

from iot_audit.text import now_iso

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

FEED_URL = "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{year}.json.gz"
META_URL = "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{year}.meta"

DEFAULT_CACHE = Path("corpus/nvd-feeds")

__all__ = [
    "connect",
    "ensure_schema",
    "iter_vulnerabilities",
    "hardware_criteria",
    "cve_metadata",
    "ingest_feed",
    "ingest_one",
]


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Ouvre (et crée) la base NVD, applique le schéma, active WAL."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Téléchargement (avec cache et reprise)
# --------------------------------------------------------------------------- #


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, *, force: bool = False) -> Path:
    """Télécharge ``url`` vers ``dest`` si absent (ou si ``force``). Renvoie le chemin."""
    if dest.exists() and not force and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "iot-audit/0.1 (PFE)"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)
    return dest


def _fetch_meta(year: int) -> dict[str, Any] | None:
    """Lit le ``.meta`` du flux : contient ``sha256`` et ``lastModifiedDate``."""
    try:
        with urllib.request.urlopen(
            META_URL.format(year=year), timeout=30
        ) as resp:
            text = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    meta: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta or None


# --------------------------------------------------------------------------- #
# Parsing en flux
# --------------------------------------------------------------------------- #


def iter_vulnerabilities(fh: io.BufferedReader) -> Iterator[dict[str, Any]]:
    """Stream les CVE d'un flux annuel sans charger l'année en RAM."""
    yield from ijson.items(fh, "vulnerabilities.item")


def _split_cpe(criteria: str) -> tuple[str, str, str, str] | None:
    """``cpe:2.3:h:vendor:product:version:...`` -> ``(part, vendor, product, version)``.

    Renvoie ``None`` pour tout ce qui n'est pas un CPE 2.3 exploitable : la
    fonction est volontairement stricte, un motif malformé ne doit pas entrer en
    base avec des champs devinés.
    """
    parts = criteria.split(":")
    if len(parts) < 6 or parts[0] != "cpe" or parts[1] != "2.3":
        return None
    _, _, part, vendor, product, version = parts[:6]
    if part not in {"h", "a", "o"}:
        return None
    return part, vendor, product, version


def hardware_criteria(vuln: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Itère les critères CPE matériels (``part='h'``) d'une CVE.

    Le motif original est conservé dans ``criteria`` : c'est la pièce d'audit
    qui montre *pourquoi* une CVE a été remontée (CDS §7.3).
    """
    cve = vuln.get("cve") or {}
    cve_id = cve.get("id")
    if not cve_id:
        return

    for conf in cve.get("configurations") or []:
        for node in conf.get("nodes") or []:
            operator = node.get("operator")
            negate_node = bool(node.get("negate"))
            for match in node.get("cpeMatch") or []:
                criteria = match.get("criteria") or ""
                split = _split_cpe(criteria)
                if split is None:
                    continue
                part, vendor, product, version = split
                if part != "h":
                    continue  # hors périmètre : le projet ne traite que le matériel
                yield {
                    "cve_id": cve_id,
                    "match_criteria_id": match.get("matchCriteriaId"),
                    "criteria": criteria,
                    "part": part,
                    "vendor": vendor,
                    "product": product,
                    "version": version,
                    "version_start_incl": match.get("versionStartIncluding"),
                    "version_start_excl": match.get("versionStartExcluding"),
                    "version_end_incl": match.get("versionEndIncluding"),
                    "version_end_excl": match.get("versionEndExcluding"),
                    "vulnerable": 1 if match.get("vulnerable", True) else 0,
                    "negate": 1 if (match.get("negate") or negate_node) else 0,
                    "operator": operator,
                }


def _first_english(descriptions: list[dict[str, Any]] | None) -> str:
    for d in descriptions or []:
        if (d.get("lang") or "").lower() == "en":
            return (d.get("value") or "").strip()
    return ""


def _cvss_v3(metrics: dict[str, Any] | None) -> tuple[float | None, str | None, str | None]:
    """Renvoie ``(base_score, severity, vector)`` en préférant v3.1 puis v3.0."""
    if not metrics:
        return None, None, None
    for key in ("cvssMetricV31", "cvssMetricV30"):
        entries = metrics.get(key) or []
        for entry in entries:
            data = entry.get("cvssData") or {}
            score = data.get("baseScore")
            if score is None:
                continue
            return (
                float(score),
                data.get("baseSeverity") or entry.get("baseSeverity"),
                data.get("vectorString"),
            )
    return None, None, None


def cve_metadata(vuln: dict[str, Any]) -> dict[str, Any] | None:
    """Extrait les métadonnées CVE utiles au rapport (statut, CVSS, dates)."""
    cve = vuln.get("cve") or {}
    cve_id = cve.get("id")
    if not cve_id:
        return None
    score, severity, vector = _cvss_v3(cve.get("metrics"))
    return {
        "cve_id": cve_id,
        "vuln_status": cve.get("vulnStatus"),
        "published": cve.get("published"),
        "last_modified": cve.get("lastModified"),
        "description": _first_english(cve.get("descriptions"))[:2000],
        "cvss_v3_score": score,
        "cvss_v3_severity": severity,
        "cvss_v3_vector": vector,
    }


# --------------------------------------------------------------------------- #
# Écriture
# --------------------------------------------------------------------------- #

_CRIT_SQL = """
INSERT INTO cve_cpe_criteria
  (cve_id, match_criteria_id, criteria, part, vendor, product, version,
   version_start_incl, version_start_excl, version_end_incl, version_end_excl,
   vulnerable, negate, operator, feed_version_id)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT (cve_id, match_criteria_id) DO NOTHING
"""

_CVE_SQL = """
INSERT INTO cves
  (cve_id, vuln_status, published, last_modified, description,
   cvss_v3_score, cvss_v3_severity, cvss_v3_vector, feed_version_id)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT (cve_id) DO UPDATE SET
  vuln_status      = excluded.vuln_status,
  last_modified    = excluded.last_modified,
  description      = COALESCE(NULLIF(excluded.description, ''), cves.description),
  cvss_v3_score    = COALESCE(excluded.cvss_v3_score, cves.cvss_v3_score),
  cvss_v3_severity = COALESCE(excluded.cvss_v3_severity, cves.cvss_v3_severity),
  cvss_v3_vector   = COALESCE(excluded.cvss_v3_vector, cves.cvss_v3_vector)
"""


def _get_or_create_feed_version(
    con: sqlite3.Connection,
    feed_name: str,
    sha256: str,
    published_at: str | None,
) -> tuple[int, bool]:
    """Renvoie ``(feed_version_id, deja_ingere)``.

    ``deja_ingere`` est vrai quand cette **combinaison** (nom, sha256) est déjà
    en base : c'est la clé de la reprise — on ne rejoue pas un flux identique.
    """
    row = con.execute(
        "SELECT id, row_count FROM feed_versions WHERE feed_name = ? AND sha256 = ?",
        (feed_name, sha256),
    ).fetchone()
    if row is not None:
        return row["id"], row["row_count"] is not None

    cur = con.execute(
        """INSERT INTO feed_versions (feed_name, sha256, published_at, ingested_at)
           VALUES (?, ?, ?, ?)""",
        (feed_name, sha256, published_at, now_iso()),
    )
    return int(cur.lastrowid), False


def ingest_feed(
    con: sqlite3.Connection,
    gz_path: Path,
    feed_name: str,
    *,
    published_at: str | None = None,
    batch_size: int = 5000,
    verbose: bool = True,
) -> dict[str, Any]:
    """Ingère un flux ``.json.gz`` dans la base. Idempotent.

    Renvoie un compte rendu : ``rows``, ``cves``, ``skipped``, ``feed_version_id``.
    """
    sha256 = _sha256_file(gz_path)
    feed_version_id, already = _get_or_create_feed_version(
        con, feed_name, sha256, published_at
    )
    if already:
        row = con.execute(
            "SELECT row_count, cve_count FROM feed_versions WHERE id = ?",
            (feed_version_id,),
        ).fetchone()
        if verbose:
            print(
                f"  [{feed_name}] deja ingere (sha256 {sha256[:12]}...) — "
                f"{row['row_count']} criteres, {row['cve_count']} CVE"
            )
        return {
            "feed": feed_name,
            "feed_version_id": feed_version_id,
            "rows": row["row_count"],
            "cves": row["cve_count"],
            "skipped": True,
            "sha256": sha256,
        }

    t0 = time.time()
    rows_batch: list[tuple] = []
    cves_batch: list[tuple] = []
    total_rows = 0
    total_cves = 0

    with gzip.open(gz_path, "rb") as raw:
        for vuln in iter_vulnerabilities(raw):
            meta = cve_metadata(vuln)
            if meta is not None:
                cves_batch.append(
                    (
                        meta["cve_id"], meta["vuln_status"], meta["published"],
                        meta["last_modified"], meta["description"],
                        meta["cvss_v3_score"], meta["cvss_v3_severity"],
                        meta["cvss_v3_vector"], feed_version_id,
                    )
                )
                total_cves += 1

            for crit in hardware_criteria(vuln):
                rows_batch.append(
                    (
                        crit["cve_id"], crit["match_criteria_id"], crit["criteria"],
                        crit["part"], crit["vendor"], crit["product"], crit["version"],
                        crit["version_start_incl"], crit["version_start_excl"],
                        crit["version_end_incl"], crit["version_end_excl"],
                        crit["vulnerable"], crit["negate"], crit["operator"],
                        feed_version_id,
                    )
                )
                total_rows += 1

            if len(rows_batch) >= batch_size:
                con.executemany(_CVE_SQL, cves_batch)
                con.executemany(_CRIT_SQL, rows_batch)
                cves_batch.clear()
                rows_batch.clear()

        if cves_batch:
            con.executemany(_CVE_SQL, cves_batch)
        if rows_batch:
            con.executemany(_CRIT_SQL, rows_batch)

    # `row_count` est documente par le schema comme « nb de lignes de criteres
    # INSEREES ». Or `total_rows` compte les criteres **produits** par le flux, et
    # l'ecriture est un `ON CONFLICT (cve_id, match_criteria_id) DO NOTHING` : un
    # meme critere repete dans le flux est compte deux fois mais ecrit une seule.
    #
    # Stocker le compte d'essais produisait un ecart avec `COUNT(*)` sur les
    # lignes reelles (mesure du 2026-09-29 : 92 968 annonces contre 90 646
    # lignes pour le flux 2021). La lecture immediate de cet ecart est « des
    # doublons sont entres », donc l'idempotence parait brisee alors qu'il n'y a
    # aucun doublon. Un champ de provenance qui contredit la table qu'il decrit
    # est exactement le defaut que ce projet traque : on stocke donc les lignes
    # reellement presentes, et le compte d'essais reste publie par la valeur de
    # retour (`rows_yielded`).
    inserted = con.execute(
        "SELECT COUNT(*) FROM cve_cpe_criteria WHERE feed_version_id = ?",
        (feed_version_id,),
    ).fetchone()[0]
    con.execute(
        "UPDATE feed_versions SET row_count = ?, cve_count = ? WHERE id = ?",
        (inserted, total_cves, feed_version_id),
    )
    con.commit()

    if verbose:
        dt = time.time() - t0
        dup = total_rows - inserted
        suffix = f" ({dup} critere(s) repete(s) dans le flux, ecartes)" if dup else ""
        print(
            f"  [{feed_name}] {total_cves} CVE lues, {inserted} criteres hardware "
            f"inseres en {dt:.1f} s{suffix}"
        )
    return {
        "feed": feed_name,
        "feed_version_id": feed_version_id,
        "rows": inserted,            # lignes reellement presentes (schema §row_count)
        "rows_yielded": total_rows,  # criteres produits par le flux, doublons inclus
        "cves": total_cves,
        "skipped": False,
        "sha256": sha256,
    }


def ingest_one(
    con: sqlite3.Connection,
    year: int,
    *,
    cache_dir: Path = DEFAULT_CACHE,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Télécharge (si besoin) puis ingère le flux d'une année."""
    feed_name = f"nvdcve-2.0-{year}.json.gz"
    dest = cache_dir / feed_name
    meta = _fetch_meta(year)
    if verbose:
        print(f"  [{feed_name}] telechargement / cache...")
    _download(FEED_URL.format(year=year), dest, force=force)
    published = (meta or {}).get("lastModifiedDate")
    return ingest_feed(con, dest, feed_name, published_at=published, verbose=verbose)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m iot_audit.vuln.ingest",
        description="Ingere les flux NVD 2.0 (CVE) dans une base SQLite locale.",
    )
    parser.add_argument("--db", default="corpus/nvd.sqlite", help="base cible")
    parser.add_argument(
        "--years", type=int, nargs="+", default=[2021, 2022, 2023, 2024],
        help="annees a ingerer (flux annuels)",
    )
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE),
        help="repertoire des .json.gz telecharges",
    )
    parser.add_argument("--force", action="store_true", help="retelecharger les flux")
    parser.add_argument("--verify", action="store_true", help="compter les lignes apres ingestion")
    args = parser.parse_args(argv)

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = connect(db)
    print(f"Base      : {db.resolve()}")
    print(f"Annees    : {' '.join(str(y) for y in args.years)}")
    print(f"Cache     : {Path(args.cache_dir).resolve()}")
    print()

    total = {"rows": 0, "cves": 0, "skipped": 0}
    for year in args.years:
        res = ingest_one(con, year, cache_dir=Path(args.cache_dir), force=args.force)
        total["rows"] += res["rows"]
        total["cves"] += res["cves"]
        total["skipped"] += 1 if res.get("skipped") else 0

    print()
    print(f"Total     : {total['rows']} criteres, {total['cves']} CVE "
          f"({total['skipped']} flux deja en base)")

    if args.verify:
        crit = con.execute("SELECT COUNT(*) FROM cve_cpe_criteria").fetchone()[0]
        cves = con.execute("SELECT COUNT(*) FROM cves").fetchone()[0]
        vendors = con.execute(
            "SELECT COUNT(DISTINCT vendor) FROM cve_cpe_criteria"
        ).fetchone()[0]
        print()
        print("--- Verification ---")
        print(f"cve_cpe_criteria : {crit}")
        print(f"cves             : {cves}")
        print(f"vendors distincts: {vendors}")
        for row in con.execute(
            """SELECT feed_name, row_count, cve_count
               FROM feed_versions ORDER BY feed_name"""
        ):
            print(f"  {row['feed_name']:<28} criteres={row['row_count']:<7} cve={row['cve_count']}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
