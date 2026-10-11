#!/usr/bin/env python3
"""verify_report.py — Outil tiers de vérification d'intégrité de rapport scellé (D11).

Conforme à docs/02 §D11 :
"verify_report.py (outil tiers) ne lit ni la base ni la clé secrète."

Vérifie la signature Ed25519 d'un rapport exporté (JSON). La clé privée HMAC
n'est jamais requise ; la base n'est jamais lue.

Point de conception (2026-10-06). La clé publique est **publiée par l'auditeur**
à côté du rapport ; elle n'est pas une preuve quand elle est lue *dans* le
rapport. Un rapport forgé embarque la clé de son faussaire et se vérifie tout
seul. Le verdict d'authenticité exige donc une clé de confiance fournie : sans
`--pubkey`, l'outil ne dit jamais « authentique », il dit « auto-cohérent ».

Codes de retour :
    0  rapport authentique et intègre sous la clé de confiance fournie
    1  signature invalide, contenu altéré, ou clé de confiance non concordante
    2  fichier illisible / introuvable
    3  auto-cohérent seulement : signature valide sous la clé INTÉGRÉE au
       rapport, origine NON prouvée (fournir --pubkey)

Usage:
    python verify_report.py report.json --pubkey <clé_publique_b64_de_l_auditeur>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from iot_audit.storage.seal import verify_exported_report

EXIT_AUTHENTIC = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2
EXIT_SELF_CONSISTENT_ONLY = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vérificateur tiers indépendant de rapport d'audit scellé (Ed25519)."
    )
    parser.add_argument("report_path", type=Path, help="Chemin vers le fichier rapport JSON")
    parser.add_argument(
        "--pubkey",
        type=str,
        default=None,
        help=(
            "Clé publique attendue de l'auditeur (base64). REQUISE pour un verdict "
            "d'authenticité : sans elle, la clé lue dans le rapport ne prouve que "
            "l'auto-cohérence du document."
        ),
    )

    args = parser.parse_args(argv)

    if not args.report_path.exists():
        print(f"ERREUR: Fichier introuvable: {args.report_path}", file=sys.stderr)
        return EXIT_UNREADABLE

    raw = args.report_path.read_text(encoding="utf-8")
    is_valid = verify_exported_report(raw, expected_public_key=args.pubkey)

    if not is_valid:
        print(
            f"[ECHEC] Signature invalide ou contenu altéré pour '{args.report_path}'.",
            file=sys.stderr,
        )
        return EXIT_INVALID

    if args.pubkey is None:
        print(
            "[PARTIEL] Signature cohérente avec la clé INTÉGRÉE au rapport — "
            "l'origine n'est PAS prouvée : n'importe qui peut sceller un document "
            "avec sa propre clé. Fournir --pubkey <clé b64 publiée par l'auditeur>.",
            file=sys.stderr,
        )
        return EXIT_SELF_CONSISTENT_ONLY

    print(
        f"[OK] Le rapport '{args.report_path}' est authentique et intègre "
        "(signature vérifiée sous la clé de confiance fournie)."
    )
    return EXIT_AUTHENTIC


if __name__ == "__main__":
    sys.exit(main())
