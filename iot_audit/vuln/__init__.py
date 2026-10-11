"""Spine NVD : ingestion des flux CVE et recherche par produit.

Deux roles, deux modules :

* :mod:`iot_audit.vuln.ingest` — lit les flux ``nvdcve-2.0-<annee>.json.gz`` en
  streaming et remplit ``cve_cpe_criteria`` (``part='h'`` seulement). Idempotent
  et reprenable ; le sha256 du flux est enregistre dans ``feed_versions``.
* :mod:`iot_audit.vuln.search` — pre-filtre SQL ``(vendor, product)`` puis
  evaluation des plages **en Python**, avec ``match_basis`` qui expose la
  force de la preuve (``exact_product`` vs ``vendor_wildcard``).

C'est le module dont l'absence etait le trou principal du projet
(ETAT-DES-LIEUX §0.5 : « aucune donnee CVE n'existe — or c'est l'objet du
projet »).
"""

from __future__ import annotations

from iot_audit.vuln.search import CveHit, SearchResult, search_cve

__all__ = ["CveHit", "SearchResult", "search_cve"]
