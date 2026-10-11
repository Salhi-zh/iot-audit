"""Tests du moteur `search_cve` sur base SQLite temporaire (fixtures synthetiques).

Le harnais couvre les six decisions du §9 du CDS :
  1. pre-filtre SQL large + decision en Python ;
  2. hiérarchie `match_basis` (exact_product > version_range > vendor_wildcard) ;
  3. un match vendeur-entier ne se fond JAMAIS avec un match produit exact ;
  4. `unresolved` publie l'incertitude (firmware inconnu) ;
  5. `negate` exclut (pas un faux positif silencieux) ;
  6. CVE `Rejected` mise de cote, mais traçable (`rejected_excluded`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iot_audit.vuln.ingest import connect
from iot_audit.vuln.search import MATCH_BASIS_STRENGTH, search_cve


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    con = connect(tmp_path / "nvd-test.sqlite")
    con.execute(
        "INSERT INTO feed_versions (feed_name, sha256, ingested_at) VALUES (?,?,?)",
        ("nvdcve-2.0-test.json.gz", "0" * 64, "2026-09-24T00:00:00+00:00"),
    )
    yield con
    con.close()


def _cve(con: sqlite3.Connection, cve_id: str, *, score: float | None = None,
         status: str = "Analyzed") -> None:
    con.execute(
        "INSERT INTO cves (cve_id, vuln_status, cvss_v3_score, feed_version_id) "
        "VALUES (?,?,?,1)",
        (cve_id, status, score),
    )


def _crit(con: sqlite3.Connection, cve_id: str, vendor: str, product: str, **kw) -> None:
    row = {
        "cve_id": cve_id,
        "match_criteria_id": f"{cve_id}-{vendor}-{product}-{len(kw)}",
        "criteria": f"cpe:2.3:h:{vendor}:{product}:{kw.get('version', '*')}:*:*:*:*:*:*:*",
        "part": "h",
        "vendor": vendor,
        "product": product,
        "version": kw.get("version", "*"),
        "version_start_incl": None,
        "version_start_excl": None,
        "version_end_incl": None,
        "version_end_excl": None,
        "vulnerable": 1,
        "negate": 0,
        "operator": kw.get("operator", "OR"),
        "feed_version_id": 1,
    }
    for k in ("version_start_incl", "version_start_excl",
              "version_end_incl", "version_end_excl", "negate", "vulnerable"):
        if k in kw:
            row[k] = kw[k]
    con.execute(
        f"INSERT INTO cve_cpe_criteria ({', '.join(row)}) "
        f"VALUES ({', '.join('?' * len(row))})",
        tuple(row.values()),
    )


# --------------------------------------------------------------------------- #
# 1. Pre-filtre et portee
# --------------------------------------------------------------------------- #


def test_exact_product_hit(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0001", score=9.8)
    _crit(db, "CVE-2024-0001", "tp-link", "archer_c7")
    res = search_cve(db, "tp-link", "archer_c7")
    assert res.n == 1
    assert res.hits[0].cve_id == "CVE-2024-0001"
    assert res.hits[0].match_basis == "exact_product"
    assert res.hits[0].cvss_v3_score == 9.8
    assert res.triage_scope == "product"  # toujours ecrit en sortie


def test_vendor_isolation(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0002")
    _crit(db, "CVE-2024-0002", "d-link", "dir-600")
    assert search_cve(db, "tp-link", "archer_c7").n == 0


def test_product_must_match_exactly_or_wildcard(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0003")
    _crit(db, "CVE-2024-0003", "tp-link", "archer_a7")
    assert search_cve(db, "tp-link", "archer_c7").n == 0


def test_vendor_wildcard_is_weak_and_kept_separate(db: sqlite3.Connection) -> None:
    """product='*' => preuve faible, marquee comme telle, jamais fondue."""
    _cve(db, "CVE-2024-0004")
    _crit(db, "CVE-2024-0004", "tp-link", "*")
    res = search_cve(db, "tp-link", "archer_c7")
    assert res.n == 1
    assert res.hits[0].match_basis == "vendor_wildcard"
    assert res.strong_hits() == ()          # le fort n'inclut pas le faible


def test_strong_basis_wins_when_cve_has_both(db: sqlite3.Connection) -> None:
    """La meme CVE reliee en exact ET en wildcard => rang exact conserve."""
    _cve(db, "CVE-2024-0005")
    _crit(db, "CVE-2024-0005", "tp-link", "*")
    _crit(db, "CVE-2024-0005", "tp-link", "archer_c7")
    res = search_cve(db, "tp-link", "archer_c7")
    assert res.hits[0].match_basis == "exact_product"


# --------------------------------------------------------------------------- #
# 2. Plages de versions et incertitude
# --------------------------------------------------------------------------- #


def test_version_inside_range_hits_with_basis(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0006")
    _crit(db, "CVE-2024-0006", "tp-link", "archer_c7",
          version_start_incl="1.0", version_end_excl="2.0")
    res = search_cve(db, "tp-link", "archer_c7", version="1.5")
    assert res.n == 1
    assert res.hits[0].match_basis == "version_range"
    assert res.hits[0].unresolved is False


# --------------------------------------------------------------------------- #
# 3. Negate et statut Rejected
# --------------------------------------------------------------------------- #


def test_negate_criterion_excludes(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0009")
    _crit(db, "CVE-2024-0009", "tp-link", "archer_c7", negate=1)
    assert search_cve(db, "tp-link", "archer_c7").n == 0


def test_rejected_cve_excluded_but_traceable(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0010", status="Rejected")
    _crit(db, "CVE-2024-0010", "tp-link", "archer_c7")
    res = search_cve(db, "tp-link", "archer_c7")
    assert res.n == 0
    assert res.rejected_excluded == ("CVE-2024-0010",)
    # le rapport peut la remonter sur demande explicite
    assert search_cve(db, "tp-link", "archer_c7", include_rejected=True).n == 1


def test_non_vulnerable_criterion_not_matched(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0011")
    _crit(db, "CVE-2024-0011", "tp-link", "archer_c7", vulnerable=0)
    assert search_cve(db, "tp-link", "archer_c7").n == 0


# --------------------------------------------------------------------------- #
# 4. Ranking et deduplication
# --------------------------------------------------------------------------- #


def test_hits_sorted_by_basis_then_cvss(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-LOW", score=3.1)
    _crit(db, "CVE-LOW", "tp-link", "archer_c7")
    _cve(db, "CVE-CRIT", score=9.8)
    _crit(db, "CVE-CRIT", "tp-link", "archer_c7")
    _cve(db, "CVE-WEAK", score=10.0)
    _crit(db, "CVE-WEAK", "tp-link", "*")          # wildcard : rang inferieur
    res = search_cve(db, "tp-link", "archer_c7")
    ids = [h.cve_id for h in res.hits]
    assert ids == ["CVE-CRIT", "CVE-LOW", "CVE-WEAK"]  # preuve forte d'abord


def test_duplicate_rows_collapse_to_one_hit(db: sqlite3.Connection) -> None:
    """Deux motifs differents pour la meme CVE => UNE seule entree, motifs cumules."""
    _cve(db, "CVE-2024-0012")
    _crit(db, "CVE-2024-0012", "tp-link", "archer_c7")
    db.execute("UPDATE cve_cpe_criteria SET match_criteria_id = match_criteria_id || '-bis'")
    _crit(db, "CVE-2024-0012", "tp-link", "archer_c7", version="2.0")  # motif different
    res = search_cve(db, "tp-link", "archer_c7")
    assert res.n == 1
    assert len(res.hits[0].matched_criteria) == 2   # deux motifs, une seule CVE


def test_basis_strength_is_antisymmetric() -> None:
    assert MATCH_BASIS_STRENGTH["exact_product"] > MATCH_BASIS_STRENGTH["version_range"]
    assert MATCH_BASIS_STRENGTH["version_range"] > MATCH_BASIS_STRENGTH["vendor_wildcard"]


def test_version_outside_range_excluded(db: sqlite3.Connection) -> None:
    _cve(db, "CVE-2024-0007")
    _crit(db, "CVE-2024-0007", "tp-link", "archer_c7",
          version_start_incl="1.0", version_end_excl="2.0")
    assert search_cve(db, "tp-link", "archer_c7", version="2.1").n == 0


def test_unknown_version_keeps_bounded_crit_as_unresolved(db: sqlite3.Connection) -> None:
    """Le cas nominal du projet : pas de firmware => hit publie, non resolu."""
    _cve(db, "CVE-2024-0008")
    _crit(db, "CVE-2024-0008", "tp-link", "archer_c7",
          version_start_incl="1.0", version_end_excl="2.0")
    res = search_cve(db, "tp-link", "archer_c7", version=None)
    assert res.n == 1
    assert res.hits[0].unresolved is True
