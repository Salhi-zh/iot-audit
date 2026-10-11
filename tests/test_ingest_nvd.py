"""Tests d'ingestion NVD sur un flux synthetique mini (format 2.0 reel).

Trois proprietes sont verrouillees, ce sont celles qui font G1 :
  1. **Idempotence** : rejouer `ingest_feed` ne change AUCUN compte ;
  2. **Filtrage** : seules les parties `part='h'` entrent en base (a et o rejetees) ;
  3. **Provenance** : `feed_versions` porte le sha256, et un flux deja ingere est saute.

Le fixture imite la structure exacte publiee par le NVD (2026-09), pas une
simplification inventee : si le format reel change, ce test d'abord.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from iot_audit.vuln.ingest import connect, cve_metadata, hardware_criteria, ingest_feed


def _make_feed(tmp_path: Path) -> Path:
    """Flux annuel miniature : 1 CVE materiel (bornee), 1 CVE applicative, 1 rejetee."""
    feed = {
        "resultsPerPage": 3,
        "startIndex": 0,
        "totalResults": 3,
        "format": "NVD_CVE",
        "version": "2.0",
        "timestamp": "2026-09-24T00:00:00.000",
        "vulnerabilities": [
            {"cve": {
                "id": "CVE-2024-90001",
                "sourceIdentifier": "cve@mitre.org",
                "published": "2024-03-01T00:00:00.000",
                "lastModified": "2024-06-01T00:00:00.000",
                "vulnStatus": "Analyzed",
                "descriptions": [
                    {"lang": "es", "value": "texto no usado"},
                    {"lang": "en", "value": "Heap overflow in router <b>X</b>."},
                ],
                "metrics": {"cvssMetricV31": [{
                    "source": "nvd@nist.gov", "type": "Primary",
                    "cvssData": {"version": "3.1",
                                 "vectorString": "CVSS:3.1/AV:N/AC:L",
                                 "baseScore": 9.8, "baseSeverity": "CRITICAL"},
                }]},
                "configurations": [{"nodes": [{
                    "operator": "OR", "negate": False,
                    "cpeMatch": [{
                        "vulnerable": True,
                        "criteria": "cpe:2.3:h:tp-link:archer_c7:*:*:*:*:*:*:*:*",
                        "matchCriteriaId": "MC-1",
                        "versionStartIncluding": "1.0",
                        "versionEndExcluding": "2.0",
                    }]}]}],
            }},
            {"cve": {
                "id": "CVE-2024-90002",
                "published": "2024-04-01T00:00:00.000",
                "lastModified": "2024-04-01T00:00:00.000",
                "vulnStatus": "Analyzed",
                "descriptions": [{"lang": "en", "value": "App-side only."}],
                "metrics": {},
                "configurations": [{"nodes": [{
                    "operator": "OR",
                    "cpeMatch": [{
                        "vulnerable": True,
                        "criteria": "cpe:2.3:a:tp-link:archer_c7:1.0:*:*:*:*:*:*:*",
                        "matchCriteriaId": "MC-2",
                    }]}]}],
            }},
            {"cve": {
                "id": "CVE-2024-90003",
                "published": "2024-05-01T00:00:00.000",
                "lastModified": "2024-07-01T00:00:00.000",
                "vulnStatus": "Rejected",
                "descriptions": [{"lang": "en", "value": "Rejected by CNA."}],
                "metrics": {},
                "configurations": [{"nodes": [{
                    "operator": "OR",
                    "cpeMatch": [{
                        "vulnerable": True,
                        "criteria": "cpe:2.3:h:tp-link:archer_c7:*:*:*:*:*:*:*:*",
                        "matchCriteriaId": "MC-3",
                    }]}]}],
            }},
        ],
    }
    path = tmp_path / "nvdcve-2.0-2024.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(feed, fh)
    return path


def _counts(con) -> dict[str, int]:
    return {
        "crit": con.execute("SELECT COUNT(*) FROM cve_cpe_criteria").fetchone()[0],
        "cves": con.execute("SELECT COUNT(*) FROM cves").fetchone()[0],
        "feeds": con.execute("SELECT COUNT(*) FROM feed_versions").fetchone()[0],
    }


def test_ingestion_filters_to_hardware_only(tmp_path: Path) -> None:
    feed = _make_feed(tmp_path)
    con = connect(tmp_path / "nvd.sqlite")
    rep = ingest_feed(con, feed, "nvdcve-2.0-2024.json.gz", verbose=False)
    # 3 CVE lues, mais seules les 2 lignes part='h' entrent en criteres
    assert rep["cves"] == 3
    assert rep["rows"] == 2
    parts = {r[0] for r in con.execute("SELECT DISTINCT part FROM cve_cpe_criteria")}
    assert parts == {"h"}
    con.close()


def test_ingestion_extracts_metadata_and_bounds(tmp_path: Path) -> None:
    feed = _make_feed(tmp_path)
    con = connect(tmp_path / "nvd.sqlite")
    ingest_feed(con, feed, "nvdcve-2.0-2024.json.gz", verbose=False)
    cve = con.execute("SELECT * FROM cves WHERE cve_id='CVE-2024-90001'").fetchone()
    assert cve["cvss_v3_score"] == 9.8
    assert cve["cvss_v3_severity"] == "CRITICAL"
    assert cve["vuln_status"] == "Analyzed"
    assert "<b>" in cve["description"]  # description anglaise conservee
    crit = con.execute(
        "SELECT * FROM cve_cpe_criteria WHERE match_criteria_id='MC-1'"
    ).fetchone()
    assert crit["version_start_incl"] == "1.0"
    assert crit["version_end_excl"] == "2.0"
    assert crit["vendor"] == "tp-link" and crit["product"] == "archer_c7"
    con.close()


def test_ingestion_is_idempotent(tmp_path: Path) -> None:
    """G1 : double passe => comptes identiques, zero doublon, flux saute."""
    feed = _make_feed(tmp_path)
    con = connect(tmp_path / "nvd.sqlite")
    rep1 = ingest_feed(con, feed, "nvdcve-2.0-2024.json.gz", verbose=False)
    c1 = _counts(con)
    rep2 = ingest_feed(con, feed, "nvdcve-2.0-2024.json.gz", verbose=False)
    c2 = _counts(con)
    assert rep1["skipped"] is False and rep2["skipped"] is True
    assert c1 == c2, "un re-ingest a change les comptes — idempotence brisee"
    assert rep1["sha256"] == rep2["sha256"]
    assert c2["feeds"] == 1  # pas de deuxieme ligne feed_versions
    con.close()


def test_row_count_counts_inserted_rows_not_yields(tmp_path: Path) -> None:
    """`row_count` = lignes INSEREES (schema), jamais le nombre d'essais.

    Motif : un meme `matchCriteriaId` peut apparaitre dans **plusieurs** nodes de
    configuration d'une meme CVE. Le flux le produit alors deux fois ; l'ecriture
    est un `ON CONFLICT (cve_id, match_criteria_id) DO NOTHING`, donc une seule
    ligne entre. Si `row_count` comptait les essais, il annoncerait 2 lignes la
    ou `COUNT(*)` en montre 1 : la lecture naturelle de cet ecart est « un
    doublon est entre », c'est-a-dire une idempotence brisee qui n'existe pas.
    Defaut trouve le 2026-09-29 sur les vrais flux (92 968 annonces / 90 646
    lignes pour 2021), corrige ici.
    """
    cpe = "cpe:2.3:h:tp-link:archer_c7:*:*:*:*:*:*:*:*"
    vuln = {"cve": {
        "id": "CVE-2024-91000",
        "vulnStatus": "Analyzed",
        "descriptions": [{"lang": "en", "value": "twice-listed criterion"}],
        "metrics": {},
        "configurations": [
            {"nodes": [{"operator": "OR", "cpeMatch": [
                {"vulnerable": True, "criteria": cpe, "matchCriteriaId": "MC-DUP"},
            ]}]},
            {"nodes": [{"operator": "OR", "cpeMatch": [
                {"vulnerable": True, "criteria": cpe, "matchCriteriaId": "MC-DUP"},
            ]}]},
        ],
    }}
    path = tmp_path / "nvdcve-2.0-2024.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"vulnerabilities": [vuln]}, fh)

    con = connect(tmp_path / "nvd.sqlite")
    rep = ingest_feed(con, path, "nvdcve-2.0-2024.json.gz", verbose=False)

    assert rep["rows_yielded"] == 2          # produit deux fois par le flux
    assert rep["rows"] == 1                  # ecrit une seule fois
    stored = con.execute("SELECT row_count FROM feed_versions").fetchone()[0]
    actual = con.execute("SELECT COUNT(*) FROM cve_cpe_criteria").fetchone()[0]
    assert stored == actual == 1, "row_count doit egaler les lignes reelles"
    assert rep["rows"] == stored
    con.close()


def test_feed_sha256_is_recorded(tmp_path: Path) -> None:
    """D13 : le sha256 du snapshot figure dans feed_versions (provenance de run)."""
    feed = _make_feed(tmp_path)
    expected = hashlib.sha256(feed.read_bytes()).hexdigest()
    con = connect(tmp_path / "nvd.sqlite")
    ingest_feed(con, feed, "nvdcve-2.0-2024.json.gz", verbose=False)
    stored = con.execute("SELECT sha256 FROM feed_versions").fetchone()[0]
    assert stored == expected
    con.close()


def test_parsers_reject_malformed_criteria() -> None:
    """Un motif malforme ne doit pas entrer en base avec des champs devines."""
    vuln = {"cve": {"id": "CVE-2024-90004", "configurations": [{"nodes": [{
        "operator": "OR",
        "cpeMatch": [{"vulnerable": True, "criteria": "garbage-no-cpe",
                      "matchCriteriaId": "MC-BAD"}],
    }]}]}}
    assert list(hardware_criteria(vuln)) == []
    assert list(hardware_criteria({"cve": {"id": "X"}})) == []   # pas de configurations


def test_cve_metadata_prefers_english_and_v31() -> None:
    vuln = {"cve": {"id": "CVE-2024-90005", "vulnStatus": "Awaiting Analysis",
                    "descriptions": [{"lang": "fr", "value": "ignorez-moi"}],
                    "metrics": {"cvssMetricV30": [{"cvssData": {"baseScore": 7.5,
                                                                "baseSeverity": "HIGH"}}],
                                "cvssMetricV31": [{"cvssData": {"baseScore": 8.1,
                                                                "baseSeverity": "HIGH"}}]}}}
    meta = cve_metadata(vuln)
    assert meta["description"] == ""            # aucune description anglaise
    assert meta["cvss_v3_score"] == 8.1         # v3.1 prioritaire sur v3.0
    assert cve_metadata({"cve": {}}) is None
