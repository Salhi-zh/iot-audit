"""Recherche CVE par produit : pre-filtre SQL, plages en Python (CDS §9).

Trois proprietes non negociables, chacune etant une reponse a un mode de
defaillance identifie :

1. **Le pre-filtre SQL ne decide pas.** Il ramene des candidats larges
   (`vendor` exact, `product` exact **ou** `*`). La decision d'appartenance se
   prend en Python, sur des fonctions testables — pas dans une requete que
   personne ne peut relire.
2. **`match_basis` expose la force de la preuve.** Un match « vendeur entier »
   (`product='*'`) est une preuve faible et n'est **jamais** fondu avec un match
   produit exact : l'auditeur doit pouvoir trier ce qu'il verifie.
3. **L'incertitude est publiee, pas absorbee.** Quand une borne de version ne
   peut pas etre evaluee (version inconnue de notre cote : c'est le cas normal,
   une photo ne donne pas le firmware), le resultat porte `unresolved=True` —
   il n'est ni « concerne » ni « non concerne » en silence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from iot_audit.vuln.version import is_unconstrained, within_range

__all__ = ["CveHit", "SearchResult", "search_cve", "MATCH_BASIS_STRENGTH"]

#: Hierarchie de preuve (CDS §9.3). Un match de rang superieur ecrase un match
#: de rang inferieur pour la meme CVE ; l'inverse n'arrive jamais.
MATCH_BASIS_STRENGTH = {
    "exact_product": 3,
    "version_range": 2,
    "vendor_wildcard": 1,
}


@dataclass(frozen=True, slots=True)
class CveHit:
    """Une CVE retenue pour un produit, avec la force de la preuve qui la lie."""

    cve_id: str
    match_basis: str                 # exact_product | version_range | vendor_wildcard
    unresolved: bool                 # au moins une borne de version non evaluable
    cvss_v3_score: float | None = None
    severity: str | None = None
    published: str | None = None
    vuln_status: str | None = None
    matched_criteria: tuple[str, ...] = ()   # motifs CPE, pieces d'audit


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Sortie complete : le produit interroge, les CVE, et la portee du triage.

    ``triage_scope`` vaut toujours ``'product'`` : il est ecrit ici, pas
    seulement dans le PDF (docs/01 §1).
    """

    vendor: str
    product: str
    version: str | None
    hits: tuple[CveHit, ...] = ()
    triage_scope: str = "product"
    rejected_excluded: tuple[str, ...] = field(default_factory=tuple)

    @property
    def n(self) -> int:
        return len(self.hits)

    def strong_hits(self) -> tuple[CveHit, ...]:
        """CVE liees par une preuve produit (pas par un vendeur entier)."""
        return tuple(h for h in self.hits if h.match_basis != "vendor_wildcard")

    def is_empty(self) -> bool:
        return not self.hits


def _basis_for(product_criterion: str, has_bounds: bool) -> str:
    if product_criterion == "*":
        return "vendor_wildcard"
    return "version_range" if has_bounds else "exact_product"


def _as_dict(hit: CveHit) -> dict:
    return {
        "cve_id": hit.cve_id,
        "match_basis": hit.match_basis,
        "unresolved": hit.unresolved,
        "cvss_v3_score": hit.cvss_v3_score,
        "severity": hit.severity,
        "published": hit.published,
        "vuln_status": hit.vuln_status,
        "matched_criteria": hit.matched_criteria,
    }


def search_cve(
    con: sqlite3.Connection,
    vendor: str,
    product: str,
    version: str | None = None,
    *,
    include_rejected: bool = False,
    limit: int | None = None,
) -> SearchResult:
    """Remonte les CVE qui concernent ``(vendor, product)`` au niveau produit.

    ``version`` reste ``None`` dans le chemin nominal du projet : une photo ne
    donne pas la version de firmware. Les criteres bornes sont alors marques
    ``unresolved`` au lieu d'etre ecartes — c'est exactement la difference entre
    « le produit a des CVE » et « cet exemplaire est vulnerable ».
    """
    vendor_n = (vendor or "").strip().lower().replace(" ", "_")
    product_n = (product or "").strip().lower().replace(" ", "_")

    rows = con.execute(
        """
        SELECT c.cve_id, c.criteria, c.product, c.version,
               c.version_start_incl, c.version_start_excl,
               c.version_end_incl,   c.version_end_excl,
               c.vulnerable, c.negate,
               v.cvss_v3_score, v.cvss_v3_severity, v.published, v.vuln_status
        FROM cve_cpe_criteria c
        LEFT JOIN cves v ON v.cve_id = c.cve_id
        WHERE c.part = 'h'
          AND c.vendor = :vendor
          AND c.product IN (:product, '*')
          AND c.vulnerable = 1
        """,
        {"vendor": vendor_n, "product": product_n},
    ).fetchall()

    best: dict[str, CveHit] = {}
    rejected: list[str] = []

    for (
        cve_id, criteria, crit_product, _crit_version,
        vs_incl, vs_excl, ve_incl, ve_excl,
        _vulnerable, negate,
        cvss, severity, published, vuln_status,
    ) in rows:
        # Une CVE rejetee n'est pas une vulnerabilite vivante : on la compte a
        # part (le rapport doit pouvoir dire « la CVE X a ete retiree du NVD »).
        if vuln_status == "Rejected" and not include_rejected:
            if cve_id not in rejected:
                rejected.append(cve_id)
            continue

        has_bounds = any(
            not is_unconstrained(b) for b in (vs_incl, vs_excl, ve_incl, ve_excl)
        )
        basis = _basis_for(crit_product, has_bounds)

        verdict: bool | None = None
        if version is not None and has_bounds:
            verdict = within_range(
                version,
                start_incl=vs_incl, start_excl=vs_excl,
                end_incl=ve_incl, end_excl=ve_excl,
            )

        # `unresolved` dit ce qu'on ne sait pas, jamais plus :
        #  - borne presente et version inconnue -> indetermine ;
        #  - borne presente, comparaison impossible -> indetermine.
        unresolved = has_bounds and verdict is not False and (
            version is None or verdict is None
        )

        if verdict is False:
            continue

        # `negate = 1` : le critere *exclut* ces versions (semantique NVD).
        # Un `LIKE` l'ignorerait et produirait un faux positif silencieux.
        if negate:
            continue

        previous = best.get(cve_id)
        if (
            previous is not None
            and MATCH_BASIS_STRENGTH[previous.match_basis] >= MATCH_BASIS_STRENGTH[basis]
        ):
            if criteria not in previous.matched_criteria:
                best[cve_id] = CveHit(
                    **{
                        **_as_dict(previous),
                        "matched_criteria": (*previous.matched_criteria, criteria),
                    }
                )
            continue

        best[cve_id] = CveHit(
            cve_id=cve_id,
            match_basis=basis,
            unresolved=unresolved,
            cvss_v3_score=cvss,
            severity=severity,
            published=published,
            vuln_status=vuln_status,
            matched_criteria=(criteria,),
        )

    hits = sorted(
        best.values(),
        key=lambda h: (
            MATCH_BASIS_STRENGTH[h.match_basis],
            h.cvss_v3_score if h.cvss_v3_score is not None else -1.0,
        ),
        reverse=True,
    )
    if limit is not None:
        hits = hits[:limit]

    return SearchResult(
        vendor=vendor_n,
        product=product_n,
        version=version,
        hits=tuple(hits),
        rejected_excluded=tuple(rejected),
    )
